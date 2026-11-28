#!/usr/bin/env python3
"""Exercise the real owner controller and canonical source reader with a fake Codex."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

from conversation_routing_io import CanonicalRouting


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def run(binary):
    journey = CanonicalRouting(binary)
    try:
        journey.start()
        for topic in (1, 7, 8):
            journey.admit("Seed the owned native context.", topic=topic)
            journey.wait(lambda: journey.has("Initial goal turn delivered.", topic))
            journey.idle()
        journey.stop()
        root = journey.root / "topic-folders"
        root.mkdir(mode=0o700)
        config = journey.config.read_text().replace(
            "[interaction]\n",
            f"[interaction]\ntopic_workspace_root={json.dumps(str(root))}\n",
            1,
        )
        journey.config.write_text(config + journey.target_config)
        journey.start()
        journey.wait_control_socket(journey.socket)
        journey.routing = True
        topic, = journey.row("SELECT id FROM sessions WHERE thread_id=7")[0]
        adopted = journey.read("topics", "workspace", "adopt", "7", str(topic))["result"]
        assert adopted["folder_ready"], adopted
        folder = Path(adopted["conversation_folder"])
        checkout = folder / "story"
        checkout.mkdir()
        git(checkout, "init", "--object-format=sha1")
        (checkout / "story.txt").write_text("A shared story.\n")
        git(checkout, "add", "story.txt")
        git(checkout, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-m", "First draft")
        project = str(uuid.uuid4())
        git(checkout, "config", "--local", "daimon.project-id", project)
        link = {"project": project, "locator": f"git:local:{project}",
                "commit": git(checkout, "rev-parse", "HEAD")}

        binding = journey.read("presentation", "list", "0", "0")["result"]["binding"]

        def dispatch(number, selector, thread, text, *, relation="new", requests=()):
            original, _ = journey.submit(binding, text)
            journey.wait(lambda: journey.row(
                "SELECT phase FROM conversation_inputs WHERE id=?", (original["id"],)
            ) == [("accepted",)])
            journey.call(f"route-shadow-dispatch-{number}", "dispatch", {
                "input_ref": original["id"],
                "destinations": [{"selector": selector, "relation": relation, "requests": list(requests)}],
            })
            journey.wait(lambda: len(journey.instructions(thread)) == number
                         and journey.instructions(thread)[-1][1] == "accepted")

        def shadow(thread, ident, args, *, ok=True):
            native, = journey.row("SELECT codex_thread_id FROM sessions WHERE thread_id=?", (thread,))[0]
            journey.wait(lambda: native in journey.workers)
            send = next(send for selected, send in journey.clients.values() if selected == native)
            call = f"route-shadow-{ident}"
            send({"id": call, "method": "item/tool/call", "params": {
                "threadId": native, "turnId": journey.workers[native], "callId": call,
                "tool": "interaction_controller",
                "arguments": {"operation": "project_checkpoint_shadow", "arguments": args},
            }})
            journey.wait(lambda: call in journey.tool_results)
            result = journey.tool_results[call]
            assert result["success"] is ok, result
            return json.loads(result["contentItems"][0]["text"]) if ok else None

        dispatch(1, "Alpha", 7, "Record the selected revision.")
        journey.answer_worker(7, "Staged the selected repo.\nProject link: " + json.dumps(link))
        journey.wait(lambda: journey.row("SELECT busy FROM sessions WHERE thread_id=7") == [(0,)])
        page = journey.read("presentation", "list", "0", "0")["result"]
        result = next(item for item in page["items"] if item["kind"] == "worker_result")
        source = {"kind": "conversation", "source": result["id"], "revision": result["revision"]}

        dispatch(2, "Alpha", 7, "Prepare the project's shadow checkpoint.")
        workspace = shadow(7, "workspace", {"action": "workspace"})["workspace"]
        assert workspace
        delta = {"operation": str(uuid.uuid4()), "expected_revision": 0, "workspace": workspace,
                 "link": link, "sources": [source]}
        apply = {"action": "apply", "checkout": "story", "delta": delta}
        queried_before = journey.row("SELECT count(*) FROM interaction_instructions")
        accepted = shadow(7, "accept", apply)
        assert accepted["status"] == "accepted", accepted
        assert accepted["checkpoint"]["delta"] == delta
        (folder / "archive").mkdir()
        checkout.rename(folder / "archive/moved")
        retry = shadow(7, "repeat", {**apply, "checkout": "archive/moved"})
        assert retry == {**accepted, "status": "retained"}, retry
        read = shadow(7, "read", {"action": "read", "workspace": workspace, "checkout": "archive/moved"})
        assert read == accepted["checkpoint"], read
        assert journey.row("SELECT count(*) FROM interaction_instructions") == queried_before
        assert journey.row("SELECT revision FROM project_checkpoint_deltas") == [(1,)]

        dispatch(3, "Alpha", 7, "Correct the first iteration: withdraw the old revision citation.",
                 relation="amends", requests=result["request_ids"])
        corrected = journey.read("presentation", "list", "0", "0")["result"]["items"]
        assert all(item["id"] != result["id"] or not item["current"] for item in corrected)
        assert shadow(7, "still-owned", {"action": "workspace"})["workspace"] == workspace
        corrected_count = journey.row("SELECT count(*) FROM interaction_instructions")
        shadow(7, "revoked-read", {"action": "read", "workspace": workspace, "checkout": "archive/moved"}, ok=False)
        shadow(7, "revoked-repeat", {**apply, "checkout": "archive/moved"}, ok=False)
        assert journey.row("SELECT count(*) FROM interaction_instructions") == corrected_count
        assert journey.row("SELECT revision FROM project_checkpoint_deltas") == [(1,)]
        print("PASS owned Gateway controller verified canonical conversation evidence and one durable Git revision; checkout move, exact repeat and source correction caused no duplicate dispatch or extra model call.")
    finally:
        journey.close()


if __name__ == "__main__":
    run(str(Path(sys.argv[1]).resolve()))
