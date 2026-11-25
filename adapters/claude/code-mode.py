#!/usr/bin/env python3
"""Launch native Claude Code Mode or measure it against ordinary tool calls."""
import argparse
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import uuid

TOKEN_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
MODE_ON = "Code Mode (experimental) is on"
TERMINAL_CONTROL = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]")


def environment(code_mode):
    return {
        "HOME": str(Path.home()), "PATH": "/usr/bin:/bin",
        "TERM": os.environ.get("TERM") if os.environ.get("TERM") not in (None, "dumb") else "xterm-256color",
        "CLAUDE_CODE_EXPERIMENTAL_CODE_MODE": "1" if code_mode else "0",
        "DISABLE_AUTOUPDATER": "1",
    }


def summarize(path, expected, mode):
    if not path.is_file():
        return None
    requests = {}
    tools = []
    messages = path.read_text(encoding="utf-8").splitlines()
    for line in messages:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            # The terminal process can be appending the last JSONL record.
            return None
        if record.get("type") != "assistant":
            continue
        message = record["message"]
        request = record.get("requestId")
        usage = message.get("usage")
        if request and usage:
            requests[request] = usage
        for block in message.get("content", []):
            if block.get("type") == "tool_use":
                tools.append(block.get("name"))
    if not messages:
        return None
    # A native end_turn with provider usage is the terminal answer. Sidechain
    # tool rows and synthetic terminal messages do not qualify.
    for line in reversed(messages):
        record = json.loads(line)
        if record.get("type") != "assistant" or not record.get("requestId"):
            continue
        message = record["message"]
        if message.get("stop_reason") != "end_turn":
            return None
        answer = "".join(item.get("text", "") for item in message["content"] if item.get("type") == "text")
        return {
            "correct": answer.strip() == expected,
            "mode_verified": ("REPL" in tools) if mode else ("REPL" not in tools and "Read" in tools),
            "provider_requests": len(requests),
            "read_calls": tools.count("Read"),
            "code_calls": tools.count("REPL"),
            "tokens": {key: sum(usage.get(key, 0) for usage in requests.values()) for key in TOKEN_FIELDS},
            "model": message.get("model"),
        }
    return None


