#!/usr/bin/env python3
"""Selected native history: bounded pagination, append races and private analysis."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.session_view import read,MAX_LINE,TEXT_PART,WINDOW


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

if __name__=='__main__':unittest.main()
