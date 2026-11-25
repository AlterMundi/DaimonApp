"""Explicit, owner-configured Antigravity foreground worker."""

import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import re
import stat
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from google.antigravity import Agent, LocalOpenAIAgentConfig
from google.antigravity.types import AgentBehavior, BudgetConfig, CapabilitiesConfig, SessionContinuationMode, StopReason
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from provider_gate import ProviderGate


SCHEMA = "daimon-gateway.antigravity-turn/v1"
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
BODY_FIELDS = {"beingRef", "embodimentId", "incarnationId", "manifestHash"}
EMPTY_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}
BROKER = Path(__file__).resolve().parents[1] / "acp" / "gateway-worker.mjs"


def require(condition):
    if not condition:
        raise ValueError("Invalid owner selection")


def private(path, directory=False):
    path = Path(path)
    require(path.is_absolute())
    if directory:
        meta = path.lstat()
        require(stat.S_ISDIR(meta.st_mode) and meta.st_uid == os.getuid() and not meta.st_mode & 0o077)
        return path
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        meta = os.fstat(source.fileno())
        require(stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid() and not meta.st_mode & 0o077)
        require(meta.st_nlink == 1 and 0 < meta.st_size <= 16_384)
        data = source.read(16_385)
        require(len(data) <= 16_384)
    return json.loads(data)


def check_state_capacity(root):
    entries = 0
    size = 0
    for directory, folders, files in os.walk(root, followlinks=False):
        entries += len(folders) + len(files)
        require(entries < 2048)
        for filename in files:
            size += (Path(directory) / filename).lstat().st_size
            require(size < 128 * 1024 * 1024)


async def frame(reader):
    raw = await reader.readline()
    require(0 < len(raw) <= 131_072 and raw.endswith(b"\n"))
    return json.loads(raw)


def emit(ids, **fields):
    print(json.dumps({**ids, **fields}, separators=(",", ":")), flush=True)


