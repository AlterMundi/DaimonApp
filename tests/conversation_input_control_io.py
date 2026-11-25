#!/usr/bin/env python3
"""Original non-Telegram text through the actual owner socket/native worker.

All accounts, Telegram, native peers and output are synthetic; zero model calls.
"""
import json
import hashlib
import errno
import os
import time
import re
import signal
import socket
from pathlib import Path
import subprocess
import sqlite3
import sys
import threading
import uuid
from goals_io import Goals


class Inputs(Goals):
    def __init__(self,binary):
        self.packets=[]
        self.drop_ack=False
        self.native_ack_delay=0
        self.web_thread=None
        self.web_turn=None
        self.late_ack=None
        self.hold_telegram=False
        self.telegram_methods=[]
        self.native_answers=[]
        self.hold_resume=False
        self.resume_seen=threading.Event()
        self.resume_release=threading.Event()
        super().__init__(binary)
        self.socket=self.root/'control.sock'
        config=self.config.read_text().replace('[telegram]',f'[session_control]\nsocket_path="{self.socket}"\nhuman_id=100\n[telegram]')
        self.config.write_text(config+'\n[interaction]\nhuman_id=100\nchat_id=100\ntopic_id=1\n')

    def read(self,*arguments,ok=True):
        run=subprocess.run([self.binary,'--control',str(self.config),*arguments],capture_output=True,text=True,timeout=15)
        assert (run.returncode==0)==ok,run.stderr
        return json.loads(run.stdout)

    def submit(self,binding,text,ident=None,ok=True):
        body={'id':ident or str(uuid.uuid4()),'binding':binding,'text':text}
        return body,self.read('input','submit',json.dumps(body),ok=ok)

    def handle_extra_rpc(self,message,send):
        method=message.get('method');params=message.get('params',{})
        if method is None and message.get('id') in ('canonical-question','canonical-approval'):
            self.native_answers.append(message)
            return True
        if method=='thread/resume' and self.hold_resume:
            self.resume_seen.set()
            assert self.resume_release.wait(timeout=10),'Synthetic resume was never released'
        selected=params.get('clientUserMessageId','')
        if method not in ('turn/start','turn/steer') or not (selected.startswith('conversation:') or self.hold_telegram and selected.startswith('telegram:')):
            return False
        self.packets.append((method,params))
        self.web_thread=params['threadId']
        if method=='turn/start':
            self.web_turn='conversation-turn-'+str(len(self.packets))
            if self.native_ack_delay:time.sleep(self.native_ack_delay)
            send({'id':message['id'],'result':{'turn':{'id':self.web_turn}}})
            self.broadcast(self.web_thread,'turn/started',{'turn':{'id':self.web_turn,'status':'inProgress'}})
        elif not self.drop_ack:
            send({'id':message['id'],'result':{'turnId':self.web_turn}})
        else:
            self.late_ack=(send,message['id'],self.web_turn)
        return True



def reconsider_queued_steer(binary):
    class RecoveringSteer(Inputs):
        refused = None
        mismatched = None
        held_refusals = frozenset()

        def handle_extra_rpc(self, message, send):
            params = message.get('params', {})
            selected = params.get('clientUserMessageId')
            if message.get('method') == 'turn/steer' and (selected == self.refused or selected in self.held_refusals):
                self.refused = None
                self.packets.append(('turn/steer', params))
                send({'id': message['id'], 'error': {'code': -32602, 'message': 'Synthetic definitive refusal'}})
                return True
            if message.get('method') == 'turn/steer' and params.get('clientUserMessageId') == self.mismatched:
                self.packets.append(('turn/steer', params))
                send({'id': message['id'], 'result': {'turnId': 'different-turn'}})
                return True
            return super().handle_extra_rpc(message, send)

    journey = RecoveringSteer(binary)
    try:
        journey.start()
        journey.admit('Seed integrating conversation', topic=1)
        journey.wait(lambda: journey.has('Initial goal turn delivered.', 1))
        journey.idle()
        journey.wait_control_socket(journey.socket)
        binding = journey.read('presentation', 'list', '0', '0')['result']['binding']
        _, first = journey.submit(binding, 'Hold this native turn open.')
        assert first['ok']
        journey.wait(lambda: journey.web_turn is not None)
        older = str(uuid.uuid4())
        journey.refused = 'conversation:' + older
        journey.submit(binding, 'Older message rejected by the active native turn.', older)
        def phase(ident):
            return journey.row('SELECT phase FROM conversation_inputs WHERE id=?', (ident,))[0][0]
        journey.wait(lambda: phase(older) == 'queued')
        assert journey.row("SELECT json_extract(doc,'$.steer_wait_reason') FROM conversation_inputs WHERE id=?", (older,)) == [('steer_rejected',)]
        newer, _ = journey.submit(binding, 'New message after steer is available again.')
        journey.wait(lambda: phase(older) == phase(newer['id']) == 'accepted')
        active = journey.web_turn
        sent = [(method, packet['clientUserMessageId']) for method, packet in journey.packets]
        assert sent[-3:] == [
            ('turn/steer', 'conversation:' + older),
            ('turn/steer', 'conversation:' + older),
            ('turn/steer', 'conversation:' + newer['id']),
        ], sent
        assert all(packet.get('expectedTurnId') == active for method, packet in journey.packets if method == 'turn/steer')
        unknown = str(uuid.uuid4())
        journey.mismatched = 'conversation:' + unknown
        journey.submit(binding, 'The native acknowledgement does not match the original turn.', unknown)
        journey.wait(lambda: phase(unknown) == 'uncertain')
        later, _ = journey.submit(binding, 'This later message must not reoffer the uncertain original.')
        journey.wait(lambda: phase(later['id']) == 'accepted')
        assert phase(unknown) == 'uncertain'
        assert sum(packet['clientUserMessageId'] == journey.mismatched for _, packet in journey.packets) == 1
        journey.finish(journey.web_thread, active)
        journey.idle()
        assert sum(method == 'turn/start' for method, _ in journey.packets) == 1

        # The next native turn itself triggers reconsideration, even without
        # another inbound message once the original floor closes.
        second, _ = journey.submit(binding, 'Hold a second native turn open.')
        journey.wait(lambda: phase(second['id']) == 'accepted')
        before = journey.web_turn
        first_queued, next_queued = str(uuid.uuid4()), str(uuid.uuid4())
        journey.held_refusals = {'conversation:' + ident for ident in (first_queued, next_queued)}
        journey.submit(binding, 'An earlier input ready for the next turn.', first_queued)
        journey.wait(lambda: phase(first_queued) == 'queued')
        journey.submit(binding, 'Another saved input ready for reconsideration.', next_queued)
        journey.wait(lambda: phase(first_queued) == phase(next_queued) == 'queued')
        journey.held_refusals = frozenset()
        journey.finish(journey.web_thread, before)
        journey.wait(lambda: phase(first_queued) == phase(next_queued) == 'accepted')
        assert journey.web_turn != before
        assert any(method == 'turn/steer' and packet.get('expectedTurnId') == journey.web_turn
                   and packet['clientUserMessageId'] in {'conversation:' + first_queued, 'conversation:' + next_queued}
                   for method, packet in journey.packets)
        assert sum(packet['clientUserMessageId'] == journey.mismatched for _, packet in journey.packets) == 1
        journey.finish(journey.web_thread, journey.web_turn)
        journey.idle()
        print('PASS queued steer after a later arrival and a new native turn; stale queue entries and unknown acknowledgements cause no replay')
    finally:
        journey.close()


