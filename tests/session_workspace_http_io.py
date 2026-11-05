#!/usr/bin/env python3
"""Explicit owned pins through HTTP, retained ASR and actual native dispatch; no models."""
import json
from pathlib import Path
import sys
from conversation_cold_entry_http_io import ColdEntry, Browser


def qualify(binary):
    j=ColdEntry(str(Path(binary).resolve()));b=None
    try:
        j.prepare()
        j.stop()
        # An owned native exists, but no router target is enrolled for it.
        j.config.write_text(j.config.read_text().replace(j.target_config,''))
        j.start();j.wait_control_socket(j.socket);j.routing=True
        b=Browser(j)
        workspace=b.get('/api/interaction/sessions')
        pin=next(item['destination'] for item in workspace['sessions'] if item['audio_key']=='100:7')
        assert pin and pin['source'].startswith('session:')
        original,_=b.text('#Unknown Keep the exact original words.',reply=pin)
        j.wait(lambda:j.instructions(7) and j.instructions(7)[0][1]=='accepted')
        assert b.status(original)['phase']=='routed' and not j.packets
        assert j.row('SELECT codex_thread_id FROM sessions WHERE thread_id=1')==[(None,)]
        # While the same worker is running, ordinary recorded voice steers it.
        voice,_=b.voice(reply=pin)
        j.wait(lambda:len(j.instructions(7))==2 and j.instructions(7)[1][1]=='accepted')
        j.wait(lambda:len(j.worker_packets['native-topic-7'])==2)
        assert b.status(voice)['phase']=='routed' and not j.packets
        first=j.worker_packets['native-topic-7'][0]['input'][0]['text']
        assert '#Unknown Keep the exact original words.' in first
        assert j.row('SELECT count(*) FROM interaction_enrollments')==[(0,)]
        # Exact repeated HTTP status/retry cannot manufacture another native send.
        b.status(original);b.status(voice)
        assert len(j.worker_packets['native-topic-7'])==2
        j.answer_worker(7,'Both pinned originals are incorporated.');j.idle()
        print('PASS owned unregistered pin: literal selector text + ordinary ASR voice during active worker -> native start/steer, no integrating turn/enrollment, original receipts preserved; zero models.')
    finally:
        if b:b.client.close();b.provider.close()
        j.close()


if __name__=='__main__':qualify(sys.argv[1])
