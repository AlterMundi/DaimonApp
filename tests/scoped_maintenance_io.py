#!/usr/bin/env python3
"""Owner Unix socket, durable SQLite and conditional native metadata; zero real models."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import time
import threading
import uuid
from goal_activation_io import Activation


def qualify(binary):
    j=Activation(binary)
    try:
        j.prepare(seed_entry=True)
        j.allow_native_launch=True
        j.expected_origin='automatic'
        j.wait_control_socket(j.socket)
        native='native-topic-7'
        j.goals[native]={'threadId':native,'objective':'Keep original work and history','status':'active',
                         'tokenBudget':1000,'tokensUsed':42,'timeUsedSeconds':17,'createdAt':10,'updatedAt':11}
        def observed(): return j.owner('goal','inspect','100','7')
        def prepare(seconds=240):
            snapshot=observed()
            plan={'request_id':str(uuid.uuid4()),'source':'synthetic retained human scoped-maintenance approval',
                  'entry':{'chat_id':100,'thread_id':1},'deadline':int(time.time())+seconds,
                  'targets':[{'target':{'chat_id':100,'thread_id':7},'binding':snapshot['target_binding'],'snapshot':snapshot['snapshot']}]}
            doc=j.owner('goal','maintenance','prepare',json.dumps(plan))
            assert doc['targets'][0]['snapshot']==snapshot['snapshot']
            return plan['request_id']
        def status(i):return j.owner('goal','maintenance','status',i)
        def writes():return [m for m in j.rpc if m.get('method') in ('thread/goal/conditionalSet','thread/goal/conditionalActivate')]
        before=len(j.rpc)
        i=prepare()
        assert not writes()
        doc=j.owner('goal','maintenance','pause',i)
        assert doc['targets'][0]['phase']=='paused',doc
        assert j.goals[native]['status']=='paused'
        assert len(writes())==1
        # A repeated owner command must not install another continuation/write.
        j.owner('goal','maintenance','pause',i)
        assert len(writes())==1
        # There is no interpreting model turn or controller access file at all.
        j.stop();j.start();j.wait_control_socket(j.socket)
        j.wait(lambda:status(i)['targets'][0]['phase']=='restored')
        assert j.goals[native]['status']=='active'
        assert j.goals[native]['tokensUsed']==42 and j.goals[native]['timeUsedSeconds']==17
        assert len(writes())==2
        j.owner('goal','maintenance','restore',i)
        assert len(writes())==2
        assert not any(m.get('method') in ('turn/start','turn/steer','turn/interrupt') for m in j.rpc[before:])
        activation=[m for m in j.rpc[before:] if m.get('method')=='thread/goal/conditionalActivate']
        assert len(activation)==1 and activation[0]['params']['additionalContext'],activation
        def notice(packet,identity):
            value=packet['params']['additionalContext']['telecodex.maintenance']
            assert value['kind']=='application' and identity in value['value']
            assert 'not human speech' in value['value'] and 'synthetic retained human scoped-maintenance approval' in value['value']
            assert 'telecodex.goal.followup' not in packet['params']['additionalContext']
        notice(activation[0],i)
        assert status(i)['targets'][0]['restored_receipt']['notification_admitted'] is True
        # Reuse the now-attached collector: notify with the same CAS, no extra input.
        attached=prepare();j.owner('goal','maintenance','pause',attached)
        j.owner('goal','maintenance','restore',attached)
        j.wait(lambda:status(attached)['targets'][0]['phase']=='restored')
        packet=[m for m in j.rpc if m.get('method')=='thread/goal/conditionalActivate'][-1]
        notice(packet,attached)
        assert status(attached)['targets'][0]['restored_receipt']['notification_admitted'] is True
        # Four independent native acknowledgments must not serialize restoration.
        # Copy fictional enrollment only; production sessions are never touched.
        with sqlite3.connect(j.root/'state.sqlite') as db:
            db.row_factory=sqlite3.Row
            template=dict(db.execute('SELECT * FROM sessions WHERE thread_id=7').fetchone())
            for topic in (17,18):
                row={k:v for k,v in template.items() if k!='id'}
                row.update(thread_id=topic,codex_thread_id=f'native-topic-{topic}',session_title=f'Maintenance {topic}',busy=0)
                db.execute('INSERT INTO sessions ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')',list(row.values()))
        targets=[]
        for topic in (7,8,17,18):
            thread=f'native-topic-{topic}'
            j.goals[thread]={**copy.deepcopy(j.goals[native]),'threadId':thread,'status':'active'}
            selected=j.owner('goal','inspect','100',str(topic))
            targets.append({'target':{'chat_id':100,'thread_id':topic},'binding':selected['target_binding'],'snapshot':selected['snapshot']})
        four={'request_id':str(uuid.uuid4()),'source':'synthetic retained human scoped-maintenance approval',
              'entry':{'chat_id':100,'thread_id':1},'deadline':int(time.time())+300,'targets':targets}
        j.owner('goal','maintenance','prepare',json.dumps(four))
        j.owner('goal','maintenance','pause',four['request_id'])
        assert all(t['phase']=='paused' for t in status(four['request_id'])['targets'])
        held=[];release=threading.Event();original_handle=j.handle_extra_rpc
        def hold_restore(message,send):
            if message.get('method')=='thread/goal/conditionalActivate':
                held.append(copy.deepcopy(message))
                assert release.wait(8),'Restoration waited serially for a native acknowledgment'
            return original_handle(message,send)
        j.handle_extra_rpc=hold_restore
        try:
            doc=j.owner('goal','maintenance','restore',four['request_id'])
            j.wait(lambda:len(held)==4)
            assert all(t['phase']=='restore_submitted' for t in doc['targets'])
            assert all(j.goals[f'native-topic-{topic}']['status']=='paused' for topic in (7,8,17,18))
        finally:
            release.set()
        j.wait(lambda:all(t['phase']=='restored' for t in status(four['request_id'])['targets']))
        j.handle_extra_rpc=original_handle
        assert all(t['restored_receipt']['notification_admitted'] is True for t in status(four['request_id'])['targets'])
        for packet in held:notice(packet,four['request_id'])
        # A later native human decision invalidates exact restoration authority.
        i=prepare();j.owner('goal','maintenance','pause',i)
        j.revisions[native]+=1
        j.goals[native]['objective']='Later human objective'
        count=len(writes())
        doc=j.owner('goal','maintenance','restore',i)
        assert doc['targets'][0]['phase']=='superseded',doc
        assert len(writes())==count and j.goals[native]['status']=='paused'
        # Already paused goals are observed/preserved, never resumed by maintenance.
        i=prepare();doc=j.owner('goal','maintenance','pause',i)
        assert doc['targets'][0]['phase']=='preserved'
        j.owner('goal','maintenance','restore',i)
        assert len(writes())==count
        # A pause lost ACK may have taken effect. It stays explicit and unreplayed.
        j.goals[native]['status']='active';j.revisions[native]+=1
        i=prepare();j.lose_receipt=True
        doc=j.owner('goal','maintenance','pause',i)
        assert doc['targets'][0]['phase']=='pause_unconfirmed',doc
        count=len(writes());j.lose_receipt=False
        j.owner('goal','maintenance','restore',i)
        j.stop();j.start();j.wait_control_socket(j.socket)
        assert status(i)['targets'][0]['phase']=='pause_unconfirmed'
        assert len(writes())==count and j.goals[native]['status']=='paused'
        # Isolate a new synthetic target after the retained uncertain attempt.
        # A fresh target exercises the real finite deadline without a model lease.
        j.close()
        j=Activation(binary);j.prepare(seed_entry=True);j.expected_origin='automatic'
        j.wait_control_socket(j.socket)
        j.goals[native]={'threadId':native,'objective':'Finite deadline case','status':'active','tokenBudget':1000,'tokensUsed':42,'timeUsedSeconds':17,'createdAt':10,'updatedAt':11}
        i=prepare(101);j.owner('goal','maintenance','pause',i)
        count=len(writes())
        deadline=time.monotonic()+90
        while status(i)['targets'][0]['phase']!='restored':
            assert time.monotonic()<deadline,status(i)
            time.sleep(.5)
        assert len(writes())==count+1 and j.goals[native]['status']=='active'
        print('PASS owner transaction before pause; no interpreter; restart exact restoration; no duplicate resume; accounting; prior paused/later decision; lost ACK preserved; zero model/input/interrupt/lifecycle operations')
    finally:j.close()

if __name__=='__main__':qualify(str(Path(sys.argv[1]).resolve()))
