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
        # Latest-message reply is a narrower versioned session destination,
        # usable by text and retained-ASR voice while that same worker is busy.
        workspace=b.get('/api/interaction/sessions')
        selected=next(item for item in workspace['sessions'] if item['audio_key']=='100:7')
        latest=selected['latest_reply']
        assert latest and '/' in latest['source'] and selected['result_available'] is True
        follow,_=b.text('About that exact latest result.',reply=latest)
        j.wait(lambda:len(j.worker_packets['native-topic-7'])==3)
        follow_voice,_=b.voice(reply=latest)
        j.wait(lambda:len(j.worker_packets['native-topic-7'])==4)
        for original_id in (follow,follow_voice):
            assert json.loads(j.row("SELECT json_extract(doc,'$.reply') FROM conversation_inputs WHERE id=?",(original_id,))[0][0])==latest
        assert not j.packets and j.row('SELECT count(*) FROM turns WHERE session_id=(SELECT id FROM sessions WHERE thread_id=1)')==[(0,)]
        j.answer_worker(7,'Exact-message text and voice are incorporated.');j.idle()
        # The selected history endpoint reads only that owned native root. Its
        # synthetic rollout exercises HTTP framing, tools and append completion;
        # it is not a real provider transcript or a claim of physical hearing.
        import sqlite3
        native_home=j.root/'history-fixture';sessions=native_home/'sessions';sessions.mkdir(parents=True)
        history=sessions/'worker.jsonl'
        header={'type':'session_meta','payload':{'id':'native-topic-7'}}
        tool={'type':'response_item','payload':{'type':'function_call','name':'inspect','arguments':'{"fixture":true}'}}
        result={'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'Late worker answer'}]}}
        history.write_text(json.dumps(header)+'\n'+json.dumps(tool)+'\n')
        with sqlite3.connect(native_home/'state_5.sqlite') as db:
            db.execute('CREATE TABLE threads(id TEXT,rollout_path TEXT,archived INTEGER)')
            db.execute('INSERT INTO threads VALUES(?,?,0)',('native-topic-7',str(history)))
        b.provider.native_home=native_home
        url='/api/interaction/sessions/'+selected['id']
        first=b.get(url+'?technical=true');assert first['items'][0]['kind']=='tool_call'
        with history.open('a') as stream:stream.write(json.dumps(result))
        cursor='?technical=true&revision='+first['revision']+'&after='+str(first['after'])
        assert b.get(url+cursor)['items']==[]
        with history.open('a') as stream:stream.write('\n')
        assert b.get(url+cursor)['items'][0]['text']=='Late worker answer'
        print('PASS owned unregistered pin and exact latest-message reply: text + retained ASR voice start/steer the busy native worker without integrating work; selected technical-history HTTP waits for complete appended records; original receipts preserved; zero models.')
    finally:
        if b:b.client.close();b.provider.close()
        j.close()


if __name__=='__main__':qualify(sys.argv[1])
