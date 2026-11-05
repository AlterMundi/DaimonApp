#!/usr/bin/env python3
"""Actual owner IPC/SQLite/collector restart with synthetic native work only."""
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.provider import Provider, ProviderUnavailable
from stopping_io import Stopping


def qualify(binary):
    j=Stopping(str(Path(binary).resolve()))
    try:
        with j.config.open('a')as f:
            f.write('\n[interaction]\nhuman_id=100\nchat_id=100\ntopic_id=7\n')
        j.seed()
        provider=Provider({'receiver_config':str(j.config)})
        binding=provider.presentation('input voice native capabilities')['binding']
        frozen=provider.codex_voice_binding(binding)
        assert frozen['native_thread']=='native-topic-7'
        physical=j.holding[frozen['native_thread']]
        j.wait(lambda:provider.codex_voice_collect(frozen,physical)['state']=='collecting')
        j.holding[frozen['native_thread']]='new-writer-not-yet-collected'
        assert provider.codex_voice_collect(frozen,'new-writer-not-yet-collected')['state']=='pending'
        j.holding[frozen['native_thread']]=physical
        starts=sum(r.get('method')=='turn/start'for r in j.rpc)
        goals=copy.deepcopy(j.goals)
        assert provider.codex_voice_collect(frozen,'completed-or-unrelated')['state']=='not_current'
        try:provider.codex_voice_binding('b'*64)
        except ProviderUnavailable:pass
        else:raise AssertionError('Stale voice binding was accepted')
        j.stop();j.start()
        checkpoint=len(j.rpc)
        def attach():
            try:return provider.codex_voice_collect(frozen,physical)['state']
            except ProviderUnavailable:return 'superseded'
        with ThreadPoolExecutor(max_workers=2)as pool:
            outcomes=list(pool.map(lambda _:attach(),range(2)))
        assert outcomes.count('attachment_queued')==1,outcomes
        assert set(outcomes)<={'attachment_queued','collecting','pending','superseded'},outcomes
        j.wait(lambda:provider.codex_voice_collect(frozen,physical)['state']=='collecting')
        for _ in range(3):
            assert provider.codex_voice_collect(frozen,physical)['state']=='collecting'
        assert j.row("SELECT count(*) FROM turns WHERE prompt='Owner-local collector attachment; no new native input.'")==[(1,)]
        assert sum(r.get('method')=='turn/start'for r in j.rpc)==starts
        assert not any(r.get('method')in('turn/steer','turn/interrupt','thread/goal/set','thread/goal/clear')for r in j.rpc[checkpoint:])
        assert j.goals==goals
        # Synthetic retained fences only, not a Stop operation or interruption.
        for held in ('maintenance','stop'):
            with sqlite3.connect(j.root/'state.sqlite')as db:
                if held=='maintenance':
                    db.execute("INSERT INTO bot_state(key,value)VALUES('native_writer_hold:100:7','synthetic')")
                else:
                    db.execute("INSERT INTO stop_operations VALUES('synthetic-fence',100,'synthetic-fence','stopped','{}')")
            before=len(j.rpc)
            for command in ('input voice native capabilities','input voice native attach '+json.dumps({
                    'binding':binding,'native_thread':frozen['native_thread'],'native_turn':physical})):
                try:provider.presentation(command)
                except ProviderUnavailable:pass
                else:raise AssertionError('Held native voice was admitted')
            assert len(j.rpc)==before
            with sqlite3.connect(j.root/'state.sqlite')as db:
                if held=='maintenance':db.execute("DELETE FROM bot_state WHERE key='native_writer_hold:100:7'")
                else:db.execute("DELETE FROM stop_operations WHERE id='synthetic-fence'")
        j.holding.pop(frozen['native_thread'])
        j.finish(frozen['native_thread'],physical)
        j.wait(lambda:j.has('Initial goal turn delivered.',7))
        assert provider.codex_voice_collect(frozen,physical)['state']=='not_current'
        assert j.row('SELECT count(*) FROM stop_operations')==[(0,)]
        print('PASS native voice owner binding and exact collector restart without input replay, duplicate worker, goal mutation or Stop')
    finally:j.close()


if __name__=='__main__':qualify(sys.argv[1])
