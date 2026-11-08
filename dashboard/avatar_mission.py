"""Mission entry/return over the existing account store and trusted school host.

The optional host resolves retained, authorized selections. No browser request
can supply a learner, space, actor, path, observation or display-review result.
"""
import copy
import hashlib


class AvatarMission:
    def __init__(self, store, host):
        self.store, self.host = store, host

    def context(self, human, request_id):
        self.store._ident(request_id)
        context = self.host.resolve(human, request_id)
        if (not isinstance(context, dict)
                or context.get('schema') != 'school-creativity.ascii-workshop-request/v1'
                or context.get('request_id') != request_id or context.get('mission_id') != 'ascii'):
            raise ValueError('The selected ASCII mission is unavailable')
        return copy.deepcopy(context)

    def entry(self, human, request_id):
        context = self.context(human, request_id)
        retained = self.host.returned(human, context)
        # No learner/space identifiers or private workspace paths in the editor.
        return {'request_id': request_id, 'mission_id': 'ascii', 'returned': retained}

    def return_saved(self, human, request_id, revision_id):
        context = self.context(human, request_id)
        record = self.store.get(human, revision_id)
        # Reuse the existing immutable read added by App785. A later validator
        # must not rewrite bytes or identity of an already saved revision.
        canonical = self.store.get(human, revision_id, canonical=True)
        if (not isinstance(canonical, str) or len(canonical.encode()) > 524288
                or hashlib.sha256(canonical.encode()).hexdigest() != record['sha256']):
            raise ValueError('Saved revision differs from its stored canonical bytes')
        snapshot = self.store.snapshot(human)
        # The host retains exact bytes and rechecks its selection before commit.
        # It must refuse a different revision for a previously returned request.
        return self.host.retain_return(human, context, record, snapshot, canonical.encode())
