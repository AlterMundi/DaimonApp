#!/usr/bin/env python3
"""Recover the exact Telegram original through Gateway's local owner socket."""

from pathlib import Path
import json
import sys

from conversation_routing_io import CanonicalRouting


def recover_known_unsent(binary):
    journey = CanonicalRouting(binary)
    try:
        journey.start()
        journey.admit("Seed the old Codex conversation", topic=7)
        journey.wait(lambda: journey.has("Initial goal turn delivered.", 7))
        journey.idle()
        journey.stop()

        status = journey.root / "status.py"
        status.write_text("""
import json
print(json.dumps({"schema":"dm.runtime.status/v1","integrity":"ok",
 "being_ref":"dm:being:v1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA","manifest_hash":"a"*64,"local_origin":{
 "embodiment_id":"embodiment:00000000-0000-4000-8000-000000000001","incarnation_id":"fixture-incarnation"}}))
""")
        ready = journey.root / "worker-ready"
        worker = journey.root / "worker.py"
        worker.write_text("""
from pathlib import Path
import json,sys
frame = json.loads(sys.stdin.readline())
wire = {key:frame[key] for key in ("schema","inputId","sessionId")}
def emit(**body):
    print(json.dumps({**wire, **body}), flush=True)
if not Path(sys.argv[1]).exists():
    emit(type="outcome", outcome={"phase":"not_submitted"})
    raise SystemExit
session = frame["resume"]["sessionId"] if frame["resume"] else frame["freshNativeSessionId"]
emit(type="prepare_submission", nativeSessionId=session,
     sessionScope="b"*64, workspace=frame["workspace"])
assert json.loads(sys.stdin.readline())["committed"]
with Path(sys.argv[1]).open("a") as count:
    count.write("1")
if frame["text"] == "uncertain fixture":
    emit(type="outcome", outcome={"phase":"uncertain","sessionId":session})
else:
    assert frame["text"] == "original fixture"
    emit(type="outcome", outcome={"phase":"completed","sessionId":session,
                                 "text":"Recovered original fixture."})
""")
        journey.config.write_text(journey.config.read_text()
            + journey.target_config.replace('name="Alpha"', 'name="Alpha"\nharness="claude"')
            + '\n[interaction.claude_foreground]\ninteraction_direct=true\n'
            + 'worker_command=' + json.dumps([sys.executable, str(worker), str(ready)])
            + '\n[interaction.claude_foreground.transport]\ntimeout_seconds=10\n'
            + 'command=' + json.dumps([sys.executable, str(status)])
            + '\nsource={kind="body",being_ref="dm:being:v1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",embodiment_id="embodiment:00000000-0000-4000-8000-000000000001"}\n')
        journey.start()
        journey.wait_control_socket(journey.socket)
        original = journey.admit("original fixture", topic=7)

        def instruction(update):
            rows = journey.row(
                "SELECT i.id,i.phase FROM interaction_instructions i "
                "JOIN interaction_sources s ON s.id=i.input_id WHERE s.update_id=?", (update,))
            return rows[0] if rows else (None, None)

        journey.wait(lambda: instruction(original)[1] == "retained_unsent")
        original_instruction = instruction(original)[0]
        ready.touch()

        def recover(selected):
            return journey.read("input", "recover-retained-telegram", selected)["result"]

        assert recover(original_instruction)["recovered"]
        journey.wait(lambda: journey.has("Recovered original fixture.", 7))
        assert instruction(original) == (original_instruction, "accepted")
        assert not recover(original_instruction)["recovered"]
        assert ready.read_text() == "1"
        assert journey.row(
            "SELECT count(*) FROM audit_log WHERE action='telegram_original_owner_recovery'") == [(1,)]

        uncertain = journey.admit("uncertain fixture", topic=7)
        journey.wait(lambda: instruction(uncertain)[1] == "uncertain")
        assert not recover(instruction(uncertain)[0])["recovered"]
        assert ready.read_text() == "11"
        print("Original recovered exactly once. Accepted and uncertain replays refused.")
    finally:
        journey.close()


if __name__ == "__main__":
    recover_known_unsent(str(Path(sys.argv[1]).absolute()))
