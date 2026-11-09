#!/usr/bin/env python3
"""Voice-first metadata creation through the real native owner; zero inference."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from conversation_input_control_io import Inputs


def run(binary):
    j=Inputs(binary)
    j.config.write_text(j.config.read_text()+'\n[voice]\ntranscription_command=["/usr/bin/false"]\ntranscriber_label="synthetic/must-not-run"\n')
    try:
        j.start();j.wait_control_socket(j.socket)
        caps=j.read('input','voice','capabilities')['result']
        binding=caps['binding']
        assert caps['voice_available'] is True and not caps['entry_binding'][3],caps
        assert j.row('SELECT count(*) FROM turns')==[(0,)]
        assert not [r for r in j.rpc if r.get('method')=='thread/start']
        rejected=j.read('input','voice','native','initialize',json.dumps({'binding':'f'*64}),ok=False)
        assert rejected['ok'] is False
        def initialize():return j.read('input','voice','native','initialize',json.dumps({'binding':binding}))['result']
        with ThreadPoolExecutor(max_workers=2) as workers:
            futures=[workers.submit(initialize) for _ in range(2)]
            outcomes=[future.result(timeout=15) for future in futures]
        result=outcomes[0];assert outcomes[1]==result,outcomes
        native=result['entry_binding'][3]
        assert native and result['binding']==binding,result
        assert len([r for r in j.rpc if r.get('method')=='thread/start'])==1,j.rpc
        assert not [r for r in j.rpc if r.get('method')=='turn/start'],j.rpc
        for table in ('turns','conversation_inputs','incoming_updates'):
            assert j.row('SELECT count(*) FROM '+table)==[(0,)],table
        again=j.read('input','voice','native','initialize',json.dumps({'binding':binding}))['result']
        assert again==result,(again,result)
        j.stop();j.start();j.wait_control_socket(j.socket)
        reopened=j.read('input','voice','native','initialize',json.dumps({'binding':binding}))['result']
        assert reopened['entry_binding'][3]==native and reopened['binding']==binding
        assert len([r for r in j.rpc if r.get('method')=='thread/start'])==1
        assert j.row("SELECT json_extract(native_initialization,'$.phase') FROM conversation_entry_generations WHERE session_id=?",(result['entry_binding'][2],))==[('bound',)]
        print('PASS voice-first native owner: one thread/start, zero turn/start or invented input, stable logical binding, concurrent starts, warm retry and receiver restart reuse exact retained native metadata; zero providers.')
    finally:j.close()

if __name__=='__main__':run(sys.argv[1])
