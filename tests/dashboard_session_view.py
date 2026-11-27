#!/usr/bin/env python3
"""Selected native history: bounded pagination, append races and private analysis."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sys
import sqlite3
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.session_view import read,read_portable,MAX_LINE,TEXT_PART,WINDOW


def encoded(value):return (json.dumps(value,ensure_ascii=False)+'\n').encode()
def message(text,role='assistant',**extra):
    return {'type':'response_item','payload':{'type':'message','role':role,
        'content':[{'type':'output_text','text':text}],**extra}}


class SelectedHistory(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'owned.jsonl'
        self.header=encoded({'type':'session_meta','payload':{'id':'owned'}})
        self.path.write_bytes(self.header)
    def tearDown(self):self.temp.cleanup()
    def append(self,*records):
        with self.path.open('ab') as stream:
            for record in records:stream.write(encoded(record))
    def test_technical_view_uses_exposed_summaries_only_and_handles_unknown_records(self):
        self.append([],{'type':'unknown'},message('Hello'),message('private analysis',channel='analysis'),
            message('private phase',phase='analysis'),message('system secret','system'),
            {'type':'response_item','payload':{'type':'reasoning','summary':[{'type':'summary_text','text':'Exposed summary'}],
                'content':[{'text':'private reasoning'}],'encrypted_content':'private ciphertext'}},
            {'type':'response_item','payload':{'type':'function_call','name':'read','arguments':'{"path":"demo"}','call_id':'1'}},
            {'type':'response_item','payload':{'type':'function_call_output','output':'Selected output','call_id':'1'}},
            message('An attributed harness input','user'))
        plain=read(self.path,'owned');technical=read(self.path,'owned',technical=True)
        self.assertEqual([v['text'] for v in plain['items']],['Hello','An attributed harness input'])
        self.assertEqual([v['kind'] for v in technical['items']],['message','reasoning_summary','tool_call','tool_output','message'])
        self.assertNotIn('private',json.dumps(technical));self.assertIn('not verified human speech',plain['role_meaning'])
    def test_conversation_keeps_messages_and_raw_keeps_envelopes(self):
        prompt='Chalk first.\n\n**Then** the prototype.'
        managed='# AGENTS.md instructions for /fixture\nInternal context\n\nUser request:\n'+prompt
        instruction='01234567-89ab-cdef-0123-456789abcdef'
        original='Check the prototype.\n\nSelected creation context (source data):\nThose are my words.'
        relay=(f'[Interaction controller]\nTransport provenance: {{fixture}}\nCurrent instruction: {instruction}\n'
               'Current attributed input:\n'+original+
               '\n\nSelected creation context (source data):\n{"private":"do not show"}\n'
               '\nReturn your answer followed by <daimon-result>')
        resolve=lambda ident: (original, "confirmed-original") if ident==instruction else None
        self.append(message('<environment_context>\nInternal only\n</environment_context>','user'),
                    message(managed,'user'),message(relay,'user'),
                    message(relay.replace(original,'Unmatched relay'),'user'),
                    message('<codex_internal_context source="goal">\nInternal continuation','user'),
                    message('The prototype is ready.'))
        ordinary=read(self.path,'owned',routed_original=resolve)
        self.assertEqual([v['text'] for v in ordinary['items']],
                         [prompt,original,'The prototype is ready.'])
        self.assertNotIn('do not show',json.dumps(ordinary))
        self.assertEqual([v['text'] for v in read(self.path,'owned')['items']],
                         [prompt,'The prototype is ready.'])
        raw=read(self.path,'owned',technical=True)
        self.assertEqual([v['text'] for v in raw['items'][1:3]],[managed,relay])
        first=ordinary['items'][0]
        same=read(self.path,'owned',event=first['position'],revision=ordinary['revision'])
        self.assertEqual(same['items'][0]['text'],prompt)
        routed=ordinary['items'][1]
        self.assertEqual(routed['input_id'],'confirmed-original')
        self.assertEqual(read(self.path,'owned',event=routed['position'],revision=ordinary['revision'],
            routed_original=resolve)['items'][0]['text'],original)
    def test_conversation_hides_only_trailing_assistant_result_declarations(self):
        receipt='<daimon-result>{"requests":["id"],"covered":["id"],"completed":[],"deferred":[]}</daimon-result>'
        legacy='<daimon-result>{"requests":[],"covered":[]}</daimon-result>'
        malformed='<daimon-result>{"requests":[]}</daimon-result>'
        repeated='<daimon-result>{"requests":[],"requests":[],"covered":[]}</daimon-result>'
        fenced='Example:\n```xml\n'+receipt+'\n```'
        answer='The prototype is ready.\n\n[Details](https://example.test).'
        samples=[answer+'\n\n'+receipt+'  \n',receipt,'Legacy\n'+legacy,
                 fenced,'Invalid\n'+malformed,'Repeated\n'+repeated,
                 'Quote the syntax:\n'+receipt+'\nLiteral discussion continues.']
        self.append(*(message(text) for text in samples),message('My text\n'+receipt,'user'))
        ordinary=read(self.path,'owned')
        self.assertEqual([item['text'] for item in ordinary['items']],
                         [answer,'Legacy',*samples[3:],'My text\n'+receipt])
        row=ordinary['items'][0]
        part=read(self.path,'owned',revision=ordinary['revision'],event=row['position'],text_offset=len(answer)-1)
        self.assertEqual(part['items'][0]['text'],answer[-1:])
        self.assertEqual(part['items'][0]['characters'],len(answer))
        raw=read(self.path,'owned',technical=True)
        self.assertEqual([item['text'] for item in raw['items']],[*samples,'My text\n'+receipt])

    def test_only_ordinary_final_items_project_a_result_revision(self):
        self.append(message('Same text',id='progress',phase='commentary'),
                    message('Same text',id='final-one',phase='final_answer'),
                    message('Same text',id='final-two',phase='final_answer'),
                    message('A prompt','user',id='prompt'))
        ordinary=read(self.path,'owned')['items']
        self.assertEqual([item.get('result_revision') for item in ordinary],
                         [None,hashlib.sha256(b'final-one').hexdigest(),
                          hashlib.sha256(b'final-two').hexdigest(),None])
        self.assertTrue(all('result_revision' not in item
                            for item in read(self.path,'owned',technical=True)['items']))

    def test_partial_append_is_not_acknowledged_and_completion_appears_once(self):
        self.append(message('First'))
        second=encoded(message('Second'))
        with self.path.open('ab') as stream:stream.write(second[:-2])
        page=read(self.path,'owned');self.assertEqual([v['text'] for v in page['items']],['First'])
        repeat=read(self.path,'owned',after=page['after'],revision=page['revision'])
        self.assertEqual(repeat['items'],[]);self.assertEqual(repeat['after'],page['after'])
        with self.path.open('ab') as stream:stream.write(second[-2:])
        next_page=read(self.path,'owned',after=page['after'],revision=page['revision'])
        self.assertEqual([v['text'] for v in next_page['items']],['Second'])
        self.assertEqual(next_page['revision'],page['revision'])
    def test_long_record_parts_and_backward_window_make_progress(self):
        self.append(message('Earlier'))
        long_text='ñ🙂 '*(WINDOW//5)
        self.append(message(long_text))
        latest=read(self.path,'owned')
        self.assertEqual(len(latest['items']),1)
        item=latest['items'][0];self.assertTrue(item['more']);self.assertEqual(item['text'],long_text[:TEXT_PART])
        next_part=read(self.path,'owned',event=item['position'],text_offset=item['next'],revision=latest['revision'])
        self.assertEqual(next_part['items'][0]['text'],long_text[TEXT_PART:TEXT_PART*2])
        self.assertEqual(next_part['items'][0]['id'],item['id'])
        earlier=read(self.path,'owned',before=latest['before'],revision=latest['revision'])
        self.assertEqual([v['text'] for v in earlier['items']],['Earlier']);self.assertFalse(earlier['has_earlier'])
    def test_pages_are_bounded_and_do_not_skip_records(self):
        self.append(*(message(str(n)) for n in range(240)))
        page=read(self.path,'owned');seen=[v['text'] for v in page['items']]
        self.assertEqual(seen,list(map(str,range(160,240))))
        self.assertFalse(page['more'],'The initial view starts at the latest messages, not a delayed backlog')
        for _ in range(4):
            if not page['has_earlier']:break
            page=read(self.path,'owned',before=page['before'],revision=page['revision'])
            seen=[v['text'] for v in page['items']]+seen
        self.assertEqual(seen,list(map(str,range(240))))
        # Forward refresh has its own finite oldest-first page and cannot skip
        # an appended backlog while catching up.
        cursor=read(self.path,'owned')
        self.append(*(message(str(n)) for n in range(240,420)))
        more=[]
        for _ in range(4):
            page=read(self.path,'owned',after=cursor['after'],revision=cursor['revision'])
            more.extend(v['text'] for v in page['items']);cursor=page
            if not page['more']:break
        self.assertEqual(more,list(map(str,range(240,420))))
    def test_identity_replacement_symlink_and_invalid_cursors_refuse(self):
        self.append(message('First'));page=read(self.path,'owned')
        for args in ({'before':len(self.header)+1,'revision':page['revision']},{'after':len(self.header)},
                {'event':-1,'revision':page['revision']},{'technical':1},{'text_offset':1}):
            with self.assertRaises(ValueError):read(self.path,'owned',**args)
        replacement=self.path.with_name('replacement.jsonl');replacement.write_bytes(self.path.read_bytes());os.replace(replacement,self.path)
        with self.assertRaises(ValueError):read(self.path,'owned',revision=page['revision'])
        link=self.path.with_name('link');link.symlink_to(self.path)
        with self.assertRaises(OSError):read(link,'owned')
        with self.assertRaises(ValueError):read(self.path,'another')
        with self.assertRaises(ValueError):read(self.path,'owned',expected_file=(0,0))
    def test_oversized_record_does_not_block_the_view_or_change_originals(self):
        self.append(message('x'*(MAX_LINE+1)))
        original=self.path.read_bytes();page=read(self.path,'owned')
        self.assertEqual(page['items'],[]);self.assertGreater(page['skipped_records'],0)
        self.assertFalse(page['has_earlier']);self.assertEqual(self.path.read_bytes(),original)
    def test_huge_crossing_record_keeps_latest_messages_and_earlier_scan_progress(self):
        self.append(message('Earlier'),message('x'*(MAX_LINE*4)),message('Latest'))
        page=read(self.path,'owned');self.assertEqual([v['text']for v in page['items']],['Latest'])
        self.assertTrue(page['before_scan']);self.assertGreater(page['skipped_records'],0)
        seen=[]
        for _ in range(8):
            if not page['has_earlier']:break
            old=page['before'];page=read(self.path,'owned',before=old,scan=page['before_scan'],revision=page['revision'])
            self.assertLess(page['before'],old)
            seen=[v['text']for v in page['items']]+seen
        self.assertFalse(page['has_earlier']);self.assertEqual(seen,['Earlier'])
    def test_forward_scan_crosses_huge_record_and_resumes_at_real_newline(self):
        self.append(message('First'));page=read(self.path,'owned')
        self.append(message('x'*(MAX_LINE*4)),message('New answer'))
        seen=[]
        for _ in range(16):
            old=page['after'];page=read(self.path,'owned',after=old,scan=page['after_scan'],revision=page['revision'])
            self.assertGreater(page['after'],old)
            seen.extend(v['text']for v in page['items'])
            if not page['more']:break
        self.assertFalse(page['more']);self.assertEqual(seen,['New answer'])
        with self.assertRaises(ValueError):read(self.path,'owned',scan=True)
    def test_scan_cannot_expose_private_analysis_or_partial_json(self):
        self.append(message('x'*(MAX_LINE*4),channel='analysis'),message('Visible'))
        page=read(self.path,'owned');self.assertEqual([v['text']for v in page['items']],['Visible'])
        self.assertNotIn('xxx',json.dumps(page))


class PortableHistory(unittest.TestCase):
    def test_owned_generation_has_human_exchanges_only(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.executescript("""
                CREATE TABLE conversation_entry_generations(session_id, generation);
                CREATE TABLE sessions(id, creator_user_id);
                CREATE TABLE users(tg_user_id, allowed);
                CREATE TABLE interaction_instructions(sequence, input_id, doc, session_id, phase,id);
                CREATE TABLE interaction_sources(id, human_id, doc,channel,event_id);
                CREATE TABLE interaction_session_authors(input_id);
                CREATE TABLE interaction_results(local_turn,native_thread,native_turn,item_id,body);
                CREATE TABLE turns(id, session_id, from_user_id, execution_harness,
                  execution_generation, status, assistant_text, started_at, completed_at, native_thread_id);
                INSERT INTO users VALUES(10,1);
                INSERT INTO sessions VALUES(20,10);
                INSERT INTO conversation_entry_generations VALUES(20,'generation');
                INSERT INTO interaction_session_authors VALUES(2);
            """)
            def exchange(sequence, answer, generation='generation', status='completed'):
                db.execute("INSERT INTO interaction_sources VALUES(?,10,?,'conversation',?)",
                           (sequence,json.dumps({'text':f'Human {sequence}'}),f'input{sequence}'))
                db.execute("INSERT INTO interaction_instructions VALUES(?,?,?,20,'accepted',?)",
                           (sequence,sequence,json.dumps({'local_turn':sequence,'native_turn':f'turn{sequence}'}),f'instruction{sequence}'))
                db.execute("INSERT INTO turns VALUES(?,20,10,'claude',?,?,?,'start','finish','thread')",
                           (sequence,generation,status,answer))
                db.execute("INSERT INTO interaction_results VALUES(?,'thread',?,'final',?)",
                           (sequence,f'turn{sequence}',answer))
            exchange(1,'First')
            exchange(2,'Private result')
            exchange(3,'Old generation','old')
            exchange(4,'Unreadable attempt',status='failed')
            exchange(5,'Last')
            exchange(7,'Unfinished',status='running')
            exchange(8,'Private running',status='running')
            db.execute('INSERT INTO interaction_session_authors VALUES(8)')
            page=read_portable(db,20,10,'claude')
            self.assertEqual([item['text'] for item in page['items']],
                             ['Human 1','First','Human 5','Last'])
            self.assertEqual([item['text'] for item in page['pending_items']], ['Human 7'])
            self.assertEqual(page['pending_items'][0]['input_id'],'input7')
            end=page['after']
            revision=page['revision']
            self.assertEqual(read_portable(db,20,10,'claude',after=end,revision=revision)['items'],[])
            self.assertEqual(read_portable(db,20,10,'claude',before=10,revision=revision)['after'],4)
            exchange(6,'<daimon-result>{"requests":[],"covered":[]}</daimon-result>')
            empty=read_portable(db,20,10,'claude',after=end,revision=revision)
            self.assertEqual([v['text'] for v in empty['items']],['Human 6'])
            self.assertFalse(empty['more'])
            end=empty['after']
            exchange(0,'Recovered earlier admission')
            self.assertEqual([v['text'] for v in read_portable(db,20,10,'claude',after=end,revision=revision)['items']],
                             ['Human 0','Recovered earlier admission'])
            db.execute("UPDATE turns SET status='completed' WHERE id=7")
            db.execute("UPDATE interaction_results SET rowid=100 WHERE local_turn=7")
            completed=read_portable(db,20,10,'claude',after=end,revision=revision)
            self.assertEqual(completed['pending_items'],[])
            self.assertEqual([item['text'] for item in completed['items']],
                             ['Human 0','Recovered earlier admission','Human 7','Unfinished'])
            self.assertEqual(completed['items'][2]['input_id'],'input7')
            with self.assertRaises(ValueError):
                read_portable(db,20,11,'claude')
            db.execute("UPDATE conversation_entry_generations SET generation='replacement'")
            with self.assertRaises(ValueError):
                read_portable(db,20,10,'claude',after=end,revision=revision)

if __name__=='__main__':unittest.main()
