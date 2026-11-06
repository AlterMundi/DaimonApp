"""Existing App authentication and CSRF for account-owned workshop revisions."""
import asyncio
import json
import secrets
from pathlib import Path

from fastapi import HTTPException,Request
from fastapi.responses import FileResponse

from .avatar_workshop import AvatarWorkshop,WorkshopConflict
from .provider import ProviderUnavailable
from scripts.speech_render import RenderError


def install(app,config,provider,authorize,origins):
    store=AvatarWorkshop(config['state_dir'])
    # Only the shipped MIT editor/modules are public. Account revisions never
    # enter this tree, and request paths cannot select arbitrary local files.
    public=Path(__file__).parent/'web/avatar-workshop'
    assets={p.relative_to(public).as_posix():p for p in public.rglob('*')
            if p.is_file() and not p.is_symlink() and p.suffix in ('.mjs','.css','.html','.json')
            and p.name!='PROVENANCE.json' and p.name!='validate-design.mjs'}

    @app.get('/assets/avatar-workshop/{name:path}')
    async def workshop_asset(name:str):
        if name not in assets:raise HTTPException(404,'Workshop asset unavailable')
        media='text/javascript' if name.endswith('.mjs') else None
        return FileResponse(assets[name],media_type=media,headers={'Cache-Control':'public, max-age=0, must-revalidate'})

    async def owner(request,write=False):
        session=await authorize(request)
        if dict(session).get('scope','interaction_only')!='interaction_only':
            raise HTTPException(403,'The avatar workshop requires your own interaction access')
        human=session['human']
        if not provider.authorized(human):raise HTTPException(403,'Avatar account access changed')
        if write and (request.headers.get('origin') not in origins or not secrets.compare_digest(
                request.headers.get('x-dashboard-csrf',''),session['csrf'])):
            raise HTTPException(403,'Fresh avatar action token required')
        return human

    async def call(request,function,*args,write=False):
        human=await owner(request,write)
        try:value=await asyncio.to_thread(function,human,*args)
        except WorkshopConflict as e:raise HTTPException(409,str(e)) from None
        except KeyError:raise HTTPException(404,'Avatar revision unavailable for this account') from None
        except (ValueError,TypeError) as e:raise HTTPException(400,str(e)) from None
        except (OSError,RenderError,ProviderUnavailable):
            raise HTTPException(503,'Avatar storage unavailable; previous selection is kept') from None
        # A committed write is retained even if access expires before its ACK.
        await owner(request,write)
        return value

    @app.get('/api/interaction/avatars')
    async def avatars(request:Request):
        return await call(request,store.snapshot)

    @app.get('/api/interaction/avatars/{ident}')
    async def avatar(request:Request,ident:str):
        return await call(request,store.get,ident)

    @app.post('/api/interaction/avatars')
    async def change_avatar(request:Request):
        await owner(request,True)
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>1024*1024:raise HTTPException(413,'Avatar import exceeds 1MiB')
        try:body=json.loads(raw)
        except ValueError:raise HTTPException(400,'Select one avatar action') from None
        if not isinstance(body,dict):raise HTTPException(400,'Select one avatar action')
        if body.get('action')=='save' and set(body)=={'action','id','design','parentId','generation'}:
            return await call(request,store.save,body['id'],body['design'],body['parentId'],body['generation'],write=True)
        if body.get('action') in ('edit','activate') and set(body)=={'action','id','generation'}:
            def select(human,ident,generation):
                return store.select(human,ident,generation,activate=body['action']=='activate')
            return await call(request,select,body['id'],body['generation'],write=True)
        raise HTTPException(400,'Select a bounded save, edit or use action')

    return store
