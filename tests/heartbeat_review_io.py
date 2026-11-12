#!/usr/bin/env python3
"""Owner console/store/worker journey with synthetic native; zero real providers."""
from datetime import datetime, timedelta, timezone
import json
import hashlib
from pathlib import Path
import sys
import uuid
from heartbeat_io import HeartbeatJourney


def qualify(binary, production=False, periodic=False, projection=False):
    assert not projection or periodic, "Projection requires the existing periodic Reports fixture"
    j = HeartbeatJourney(str(Path(binary).resolve()))
    try:
        if production:j.expected_attempts=64
        j.start()
        for topic in (7, 8, 1):
            j.admit('Seed this synthetic owned context', topic=topic)
            j.wait(lambda: j.has('Initial goal turn delivered.', topic)); j.idle()
        j.stop()
        j.config.write_text(j.config.read_text().replace('[telegram]', '[telegram]\nenabled=false') + j.target_config)
        if projection:
            snapshot = j.root/'projection-source.json'
            snapshot.write_text('{"selected":"original"}')
            reconciliation = j.root/'projection-cursor.json'
            helper = j.root/'projection-helper.py'
            helper.write_text("""import sys,json,hashlib,pathlib
raw=sys.stdin.buffer.read()
if '--inspect-stdin' not in sys.argv:
 pathlib.Path(__file__).with_suffix('.runs').write_text('one')
 print(json.dumps({'source_sha256':hashlib.sha256(raw).hexdigest(),'state':'unknown_effect'}))
else:
 assert json.loads(raw)=={'selected':'original'}
 print(json.dumps({'source_sha256':hashlib.sha256(raw).hexdigest(),'state':'existing_projection_verified','artifact_ref':'fixture-artifact','version_ref':'fixture-version','immutable_files_match':True,'owner_broker_all_files_match':True,'checkpoint_matches':False}))
""")
            with j.config.open('a') as stream:
                stream.write('\n[interaction.private_projection]\n'+
                    'task_id="bitacora"\ncommand='+json.dumps(['/usr/bin/python3',str(helper)])+'\n'+
                    'working_directory='+json.dumps(str(j.root))+'\n'+
                    'snapshot='+json.dumps(str(snapshot))+'\n'+
                    'reconciliation='+json.dumps(str(reconciliation))+'\n'+
                    'reconciliation_return_pointer="/latest_check/heartbeat_return"\n'+
                    'reconciliation_partial_pointer="/latest_check/partial"\ntimeout_seconds=2\n')
        j.start(); j.wait_control_socket(j.socket); j.routing = True
        binding = j.read('presentation', 'list', '0', '0')['result']['binding']
        purpose_text = ('Review selected child deployment milestones in production; preserve messaging.' if production else
                        'Review selected child deployment milestones within the remaining shared pilot; preserve messaging.')
        original, _ = j.submit(binding, purpose_text)
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
        if production:
            # Disposable fixture: prove production never revives the exhausted pilot.
            j.row("UPDATE bot_state SET value=json_set(value,'$.reserved_provider_attempts',12,'$.continuous.reserved_in_window',12,'$.continuous.reserved_provider_attempts',12) WHERE key LIKE 'heartbeat_resources:%'")
            prior=j.read('heartbeat','status')['result']['resources']
            selected=j.read('heartbeat','production-defaults',generation,json.dumps('synthetic explicit production direction'))['result']['resources']
            assert selected['reserved_provider_attempts']==prior['reserved_provider_attempts']==12
            assert selected['continuous']['window_started_at_unix_ms']==prior['continuous']['window_started_at_unix_ms']
            assert selected['production']['max_executions_per_hour']==48
            assert selected['remaining_execution_envelopes']==47
            assert selected['effective_execution']['provider_attempts_per_execution']==64
            assert selected['effective_execution']['execution_seconds']==600
        report = j.root / 'selected-progress.json'
        report.write_text(json.dumps({'milestone':'synthetic checkpoint A','clock':1}))
        review = dict(purpose={'input_ref':original['id'],'channel':'conversation'},
                      reports=[dict(id='children',path=str(report),pointers=['/milestone'])],
                      interval_seconds=900,max_checks=96,expires_at_unix_ms=expiry)
        if production:
            review.update(production=True,max_checks=None,expires_at_unix_ms=None)
        before = j.read('heartbeat','status')['result']
        selected = j.read('heartbeat','select-review',generation,json.dumps(review))['result']
        assert selected['generation'] == before['generation']
        assert selected['lanes'] == before['lanes']
        assert selected['resources'] == before['resources']
        assert selected['producer']['checks'] == before['producer']['checks']
        assert selected['producer']['finite_review']['state'] == 'configured'
        assert all(l['paused'] for l in selected['lanes'].values())
        if periodic:
            before_task=j.read('heartbeat','status')['result']
            task=dict(id='bitacora',purpose=review['purpose'],purpose_revision='',instructions='Reconcile institutional intake with persistent cursors; preserve originals before cache cleanup; no publication.')
            task_selected=j.read('heartbeat','select-review-task',generation,json.dumps(task))['result']
            expected=task_selected['producer']['finite_review']['periodic_tasks'][0]['revision']
            task['instructions'] += ' Refresh the same private viewer only after meaningful changes.'
            task_selected=j.read('heartbeat','replace-review-task',generation,expected,json.dumps(task))['result']
            assert task_selected['producer']['finite_review']['periodic_tasks'][0]['revision'] != expected
            assert task_selected['resources']==before_task['resources']
            assert task_selected['producer']['finite_review']['checks']==before_task['producer']['finite_review']['checks']
            assert task_selected['producer']['finite_review']['next_check_ms']==before_task['producer']['finite_review']['next_check_ms']
            assert task_selected['producer']['finite_review']['contract']==before_task['producer']['finite_review']['contract']
        j.read('heartbeat','resume-lane','reports',str(selected['lanes']['reports']['generation']))
        j.read('heartbeat','resume',generation)
        j.wait(lambda:j.read('heartbeat','status')['result']['producer']['finite_review']['checks']>=1,seconds=45)
        waiting=j.read('heartbeat','status')['result']
        assert waiting['producer']['pending'] and waiting['resources']['reserved_provider_attempts']==(12 if production else 0)
        assert len(j.bounded)==0, 'Busy observation must retain metadata without a native/model request'
        if production:
            # Yield the completed collector without changing the actual goal.
            goal=dict(threadId=j.web_thread,objective='Preserve synthetic ongoing goal',status='active',tokenBudget=None,tokensUsed=17,timeUsedSeconds=3,createdAt=1,updatedAt=1)
            j.goals[j.web_thread]=goal.copy()
            j.broadcast(j.web_thread,'thread/goal/updated',{'goal':goal})
        native_reads=sum(m.get('method')=='thread/read' and m.get('params',{}).get('threadId')==j.web_thread for m in j.rpc)
        if production:j.native_fixture_busy=True
        j.broadcast(j.web_thread,'turn/completed',{'turn':{'id':j.web_turn,'status':'completed'}}); j.idle()
        if production:
            j.wait(lambda:sum(m.get('method')=='thread/read' and m.get('params',{}).get('threadId')==j.web_thread for m in j.rpc)>native_reads,seconds=45)
            assert len(j.bounded)==0, 'Known native contention spent an execution envelope'
            assert j.read('heartbeat','status')['result']['resources']['reserved_provider_attempts']==12
            j.native_fixture_busy=False

        j.wait(lambda:len(j.bounded)==1,seconds=45)
        j.wait(lambda:j.row("SELECT count(*) FROM bot_state,json_each(bot_state.value,'$.native_returns') r WHERE bot_state.key LIKE 'heartbeat_producer:%' AND json_extract(r.value,'$.phase')='accepted'")==[(1,)])
        packet=json.loads(j.bounded[0]['turn']['toolOutput']['output'])
        purpose=packet['evidence']['operating_purpose']; read=j.call('route-purpose',purpose['reader']['operation'],purpose['reader']['arguments'])
        assert read['input_ref']==original['id'] and read['retained_human_original']
        assert purpose_text in read['text']
        offer=packet['evidence']['offers'][0]; reader=offer['evidence']['reader']
        read=j.call('route-report',reader['operation'],dict(reader['arguments'],return_id=packet['return_id']))
        assert 'synthetic checkpoint A' in json.dumps(read)
        if periodic:
            task_offer=next(o for o in packet['evidence']['offers'] if o['key']=='review-task:bitacora')
            reader=task_offer['evidence']['reader']
            task_read=j.call('route-periodic',reader['operation'],dict(reader['arguments'],return_id=packet['return_id']))
            assert 'Reconcile institutional intake' in task_read['text'] and purpose_text in task_read['text']
        if projection:
            reconciliation.write_text(json.dumps({'latest_check':{'heartbeat_return':packet['return_id'],'partial':False}}))
            action=dict(action='run',return_id=packet['return_id'],batch_revision=packet['evidence']['revision'],
                task_revision=task_offer['revision'],snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                reconciliation_sha256=hashlib.sha256(reconciliation.read_bytes()).hexdigest())
            result=j.call('route-projection-run','private_projection',action)
            assert result['outcome']['phase']=='unconfirmed', result
            status=j.call('route-projection-held','private_projection',dict(action='status'))
            assert status['input_retained'] is True and 'original' not in json.dumps(status), status
            snapshot.write_text('{"selected":"later mutable input"}')
            observed=j.call('route-projection-inspect','private_projection',dict(action='inspect',invocation=result['invocation']))
            assert observed['current']['phase']=='observed' and not observed['input_retained'], observed
            assert observed['current']['outcome']['verification_only'] is True, observed
            assert observed['current']['outcome']['original_invocation_execution']=='not_established', observed
            action['snapshot_sha256']=hashlib.sha256(snapshot.read_bytes()).hexdigest()
            again=j.call('route-projection-repeat','private_projection',action)
            assert again.get('claimed') is False, again
            assert helper.with_suffix('.runs').read_text()=='one'
        j.call('route-reviewed','heartbeat_reported',{'return_id':packet['return_id'],'revision':packet['evidence']['revision']})
        j.broadcast(j.web_thread,'turn/completed',{'turn':{'id':j.web_turn,'status':'completed'}}); j.idle()
        j.wait(lambda:j.read('heartbeat','status')['result']['executions'][0]['phase']=='terminal')
        assert j.read('heartbeat','status')['result']['resources']['reserved_provider_attempts']==(12 if production else 3)
        if production and not periodic:
            # An ordinary goal starts after the bounded collector closes. Only
            # metadata and exact collector attachment may bridge that gap.
            before_calls=len([m for m in j.rpc if m.get('method') in ('turn/start','turn/steer','turn/startBoundedIfIdle','thread/goal/set')])
            before_resources=j.read('heartbeat','status')['result']['resources']
            j.native_fixture_busy=True
            j.native_continuation='existing-ordinary-goal-successor'
            j.web_turn=j.native_continuation
            j.row("UPDATE bot_state SET value=json_set(value,'$.next_check_ms',0,'$.review.next_check_ms',0) WHERE key LIKE 'heartbeat_producer:%'")
            j.wait(lambda:j.row("SELECT count(*) FROM bot_state WHERE key LIKE 'collector_attachment:%' AND json_extract(value,'$.native_turn')=?",(j.native_continuation,))==[(1,)],seconds=45)
            assert before_calls==len([m for m in j.rpc if m.get('method') in ('turn/start','turn/steer','turn/startBoundedIfIdle','thread/goal/set')]), 'Collection must not start or steer native work'
            assert j.goals[j.web_thread]==goal
            assert j.read('heartbeat','status')['result']['resources']==before_resources
            assert len(j.bounded)==1
        # Advance only this disposable fixture's clock fence. An unchanged field
        # projection must not create another bounded execution.
        report.write_text(json.dumps({'milestone':'synthetic checkpoint A','clock':2}))
        j.row("UPDATE bot_state SET value=json_set(value,'$.next_check_ms',0,'$.review.next_check_ms',0) WHERE key LIKE 'heartbeat_producer:%'")
        j.wait(lambda:j.read('heartbeat','status')['result']['producer']['finite_review']['checks']>=2,seconds=45)
        if periodic:
            j.wait(lambda:len(j.bounded)==2,seconds=45)
            second=json.loads(j.bounded[1]['turn']['toolOutput']['output'])
            assert [o['key'] for o in second['evidence']['offers']]==['review-task:bitacora'], 'Unchanged ordinary report must remain quiet'
            assert second['evidence']['offers'][0]['revision']!=task_offer['revision']
            j.call('route-periodic-again','heartbeat_reported',{'return_id':second['return_id'],'revision':second['evidence']['revision']})
            j.broadcast(j.web_thread,'turn/completed',{'turn':{'id':j.web_turn,'status':'completed'}});j.idle()
            j.wait(lambda:j.read('heartbeat','status')['result']['executions'][0]['phase']=='terminal')
        else:
            assert len(j.bounded)==1
        status=j.read('heartbeat','pause-lane','reports')['result']
        funding=status['resources'];j.stop();j.start();j.wait_control_socket(j.socket)
        restarted=j.read('heartbeat','status')['result']
        assert restarted['lanes']['reports']['paused'] and restarted['resources']==funding
        if production:
            j.row("UPDATE bot_state SET value=json_set(value,'$.review.checks',10000,'$.checks',10000,'$.contract.expires_at_unix_ms',1) WHERE key LIKE 'heartbeat_producer:%'")
        else:
            j.row("UPDATE bot_state SET value=json_set(value,'$.review.contract.expires_at_unix_ms',1) WHERE key LIKE 'heartbeat_producer:%'")
        status=j.read('heartbeat','status')['result']
        assert status['producer']['finite_review']['state']==('configured' if production else 'expired')
        assert status['resources']==funding and status['producer']['mode']=='continuous'
        assert len(j.bounded)==(2 if periodic else 1)
        if periodic:assert restarted['producer']['finite_review']['periodic_tasks'][0]['id']=='bitacora'
        if production:
            assert j.goals[j.web_thread]==goal, 'Heartbeat handoff changed native goal or accounting'
        print('finite review owner selection/purpose/source/one bounded execution/no-change/pause/restart/expiry: PASS; synthetic native, real providers=0')
    finally:
        j.close()

if __name__ == '__main__':
    if '--projection' in sys.argv[2:]:
        qualify(sys.argv[1],True,True,True)
    elif '--periodic' in sys.argv[2:]:
        qualify(sys.argv[1],True,True)
    elif '--production' in sys.argv[2:]:
        qualify(sys.argv[1], True)
    elif '--finite' in sys.argv[2:]:
        qualify(sys.argv[1], False)
    else:
        qualify(sys.argv[1], False)
        qualify(sys.argv[1], True)
