#!/usr/bin/env python3
"""Owner Unix socket, durable SQLite and conditional native metadata; zero real models."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import time
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
