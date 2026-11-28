#!/usr/bin/env python3
"""Exercise both surfaces and a paired handoff against the owner-selected agy."""

import binascii
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import sys
import tomllib
import uuid
import zlib

from conversation_routing_io import CanonicalRouting


def image(color):
    def chunk(kind, data):
        checksum = binascii.crc32(kind + data) & 0xffffffff
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    scanline = b"\x00" + bytes(color) * 48
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", 48, 48, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanline * 48))
        + chunk(b"IEND", b"")
    )


def qualify(binary, source_profile):
    journey = CanonicalRouting(binary)
    try:
        journey.start()
        for topic in (1, 7, 8):
            journey.admit("Seed an isolated topic", topic=topic)
            journey.wait(lambda: journey.has("Initial goal turn delivered.", topic))
            journey.idle()
        journey.stop()

        cwd = journey.root / "agy"
        cwd.mkdir(mode=0o700)
        with sqlite3.connect(journey.root / "state.sqlite") as db:
            assert db.execute("UPDATE sessions SET cwd=? WHERE thread_id=7", (str(cwd),)).rowcount == 1

        raw = source_profile.read_text()
        authoritative = tomllib.loads(raw)["interaction"]["antigravity_foreground"]
        command = authoritative["worker_command"].copy()
        owner = json.loads(Path(command[-1]).read_text())
        local_profile = journey.root / "agy-worker.json"
        local_profile.touch(mode=0o600)
        local_profile.write_text(json.dumps({**owner, "cwd": str(cwd)}))
        command[-1] = str(local_profile)
        transport = raw.split("[interaction.antigravity_foreground.transport]", 1)[1]
        transport = transport.split("[interaction.antigravity_matrix_foreground]", 1)[0]
        journey.config.write_text(
            journey.config.read_text()
            + "\ntelegram_projection=true\ntelegram_entry_projection=true\n"
            + journey.target_config.replace('name="Alpha"', 'name="Alpha"\nharness="antigravity"')
            + "\n[interaction.antigravity_foreground]\ninteraction_direct=true\nagy_cli=true\n"
            + "worker_command=" + json.dumps(command)
            + "\n[interaction.antigravity_foreground.transport]" + transport
        )
        journey.start()
        journey.wait_control_socket(journey.socket)

        def result(original, expected):
            def record():
                rows = journey.row(
                    "SELECT i.phase,t.status,t.native_thread_id,t.assistant_text,"
                    "json_extract(i.doc,'$.native_input_accepted') "
                    "FROM interaction_sources s JOIN interaction_instructions i ON i.input_id=s.id "
                    "JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE s.event_id=?",
                    (str(original),),
                )
                return rows[0] if rows else (None, None, None, None, None)

            journey.wait(lambda: record()[0] in {"accepted", "retained_unsent", "uncertain", "rejected"},
                         seconds=28)
            phase, status, native, answer, accepted = record()
            assert accepted == 1, "Native incorporation receipt missing"
            assert (phase, status) == ("accepted", "completed"), (phase, status)
            assert answer.strip().lower().strip(".") == expected, answer
            return native

        question = "What single primary color is shown? Answer with the color only. Do not use tools."
        name = "red-fixture.png"
        red = image((220, 20, 30))
        journey.media_files = {name: red}
        telegram = journey.admit(topic=7, message_fields={
            "caption": question, "document": {
                "file_id": name, "file_name": name, "mime_type": "image/png", "file_size": len(red),
            },
        })
        first = result(telegram, "red")
        journey.wait(lambda: any(
            answer["text"].strip().lower().strip(".") == "red"
            and sent.get("reply_parameters", {}).get("message_id") == telegram
            for answer, sent in journey.messages
        ), seconds=10)

        store = journey.root / "state.sqlite.files"
        store.mkdir(mode=0o700, exist_ok=True)
        blue = image((25, 45, 205))
        digest = hashlib.sha256(blue).hexdigest()
        blob = store / digest
        blob.touch(mode=0o600)
        blob.write_bytes(blue)
        binding = journey.read("presentation", "list", "0", "0")["result"]["binding"]
        ident = str(uuid.uuid4())
        packet = {
            "binding": binding, "id": ident, "text": "#Alpha " + question,
            "files": [{
                "file_id": str(uuid.uuid4()), "sha256": digest, "name": "blue-fixture.png",
                "mime": "image/png", "size": len(blue),
            }],
        }
        assert journey.read("input", "submit-human", json.dumps(packet))["result"]["new_input"]
        assert result(ident, "blue") == first
        print("Telegram and Conversation images reached the same native Antigravity session with incorporation receipts.")

        journey.routing = True
        journey.allow_local_dependencies = True
        original = str(uuid.uuid4())
        journey.read("input", "submit-human", json.dumps({
            "id": original, "binding": binding, "text": "Request an attributed synthetic color check.",
        }))
        journey.wait(lambda: journey.row("SELECT phase FROM conversation_inputs WHERE id=?",
                                        (original,)) == [("accepted",)])
        parents = journey.call("route-agy-parents", "coordination_inputs", {})["inputs"]
        parent, = [row for row in parents if row["source_event"] == original
                   and row["eligible_coordination_parent"]]
        request = {
            "parent_instruction": parent["instruction"], "request_id": "agy-color-check",
            "selector": "Alpha", "report_to_topic": True,
            "text": "Name the color in the last image with the prefix COLOR- and include the requested completion footer.",
        }
        handoff = journey.call("route-agy-request", "session_request", request)
        assert handoff.get("new_admission"), handoff
        instruction = handoff["instruction"]["id"]
        repeat = journey.call("route-agy-inspect-existing", "session_request", request)
        assert not repeat["new_admission"] and repeat["instruction"]["id"] == instruction, repeat
        caller = journey.web_thread
        journey.finish(caller, journey.web_turn)

        def handoff_state():
            return journey.row("""
                SELECT i.phase,t.native_thread_id,json_extract(i.doc,'$.native_input_accepted'),
                       t.assistant_text,c.phase
                FROM interaction_session_requests c JOIN interaction_instructions i ON i.id=c.target_instruction
                LEFT JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn') WHERE i.id=?
            """, (instruction,))

        journey.wait(lambda: handoff_state()[0][0] in {"accepted", "retained_unsent", "uncertain", "rejected"},
                     seconds=35)
        phase, native, receipt, answer, _ = handoff_state()[0]
        assert (phase, native, receipt) == ("accepted", first, 1), handoff_state()
        assert "COLOR-BLUE" in answer.upper(), answer
        journey.wait(lambda: journey.has(request["text"], 7) and journey.has("COLOR-", 7), seconds=12)
        journey.wait(lambda: handoff_state()[0][-1] == "returned", seconds=12)
        journey.wait(lambda: any("COLOR-BLUE" in str(packet["input"]).upper()
                                for packet in journey.worker_packets.get(caller, [])), seconds=12)
        assert sum("COLOR-BLUE" in str(packet["input"]).upper()
                   for packet in journey.worker_packets[caller]) == 1
        assert sum(request["text"] in message["text"]
                   for message, _ in journey.messages) == 1
        print("A paired Codex handoff reached the same Antigravity history, appeared in the topic and returned its canonical result to Codex.")
        journey.finish(caller, journey.workers[caller])
        latest = str(uuid.uuid4())
        original = (
            "#Alpha Pedile a Beta que elija una palabra sin decírtela de antemano. "
            "Cuando te vuelva su respuesta, decime acá qué palabra eligió."
        )
        assert journey.read("input", "submit-human", json.dumps({
            "id": latest, "binding": binding, "text": original,
        }))["result"]["new_input"]
        beta = journey.row("SELECT codex_thread_id FROM sessions WHERE thread_id=8")[0][0]
        journey.wait(lambda: beta in journey.workers, seconds=45)
        assert journey.worker_packets[beta], "The ordinary request did not reach the selected topic."
        marker = "RUBY-LANTERN"
        journey.answer_worker(8, marker)

        def returned():
            return journey.row("""
                SELECT i.phase,t.native_thread_id,json_extract(i.doc,'$.native_input_accepted'),
                       t.assistant_text
                FROM interaction_session_requests c
                JOIN interaction_instructions i ON i.id=json_extract(c.doc,'$.return_instruction')
                JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn')
                WHERE c.caller_topic=7 AND c.target_instruction IN
                  (SELECT id FROM interaction_instructions WHERE session_id=(SELECT id FROM sessions WHERE thread_id=8))
            """)

        journey.wait(lambda: returned() and returned()[0][0] in
                     {"accepted", "retained_unsent", "uncertain", "rejected"}, seconds=45)
        row, = returned()
        assert row[:3] == ("accepted", first, 1) and marker in row[3], row
        assert len(journey.worker_packets[beta]) == 1
        print("Antigravity started one paired request and incorporated its Codex result in the same history.")

    finally:
        journey.close()


if __name__ == "__main__":
    qualify(str(Path(sys.argv[1]).absolute()), Path(sys.argv[2]).absolute())
