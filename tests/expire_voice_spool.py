import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid

from scripts.expire_voice_spool import expire, MAX_AGE_SECONDS


class VoiceSpoolExpiry(unittest.TestCase):
    def test_expiry_preserves_receipts_recent_audio_and_explicit_holds(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "receiver.sqlite3"
            spool = Path(str(db) + ".voice")
            spool.mkdir(mode=0o700)
            (spool / "admission.lock").touch(mode=0o600)
            now = 1_800_000_000

            def captured(age):
                path = spool / str(uuid.uuid4())
                path.touch(mode=0o600)
                path.write_bytes(b"recording")
                os.utime(path, (now-age, now-age))
                return path

            old = captured(MAX_AGE_SECONDS)
            durable = captured(MAX_AGE_SECONDS+1)
            protected = captured(MAX_AGE_SECONDS+1)
            recent = captured(MAX_AGE_SECONDS-1)
            unrelated = spool / "unrelated"
            unrelated.write_bytes(b"outside the capture format")
            symlink = spool / str(uuid.uuid4())
            symlink.symlink_to(unrelated)
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE conversation_inputs (id TEXT PRIMARY KEY, doc TEXT NOT NULL)")
                conn.executemany("INSERT INTO conversation_inputs VALUES (?,?)", [
                    (protected.name, json.dumps({"voice": {"preserve_original": True}})),
                    (durable.name, json.dumps({"text": "Retained transcript", "voice": {}})),
                ])
            self.assertEqual(expire(db, now=now), {"expired": 2, "bytes": 18, "protected": 1})
            self.assertTrue(old.exists())
            self.assertEqual(expire(db, now=now, apply=True)["expired"], 2)
            self.assertFalse(old.exists())
            self.assertFalse(durable.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(protected.exists())
            self.assertTrue(unrelated.exists())
            self.assertTrue(symlink.is_symlink())
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM conversation_inputs").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
