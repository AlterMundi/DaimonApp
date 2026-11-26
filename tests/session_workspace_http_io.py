#!/usr/bin/env python3
"""Explicit owned pins through HTTP, retained ASR and actual native dispatch; no models."""
import json
from pathlib import Path
import sqlite3
import sys
import time
from conversation_cold_entry_http_io import ColdEntry, Browser
from scripts.activity_indicator import inventory_source


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
        native_home=j.root/'history-fixture';sessions=native_home/'sessions';sessions.mkdir(parents=True)
        history=sessions/'worker.jsonl'
        header={'type':'session_meta','payload':{'id':'native-topic-7'}}
        tool={'type':'response_item','payload':{'type':'function_call','name':'inspect','arguments':'{"fixture":true}'}}
        result={'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'Late worker answer'}]}}
        relay={'type':'response_item','payload':{'type':'message','role':'user',
            'content':[{'type':'input_text','text':first.replace(
                '\nReturn your answer followed by <daimon-result>',
                '\nSelected creation context (source data):\n{"fixture":"receiving context"}\n\nReturn your answer followed by <daimon-result>')} ]}}
        history.write_text('\n'.join(map(json.dumps,[header,tool,relay]))+'\n')
        with sqlite3.connect(native_home/'state_5.sqlite') as db:
            db.execute('CREATE TABLE threads(id TEXT,rollout_path TEXT,archived INTEGER)')
            db.execute('INSERT INTO threads VALUES(?,?,0)',('native-topic-7',str(history)))
        b.provider.native_home=native_home
        url='/api/interaction/sessions/'+selected['id']
        assert [item['text'] for item in b.get(url)['items']]==['#Unknown Keep the exact original words.']
        first=b.get(url+'?technical=true');assert first['items'][0]['kind']=='tool_call'
        assert 'receiving context' in first['items'][1]['text']
        with history.open('a') as stream:stream.write(json.dumps(result))
        cursor='?technical=true&revision='+first['revision']+'&after='+str(first['after'])
        assert b.get(url+cursor)['items']==[]
        with history.open('a') as stream:stream.write('\n')
        assert b.get(url+cursor)['items'][0]['text']=='Late worker answer'
        print('PASS owned unregistered pin and exact latest-message reply: text + retained ASR voice start/steer the busy native worker without integrating work; selected technical-history HTTP waits for complete appended records; original receipts preserved; zero models.')
    finally:
        if b:b.client.close();b.provider.close()
        j.close()


def portable_activity(binary):
    j=ColdEntry(str(Path(binary).resolve()));b=None
    try:
        j.prepare()
        j.stop()
        config=j.config.read_text()
        targets=j.target_config.replace('topic_id=7','topic_id=7\nharness="goose"').replace(
            'topic_id=8','topic_id=8\nharness="goose"')
        j.config.write_text(config.replace(j.target_config,targets)+f'''
[interaction.goose_foreground]
interaction_direct=true
worker_command=["/usr/bin/false"]
[interaction.goose_foreground.transport]
command=["/usr/bin/false"]
source={{kind="body",being_ref="dm:being:v1:{'A'*43}",embodiment_id="embodiment:fixture-goose"}}
timeout_seconds=5
''')
        with sqlite3.connect(j.root/'state.sqlite') as db:
            db.execute('UPDATE sessions SET codex_thread_id=NULL WHERE thread_id=8')
            db.row_factory=sqlite3.Row
            source=inventory_source(db)
        j.start();j.wait_control_socket(j.socket);b=Browser(j)
        activity=j.root/'activity'
        activity.mkdir()
        snapshot=activity/'topics.json'
        snapshot.touch(mode=0o600)
        snapshot.write_text(json.dumps({'schema':'telecodex.topic-observations/v1','source':source,
            'connected':True,'observations':{'100:7':{'native':'native-topic-7','human':100,
            'observed_at':time.time(),'execution':'working','goal_state':'active',
            'tools_running':True,'waiting_for_human':True,'error':True}}}))
        b.provider.config['activity_state_dir']=str(activity)
        def rows():
            return {row['audio_key']:row for row in b.get('/api/interaction/sessions')['sessions']}
        current=rows()
        for key in ('100:7','100:8'):
            row=current[key]
            assert row['runtime']['harness']=='goose' and row['execution']=='idle' and row['fresh'],row
            assert row['goal_state']=='unknown' and row['tools_running'] is None and row['error'] is None,row
        with sqlite3.connect(j.root/'state.sqlite') as db:
            db.execute("""INSERT INTO turns(session_id,from_user_id,prompt,status,started_at,execution_harness)
                SELECT id,creator_user_id,'fixture','running',strftime('%Y-%m-%dT%H:%M:%SZ','now'),'goose'
                FROM sessions WHERE thread_id=8""")
        current=rows()
        assert current['100:7']['execution']=='idle' and current['100:8']['execution']=='working'
        print('PASS Activity follows the selected portable harness, even without an old native Codex binding.')
    finally:
        if b:b.client.close();b.provider.close()
        j.close()


if __name__=='__main__':
    qualify(sys.argv[1])
    portable_activity(sys.argv[1])
