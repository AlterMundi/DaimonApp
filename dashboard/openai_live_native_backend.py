"""Finite client-delegation preparation above existing native owners.

No background service, provider switch or separate Responses reasoner. The
caller owns one foreground preparation task and must end capture before cleanup.
"""
import re
import json
import uuid

from .codex_voice_history import history_lock
from .openai_live_originals import enroll_original
from .openai_live_window import freeze_input_window
from .openai_live_native_work import delegate_native
from .openai_live_native_results import return_native_part, _origin_returns
from .provider import ProviderUnavailable


FORMULATION = (
    'Respond to the request in these exact retained acoustic originals, using '
    'your existing identity, memory and execution tools. Their text is a machine '
    'interpretation, not verified written human speech. Incorporate corrections; '
    'ask when intent is incomplete. Original retention and native acceptance '
    'do not establish task completion. Route any work through the existing integrator.')


def prepare_native(history, ident, human, owner, delegation, provider, key_file,
                   recognizer_factory=None, stopped=None,before_delegate=None):
    """Once per trusted sealed request; component intents own unknown effects."""
    def current(check_capture=True):
        if check_capture and stopped is not None and stopped.is_set():
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

    # The configured key and old fixture factory cannot start recognition here.
    del key_file, recognizer_factory
    current(False)
    caps=provider.presentation('input voice capabilities')
    if (caps.get('binding')!=owner['binding'] or caps.get('foreground_live_window')!='journal-input/v1'
            or caps.get('voice_available') is not True):
        raise ValueError('Native Live-window reader is not selected; no second ASR or work requested')
    with history_lock(history.root / '.lock'):
        value = history.read(ident,human,owner)
        work = value['delegations'].get(delegation, {})
        if work.get('target') != 'client': raise ValueError('Select a trusted client delegation')
        if 'native_pipeline' in work: return dict(work['native_pipeline'])
        if value['admission']['epoch']!=history.epoch:
            raise ValueError('Restart cannot start unattempted native preparation')
        cancelled=stopped is not None and stopped.is_set()
        try:history.check_capture(value)
        except ValueError:cancelled=True
        if cancelled:
            work['native_pipeline']={'state':'held','work_completed':False,
                'meaning':'No new preparation was started; previous component outcomes are retained.'}
            work['state']='native_preparation_held';history._write(value)
            return dict(work['native_pipeline'])
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
        for ordinal in ordinals:
            current()
            if enroll_original(history,ident,human,owner,ordinal,provider)['state'] != 'observed': break
        else:
            current()
            window=freeze_input_window(history,ident,human,owner,delegation)
            current()
            formulation=FORMULATION+' Live input language belongs to the entire retained acoustic window, with approximate provider timing; never assign it verbatim to an individual audio chunk. Preserve uncertainty, missing or late fragments and later corrections.'
            if before_delegate is not None:
                reference=before_delegate()
                if (not isinstance(reference,dict) or set(reference)!={'dialogue','generation'}
                        or any(not isinstance(reference[k],str) or str(uuid.UUID(reference[k]))!=reference[k]
                            for k in ('dialogue','generation'))):
                    raise ValueError('Select the exact native semantic context reference')
                current()
                formulation+=' Prior conversation source context is retained in the existing native semantic producer: '+json.dumps(reference,separators=(',',':'))+'. Read it when resolving prior facts, corrections or short replies; it is not another work request.'
            admitted = delegate_native(history,ident,human,owner,delegation,ordinals,formulation,ExecutionOwner(),live_window=window)
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