def measure(binary, model, root, prompt, expected, code_mode):
    session = str(uuid.uuid4())
    project = re.sub(r"[^A-Za-z0-9-]", "-", str(root))
    transcript = Path.home() / ".claude" / "projects" / project / f"{session}.jsonl"
    tools = "REPL,Read" if code_mode else "Read"
    command = [binary, "--session-id", session, "--model", model,
               "--setting-sources", "", "--strict-mcp-config",
               "--tools", tools, "--allowedTools", "Read", "--permission-mode", "dontAsk"]
    child, terminal = pty.fork()
    if child == 0:
        os.chdir(root)
        fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
        os.execve(binary, command, environment(code_mode))

    start = None
    prompt_ready = None
    screen = ""
    accepted_trust = False
    accepted_mode = False
    evidence = None
    deadline = time.monotonic() + 90
    try:
        while time.monotonic() < deadline:
            if select.select([terminal], [], [], 0.15)[0]:
                try:
                    chunk = os.read(terminal, 8192)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    chunk = b""
                if not chunk:
                    raise ValueError("Native terminal exited before a measured reply")
                screen = (screen + chunk.decode(errors="replace"))[-32768:]
            if start is not None:
                evidence = summarize(transcript, expected, code_mode)
                if evidence is not None:
                    return {"seconds": round(time.monotonic() - start, 3), **evidence}
                continue

            if prompt_ready is not None:
                if time.monotonic() >= prompt_ready:
                    start = time.monotonic()
                    os.write(terminal, b"\r")
                continue
            visible = re.sub(r"\s+", "", TERMINAL_CONTROL.sub("", screen))
            if code_mode and "Startingwiththeordinarytools" in visible:
                raise ValueError("Native CLI declined Code Mode before submission")
            if not accepted_trust and "Yes,Itrustthisfolder" in visible:
                # This directory contains only fixtures created by this script.
                os.write(terminal, b"\x1b[B\r")
                accepted_trust = True
                screen = ""
            elif code_mode and not accepted_mode and "Yes,turnonCodeMode" in visible:
                os.write(terminal, b"\x1b[B\r")
                accepted_mode = True
                screen = ""
            elif "don'taskon" in visible and (not code_mode or MODE_ON.replace(" ", "") in visible):
                os.write(terminal, prompt.encode())
                prompt_ready = time.monotonic() + 0.15
        if start is not None:
            raise ValueError("Native submission was made, but no completed reply was observed")
        mode = "Code Mode" if code_mode else "ordinary mode"
        raise ValueError(f"Native terminal did not confirm {mode} readiness (fixture trusted: {accepted_trust})")
    finally:
        os.close(terminal)
        try:
            os.killpg(child, signal.SIGHUP)
        except ProcessLookupError:
            pass
        shutdown = time.monotonic() + 2
        while not os.waitpid(child, os.WNOHANG)[0]:
            if time.monotonic() >= shutdown:
                try:
                    os.killpg(child, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                os.waitpid(child, 0)
                break
            time.sleep(0.05)
        if evidence is not None:
            transcript.unlink(missing_ok=True)


def compare(binary, model, pairs):
    cases = []
    for pair in range(pairs):
        with tempfile.TemporaryDirectory(prefix="dm-codemode-") as directory:
            root = Path(directory)
            files = []
            expected = []
            for i in range(1, 9):
                filename = f"record-{i}.txt"
                value = uuid.uuid4().hex[:8]
                (root / filename).write_text(
                    f"value={value}\n" + ("The other lines of this record are filler.\n" * 35),
                    encoding="utf-8",
                )
                files.append(filename)
                expected.append(value)
            prompt = (f"Read only these eight files in the current directory, in order: {', '.join(files)}. "
                      "Extract the value after value= from the first line in each file. "
                      "Return only the eight values joined by commas, with no spaces or Markdown. "
                      "Use Read for the files, and do not access other paths or modify anything.")
            modes = (False, True) if pair % 2 == 0 else (True, False)
            results = {}
            for code_mode in modes:
                name = "code_mode" if code_mode else "ordinary"
                results[name] = measure(binary, model, root, prompt, ",".join(expected), code_mode)
            ordinary, code = results["ordinary"], results["code_mode"]
            comparable = (ordinary["model"] and ordinary["model"] == code["model"]
                          and all(r["correct"] and r["mode_verified"] for r in results.values()))
            cases.append({
                "order": list(results), "comparable": bool(comparable), **results,
                "code_minus_ordinary": {
                    "seconds": round(code["seconds"] - ordinary["seconds"], 3),
                    "provider_requests": code["provider_requests"] - ordinary["provider_requests"],
                    "tokens": {key: code["tokens"][key] - ordinary["tokens"][key] for key in TOKEN_FIELDS},
                } if comparable else None,
            })
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=lambda path: str(Path(path).resolve()))
    parser.add_argument("--model", default="sonnet")
    actions = parser.add_subparsers(dest="action", required=True)
    run = actions.add_parser("run", help="Open an interactive Code Mode session for tool-heavy work")
    run.add_argument("--resume", type=uuid.UUID)
    bench = actions.add_parser("compare", help="Measure two modes on the same synthetic read workload")
    bench.add_argument("--pairs", type=int, choices=range(1, 4), default=1)
    args = parser.parse_args()

    if args.action == "run" and not (sys.stdin.isatty() and sys.stdout.isatty()):
        parser.error("run requires an interactive terminal")

    env = environment(False)
    try:
        probe = subprocess.run([args.binary, "auth", "status"], env=env, text=True,
                               capture_output=True, check=True, timeout=8)
        auth = json.loads(probe.stdout)
        if (auth.get("loggedIn") is not True or auth.get("authMethod") != "claude.ai"
                or auth.get("apiProvider") != "firstParty" or auth.get("apiKeySource") is not None):
            raise ValueError("An existing native Claude subscription login is required")
        if args.action == "run":
            argv = [args.binary, "--model", args.model]
            if args.resume:
                argv.extend(("--resume", str(args.resume)))
            os.execve(args.binary, argv, environment(True))
        version = subprocess.check_output([args.binary, "--version"], env=env, text=True, timeout=8).strip()
        pairs = compare(args.binary, args.model, args.pairs)
        print(json.dumps({"cli": version, "pairs": pairs}, indent=2))
        return 0 if all(pair["comparable"] for pair in pairs) else 1
    except KeyboardInterrupt:
        print("Native comparison interrupted", file=sys.stderr)
    except (subprocess.SubprocessError, OSError):
        print("Could not start or verify the selected native Claude executable", file=sys.stderr)
    except ValueError as error:
        print(str(error), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