def foreground_retention(binary):
    journey=Inputs(binary)
    try:
        journey.start()
        journey.admit('Seed the existing integrating conversation.',topic=1)
        journey.wait(lambda:journey.has('Initial goal turn delivered.',1))
        journey.idle()
        journey.wait_control_socket(journey.socket)
        binding=journey.read('presentation','list','0','0')['result']['binding']
        initial_turns=journey.row('SELECT count(*) FROM turns')
        initial_packets=list(journey.packets)
        original={'binding':binding,'id':str(uuid.uuid4()),'text':'  Una idea sin delegar todavía. 🦉\n',
                  'dialogue_id':str(uuid.uuid4()),'capture_questions':{}}
        def retain(body=original,ok=True):
            return journey.read('input','foreground','retain',json.dumps(body),ok=ok)
        first=retain()['result']
        assert first['new_input'] and first['phase']=='foreground'
        assert first['text']==original['text'] and first['foreground_dialogue']==original['dialogue_id']
        assert first['native_acceptance']=='not_requested' and first['local_turn'] is None
        assert not retain()['result']['new_input']
        assert not retain({**original,'text':'Rewritten as work'},ok=False)['ok']
        assert not retain({**original,'dialogue_id':str(uuid.uuid4())},ok=False)['ok']
        assert not journey.read('input','submit',json.dumps({k:original[k] for k in ('binding','id','text')}),ok=False)['ok']
        status=journey.read('input','status',original['id'])['result']
        assert status['phase']=='foreground' and status['text']==original['text']
        history=journey.read('input','list','0')['result']['items']
        listed=next(item for item in history if item['id']==original['id'])
        assert listed['phase']=='foreground' and listed['foreground_dialogue']==original['dialogue_id']
        assert journey.row('SELECT count(*) FROM original_ingress_order WHERE event_id=?',(original['id'],))==[(1,)]
        assert journey.row('SELECT count(*) FROM turns')==initial_turns
        assert journey.packets==initial_packets,'Foreground retention started native work'
        print('PASS foreground original retained once, immutable and visible; no native work admission; zero models.')
    finally:
        journey.close()



def foreground_delegation(binary):
    journey=Inputs(binary)
    try:
        journey.start();journey.admit('Seed integrating conversation.',topic=1)
        journey.wait(lambda:journey.has('Initial goal turn delivered.',1));journey.idle()
        journey.wait_control_socket(journey.socket)
        binding=journey.read('presentation','list','0','0')['result']['binding']
        dialogue=str(uuid.uuid4());originals=[]
        for text in ('Build the selected report without publishing.','#UnknownWorker Use nineteen, not seventeen.'):
            body={'binding':binding,'id':str(uuid.uuid4()),'text':text,'dialogue_id':dialogue}
            journey.read('input','foreground','retain',json.dumps(body));originals.append(body)
        assert not journey.packets
        latest=originals[-1]
        delegated={'binding':binding,'id':latest['id'],'intent_id':str(uuid.uuid4()),
                   'formulation':'Prepare the report with nineteen. Keep it private.',
                   'source_ids':[body['id'] for body in originals]}
        result=journey.read('input','foreground','delegate',json.dumps(delegated))['result']
        assert result['new_input']
        journey.wait(lambda:journey.row('SELECT phase FROM conversation_inputs WHERE id=?',(latest['id'],))==[('accepted',)])
        assert len(journey.packets)==1
        packet=journey.packets[0][1]
        text=packet['input'][0]['text']
        assert 'assistant-authored derivative' in text and delegated['formulation'] in text
        assert all(original['text'] in text for original in originals)
        assert packet['clientUserMessageId']=='conversation:'+latest['id']
        repeated=journey.read('input','foreground','delegate',json.dumps(delegated))['result']
        assert not repeated['new_input'] and repeated['phase']=='accepted'
        assert not journey.read('input','foreground','delegate',json.dumps({**delegated,'formulation':'Changed request'}),ok=False)['ok']
        assert len(journey.packets)==1,'Exact delegation retry duplicated integrator work'
        assert journey.read('input','status',originals[0]['id'])['result']['phase']=='foreground'
        journey.finish(journey.web_thread,journey.web_turn);journey.idle()
        print('PASS sourced foreground formulation enters only the integrator once; originals and retry attribution preserved; zero models.')
    finally:journey.close()


