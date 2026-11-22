#!/usr/bin/env python3
"""One legacy validation rejection repaired through real controller/SQLite; no models."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import uuid
from goal_activation_io import Activation


def qualify(binary):
    j = Activation(binary)
    try:
        j.prepare(seed_entry=True)
        j.allow_native_launch = True
        j.wait_control_socket(j.socket)
        binding = j.owner('presentation', 'list', '0', '0')['binding']
        original = str(uuid.uuid4())
        j.owner('input', 'submit', json.dumps({'id': original, 'binding': binding,
                                             'text': 'Start Alpha with the complete selected task. Preserve final human reset confirmation.'}))
        j.wait(lambda: j.row('SELECT phase FROM conversation_inputs WHERE id=?', (original,)) == [('accepted',)])
        entry = j.access(1)
        observed = j.cli(entry, 'goal_inspect', {'selector': 'Alpha'})
        args = {'selector': 'Alpha', 'input_ref': original, 'target_binding': observed['target_binding'],
                'reason': 'Explicit retained human start', 'plan': {'action': 'start',
                'expected': observed['snapshot'], 'objective': 'Complete selected task; final reset remains human-only.',
                'token_budget': None, 'followup': None}}
        oversized = copy.deepcopy(args)
        oversized['plan']['objective'] = '😀' * 4001
        j.cli(entry, 'goal_prepare', oversized, ok=False)
        assert j.row('SELECT count(*) FROM interaction_goal_controls') == [(0,)]
        first = j.cli(entry, 'goal_prepare', args)['control']
        selected = first['id']
        # Historical on-disk receipt from the previous writer: definitive native
        # validation rejection, with no goal or partial replacement effect.
        old = copy.deepcopy(first['intent'])
        old['plan']['objective'] = 'x' * 4039
        old['ever_claimed'] = True
        old['attempt'] = 'legacy-rejected-attempt'
        old['expires_at'] = 1  # The rejected interpretation's submission window expired.
        receipt = {'native_error_code': -32600,
                   'error': 'goal objective must be at most 4000 characters | code -32600',
                   'native_receipt': None, 'replacement_clear': None}
        with sqlite3.connect(j.root / 'state.sqlite') as db:
            db.execute("UPDATE interaction_goal_controls SET phase='rejected',doc=?,result=? WHERE id=?",
                       (json.dumps(old), json.dumps(receipt), selected))
            db.execute("INSERT INTO bot_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       ('goal_intent:100:7', selected))
        count = j.row('SELECT count(*) FROM conversation_inputs')
        # Uncertain results may never enter the repair branch.
        with sqlite3.connect(j.root / 'state.sqlite') as db:
            db.execute("UPDATE interaction_goal_controls SET phase='uncertain' WHERE id=?", (selected,))
        j.cli(entry, 'goal_prepare', args, ok=False)
        with sqlite3.connect(j.root / 'state.sqlite') as db:
            db.execute("UPDATE interaction_goal_controls SET phase='rejected' WHERE id=?", (selected,))
        repaired = j.cli(entry, 'goal_prepare', args)['control']
        assert repaired['id'] == selected and repaired['phase'] == 'known_unsent'
        assert repaired['intent']['objective_validation_repair']['plan'] == old['plan']
        assert repaired['intent']['objective_validation_repair']['result'] == receipt
        assert repaired['intent']['original'] == old['original']
        assert repaired['intent']['objective_validation_repair']['expires_at'] == old['expires_at']
        assert repaired['intent']['expires_at'] > old['expires_at']
        assert j.cli(entry, 'goal_prepare', args)['control'] == repaired
        assert j.row('SELECT count(*) FROM conversation_inputs') == count
        j.cli(entry, 'goal_execute', {'id': selected})
        j.wait(lambda: j.row('SELECT phase FROM interaction_goal_controls WHERE id=?', (selected,)) == [('acknowledged',)])
        assert j.goals['native-topic-7']['status'] == 'active'
        assert j.goals['native-topic-7']['objective'] == args['plan']['objective']
        before = sum(m.get('method') == 'thread/goal/conditionalActivate' for m in j.rpc)
        j.cli(entry, 'goal_execute', {'id': selected})
        assert sum(m.get('method') == 'thread/goal/conditionalActivate' for m in j.rpc) == before == 1
        print('PASS same-original legacy objective repair, no uncertain replay, preserved source/original deadline, one bounded fresh window, one native activation')
    finally:
        j.close()


if __name__ == '__main__':
    qualify(str(Path(sys.argv[1]).resolve()))