async def run(profile, reader):
    expect = {"node", "stateRoot", "model", "providerPort", "body", "matrixStatusCommand"}
    require(set(profile) in (expect, expect | {"selectedMemory"}))
    require(Path(profile["node"]).is_absolute() and isinstance(profile["model"], str))
    require(0 < len(profile["model"]) <= 128 and type(profile["providerPort"]) is int)
    require(1 <= profile["providerPort"] <= 65_535 and set(profile["body"]) == BODY_FIELDS)
    state = private(profile["stateRoot"], directory=True)
    check_state_capacity(state)
    os.environ.update({name: str(state) for name in (
        "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"
    )})
    os.environ["PATH"] = "/usr/bin:/bin"
    first = await frame(reader)
    require(set(first) == {"schema", "type", "inputId", "sessionId", "body", "text"})
    require(first["schema"] == SCHEMA and first["type"] == "start")
    require(UUID.fullmatch(first["inputId"]) and UUID.fullmatch(first["sessionId"]))
    require(first["body"] == profile["body"] and isinstance(first["text"], str))
    require(0 < len(first["text"].encode()) <= 65_536)
    ids = {key: first[key] for key in ("schema", "inputId", "sessionId")}
    memory = profile.get("selectedMemory")
    binding = {key: profile[key] for key in ("body", "matrixStatusCommand")}
    if memory and memory["inputId"] == first["inputId"]:
        binding["selectedMemory"] = memory

    node = StdioServerParameters(
        command=profile["node"], args=[str(BROKER), "--matrix-mcp"],
        env={"PATH": "/usr/bin:/bin", "DAIMON_OBSERVATION": json.dumps(binding)},
    )
    tools = {"daimon_status"}
    if "selectedMemory" in binding:
        tools.add("dmk_read_selected")
    gate = ProviderGate(profile["model"], profile["providerPort"], tools, first["text"])
    committed = False

    try:
        async with stdio_client(node) as (receive, send), ClientSession(receive, send) as broker:
            await broker.initialize()
            listing = (await broker.list_tools()).tools
            require(len(listing) == len(tools) and {tool.name for tool in listing} == tools)
            require(all(tool.input_schema == EMPTY_SCHEMA for tool in listing))

            async def observe(name):
                result = await broker.call_tool(name, {})
                require(not result.is_error and len(result.content) == 1 and result.content[0].type == "text")
                data = result.content[0].text
                require(0 < len(data.encode()) <= 12_288)
                return data

            observed = await observe("daimon_status")
            require(json.loads(observed) == profile["body"])
            used = False

            async def reply_with(name):
                nonlocal used
                require(committed and not used)
                used = True
                result = await observe(name)
                gate.allow_followup()
                return result

            async def daimon_status() -> str:
                """Read authenticated metadata for this Matrix body."""
                return await reply_with("daimon_status")

            async def dmk_read_selected() -> str:
                """Read the one memory selected by the owner."""
                return await reply_with("dmk_read_selected")

            with gate.serve() as url:
                config = LocalOpenAIAgentConfig(
                    model=profile["model"], base_url=url,
                    conversation_id=first["sessionId"],
                    session_continuation_mode=SessionContinuationMode.CREATE_ONLY,
                    save_dir=str(state), app_data_dir=str(state), workspaces=[str(state)],
                    capabilities=CapabilitiesConfig(enabled_tools=[], enable_subagents=False,
                                                    agent_behavior=AgentBehavior.MINIMAL),
                    budget_config=BudgetConfig(max_model_calls=4, max_tool_calls=2),
                    tools=[daimon_status, dmk_read_selected] if len(tools) == 2 else [daimon_status],
                )
                with TemporaryDirectory(prefix="catalog-check-", dir=state) as disposable:
                    probe_id = str(uuid4())
                    probe = config.model_copy(update={
                        "conversation_id": probe_id, "save_dir": disposable,
                        "app_data_dir": disposable, "workspaces": [disposable],
                    })
                    async with Agent(config=probe) as check_agent:
                        check = await check_agent.chat(gate.challenge)
                        require((await check.text()).strip() == gate.marker)
                        require(gate.checked and check_agent.conversation_id == probe_id)

                async with Agent(config=config) as agent:
                    require(not agent.conversation.history)
                    reply = await agent.chat(first["text"])

                    async def collect_reply():
                        text = await reply.text()
                        require(reply.stop_reason == StopReason.UNSPECIFIED)
                        require(0 < gate.succeeded == gate.forwarded <= 2)
                        require(agent.conversation_id == first["sessionId"] and 0 < len(text.strip().encode()) <= 16_384)
                        return text

                    turn = asyncio.create_task(collect_reply())
                    ended = None
                    try:
                        async with asyncio.timeout(10):
                            while not gate.request_waiting.is_set() or agent.conversation_id is None:
                                require(not turn.done())
                                await asyncio.sleep(.02)
                        require(agent.conversation_id == first["sessionId"])
                        require(json.loads(await observe("daimon_status")) == profile["body"])
                        emit(ids, type="prepare_submission", nativeSessionId=agent.conversation_id)
                        decision = await frame(reader)
                        require(decision == {**ids, "type": "submission_decision", "committed": True})
                        committed = True
                        gate.release()
                        ended = asyncio.create_task(reader.read(1))
                        done, _ = await asyncio.wait({turn, ended}, return_when=asyncio.FIRST_COMPLETED)
                        require(ended not in done)
                        text = await turn
                    finally:
                        gate.abort()
                        if not turn.done():
                            with suppress(Exception):
                                await asyncio.wait_for(agent.conversation.cancel(), 2)
                            turn.cancel()
                        if ended:
                            ended.cancel()
                            await asyncio.gather(turn, ended, return_exceptions=True)
                        else:
                            await asyncio.gather(turn, return_exceptions=True)
        emit(ids, type="outcome", outcome={"phase": "completed", "sessionId": first["sessionId"], "text": text})
    except Exception:
        if committed:
            outcome = {"phase": "uncertain", "sessionId": first["sessionId"]}
        else:
            outcome = {"phase": "not_submitted", "reason": "antigravity_preflight_refused"}
        emit(ids, type="outcome", outcome=outcome)


async def main(path):
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=131_072)
    pipe, _ = await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    try:
        async with asyncio.timeout(122):
            await run(private(path), reader)
    finally:
        pipe.close()


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--profile":
        sys.exit(1)
    try:
        asyncio.run(main(sys.argv[2]))
    except Exception:
        sys.exit(1)