def qualify(binary):
    journey=Inputs(binary)
    try:
        journey.start()
        journey.admit('Seed existing integrating conversation',topic=1)
        journey.wait(lambda:journey.has('Initial goal turn delivered.',1))
        journey.idle()
        journey.wait_control_socket(journey.socket)
        initial_journal=journey.row('SELECT count(*) FROM incoming_updates')
        binding=journey.read('presentation','list','0','0')['result']['binding']
        journey.messages.clear()
        text='  Original browser text. ¿Y la corrección? 🦉\n'+'A complex requirement remains exact. '*200
        original,result=journey.submit(binding,text)
        assert result['ok'] and result['result']['new_input']
        journey.wait(lambda:journey.row('SELECT phase FROM conversation_inputs WHERE id=?',(original['id'],))==[('accepted',)])
        assert len(journey.packets)==1 and journey.packets[0][0]=='turn/start'
        assert text in journey.packets[0][1]['input'][0]['text']
        local_turn=journey.row('SELECT local_turn FROM conversation_inputs WHERE id=?',(original['id'],))[0][0]
        assert isinstance(local_turn,int) and local_turn>0
        status=journey.read('input','status',original['id'])['result']
        assert status.get('local_turn')==local_turn,'Accepted input status omitted its canonical native turn'
        history=journey.read('input','list','0')['result']['items']
        listed=next(item for item in history if item['id']==original['id'])
        assert listed.get('local_turn')==local_turn,'Input history omitted its canonical native turn'
        correction,_=journey.submit(binding,'A later correction must enter this running native turn.')
        journey.wait(lambda:journey.row('SELECT phase FROM conversation_inputs WHERE id=?',(correction['id'],))==[('accepted',)])
        assert len(journey.packets)==2 and journey.packets[1][0]=='turn/steer'
        repeated=journey.read('input','submit',json.dumps(correction))['result']
        assert not repeated['new_input'] and repeated['phase']=='accepted'
        assert repeated.get('local_turn')==local_turn,'Same-turn correction lost its native correlation'
        forged={**correction,'text':'Replacement of the retained original'}
        assert not journey.read('input','submit',json.dumps(forged),ok=False)['ok']
        assert len(journey.packets)==2
        journey.drop_ack=True
        uncertain,_=journey.submit(binding,'This synthetic steer loses its acknowledgment.')
        journey.wait(lambda:journey.row('SELECT phase FROM conversation_inputs WHERE id=?',(uncertain['id'],))==[('uncertain',)],seconds=18)
        retained=journey.read('input','submit',json.dumps(uncertain))['result']
        assert retained['phase']=='uncertain' and not retained['new_input']
        assert len(journey.packets)==3
        send,ident,turn=journey.late_ack
        send({'id':ident,'result':{'turnId':turn}})
        journey.wait(lambda:journey.row('SELECT phase FROM conversation_inputs WHERE id=?',(uncertain['id'],))==[('accepted',)])
        assert len(journey.packets)==3,'Late acknowledgment caused another submission'
        assert journey.read('input','status',uncertain['id'])['result'].get('local_turn')==local_turn,'Late acknowledgment did not expose the retained turn'
        assert journey.row('SELECT count(*) FROM incoming_updates')==initial_journal,'Browser input fabricated a Telegram update'
        journey.finish(journey.web_thread,journey.web_turn)
        journey.idle()
        assert not journey.messages,'Browser work was published to Telegram'
        # Revocation while the actual native resume is held must not be undone
        # by its late ThreadStarted callback. No global Stop is used.
        for change in ('clear','hold'):
            journey.hold_resume=True
            journey.resume_seen.clear();journey.resume_release.clear()
            pending,_=journey.submit(binding,'Do not submit after '+change)
            assert journey.resume_seen.wait(timeout=8),'Native resume boundary not reached'
            correction,_=journey.submit(binding,'Correction admitted while root prepares: '+change)
            journey.wait(lambda:journey.row('SELECT phase FROM conversation_inputs WHERE id=?',(correction['id'],))==[('steering',)])
            with sqlite3.connect(journey.root/'state.sqlite') as db:
                if change=='clear':
                    db.execute('UPDATE sessions SET codex_thread_id=NULL,force_fresh_thread=1 WHERE thread_id=1')
                else:
                    db.execute("INSERT INTO bot_state(key,value) VALUES('native_writer_hold:100:1','fixture-hold')")
            journey.resume_release.set()
            journey.wait(lambda:journey.row('SELECT phase FROM conversation_inputs WHERE id=?',(pending['id'],))==[('retained_unsent',)])
            journey.wait(lambda:journey.row('SELECT phase FROM conversation_inputs WHERE id=?',(correction['id'],))==[('retained_unsent',)])
            assert len(journey.packets)==3,'Retired/held root or correction reached native write'
            with sqlite3.connect(journey.root/'state.sqlite') as db:
                if change=='clear':
                    assert db.execute('SELECT codex_thread_id,force_fresh_thread FROM sessions WHERE thread_id=1').fetchone()==(None,1)
                    db.execute('UPDATE sessions SET codex_thread_id=?,force_fresh_thread=0 WHERE thread_id=1',(journey.web_thread,))
                else:
                    db.execute("DELETE FROM bot_state WHERE key='native_writer_hold:100:1'")
            if change=='clear':
                assert not journey.read('input','submit',json.dumps(pending),ok=False)['ok']
                binding=journey.read('presentation','list','0','0')['result']['binding']
                assert binding!=pending['binding'],'Clear/restore revived the old browser generation'
            retry={**pending,'binding':binding}
            repeated=journey.read('input','submit',json.dumps(retry))['result']
            assert not repeated['new_input'] and repeated['phase']=='retained_unsent'
            if change=='clear':assert repeated['retired']
        journey.hold_resume=False
        assert not journey.messages,'Retired or held browser input published an error to Telegram'
        print('PASS actual owner socket → durable original browser text → same native worker/steer; exact >4KiB input, accepted receipts, reconnect dedup, changed-original rejection, uncertain steer not replayed and resolved by late acknowledgment, no fabricated Telegram update/publication; zero model calls')
        print('PASS held actual resume + entry clear/restore and maintenance hold: no native submission, no restored binding, retained known-unsent input and no reconnect replay')
    finally:
        journey.close()


