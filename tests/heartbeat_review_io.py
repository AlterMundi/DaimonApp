#!/usr/bin/env python3
"""Owner console/store/worker journey with synthetic native; zero real providers."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import uuid
from heartbeat_io import HeartbeatJourney


def qualify(binary):
    j = HeartbeatJourney(str(Path(binary).resolve()))
    try:
        j.start()
        for topic in (7, 8, 1):
            j.admit('Seed this synthetic owned context', topic=topic)
            j.wait(lambda: j.has('Initial goal turn delivered.', topic)); j.idle()
        j.stop()
        j.config.write_text(j.config.read_text().replace('[telegram]', '[telegram]\nenabled=false') + j.target_config)
        j.start(); j.wait_control_socket(j.socket); j.routing = True
        binding = j.read('presentation', 'list', '0', '0')['result']['binding']
        original, _ = j.submit(binding, 'Review selected child deployment milestones within the remaining shared pilot; preserve messaging.')
        j.wait(lambda: j.row('SELECT phase FROM conversation_inputs WHERE id=?', (original['id'],)) == [('accepted',)])
        paused = j.read('heartbeat', 'pause')['result']; generation = str(paused['generation'])
        expiry = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()*1000)
        resources = dict(contract_id=str(uuid.uuid4()), max_provider_attempts=12,
                         provider_attempts_per_execution=3, max_request_bytes=1024*1024,
                         execution_seconds=60, expires_at_unix_ms=expiry)
        j.read('heartbeat', 'configure-resources', generation, json.dumps(resources))
        producer = dict(interval_seconds=30, max_checks=4, expires_at_unix_ms=expiry,
                        matrix_replies=True, workflows=False)
        j.read('heartbeat', 'configure-producer', generation, json.dumps(producer))
        j.read('heartbeat', 'continuous', generation, '12')
        report = j.root / 'selected-progress.json'
        report.write_text(json.dumps({'milestone':'synthetic checkpoint A','clock':1}))
        review = dict(purpose={'input_ref':original['id'],'channel':'conversation'},
                      reports=[dict(id='children',path=str(report),pointers=['/milestone'])],
                      interval_seconds=900,max_checks=96,expires_at_unix_ms=expiry)
        before = j.read('heartbeat','status')['result']
        selected = j.read('heartbeat','select-review',generation,json.dumps(review))['result']
        assert selected['generation'] == before['generation']
        assert selected['lanes'] == before['lanes']
        assert selected['resources'] == before['resources']
        assert selected['producer']['checks'] == before['producer']['checks']
        assert selected['producer']['finite_review']['state'] == 'configured'
        assert all(l['paused'] for l in selected['lanes'].values())
        j.read('heartbeat','resume-lane','reports',str(selected['lanes']['reports']['generation']))
        j.read('heartbeat','resume',generation)
        j.broadcast(j.web_thread,'turn/completed',{'turn':{'id':j.web_turn,'status':'completed'}}); j.idle()
        j.wait(lambda:len(j.bounded)==1,seconds=45)
        j.wait(lambda:j.row("SELECT count(*) FROM bot_state,json_each(bot_state.value,'$.native_returns') r WHERE bot_state.key LIKE 'heartbeat_producer:%' AND json_extract(r.value,'$.phase')='accepted'")==[(1,)])
        packet=json.loads(j.bounded[0]['turn']['toolOutput']['output'])
        purpose=packet['evidence']['operating_purpose']; read=j.call('route-purpose',purpose['reader']['operation'],purpose['reader']['arguments'])
        assert read['input_ref']==original['id'] and read['retained_human_original']
        assert 'remaining shared pilot' in read['text']
        offer=packet['evidence']['offers'][0]; reader=offer['evidence']['reader']
        read=j.call('route-report',reader['operation'],dict(reader['arguments'],return_id=packet['return_id']))
        assert 'synthetic checkpoint A' in json.dumps(read)
        j.call('route-reviewed','heartbeat_reported',{'return_id':packet['return_id'],'revision':packet['evidence']['revision']})
        j.broadcast(j.web_thread,'turn/completed',{'turn':{'id':j.web_turn,'status':'completed'}}); j.idle()
        j.wait(lambda:j.read('heartbeat','status')['result']['executions'][0]['phase']=='terminal')
        assert j.read('heartbeat','status')['result']['resources']['reserved_provider_attempts']==3
        # Advance only this disposable fixture's clock fence. An unchanged field
        # projection must not create another bounded execution.
        report.write_text(json.dumps({'milestone':'synthetic checkpoint A','clock':2}))
        j.row("UPDATE bot_state SET value=json_set(value,'$.next_check_ms',0,'$.review.next_check_ms',0) WHERE key LIKE 'heartbeat_producer:%'")
        j.wait(lambda:j.read('heartbeat','status')['result']['producer']['finite_review']['checks']>=2,seconds=45)
        assert len(j.bounded)==1
        status=j.read('heartbeat','pause-lane','reports')['result']
        funding=status['resources'];j.stop();j.start();j.wait_control_socket(j.socket)
        restarted=j.read('heartbeat','status')['result']
        assert restarted['lanes']['reports']['paused'] and restarted['resources']==funding
        j.row("UPDATE bot_state SET value=json_set(value,'$.review.contract.expires_at_unix_ms',1) WHERE key LIKE 'heartbeat_producer:%'")
        status=j.read('heartbeat','status')['result']
        assert status['producer']['finite_review']['state']=='expired'
        assert status['resources']==funding and status['producer']['mode']=='continuous'
        assert len(j.bounded)==1
        print('finite review owner selection/purpose/source/one bounded execution/no-change/pause/restart/expiry: PASS; synthetic native, real providers=0')
    finally:
        j.close()

if __name__=='__main__':qualify(sys.argv[1])
