"""Finite client-delegation preparation above existing native owners.

No background service, provider switch or separate Responses reasoner. The
caller owns one foreground preparation task and must end capture before cleanup.
"""
from .codex_voice_history import history_lock
from .openai_live_originals import enroll_original
from .openai_live_transcription import OriginalTranscription, interpret_original, commit_interpretation
from .openai_live_native_work import delegate_native
from .openai_live_native_results import return_native_part
from .provider import ProviderUnavailable


FORMULATION = (
    'Respond to the request in these exact retained acoustic originals, using '
    'your existing identity, memory and execution tools. Their text is a machine '
    'interpretation, not verified written human speech. Incorporate corrections; '
    'ask when intent is incomplete. Original retention and native acceptance '
    'do not establish task completion. Route any work through the existing integrator.')


def prepare_native(history, ident, human, owner, delegation, provider, key_file,
                   recognizer_factory=None, stopped=None):
    """Once per trusted sealed request; component intents own unknown effects."""
    def current(check_capture=True):
        if stopped is not None and stopped.is_set():
            raise ValueError('Native source preparation stopped; preserve in-flight outcomes')
        if not provider.authorized(human) or provider.public_live_binding(owner['binding']) != owner:
            raise ProviderUnavailable('Native preparation owner changed')
        value = history.read(ident, human, owner)
        if check_capture: history.check_capture(value)
        return value

    class ExecutionOwner:
        def __getattr__(self,name):return getattr(provider,name)
        def conversation_foreground_delegate(self,body):
            current()
            return provider.conversation_foreground_delegate(body)

    current(False)
    with history_lock(history.root / '.lock'):
        value = history.read(ident,human,owner)
        work = value['delegations'].get(delegation, {})
        if work.get('target') != 'client': raise ValueError('Select a trusted client delegation')
        if 'native_pipeline' in work: return dict(work['native_pipeline'])
        history.check_capture(value)
        seal = work.get('source_seal', {})
        if seal.get('state') not in ('sealed','empty'):
            raise ValueError('Select a confirmed source window')
        if not 1 <= len(seal['recordings']) <= 8:
            work['native_pipeline']={'state':'held','work_completed':False,
                'meaning':'The confirmed source window is empty or exceeds the native source bound; no inference was requested.'}
            work['state']='native_preparation_held';history._write(value)
            return dict(work['native_pipeline'])
        ordinals = [row['ordinal'] for row in seal['recordings']]
        work['native_pipeline'] = {'state':'preparing','ordinals':ordinals}
        work['native_pipeline_reserve'] = ' ' * 2048
        history._write(value)
    result = {'state':'held','ordinals':ordinals,'work_completed':False,
        'meaning':'Preparation outcome needs review; originals and exact component intents are retained. Do not replay.'}
    try:
        total = 0
        for ordinal in ordinals:
            current()
            if enroll_original(history,ident,human,owner,ordinal,provider)['state'] != 'observed': break
            current()
            old = history.read(ident,human,owner)['native_originals'][str(ordinal)].get('interpretation')
            recognizer=None
            if old is None:
                selected=(recognizer_factory or OriginalTranscription)(key_file)
                class OwnedRecognizer:
                    model=selected.model
                    def transcribe(self,data):
                        current()
                        return selected.transcribe(data)
                recognizer=OwnedRecognizer()
            derivative = interpret_original(history,ident,human,owner,ordinal,provider,
                recognizer)
            if derivative['state'] != 'completed': break
            total += len(derivative['text'].encode())
            if total > 65536: raise ValueError('Native source context exceeds its existing bound')
            current()
            if commit_interpretation(history,ident,human,owner,ordinal,provider)['state'] != 'observed': break
        else:
            current()
            admitted = delegate_native(history,ident,human,owner,delegation,ordinals,FORMULATION,ExecutionOwner())
            result = {'state':'admitted' if admitted['state']=='observed' else 'unconfirmed',
                'ordinals':ordinals,'root':admitted['root'],'work_completed':False,
                'meaning':'Native handoff observation only; actual work/results and hearing remain separate.'}
    finally:
        # A paid/native operation may have completed after revocation or close.
        # Preserve its bounded outcome without requiring a live interpreting turn.
        with history_lock(history.root / '.lock'):
            value = history.read(ident,human,owner); work=value['delegations'][delegation]
            work['native_pipeline']=result
            work['state']='native_handed_off' if result['state']=='admitted' else 'native_preparation_held'
            work.pop('native_pipeline_reserve',None)
            history._write(value)
    return dict(result)


def return_one_native_part(history, ident, human, owner, delegation, provider, sideband):
    """One bounded source page per foreground poll; never starts native work.

    Same-turn progress/answers are supported here. Cross-turn native callbacks,
    older worker deliveries and renewal catch-up still require retained trace
    association and cursor integration; they must not be guessed from recency.
    """
    if not provider.authorized(human) or provider.public_live_binding(owner['binding'])!=owner:
        raise ProviderUnavailable('Native result owner changed')
    value=history.read(ident,human,owner)
    work=value['delegations'].get(delegation,{})
    if work.get('native_work',{}).get('state')!='observed': return None
    updates=[row for row in value.get('native_result_updates',{}).values() if row['delegation']==delegation]
    for row in updates:
        if row['state']!='context_injected': return None
        if row['next_offset'] is not None and not any(other['source']==row['source']
                and other['revision']==row['revision'] and other['offset']==row['next_offset'] for other in updates):
            return return_native_part(history,ident,human,owner,delegation,row['source'],row['revision'],
                row['next_offset'],provider,sideband)
    native=provider.conversation_input_status(work['native_work']['root'])
    if type(native.get('local_turn')) is not int: return None
    cursor={'delivery':0,'native':work['native_work']['native_source_floor']}
    for _ in range(8):
        page=provider.presentation_list(cursor['delivery'],cursor['native'],'after')
        if page.get('binding')!=owner['binding']:raise ProviderUnavailable('Native result conversation changed')
        for source in page['items']:
            if (source.get('kind') in ('integrator_answer','integrator_progress')
                    and source.get('local_turn')==native['local_turn']
                    and source.get('current') is not False and source.get('correction_pending') is not True
                    and source.get('native_binding_current') is not False
                    and not any(row['source']==source['id'] and row['revision']==source['revision'] for row in updates)):
                return return_native_part(history,ident,human,owner,delegation,source['id'],source['revision'],0,provider,sideband)
        if not page.get('more'): break
        if page.get('cursor')==cursor:raise ValueError('Native result cursor did not advance')
        cursor=page['cursor']
    return None