def mixed_origin_returns(binary):
    journey=Inputs(binary)
    forbidden={'sendMessage','sendMessageDraft','editMessageText','sendPhoto','sendDocument','sendVideo','sendAudio','sendVoice','sendChatAction'}
    try:
        journey.start();journey.admit('Seed existing conversation',topic=1)
        journey.wait(lambda:journey.has('Initial goal turn delivered.',1));journey.idle()
        binding=journey.read('presentation','list','0','0')['result']['binding']
        journey.hold_telegram=True
        journey.admit('A Telegram-root task remains active.',topic=1)
        journey.wait(lambda:len(journey.packets)==1)
        assert journey.row('SELECT count(*) FROM conversation_returns')==[(0,)]
        web,_=journey.submit(binding,'Continue this active task from the canonical conversation.')
        journey.wait(lambda:journey.row('SELECT phase FROM conversation_inputs WHERE id=?',(web['id'],))==[('accepted',)])
        assert len(journey.packets)==2 and journey.packets[1][0]=='turn/steer','Browser correction waited for the root task'
        journey.telegram_methods.clear();journey.messages.clear()
        thread=journey.web_thread;turn=journey.web_turn
        journey.broadcast(thread,'item/completed',{'turnId':turn,'item':{'type':'agentMessage','id':'canonical-progress','phase':'commentary','text':'Browser-influenced progress must stay canonical.'}})
        send=next(send for selected,send in journey.clients.values() if selected==thread)
        send({'id':'canonical-question','method':'item/tool/requestUserInput','params':{'threadId':thread,'turnId':turn,'itemId':'canonical-choice','isBlocking':True,'questions':[{'id':'scope','header':'Scope','question':'Which scope should this private continuation use?','isOther':True,'isSecret':False,'options':[{'label':'Selected scope','description':'Only this request'}]}]}})
        send({'id':'canonical-approval','method':'item/commandExecution/requestApproval','params':{'threadId':thread,'turnId':turn,'itemId':'canonical-command','command':'synthetic command requiring an explicit human choice','reason':'Do not grant this automatically'}})
        journey.wait(lambda:journey.row("SELECT count(*) FROM human_interactions WHERE state='pending' AND json_extract(payload_json,'$.source.kind') IN ('question','approval')")==[(2,)])
        assert not journey.native_answers,'A native request was answered without human selection'
        runtime=''.join(v['value'] for k,v in sorted(journey.packets[0][1]['additionalContext'].items()) if k=='telecodex.runtime' or k.startswith('telecodex.runtime.'))
        output=Path(re.search(r'\n([^\n]+/out)\n',runtime).group(1))
        artifact=output/'canonical-deliverable.txt';artifact.write_text('Canonical-only generated artifact')
        journey.broadcast(thread,'item/completed',{'turnId':turn,'item':{'type':'agentMessage','id':'canonical-final','phase':'final_answer','text':'The canonical result and its artifact remain retained.'}})
        journey.broadcast(thread,'turn/completed',{'turn':{'id':turn,'status':'completed'}})
        journey.idle()
        assert journey.row("SELECT count(*) FROM interaction_native_messages WHERE text='The canonical result and its artifact remain retained.'")==[(1,)]
        assert artifact.read_text()=='Canonical-only generated artifact'
        assert not forbidden.intersection(journey.telegram_methods),(journey.telegram_methods,journey.messages)
        assert not any(answer.get('result',{}).get('decision') in ('accept','acceptForSession') for answer in journey.native_answers)
        journey.stop();journey.start();journey.telegram_methods.clear()
        journey.admit('Continue the same native context after restart.',topic=1)
        journey.wait(lambda:len(journey.packets)==3)
        journey.finish(journey.web_thread,journey.web_turn);journey.idle()
        journey.wait(lambda:journey.has('Initial goal turn delivered.',1))
        assert sum(m['text']=='Initial goal turn delivered.' for m,_ in journey.messages)==1
        assert journey.packets[-1][1]['input'][0]['text']=='Continue the same native context after restart.'
        assert journey.row('SELECT count(*) FROM conversation_inputs')==[(1,)],'Direct continuation entered web ingress'
        print('PASS active Telegram-root + browser steer retains canonical progress/final/artifact and unanswered native requests; after restart a raw direct continuation restores its own topic response once; zero models')
    finally:
        journey.close()


def late_artifact_return(binary):
    journey=Inputs(binary)
    try:
        journey.start();journey.admit('Seed existing conversation',topic=1)
        journey.wait(lambda:journey.has('Initial goal turn delivered.',1));journey.idle()
        binding=journey.read('presentation','list','0','0')['result']['binding']
        journey.hold_telegram=True
        journey.native_ack_delay=.25
        journey.admit('Produce an artifact on the original return surface.',topic=1)
        journey.wait(lambda:len(journey.packets)==1)
        runtime=''.join(v['value'] for k,v in sorted(journey.packets[0][1]['additionalContext'].items()) if k=='telecodex.runtime' or k.startswith('telecodex.runtime.'))
        output=Path(re.search(r'\n([^\n]+/out)\n',runtime).group(1))
        artifact=output/'late-deliverable.txt';artifact.write_text('Retained across return-selection race')
        # A fixture packet can precede the proxy ACK and live collection. Do
        # not emit synthetic completion into an execution that is not ready.
        journey.wait(lambda:journey.row("SELECT count(*) FROM native_collections n JOIN turns t ON t.id=n.local_turn WHERE t.native_thread_id=? AND n.first_turn=? AND t.status='running'",(journey.web_thread,journey.web_turn))==[(1,)])
        journey.finish(journey.web_thread,journey.web_turn)
        # The ordinary final text has completed. The artifact is now waiting at
        # the shared outbound limiter, after its retained attempt record.
        journey.wait(lambda:journey.row("SELECT count(*) FROM audit_log WHERE action='artifact_delivery_attempted'")==[(1,)])
        uploads={'sendPhoto','sendDocument','sendVideo','sendAudio','sendVoice'}
        assert not uploads.intersection(journey.telegram_methods)
        original,_=journey.submit(binding,'Select the canonical return while the artifact is still unsent.')
        journey.wait(lambda:journey.row('SELECT phase FROM conversation_inputs WHERE id=?',(original['id'],))==[('accepted',)])
        assert artifact.read_text()=='Retained across return-selection race','Successful native completion deleted an unuploaded artifact'
        assert journey.row("SELECT status FROM turns WHERE id=2")==[('completed',)]
        assert not uploads.intersection(journey.telegram_methods),journey.telegram_methods
        journey.finish(journey.web_thread,journey.web_turn);journey.idle()
        assert artifact.exists()
        print('PASS late return selection during actual artifact cooldown: no upload attempt, native completion retained and unuploaded file survives ordinary finalization cleanup; zero models')
    finally:
        journey.close()


