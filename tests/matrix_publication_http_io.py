#!/usr/bin/env python3
"""Actual owner socket/SQLite/shared-login HTTP publication; no Telegram or inference.

Identity response and native harness are synthetic. Real Matrix receiving and
household/device acceptance require the deployed seven-body journey separately.
"""
import base64
import json
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi.testclient import TestClient
from dashboard.app import create_app
from dashboard.provider import Provider
from conversation_input_control_io import Inputs
from daimon_matrix import mandatory_echo as echo


def canonical(v):
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()


def qualify(binary):
    j=Inputs(str(Path(binary).resolve()));client=None;native=None
    fixture=json.loads((Path(__file__).parent/'fixtures/matrix-publication-v1.json').read_text())
    request=fixture['request'];publication=fixture['policy']['publication']
    try:
        key=j.root/'publication.key';key.write_bytes(b'p'*32);key.chmod(0o600)
        config=j.config.read_text().replace('[telegram]','[telegram]\nenabled=false')
        config='\n'.join(v for v in config.splitlines() if not v.startswith('bot_token_file='))+'\n'
        config+='\n[interaction.matrix_publication]\nsurface_ref='+json.dumps(publication['surface_ref'])+'\naudience='+json.dumps(publication['audience'])+'\nsigning_key_file='+json.dumps(str(key))+'\n'
        j.config.write_text(config);(j.root/'bot.token').unlink()
        j.start();j.wait_control_socket(j.socket)
        assert j.row('SELECT codex_thread_id FROM sessions WHERE thread_id=1')==[(None,)]
        turns=j.row('SELECT count(*) FROM turns')
        def commit(value,ok=True):
            result=subprocess.run([j.binary,'--control',str(j.config),'matrix','publication','commit'],
                input=canonical(value),capture_output=True,timeout=15)
            assert (result.returncode==0)==ok,result.stderr.decode()
            return json.loads(result.stdout)
        assert j.read('matrix','publication','status')['result']==publication
        # Real native journal -> actual existing App owner socket -> durable
        # signed receipt -> native commit -> exact acknowledgment for retirement.
        publisher=echo.ConversationJournalTransport(j.socket)
        projection=json.loads(request['text'].split('\n',1)[1])
        native=sqlite3.connect(j.root/'native-publication.sqlite',isolation_level=None)
        native.execute('BEGIN IMMEDIATE')
        echo.EchoJournal.initialize(native,catalog_id='portable-fixture',authentication_key=b'k'*32)
        native.commit()
        journal=echo.EchoJournal(native,catalog_id='portable-fixture',authentication_key=b'k'*32)
        native.execute('BEGIN IMMEDIATE')
        digest=journal.admit('portable-operation',projection,fixture['policy'],publication_not_after_ms=request['not_after_ms'])
        native.commit()
        worker=echo.MandatoryEcho(journal,transport=publisher,resolve=lambda _:projection,authorize=lambda _:True)
        acknowledge=publisher.confirm_publications
        def after_native_commit(values):
            assert not native.in_transaction
            observer=sqlite3.connect(j.root/'native-publication.sqlite',isolation_level=None)
            try:
                observed=echo.EchoJournal(observer,catalog_id='portable-fixture',authentication_key=b'k'*32)
                assert echo._status(observed._load('portable-operation',digest))['state']=='confirmed'
            finally:observer.close()
            acknowledge(values)
        with patch.object(publisher,'confirm_publications',side_effect=after_native_commit):
            assert worker.advance('portable-operation',digest)['state']=='confirmed'
            assert worker.advance('portable-operation',digest)['state']=='confirmed'
        record=worker.require_confirmed('portable-operation',digest)
        first=json.loads(record['parts'][0]['attempts'][0]['response']);assert first['durable'] is True
        assert j.row('SELECT confirmed_at_ms IS NOT NULL FROM conversation_matrix_publications')==[(1,)]
        body={k:v for k,v in first.items() if k!='signature'}
        Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(publication['receipt_key']+'=')).verify(
            base64.urlsafe_b64decode(first['signature']+'=='),canonical(body))
        assert commit(request)['result']==first
        assert j.read('matrix','publication','confirm',request['publication_id'],first['request_sha256'])['result']['publication_acknowledged'] is True
        assert j.read('matrix','publication','retire')['result']['retired']==0
        assert j.row('SELECT count(*) FROM conversation_matrix_publications')==[(1,)]
        wrong={**request,'text':'Changed under the same publication ID'}
        assert commit(wrong,ok=False)['ok'] is False
        wrong={**request,'audience':['fixture:foreign-human']}
        assert commit(wrong,ok=False)['ok'] is False
        # No browser was required for publication. A later authenticated reader
        # consumes that same committed content through ordinary presentation.
        c={'receiver_config':str(j.config),'state_dir':str(j.root/'web-only'),
            'origin':'https://child.example.test','prefix':'/interaction','application_id':str(uuid.uuid4()),
            'shared_auth':{'enabled':True,'home_origin':'https://child.example.test',
                           'human_ref':publication['audience'][0]}}
        provider=Provider(c);assert provider.authorized(100)
        client=TestClient(create_app(c,provider),base_url=c['origin'])
        headers={'Host':'child.example.test','Origin':c['origin'],'Cookie':'__Host-home='+'h'*43}
        identity={'contract':'dm.home-session/v1','origin':c['origin'],'expires':int(time.time())+3600,
                  'actor':{'kind':'human','ref':publication['audience'][0]}}
        with patch('dashboard.home_auth.identity_response',return_value=identity):
            page=client.get('/api/interaction?matrix=0&inbox=0&responses=0&publications=0',headers=headers)
            assert page.status_code==200,page.text
            rows=page.json()['items'];assert len(rows)==1,rows
            selected=rows[0];assert selected['kind']=='matrix_visibility'
            assert selected['id']=='matrix-publication:'+request['publication_id']
            result=client.get('/api/interaction/part',params={'source':selected['id'],
                'revision':selected['revision'],'offset':0},headers=headers)
            assert result.status_code==200,result.text
            assert result.json()['text']==request['text']
            foreign={**identity,'actor':{'kind':'human','ref':'human:local:00000000-0000-4000-8000-000000000200'}}
            with patch('dashboard.home_auth.identity_response',return_value=foreign):
                denied=client.get('/api/interaction/part',params={'source':selected['id'],
                    'revision':selected['revision'],'offset':0},headers={**headers,'Cookie':'__Host-home='+'f'*43})
                assert denied.status_code in (401,403),denied.text
        client.close();client=None
        # A lost result can be recovered by an exact read, never another write.
        # If that read is unavailable too, uncertainty stays pinned across calls.
        for operation,read_unavailable in (('lost-publication',False),('lost-and-unreadable',True)):
            native.execute('BEGIN IMMEDIATE')
            lost=journal.admit(operation,projection,fixture['policy'],publication_not_after_ms=request['not_after_ms'])
            native.commit()
            uncertain=echo.ConversationJournalTransport(j.socket)
            exchange=uncertain._exchange
            def drop_result(command,deadline):
                if read_unavailable and command.startswith('matrix publication inspect '):
                    raise TimeoutError('fixture retained proof read unavailable')
                value=exchange(command,deadline)
                if command.startswith('matrix publication commit '):
                    raise TimeoutError('fixture lost result after actual backend commit')
                return value
            lost_worker=echo.MandatoryEcho(journal,transport=uncertain,resolve=lambda _:projection,authorize=lambda _:True)
            with patch.object(uncertain,'_exchange',side_effect=drop_result) as attempts:
                expected='ambiguous' if read_unavailable else 'confirmed'
                assert lost_worker.advance(operation,lost)['state']==expected
                assert lost_worker.advance(operation,lost)['state']==expected
                commands=[call.args[0] for call in attempts.call_args_list]
                assert sum(c.startswith('matrix publication commit ') for c in commands)==1
                assert sum(c.startswith('matrix publication inspect ') for c in commands)==1
            if not read_unavailable:
                retained=journal._load(operation,lost)
                assert retained['parts'][0]['attempts'][0]['response_source']=='retained-publication'
        assert j.row('SELECT count(*) FROM conversation_matrix_publications WHERE confirmed_at_ms IS NULL')==[(1,)]
        j.stop();j.start();j.wait_control_socket(j.socket)
        assert j.read('matrix','publication','inspect',request['publication_id'])['result']==first
        assert j.row('SELECT count(*) FROM turns')==turns
        assert j.row('SELECT count(*) FROM incoming_updates')==[(0,)]
        assert not j.telegram_methods and not j.messages and not j.packets
        assert not (j.root/'bot.token').exists()
        print('PASS actual native journal -> App owner publication -> committed native proof acknowledgment; no-browser authenticated HTTP/foreign denial, restart/exact recovery, bounded lost-result proof inspection and no duplicate publication; zero inference, Telegram or peer transmissions')
    finally:
        if client:client.close()
        if native:native.close()
        j.close()

if __name__=='__main__':qualify(sys.argv[1])
