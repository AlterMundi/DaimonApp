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

BODY_BYTES = 2 * FILE_BYTES + 8192


def install(app, config, provider, authorize, origins):
    store = AtelierWorkshop(config['state_dir'])
    app.state.atelier_workshop = store

    async def owner(request, write=False):
        session = await authorize(request)
        if dict(session).get('scope', 'interaction_only') != 'interaction_only' or not provider.authorized(session['human']):
            raise HTTPException(403, 'Open your own conversation to use the 3D workshop')
        if write and (request.headers.get('origin') not in origins or not secrets.compare_digest(
                request.headers.get('x-dashboard-csrf', ''), session['csrf'])):
            raise HTTPException(403, 'Refresh your conversation before saving')
        return session['human']

    async def call(request, fn, *args, write=False):
        human = await owner(request, write)
        try:
            result = await asyncio.to_thread(fn, human, *args)
        except AtelierConflict as e:
            raise HTTPException(409, str(e)) from None
        except KeyError:
            raise HTTPException(404, 'Request unavailable in this account') from None
        except (ValueError, TypeError, UnicodeError) as e:
            raise HTTPException(400, str(e)) from None
        except (OSError, sqlite3.Error):
            raise HTTPException(503, 'Saved sculptures are temporarily unavailable') from None
        if await owner(request, write) != human:
            raise HTTPException(403, 'The account changed; reopen your workshop')
        return result

    @app.get('/api/interaction/atelier')
    async def snapshot(request: Request):
        return JSONResponse(await call(request, store.snapshot), headers={'Cache-Control':'private, no-store'})

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
