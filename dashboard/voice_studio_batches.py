"""Bounded frozen A/B attempts in the existing workshop account document.

No provider calls or media store. Server-owned planner/retirer callbacks reuse
existing speech job identities and locks; unknown effects are never retired.
"""
import copy
import hashlib
import json
import time
from .codex_voice_history import history_lock
from .avatar_workshop_voice import voice_state,voice_profile
from .voice_studio import choice

PASSAGE='Dale, Compai. Sigamos con la idea de Alter Mundi, con calma y claridad.'
MAX_BATCHES=4
TERMINAL={'rendered','not_started','cancelled_verified'}


def preview_state(value):
    state=value.get('voice_previews',{'generation':0,'batches':[]})
    if (not isinstance(state,dict) or set(state)!={'generation','batches'}
            or type(state['generation']) is not int or not 0<=state['generation']<2**53
            or not isinstance(state['batches'],list) or len(state['batches'])>MAX_BATCHES):
        raise ValueError('Voice previews need review; no state was reset')
    return state


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


class WorkshopPreviewBatches:
    def preview_snapshot(self,human):
        with history_lock(self.root/'.lock'):return copy.deepcopy(preview_state(self._read(human)))

    def preview_prepare(self,human,ident,profile,delivery,voice_generation,generation,planner):
        self._ident(ident);voice_profile(profile,delivery)
        request=digest([profile,delivery,voice_generation,generation])
        with history_lock(self.root/'.lock'):
            value=self._read(human);previews=preview_state(value)
            old=next((r for r in previews['batches'] if r['id']==ident),None)
            if old is not None:
                if old['request_sha256']!=request:raise self.conflict_error('A preview batch is immutable')
                return copy.deepcopy(old)
            self._expected(previews,generation);voices=voice_state(value);self._expected(voices,voice_generation)
            if len(previews['batches'])>=MAX_BATCHES:raise ValueError('Preview library is full; retire a completed batch')
            active=next((r for r in voices['versions'] if r['id']==voices['active']),None)
            current=choice(active,profile)
            candidate={'revision':None,'profile':copy.deepcopy(profile),'delivery':delivery,
                       'sha256':voice_profile(profile,delivery)[1]}
            row={'id':ident,'generation':generation+1,'request_sha256':request,'createdAt':int(time.time()*1000),
                 'phase':'prepared','passage':PASSAGE,'choices':{'A':current,'B':candidate}}
            planned=planner(copy.deepcopy(row))
            if (not isinstance(planned,dict) or set(planned)!={'A','B'}
                    or any(not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v) for v in planned.values())):
                raise ValueError('Preview needs exact receiving render identities')
            row['renders']={k:{'id':v,'state':'prepared'} for k,v in planned.items()}
            previews=copy.deepcopy(previews);previews['generation']+=1;previews['batches'].append(row)
            value['voice_previews']=previews;self._write(human,value)
            return copy.deepcopy(row)

    @staticmethod
    def _preview_row(state,ident,generation):
        if not isinstance(ident,str) or type(generation) is not int or not 0<generation<2**53:
            raise ValueError('Select the exact preview batch generation')
        row=next((r for r in state['batches'] if r['id']==ident and r['generation']==generation),None)
        if row is None:raise KeyError('Preview batch unavailable for this account or generation')
        return row

    def preview_start(self,human,ident,generation,slot):
        if slot not in ('A','B'):raise ValueError('Select preview A or B')
        with history_lock(self.root/'.lock'):
            value=self._read(human);previews=copy.deepcopy(preview_state(value));row=self._preview_row(previews,ident,generation)
            if row['phase']=='retiring':raise ValueError('Preview retirement is incomplete; no new work')
            render=row['renders'][slot];fresh=render['state']=='prepared'
            if fresh:
                render.update(state='intent',startedAt=int(time.time()*1000));value['voice_previews']=previews;self._write(human,value)
            return copy.deepcopy(row),fresh

    def preview_cancel(self,human,ident,generation):
        with history_lock(self.root/'.lock'):
            value=self._read(human);previews=copy.deepcopy(preview_state(value));row=self._preview_row(previews,ident,generation)
            if row['phase']=='retiring':return copy.deepcopy(row)
            for render in row['renders'].values():
                if render['state']=='prepared':
                    render.update(state='not_started',outcome={'state':'not_started','receipt':{'provider_attempted':False,'reason':'cancelled_before_generation'}})
                elif render['state']=='intent':render['state']='cancel_requested'
            value['voice_previews']=previews;self._write(human,value)
            return copy.deepcopy(row)

    def preview_observe(self,human,ident,generation,slot,render_id,outcome):
        if slot not in ('A','B') or not isinstance(outcome,dict) or set(outcome)!={'state','receipt'}:
            raise ValueError('Select one bounded preview outcome')
        if outcome['state'] not in TERMINAL|{'unconfirmed'} or len(json.dumps(outcome).encode())>32768:
            raise ValueError('Preview outcome exceeds its bound')
        with history_lock(self.root/'.lock'):
            value=self._read(human);previews=copy.deepcopy(preview_state(value));row=self._preview_row(previews,ident,generation)
            render=row['renders'][slot]
            if row['phase']=='retiring' or render['id']!=render_id or render['state']=='prepared':
                raise ValueError('Preview result does not match a retained attempt')
            if render['state'] in TERMINAL:
                if render.get('outcome')!=outcome:raise self.conflict_error('A terminal preview outcome is immutable')
                return copy.deepcopy(row)
            render.update(state=outcome['state'],outcome=copy.deepcopy(outcome));value['voice_previews']=previews
            self._write(human,value);return copy.deepcopy(row)

    def preview_retire(self,human,ident,batch_generation,generation,retirer):
        """Claim before disposable media cleanup; repeat only the same retirement.

        The retirer must verify the exact speech jobs/bytes, accept already
        removed bytes only under this owned claim and never invoke synthesis.
        """
        with history_lock(self.root/'.lock'):
            value=self._read(human);previews=copy.deepcopy(preview_state(value));self._expected(previews,generation)
            row=self._preview_row(previews,ident,batch_generation)
            if any(r['state'] not in TERMINAL|{'prepared'} for r in row['renders'].values()):
                raise ValueError('Uncertain or active preview outcomes are kept')
            if row['phase']!='retiring':
                row['phase']='retiring';value['voice_previews']=previews;self._write(human,value)
            retirer(copy.deepcopy(row))
            previews['batches'].remove(row);previews['generation']+=1;value['voice_previews']=previews
            self._write(human,value);return copy.deepcopy(previews)