def return_one_native_part(history, ident, human, owner, delegation, provider, sideband, *, stopped=None, source_visit=None):
    """Read at most eight source pages and append one fragment per foreground poll.

    Current trace-associated worker deliveries use exact canonical revisions,
    even after the native turn ends or the conversation page moves on. Older
    readers without revision-bearing traces keep same-turn progress/answers;
    excerpts are never substituted. A renewed voice reads the original work
    proof and flat forwarding references without issuing that work again.
    """
    def current():
        if stopped is not None and stopped.is_set():raise ValueError('Voice result read ended')
    current()
    if not provider.authorized(human) or provider.public_live_binding(owner['binding'])!=owner:
        raise ProviderUnavailable('Native result owner changed')
    origin=ident if source_visit is None else history._ident(source_visit)
    value=history.read(origin,human,owner)
    work=value['delegations'].get(delegation,{})
    if work.get('native_work',{}).get('state')!='observed': return None
    if origin==ident:
        updates=[row for row in value.get('native_result_updates',{}).values()
                 if row['delegation']==delegation and row.get('origin_visit',ident)==ident]
    else:
        with history_lock(history.root / '.lock'):
            updates=[row for _,row in _origin_returns(history,history.read(origin,human,owner),human,owner,delegation)]
    def emit(source,revision,offset):
        return return_native_part(history,ident,human,owner,delegation,source,revision,
                                  offset,provider,sideband,stopped=stopped,source_visit=source_visit)
    for row in updates:
        if row['state']!='context_injected': return None
        if row['next_offset'] is not None and not any(other['source']==row['source']
                and other['revision']==row['revision'] and other['offset']==row['next_offset'] for other in updates):
            return emit(row['source'],row['revision'],row['next_offset'])
    trace=provider.conversation_input_trace(work['native_work']['root'])
    current()
    if (trace.get('id')!=work['native_work']['root']
            or trace.get('entry_binding')!=owner['entry_binding']):
        raise ProviderUnavailable('Worker result original binding changed')
    routes=trace.get('routes',[])
    if not isinstance(routes,list) or len(routes)>5:raise ValueError('Native result route bound exceeded')
    for route in routes:
        results=route.get('results',[])
        if not isinstance(results,list) or len(results)>8:raise ValueError('Native result trace bound exceeded')
        if route.get('target_available') is not True:continue
        for result in reversed(results):
            source,revision=result.get('source'),result.get('revision')
            if (result.get('instruction_covered') is True and result.get('current') is True
                    and result.get('correction_pending') is False
                    and isinstance(source,str) and re.fullmatch(r'delivery:[a-f0-9-]{36}',source)
                    and isinstance(revision,str) and re.fullmatch('[a-f0-9]{64}',revision)
                    and not any(row['source']==source and row['revision']==revision for row in updates)):
                return emit(source,revision,0)
    native=provider.conversation_input_status(work['native_work']['root'])
    current()
    if type(native.get('local_turn')) is not int: return None
    def scanned(after):
        if type(after) is not int or after<0:raise ValueError('Invalid native result cursor')
        with history_lock(history.root / '.lock'):
            latest=history.read(origin,human,owner)
            pipeline=latest['delegations'][delegation]['native_pipeline']
            pipeline['return_after']=max(pipeline.get('return_after',0),after)
            history._write(latest)
    cursor={'delivery':0,'native':work['native_pipeline'].get('return_after',work['native_work']['native_source_floor'])}
    for _ in range(8):
        current()
        page=provider.presentation_list(cursor['delivery'],cursor['native'],'after')
        current()
        if page.get('binding')!=owner['binding']:raise ProviderUnavailable('Native result conversation changed')
        for source in page['items']:
            if (source.get('kind') in ('integrator_answer','integrator_progress')
                    and source.get('local_turn')==native['local_turn']
                    and source.get('current') is not False and source.get('correction_pending') is not True
                    and source.get('native_binding_current') is not False
                    and not any(row['source']==source['id'] and row['revision']==source['revision'] for row in updates)):
                result=emit(source['id'],source['revision'],0)
                scanned(int(source['id'].split(':')[1]))
                return result
        scanned(page.get('cursor',cursor)['native'])
        if not page.get('more'): break
        if page.get('cursor')==cursor:raise ValueError('Native result cursor did not advance')
        cursor=page['cursor']
    return None


def return_next_native_part(history,ident,human,owner,cycle,provider,sideband,*,stopped=None):
    """One owned foreground task alternates current work and historical origins.

    Discovery and native reads stay outside the browser-control loop. The
    persisted flat cursor survives another voice replacement, not a model lease.
    """
    if type(cycle) is not int or cycle<0:raise ValueError('Select a bounded return cycle')
    if stopped is not None and stopped.is_set():return None
    if not provider.authorized(human) or provider.public_live_binding(owner['binding'])!=owner:
        raise ProviderUnavailable('Native result owner changed')
    value=history.read(ident,human,owner)
    ready=[key for key,work in value['delegations'].items()
           if work.get('native_work',{}).get('state')=='observed']
    previous=None
    if not ready or cycle%2:
        previous=history.native_return_origin(ident,human,owner)
    if stopped is not None and stopped.is_set():return None
    if previous:
        return return_one_native_part(history,ident,human,owner,previous['delegation'],provider,
                                      sideband,stopped=stopped,source_visit=previous['visit'])
    if ready:
        return return_one_native_part(history,ident,human,owner,ready[(cycle//2)%len(ready)],
                                      provider,sideband,stopped=stopped)
    return None