def canonical_turn_skips_unused_limits_history(binary):
    """A slow quota source must not hold web dialogue; legacy previews still read it."""
    journey=Inputs(binary);opened=threading.Event();release=threading.Event();done=threading.Event();writer=None
    try:
        journey.config.write_text(journey.config.read_text().replace('show_unfinished_messages=false','show_unfinished_messages=true').replace('[interaction]\n','[interaction]\ntelegram_projection=false\ntelegram_entry_projection=false\n'))
        journey.start();journey.admit('Seed the selected entry.',topic=1)
        journey.wait(lambda:journey.has('Initial goal turn delivered.',1));journey.idle()
        journey.wait_control_socket(journey.socket)
        binding=journey.read('presentation','list','0','0')['result']['binding']
        history=journey.root/'codex-home'/'sessions';history.mkdir(parents=True,exist_ok=True)
        fifo=history/'blocked-limits.jsonl';os.mkfifo(fifo,0o600)
        def delayed_history():
            while not done.is_set():
                try:fd=os.open(fifo,os.O_WRONLY|os.O_NONBLOCK)
                except OSError as error:
                    if error.errno!=errno.ENXIO:raise
                    done.wait(.01);continue
                opened.set();fifo.unlink()
                try:
                    release.wait(10)
                    os.write(fd,(json.dumps({'timestamp':'2026-10-27T07:00:00Z','payload':{'type':'token_count','rate_limits':{'secondary':{'used_percent':17,'window_minutes':10080,'resets_at':1793200000}}}})+'\n').encode())
                except BrokenPipeError:pass
                finally:os.close(fd)
                return
        writer=threading.Thread(target=delayed_history,daemon=True);writer.start()
        journey.packets.clear()
        original,_=journey.submit(binding,'Answer in the web conversation without waiting for a quota banner.')
        journey.wait(lambda:opened.is_set()or bool(journey.packets),seconds=4)
        assert not opened.is_set(),'Canonical web turn opened blocking quota history before native admission'
        journey.wait(lambda:journey.row('SELECT phase FROM conversation_inputs WHERE id=?',(original['id'],))==[('accepted',)])
        journey.finish(journey.web_thread,journey.web_turn);journey.idle();journey.stop()
        # The legacy unfinished-preview path still has a visible quota banner.
        fake=journey.root/'codex';body=fake.read_text()
        marker="if sys.argv[1:]!=['app-server','proxy']: sys.exit(7)"
        replacement="""if sys.argv[1:]==['app-server']:
    import json
    def emit(value):print(json.dumps(value),flush=True)
    for raw in sys.stdin:
        message=json.loads(raw);method=message.get('method');ident=message.get('id')
        if ident is None:continue
        result={}
        if method in ('thread/start','thread/resume'):result={'thread':{'id':'legacy-limits-thread'},'model':'fixture-model','modelProvider':'fixture'}
        elif method=='thread/goal/get':result={'goal':None}
        elif method=='turn/start':result={'turn':{'id':'legacy-limits-turn'}}
        emit({'id':ident,'result':result})
        if method=='turn/start':
            emit({'method':'turn/started','params':{'threadId':'legacy-limits-thread','turn':{'id':'legacy-limits-turn','status':'inProgress'}}})
            emit({'method':'item/completed','params':{'threadId':'legacy-limits-thread','turnId':'legacy-limits-turn','item':{'id':'legacy-answer','type':'agentMessage','phase':'final_answer','text':'Legacy quota preview completed.'}}})
            emit({'method':'turn/completed','params':{'threadId':'legacy-limits-thread','turn':{'id':'legacy-limits-turn','status':'completed'}}})
    sys.exit(0)
"""+marker
        assert marker in body;fake.write_text(body.replace(marker,replacement))
        legacy=journey.config.read_text().split('\n[interaction]\n',1)[0]
        legacy=re.sub(r'\[session_control\]\n.*?(?=\[telegram\])','',legacy,flags=re.S)
        legacy=legacy.replace('shared_app_server=true','shared_app_server=false').replace('[telegram]\n','[telegram]\nuse_message_drafts=false\n')
        journey.config.write_text(legacy)
        journey.start();journey.admit('Keep the legacy preview quota.',topic=7)
        journey.wait(lambda:opened.is_set(),seconds=5)
        release.set();journey.wait(lambda:journey.has('Legacy quota preview completed.',7))
        assert any('83%'in message['text']for message,_ in journey.messages),'Legacy quota banner disappeared'
        journey.idle()
        print('PASS canonical web admission bypasses blocked quota history; legacy unfinished preview still reads and displays the quota; zero models.')
    finally:
        release.set();done.set()
        if writer:writer.join(2)
        journey.close()


def gateway_survives_telegram_failure(binary):
    for method, status in (('getMe', 503), ('setMyCommands', 503), ('getUpdates', 409)):
        journey = Inputs(binary)
        try:
            journey.telegram_failures = {method: status}
            journey.start()
            journey.wait(lambda: method in journey.telegram_methods)
            journey.wait_control_socket(journey.socket)
            binding = journey.read('presentation', 'list', '0', '0')['result']['binding']
            original, outcome = journey.submit(binding, 'Continue without Telegram.')
            assert outcome['ok'] and outcome['result']['new_input']
            journey.wait(lambda: journey.row('SELECT phase FROM conversation_inputs WHERE id=?',
                                             (original['id'],)) == [('accepted',)])
            journey.finish(journey.web_thread, journey.web_turn)
            journey.wait(lambda: journey.row(
                "SELECT count(*) FROM interaction_native_messages WHERE text='Initial goal turn delivered.'"
            ) == [(1,)])
            assert len(journey.packets) == 1
            assert journey.row('SELECT count(*) FROM incoming_updates') == [(0,)]
            assert not journey.messages
            assert journey.process.poll() is None
            if method == 'getMe':
                assert journey.telegram_methods == ['getMe']
        finally:
            journey.close()
    print('PASS Gateway admits and retains a native result after Telegram identity, setup and polling failures.')

