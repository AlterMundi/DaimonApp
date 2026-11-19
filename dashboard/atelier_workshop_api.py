"""Sculpture storage through existing shared Home/device auth, grants and CSRF."""
import asyncio
import hashlib
import base64
import re
import json
import secrets
import sqlite3
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from .atelier_workshop import AtelierWorkshop, AtelierConflict, FILE_BYTES
from .atelier_native import AtelierNative
from .companion import permitted
from .provider import ProviderUnavailable

BODY_BYTES = 2 * FILE_BYTES + 8192


def install(app, config, provider, authorize, origins, *, authorize_sync=None):
    store = AtelierWorkshop(config['state_dir'])
    app.state.atelier_workshop = store
    native = AtelierNative(store, provider)

    def granted(session, feature):
        selected = dict(session)
        if selected.get('scope') is None:
            return True
        path = '/api/interaction/sessions' if feature == 'workspace' else '/api/interaction/artifacts'
        return permitted('GET', path, selected['scope'],
                         artifact_access=selected.get('artifact_access', False),
                         workspace_access=selected.get('workspace_access', False))

    def check_owner(request, session, write=False, features=()):
        if dict(session).get('scope', 'interaction_only') != 'interaction_only' or not provider.authorized(session['human']):
            raise HTTPException(403, 'Open your own conversation to use the 3D workshop')
        if write and (request.headers.get('origin') not in origins or not secrets.compare_digest(
                request.headers.get('x-dashboard-csrf', ''), session['csrf'])):
            raise HTTPException(403, 'Refresh your conversation before saving')
        if any(not granted(session, feature) for feature in features):
            raise HTTPException(403, 'This access does not include the selected session or returned files')
        return session['human']

    async def owner(request, write=False, features=()):
        return check_owner(request, await authorize(request), write, features)

    def capabilities(session):
        send = authorize_sync is not None and granted(session, 'workspace') and all(callable(getattr(provider, name, None)) for name in ('session_workspace', 'conversation_inputs', 'conversation_file_upload', 'conversation_input_submit', 'conversation_input_status'))
        return {'native': send, 'nativeReturn': send and granted(session, 'artifacts') and callable(getattr(provider, 'artifact_open', None))}

    async def call(request, fn, *args, write=False, features=(), guard=False):
        human = await owner(request, write, features)
        try:
            if guard:
                if authorize_sync is None:
                    raise HTTPException(503, 'Native workshop composition is unavailable')
                def again():
                    if check_owner(request, authorize_sync(request), write, features) != human:
                        raise HTTPException(403, 'The account changed; the original request is preserved')
                from .speech import retain_io
                result = await retain_io(fn, human, *args, again)
            else:
                result = await asyncio.to_thread(fn, human, *args)
        except AtelierConflict as e:
            raise HTTPException(409, str(e)) from None
        except KeyError:
            raise HTTPException(404, 'Request unavailable in this account') from None
        except (ValueError, TypeError, UnicodeError) as e:
            raise HTTPException(400, str(e)) from None
        except (OSError, sqlite3.Error, ProviderUnavailable):
            raise HTTPException(503, 'Saved sculptures are temporarily unavailable') from None
        if await owner(request, write, features) != human:
            raise HTTPException(403, 'The account changed; reopen your workshop')
        return result

    @app.get('/api/interaction/atelier')
    async def snapshot(request: Request):
        value = await call(request, store.snapshot)
        value['capabilities'] = capabilities(await authorize(request))
        return JSONResponse(value, headers={'Cache-Control':'private, no-store'})

    @app.get('/api/interaction/atelier/destinations')
    async def destinations(request: Request):
        return JSONResponse(await call(request, lambda human: native.choices(), features=('workspace',)), headers={'Cache-Control':'private, no-store'})

    @app.get('/api/interaction/atelier/requests/{ident}/native')
    async def status(request: Request, ident: str):
        files = granted(await authorize(request), 'artifacts')
        return JSONResponse(await call(request, native.status, ident, files, features=('workspace',)), headers={'Cache-Control':'private, no-store'})

    @app.get('/api/interaction/atelier/requests/{ident}')
    async def record(request: Request, ident: str, format: str = 'record'):
        if format not in ('record', 'request', 'reply'):
            await owner(request)
            raise HTTPException(400, 'Choose a saved request or proposal')
        value = await call(request, store.get, ident)
        if format == 'record':
            return JSONResponse(value, headers={'Cache-Control':'private, no-store'})
        if format not in value:
            raise HTTPException(404, 'No proposal has been saved yet')
        raw = value[format].encode('utf-8')
        return Response(raw, media_type='application/json', headers={
            'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
            'ETag': '"sha256-' + hashlib.sha256(raw).hexdigest() + '"',
            'Content-Disposition': 'attachment; filename="' + ident + ('.clayrequest' if format == 'request' else '.clayreply') + '"'})

    @app.post('/api/interaction/atelier')
    async def save(request: Request):
        await owner(request, True)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > BODY_BYTES:
                raise HTTPException(413, 'The sculpture exchange is too large')
        try:
            value = json.loads(raw)
        except (ValueError, RecursionError):
            raise HTTPException(400, 'Choose one sculpture exchange') from None
        if isinstance(value, dict) and set(value) == {'action', 'request'} and value['action'] == 'save-request':
            return JSONResponse(await call(request, store.save_request, value['request'], write=True), headers={'Cache-Control':'private, no-store'})
        if isinstance(value, dict) and set(value) == {'action', 'requestId', 'reply'} and value['action'] == 'save-reply':
            return JSONResponse(await call(request, store.save_reply, value['requestId'], value['reply'], write=True), headers={'Cache-Control':'private, no-store'})
        if isinstance(value, dict) and set(value) == {'action', 'requestId', 'choice'} and value['action'] == 'dispatch':
            return JSONResponse(await call(request, native.send, value['requestId'], value['choice'], write=True, features=('workspace',), guard=True), headers={'Cache-Control':'private, no-store'})
        if isinstance(value, dict) and set(value) == {'action', 'requestId'} and value['action'] == 'retry-dispatch':
            return JSONResponse(await call(request, native.retry, value['requestId'], write=True, features=('workspace',), guard=True), headers={'Cache-Control':'private, no-store'})
        if isinstance(value, dict) and set(value) == {'action', 'requestId', 'artifactId', 'source', 'revision'} and value['action'] == 'collect':
            return JSONResponse(await call(request, native.collect, value['requestId'], value['artifactId'], value['source'], value['revision'], write=True, features=('workspace', 'artifacts'), guard=True), headers={'Cache-Control':'private, no-store'})
        raise HTTPException(400, 'Choose a request or its returned proposal')

    # Only generic MIT editor code is served. Source validators and private
    # per-account exchanges never become static assets.
    public = Path(__file__).parent / 'web/atelier-workshop'
    @app.get('/assets/atelier-workshop/{name}')
    async def asset(name: str):
        if name not in ('index.html', 'host.js'):
            raise HTTPException(404, 'Workshop unavailable')
        return FileResponse(public / name, headers={'Cache-Control': 'no-store', **({'Content-Security-Policy':editor_csp()} if name=='index.html' else {})})
    return store


def editor_csp():
    raw=(Path(__file__).parent/'web/atelier-workshop/index.html').read_text()
    script=re.search(r'<script type="module">(.*?)</script>',raw,re.S).group(1)
    sha=base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    return "default-src 'none'; script-src 'sha256-"+sha+"'; style-src 'unsafe-inline'; font-src data:; img-src 'self' data: blob:; connect-src 'self' blob:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