def independent_telegram_polling(binary, *, named_roles=False, embedded_binary=None):
    class MigratingInputs(Inputs):
        unknown_steer = None
        deferred_steer = None

        def handle_extra_rpc(self, message, send):
            params = message.get("params", {})
            selected = params.get("clientUserMessageId")
            if (message.get("method") == "turn/steer" and selected is not None
                    and selected in (self.unknown_steer, self.deferred_steer)):
                self.packets.append(("turn/steer", params))
                if selected == self.unknown_steer:
                    send({"id": message["id"], "result": {"turnId": "another-turn"}})
                else:
                    send({"id": message["id"], "error": {
                        "code": -32602, "message": "Synthetic definitive refusal",
                    }})
                return True
            if message.get("method") == "thread/goal/snapshot":
                thread = message["params"]["threadId"]
                send({"id": message["id"], "result": {
                    "goal": self.goals.get(thread), "revision": "migration-fixture:1",
                }})
                return True
            return super().handle_extra_rpc(message, send)

    embedded_binary = embedded_binary or binary
    journey = MigratingInputs(embedded_binary)
    journey.acknowledged_updates = True
    journey.poll_offsets = []
    original_config = journey.config.read_text()
    external_config = original_config.replace(
        "[telegram]\n", "[telegram]\nexternal_polling=true\n")
    activity_state = journey.root / "activity"
    activity_state.mkdir(mode=0o700)
    external_config = f'activity_projection_state="{activity_state}"\n' + external_config
    poll_config = journey.root / "poll.toml"
    # The adapter needs only Bot API and the existing socket. Gateway retains
    # its old journal and gets neither the bot token nor a working API endpoint.
    telegram_settings = external_config.split("[session_control]", 1)[1]
    poll_config.write_text("[session_control]" + telegram_settings.split("[codex]", 1)[0])
    poll_config.chmod(0o600)
    external_config = re.sub(r"^(?:bot_token(?:_env|_file)?|api_base)=.*\n", "", external_config, flags=re.M)
    external_config = external_config.replace(
        "[telegram]\n", '[telegram]\napi_base="http://127.0.0.1:1"\n')
    adapter = None
    env = {"PATH": "/usr/bin:/bin", "HOME": str(journey.root), "LANG": "C.UTF-8"}
    adapter_command = [binary, "--tele-daimon-poll", str(poll_config)]
    if named_roles:
        gateway_path = journey.root / "daimon-gateway"
        gateway_path.symlink_to(Path(binary).resolve())
        adapter_path = journey.root / "teledaimon"
        adapter_path.symlink_to(gateway_path.name)
        adapter_command = [str(adapter_path), str(poll_config)]

    def start_adapter():
        return subprocess.Popen(
            adapter_command, cwd=journey.root, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def assert_command_refused(args, error):
        result = subprocess.run(args, cwd=journey.root, env=env, capture_output=True, text=True, timeout=12)
        assert result.returncode != 0 and error in result.stderr, result.stderr

    def stop_adapter(process):
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        _, error = process.communicate(timeout=8)
        assert process.returncode == 0, error

    def owner_operation(surface, request):
        with socket.socket(socket.AF_UNIX) as conn:
            conn.settimeout(5)
            conn.connect(str(journey.socket))
            conn.sendall(json.dumps({surface: request}).encode() + b"\n")
            with conn.makefile("rb") as stream:
                return json.loads(stream.readline())

    def ingress(request):
        return owner_operation("telegram_ingress", request)

    def sessions_telegram(operation, **fields):
        return owner_operation("sessions_telegram", {"operation": operation, **fields})

    def settled(update):
        return journey.row(
            "SELECT status FROM incoming_updates WHERE update_id=?", (update,)
        ) == [("settled",)]

    try:
        if named_roles:
            assert_command_refused(
                [str(gateway_path), str(journey.config)],
                "requires external or disabled Telegram transport",
            )
            assert_command_refused(
                [str(gateway_path), "--tele-daimon-poll", str(poll_config)], "teledaimon CONFIG",
            )
            assert_command_refused(
                [str(adapter_path), "--control", str(journey.config), "presentation", "list", "0", "0"],
                "Usage: teledaimon CONFIG",
            )
            token_profile = journey.root / "token-in-gateway.toml"
            token_profile.write_text(external_config.replace(
                "[telegram]\n", '[telegram]\nbot_token_file="/unreadable/test-token"\n',
            ))
            assert_command_refused(
                [str(gateway_path), str(token_profile)], "Configure Telegram bot credentials only in TeleDaimon",
            )
            assert journey.telegram_methods == []
        journey.start()
        journey.wait_control_socket(journey.socket)
        seeded = journey.admit("Original from the embedded listener", topic=1)
        journey.wait(lambda: settled(seeded))
        journey.idle()
        retained = journey.row("SELECT codex_thread_id FROM sessions WHERE thread_id=1")
        thread = retained[0][0]
        journey.goals[thread] = {
            "threadId": thread, "objective": "Retained paused migration fixture",
            "status": "paused", "tokenBudget": 120, "tokensUsed": 47,
            "timeUsedSeconds": 6, "createdAt": 1, "updatedAt": 2,
        }
        original_goal = journey.read("goal", "inspect", "100", "1")["result"]["snapshot"]
        assert original_goal["goal"]["status"] == "paused"
        assert original_goal["goal"]["tokensUsed"] == 47
        grant = {
            "request_id": str(uuid.uuid4()), "expected_revision": None,
            "source": "https://example.test/transport-migration",
            "scope": "owned_sessions", "agents": True, "recovery": False,
        }
        journey.read("goal", "delegation", "set", json.dumps(grant))
        original_grant = journey.read("goal", "delegation")["result"]
        assert original_grant["delegation"]["agents"] is True

        binding = journey.read("presentation", "list", "0", "0")["result"]["binding"]
        previous_result, _ = journey.submit(binding, "Retain this settled reply and its original.")
        journey.wait(lambda: journey.web_turn is not None)
        result_turn = journey.web_turn
        journey.finish(journey.web_thread, result_turn)
        journey.wait(lambda: journey.row(
            "SELECT count(*) FROM interaction_native_messages WHERE native_turn=?", (result_turn,)
        ) == [(1,)])
        journey.idle()
        previous_status = journey.read("input", "status", previous_result["id"])["result"]
        assert previous_status["phase"] == "accepted"
        previous_history = journey.row(
            "SELECT text, native_turn FROM interaction_native_messages WHERE native_turn=?", (result_turn,)
        )

        held, _ = journey.submit(binding, "Hold this turn through cutover.")
        journey.wait(lambda: journey.row("SELECT phase FROM conversation_inputs WHERE id=?", (held["id"],))
                     == [("accepted",)])
        unknown_id, deferred_id = str(uuid.uuid4()), str(uuid.uuid4())
        journey.unknown_steer = "conversation:" + unknown_id
        journey.deferred_steer = "conversation:" + deferred_id
        unknown, _ = journey.submit(binding, "Provider acknowledged another turn.", unknown_id)
        journey.wait(lambda: journey.row("SELECT phase FROM conversation_inputs WHERE id=?", (unknown_id,))
                     == [("uncertain",)])
        deferred, _ = journey.submit(binding, "Keep this known-unsent input pending.", deferred_id)
        journey.wait(lambda: journey.row("SELECT phase FROM conversation_inputs WHERE id=?", (deferred_id,))
                     == [("queued",)])
        journal_before = journey.row(
            "SELECT id, doc FROM conversation_inputs WHERE id IN (?,?) ORDER BY id",
            (unknown_id, deferred_id),
        )
        before_cutover = len(journey.packets)
        journey.stop()
        journey.binary = str(gateway_path) if named_roles else binary
        wrong_bot = journey.root / "wrong-bot.toml"
        wrong_bot.write_text(external_config.replace(
            "external_polling=true\n", "external_polling=true\nexternal_bot_id=124\n").replace(
            "startup_admin_ids=[100,101]", "startup_admin_ids=[100,101,999]"))
        before_rejection = journey.row(
            "SELECT tg_user_id, role, allowed FROM users ORDER BY tg_user_id"
        )
        pending_before_rejection = journey.row(
            "SELECT id, phase, doc FROM conversation_inputs ORDER BY id"
        )
        audit_before_rejection = journey.row("SELECT COUNT(*) FROM audit_log")
        assert_command_refused([journey.binary, str(wrong_bot)], "does not match the journal identity")
        assert journey.row("SELECT tg_user_id, role, allowed FROM users ORDER BY tg_user_id") == before_rejection
        assert journey.row("SELECT id, phase, doc FROM conversation_inputs ORDER BY id") == pending_before_rejection
        assert journey.row("SELECT COUNT(*) FROM audit_log") == audit_before_rejection
        if named_roles:
            # A legacy .env must not populate the named Gateway's environment.
            (journey.root / ".env").write_text("TELECODEX_RESTART_DELAY_MS=60000\n")
        journey.config.write_text(external_config)
        journey.telegram_methods.clear()
        journey.start()
        journey.wait_control_socket(journey.socket)
        if named_roles:
            (journey.root / ".env").unlink()
        gateway_pid = journey.process.pid
        assert ingress({"operation": "ready", "bot_id": 124})["ok"] is False
        assert ingress({"operation": "ready", "bot_id": 123})["result"]["next_offset"] == seeded + 1
        assert not journey.telegram_methods
        assert journey.read("goal", "inspect", "100", "1")["result"]["snapshot"] == original_goal
        assert journey.read("goal", "delegation")["result"] == original_grant
        assert journey.read("input", "status", previous_result["id"])["result"] == previous_status
        assert journey.row(
            "SELECT text, native_turn FROM interaction_native_messages WHERE native_turn=?", (result_turn,)
        ) == previous_history
        assert journey.row(
            "SELECT id, doc FROM conversation_inputs WHERE id IN (?,?) ORDER BY id",
            (unknown_id, deferred_id),
        ) == journal_before
        for retained_original, expected in ((unknown, "uncertain"), (deferred, "retained_unsent")):
            current = journey.read("input", "status", retained_original["id"])["result"]
            duplicate_result = journey.read("input", "submit", json.dumps(retained_original))["result"]
            assert current["phase"] == expected and duplicate_result["phase"] == expected
            assert not duplicate_result["new_input"]
        assert len(journey.packets) == before_cutover
        journey.web_turn = None
        fake_identity = {"id": 123, "is_bot": False, "first_name": "Not a bot"}
        assert not ingress({"operation": "ready", "bot_id": 123, "identity": fake_identity})["ok"]
        assert not ingress({"operation": "admit", "bot_id": 123, "update": {"update_id": 199}})["ok"]
        first = journey.admit("Telegram through the separate adapter", topic=1)
        with journey.lock:
            duplicate = journey.updates[-1]
        adapter = start_adapter()
        journey.wait(lambda: thread in journey.holding)
        journey.finish(thread, journey.holding.pop(thread))
        journey.wait(lambda: settled(first))
        fingerprint = hashlib.sha256(b"synthetic-question-token").hexdigest()
        status = sessions_telegram("status")["result"]
        assert status["id"] == 123 and status["username"] == "FixtureBot"
        assert status["credential_fingerprint"] == fingerprint
        journey.telegram_failures = {}
        sends = journey.telegram_methods.count("sendMessage")
        assert not sessions_telegram("alert", credential_fingerprint="0" * 64, text="Wrong credential")["ok"]
        assert not sessions_telegram("alert", credential_fingerprint=fingerprint, chat_id=999, text="Wrong audience")["ok"]
        assert journey.telegram_methods.count("sendMessage") == sends
        delivered = sessions_telegram("alert", credential_fingerprint=fingerprint, text="Private Sessions alert")
        assert delivered["result"]["result"]["chat"]["id"] == 100
        assert delivered["result"]["result"]["text"] == "Private Sessions alert"
        assert sessions_telegram("menu_read", credential_fingerprint=fingerprint)["result"]["result"] == {"type": "default"}
        menu = {"type": "web_app", "text": "Sessions", "web_app": {"url": "https://example.test/sessions"}}
        assert sessions_telegram("menu_write", credential_fingerprint=fingerprint, menu=menu)["result"]["result"] is True
        assert sessions_telegram("menu_read", credential_fingerprint=fingerprint)["result"]["result"] == menu
        journey.telegram_failures["sendMessage"] = 400
        refused = sessions_telegram("alert", credential_fingerprint=fingerprint, text="Known Bot API rejection")
        assert refused["result"] == {"ok": False, "error_code": 400}
        journey.invalid_telegram_failure_body = {"sendMessage"}
        malformed = sessions_telegram("alert", credential_fingerprint=fingerprint, text="Invalid proxy response")
        assert not malformed["ok"]
        assert malformed["error"] == "Sessions Telegram operation unconfirmed"
        journey.telegram_failures.pop("sendMessage")
        print("PASS paired Sessions alert and menu operations use TeleDaimon custody")
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from scripts.activity_indicator import GatewayTelegram, atomic_json, pending_markup
        local_config = {"session_control":{"socket_path":str(journey.socket)},
                        "activity_telegram":{"credential_fingerprint":fingerprint}}
        activity_client = GatewayTelegram(local_config)
        assert not hasattr(activity_client, "token")
        activity_client.pace = lambda _chat: None
        native = retained[0][0]
        journey.telegram_priority = []
        payload = {"chat_id":100,"message_thread_id":1,"text":"Activity card","reply_markup":pending_markup(True)}
        assert activity_client.call("sendMessage", payload, background=True, native_thread="stale") == {
            "ok":False,"not_submitted":True}
        assert ("sendMessage","background") not in journey.telegram_priority
        good = activity_client.call("sendMessage", payload, background=True, native_thread=native)
        msg = good["result"]["message_id"]
        assert good["result"]["chat"]["id"] == 100 and good["result"]["message_thread_id"] == 1
        atomic_json(activity_state/"messages.json", {
            "100:1":{"message_id":msg,"chat_id":100,"topic":1,"native_thread":native},
            "100:9":{"message_id":msg+1,"chat_id":100,"topic":9,"native_thread":native},
        })
        assert activity_client.call("editMessageText", {"chat_id":100,"message_id":msg,"text":"Updated"},
                                    topic=1,native_thread=native)["ok"]
        assert activity_client.call("deleteMessage", {"chat_id":100,"message_id":msg+1},
                                    topic=1,native_thread=native) == {"ok":False,"not_submitted":True}
        assert not any(m=="deleteMessage" for m,_ in journey.telegram_priority)
        assert activity_client.call("deleteMessage", {"chat_id":100,"message_id":msg},
                                    topic=1,native_thread=native)["ok"]
        atomic_json(activity_state/"topic-markers.json", {"schema":"telecodex.topic-markers/v1","items":{
            "100:1":{"native_thread":native,"phase":"attempting","desired":"Activity"}
        }})
        assert activity_client.call("editForumTopic", {"chat_id":100,"message_thread_id":1,"name":"Activity"},
                                    background=True,native_thread=native)["ok"]
        assert [(m,p) for m,p in journey.telegram_priority if p] == [
          ("sendMessage","background"), ("editMessageText","foreground"),
          ("deleteMessage","foreground"), ("editForumTopic","background")]
        print("PASS tokenless Activity relay binds the topic, bot, method and priority")
        journey.idle()
        stop_adapter(adapter)
        adapter = None
        assert not sessions_telegram("status")["ok"]
        assert activity_client.call("sendMessage", {"chat_id":100,"message_thread_id":1,"text":"No adapter"},
                                    native_thread=native) == {
            "ok":False,"not_submitted":True}
        unsent = sessions_telegram("alert", credential_fingerprint=fingerprint, text="No adapter")
        assert unsent["result"] == {"ok": False, "not_submitted": True}
        assert ingress({"operation": "ready", "bot_id": 123})["result"]["next_offset"] == first + 1
        assert journey.row("SELECT codex_thread_id FROM sessions WHERE thread_id=1") == retained
        native_count = journey.native_turns
        assert ingress({"operation": "admit", "bot_id": 123, "update": duplicate})["result"]["next_offset"] == first + 1
        assert not ingress({"operation": "admit", "bot_id": 123,
                            "update": {**duplicate, "message": {**duplicate["message"], "text": "Different bytes"}}})["ok"]
        assert journey.native_turns == native_count
        polls = journey.telegram_methods.count("getUpdates")
        binding = journey.read("presentation", "list", "0", "0")["result"]["binding"]
        original, reply = journey.submit(binding, "Keep working while TeleDaimon is stopped.")
        assert reply["ok"]
        journey.wait(lambda: journey.web_turn is not None)
        journey.finish(journey.web_thread, journey.web_turn)
        journey.wait(lambda: journey.row(
            "SELECT count(*) FROM interaction_native_messages WHERE native_turn=?",
            (journey.web_turn,),
        ) == [(1,)])
        journey.idle()
        assert journey.telegram_methods.count("getUpdates") == polls
        assert journey.process.pid == gateway_pid and journey.process.poll() is None
        assert len(journey.packets) == before_cutover + 1
        assert journey.packets[-1][1]["clientUserMessageId"] == "conversation:" + original["id"]

        before = journey.native_turns
        second = journey.admit("Retain this input while polling is stopped", topic=1)
        adapter = start_adapter()
        journey.wait(lambda: thread in journey.holding)
        journey.finish(thread, journey.holding.pop(thread))
        journey.wait(lambda: settled(second))
        assert journey.row("SELECT update_id FROM incoming_updates ORDER BY update_id") == [
            (seeded,), (first,), (second,)
        ]
        assert journey.row("SELECT codex_thread_id FROM sessions WHERE thread_id=1") == retained
        assert journey.native_turns == before + 1
        assert journey.process.pid == gateway_pid
        assert journey.read("goal", "inspect", "100", "1")["result"]["snapshot"] == original_goal
        assert not any(request.get("method") in ("thread/goal/set", "thread/goal/clear", "turn/interrupt")
                       for request in journey.rpc)
        poll_held, release_poll = threading.Event(), threading.Event()

        def hold_update_poll(updates):
            if updates:
                poll_held.set()
                assert release_poll.wait(8), "Fixture long poll was not released"

        journey.before_poll_reply = hold_update_poll
        during_restart = journey.admit("Original returned during the Gateway restart", topic=1)
        try:
            assert poll_held.wait(5), "Adapter did not enter the fixture long poll"
            journey.stop()
            journey.start()
            journey.wait_control_socket(journey.socket)
            request = {"operation": "ready", "bot_id": 123}
            assert ingress(request)["result"]["identified"] is False
        finally:
            journey.before_poll_reply = None
            release_poll.set()
        journey.wait(lambda: thread in journey.holding)
        journey.finish(thread, journey.holding.pop(thread))
        journey.wait(lambda: settled(during_restart))
        ready = ingress(request)["result"]
        assert ready["identified"] and ready["next_offset"] == during_restart + 1
        assert adapter.poll() is None and journey.process.pid != gateway_pid
        assert journey.native_turns == before + 2
        print("PASS an original held by the Bot API during Gateway restart is admitted once")
        stop_adapter(adapter)
        adapter = None
        print("PASS tokenless Gateway migration with retained bot, cursor, history, grant and goal accounting; "
              "queued and uncertain inputs retained without replay, and one dispatch per new original")

        cutover_result = journey.read("input", "status", original["id"])["result"]
        postcutover_history = journey.row(
            "SELECT text, native_turn FROM interaction_native_messages WHERE native_turn=?",
            (journey.web_turn,),
        )
        assert cutover_result["phase"] == "accepted" and len(postcutover_history) == 1
        before_rollback = journey.native_turns
        packets_before_rollback = len(journey.packets)
        journey.stop()
        with journey.lock:
            journey.poll_offsets.clear()
        journey.binary = embedded_binary
        journey.config.write_text(original_config)
        final = journey.admit("First Telegram original after restoring embedded polling", topic=1)
        journey.start()
        journey.wait_control_socket(journey.socket)
        journey.wait(lambda: thread in journey.holding)
        assert journey.poll_offsets[0] == during_restart + 1
        journey.finish(thread, journey.holding.pop(thread))
        journey.wait(lambda: settled(final))
        journey.idle()
        assert journey.row("SELECT update_id FROM incoming_updates ORDER BY update_id") == [
            (seeded,), (first,), (second,), (during_restart,), (final,),
        ]
        assert journey.row("SELECT codex_thread_id FROM sessions WHERE thread_id=1") == retained
        assert journey.read("input", "status", original["id"])["result"] == cutover_result
        assert journey.row(
            "SELECT text, native_turn FROM interaction_native_messages WHERE native_turn=?",
            (journey.web_turn,),
        ) == postcutover_history
        assert journey.read("goal", "delegation")["result"] == original_grant
        assert journey.read("goal", "inspect", "100", "1")["result"]["snapshot"] == original_goal
        for retained_original, expected in ((unknown, "uncertain"), (deferred, "retained_unsent")):
            status = journey.read("input", "submit", json.dumps(retained_original))["result"]
            assert status["phase"] == expected and not status["new_input"]
        assert journey.native_turns == before_rollback + 1
        assert len(journey.packets) == packets_before_rollback
        print("PASS embedded rollback resumes at the advanced cursor and retains post-cutover work without replay")
    finally:
        if adapter is not None and adapter.poll() is None:
            adapter.kill()
            adapter.communicate(timeout=8)
        journey.close()


if __name__=='__main__':
    binary=str(Path(sys.argv[1]).resolve())
    gateway_survives_telegram_failure(binary)
    independent_telegram_polling(binary, named_roles=True)
    foreground_retention(binary)
    foreground_delegation(binary)
    reconsider_queued_steer(binary)
    qualify(binary)
    mixed_origin_returns(binary)
    late_artifact_return(binary)
    canonical_turn_skips_unused_limits_history(binary)
