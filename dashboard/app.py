"""Private Telegram Mini App shell and explicit receiving-owner controls."""
import asyncio
from contextlib import aclosing, asynccontextmanager, contextmanager
from datetime import datetime, timezone
import hashlib
import html
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time
import tomllib
from urllib.parse import parse_qsl, urlparse, urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, Response, StreamingResponse, RedirectResponse
from init_data_py import errors, validate_by_signature

from .provider import Provider, ProviderUnavailable
from .computer_health import ComputerHealth, HealthUnavailable
from .coordination import Coordination, CoordinationUnavailable, ControlRejected
from .visual import VisualSelectionInvalid
from .alerts import Receiver as AlertsReceiver, AlertsUnavailable
from .traffic import Traffic
from .menu_attention import attention_projection
from .operator import sessions_selection
from .speech import Speech, SpeechUnavailable, speech_part
from .media_retention import MediaRetention, RetentionUnavailable
from .companion import Grants as CompanionGrants, permitted as companion_permitted, application_identity
from .home_auth import HomeAuth
from scripts.speech_render import RenderError


def validate_launch(raw, bot_id):
    # Reuse Nexus's inspected production Ed25519 pattern; a menu launch has no start_param.
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True,
                          encoding='utf-8', errors='strict', max_num_fields=40)
        if len({key for key, _ in pairs}) != len(pairs):
            raise ValueError('Duplicate field')
        data = validate_by_signature(raw, bot_id, environment='prod', expires_in=300)
        if data.issued_at.timestamp() > datetime.now(timezone.utc).timestamp() + 30:
            raise ValueError('Future launch')
        if not data.user or data.user.id <= 0:
            raise ValueError('No signed user')
        return data.user.id
    except (errors.InvalidInitDataError, ValueError, UnicodeError, TypeError) as exc:
        raise ValueError('Invalid or expired Telegram launch') from exc


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def create_app(config=None, provider=None, validator=validate_launch, alerts=None, traffic=None, coordination_control=None):
    if config is None:
        config = tomllib.loads(Path(os.environ['TELECODEX_DASHBOARD_CONFIG']).read_text())
    provider = provider or Provider(config)
    application = application_identity(config, provider)
    telegram_launch = 'application_id' not in config
    companions = CompanionGrants(config, provider)
    home_auth = HomeAuth(config, provider)
    speech = Speech(config['speech']) if config.get('speech') else None
    if speech:
        speech.media_retention = MediaRetention(config['media_retention']) if config.get('media_retention') else None
    openai_speech = Speech(config['speech_openai']) if config.get('speech_openai') else None
    if openai_speech:
        from scripts.speech_render import route
        if not speech or route(openai_speech.binding)['provider'] != 'openai-realtime' or openai_speech.streaming or openai_speech.word_timestamps:
            raise ValueError('Explicit OpenAI speech requires its own bounded Realtime route')
        openai_speech.capacity = speech.capacity
        openai_speech.media_retention = speech.media_retention
    services_default = config.get('voice_services_default','current')
    if services_default not in ('current','openai') or services_default=='openai' and openai_speech is None:
        raise ValueError('Configured default voice services unavailable; no fallback')
    default_speech = openai_speech if services_default=='openai' else speech
    origin = config['origin']
    prefix = config.get('prefix', '/sessions')
    additional_origins = config.get('additional_origins', [])
    if not isinstance(additional_origins, list) or len(additional_origins) > 8:
        raise ValueError('Bounded exact additional origins required')
    for candidate in additional_origins:
        if not isinstance(candidate, str) or any(c.isspace() or c in "\\\"'<>" for c in candidate):
            raise ValueError('Exact HTTPS additional origin required')
        parsed = urlparse(candidate)
        try:
            parsed.port
        except ValueError:
            raise ValueError('Exact HTTPS additional origin required') from None
        if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError('Exact HTTPS additional origin required')

    launcher_origins = config.get('alerts', {}).get('launcher_origins', [])
    if not isinstance(launcher_origins, list) or len(launcher_origins) > 8:
        raise ValueError('Bounded exact launcher origins required')
    for candidate in launcher_origins:
        parsed = urlparse(candidate)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError('Exact HTTPS launcher origin required')
    daimon_name = config.get('daimon_name', 'Daimon')
    if not isinstance(daimon_name, str) or not 1 <= len(daimon_name) <= 80 or any(ord(c) < 32 for c in daimon_name):
        raise ValueError('daimon_name must be a display name of 1 to 80 characters')
    conversation_appearance = config.get('conversation_appearance', 'inherit')
    if conversation_appearance not in ('inherit', 'authored'):
        raise ValueError('conversation_appearance must be inherit or authored')
    appearance = config.get('appearance_origin', '').rstrip('/')
    if appearance:
        u = urlparse(appearance)
        if (u.scheme != 'https' or not u.netloc or u.path or u.query or u.fragment or
                u.username or u.password or any(c.isspace() or c in "\\\"'<>" for c in appearance)):
            raise ValueError('Exact public Homemaker consumer origin required')
    if (urlparse(origin).scheme != 'https' or urlparse(origin).netloc == ''
            or urlparse(origin).path not in ('', '/') or not re.fullmatch(r'/[a-zA-Z0-9_-]+', prefix)):
        raise ValueError('Exact HTTPS origin and one-segment prefix required')
    state = Path(config['state_dir'])
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = state.lstat()
    if not state.is_dir() or state.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('Dashboard state must be owner-only')
    computer_health = ComputerHealth(config)
    coordination = Coordination(config, provider)
    db_path = state / 'dashboard.sqlite3'
    if db_path.exists() or db_path.is_symlink():
        info = db_path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Unsafe dashboard state file')
    if alerts is None and config.get('alerts', {}).get('enabled') is True:
        alerts = AlertsReceiver(config, provider)
    if traffic is None and config.get('traffic', {}).get('enabled') is True:
        traffic = Traffic(config, provider)
    if traffic is not None and alerts is not None:
        alerts.dispatch_ready = traffic.notification_ready
    scope_binding = [application,
        getattr(provider, 'binding_bytes', getattr(provider, 'receiver_bytes', b'')).hex()]
    if alerts is not None:
        scope_binding.append(alerts.binding)
    binding = digest(json.dumps(scope_binding))

    @contextmanager
    def database():
        conn = sqlite3.connect(db_path, timeout=3)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    with database() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,
            human INTEGER NOT NULL,expires INTEGER NOT NULL,csrf TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS actions(human INTEGER,nonce TEXT,state TEXT,result TEXT,
            PRIMARY KEY(human,nonce));''')
    db_path.chmod(0o600)

    @asynccontextmanager
    async def lifespan(app):
        if traffic is not None:
            traffic.start()
        if alerts is not None:
            alerts.start()
        yield
        if alerts is not None:
            alerts.close()
        if traffic is not None:
            traffic.close()
        computer_health.close()
        provider.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def boundaries(request, call_next):
        # A device credential never acquires the ambient Telegram session or
        # administrative routes, even when a browser also carries a valid cookie.
        if any(value.lower().startswith('companion') for value in request.headers.getlist('authorization')):
            try:
                await authorize_async(request)
            except HTTPException as exc:
                return JSONResponse({'detail':exc.detail}, status_code=exc.status_code)
        if request.method == 'POST':
            allowed = launcher_origins if request.url.path == '/api/alerts/attention' else [origin, *additional_origins]
            if request.headers.get('origin') not in allowed:
                return JSONResponse({'detail': 'Wrong request origin'}, status_code=403)
            # Bound chunked bodies as well as Content-Length before parsing them.
            if request.url.path in ('/api/interaction/voice','/api/interaction/voice/limited','/api/interaction/voice/openai','/api/interaction/voice/openai/limited','/api/interaction/voice/previous','/api/interaction/voice/previous/limited','/api/interaction/voice/openai-live','/api/interaction/voice/openai-live/limited','/api/interaction/voice/previous-live','/api/interaction/voice/previous-live/limited','/api/interaction/voice/recover','/api/interaction/visual','/api/interaction/files'):
                try:
                    selected = await authorize_async(request)
                    if not secrets.compare_digest(request.headers.get('x-dashboard-csrf', ''), selected['csrf']):
                        raise HTTPException(403, 'Action token missing')
                except HTTPException as exc:
                    return JSONResponse({'detail':exc.detail}, status_code=exc.status_code)
                bound = 2*1024*1024 if request.url.path.endswith('/visual') else 20*1024*1024
            else:
                bound = (1048576 if request.url.path=='/api/interaction/avatars' else
                    262144 if (request.url.path == '/api/interaction/inputs' or re.fullmatch(r'/api/interaction/(?:internal/)?requests/[a-f0-9]{32}',request.url.path)) else 16384)
            # Native capture-only uploads own their fresh-auth/CSRF checks,
            # two upload slots and bounded streaming body. Do not
            # buffer them before that admission in the general JSON middleware.
            if not re.fullmatch(r'/api/interaction/voice/(?:codex|gpt-live)/visits/[a-f0-9-]{36}/recordings/(?:[0-9]|[12][0-9]|3[01])',request.url.path):
                data = bytearray()
                async for chunk in request.stream():
                    data.extend(chunk)
                    if len(data) > bound:
                        return JSONResponse({'detail': 'Request too large'}, status_code=413)
                request._body = bytes(data)
        response = await call_next(request)
        response.headers.setdefault('Cache-Control', 'no-store')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self' https://telegram.org" +
            (' '+appearance+'/home-style.js' if appearance else '') +
            "; style-src 'self'" + (' '+appearance if appearance else '') +
            "; font-src 'self'" + (' '+appearance if appearance else '') +
            "; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'self' https://web.telegram.org")
        return response

    def authorize(request):
        check_binding()
        token = request.cookies.get('telecodex_dashboard', '')
        headers = request.headers.getlist('authorization')
        if headers:
            if len(headers) == 1 and (device := re.fullmatch(r'Companion ([A-Za-z0-9_-]{43})', headers[0], re.IGNORECASE)):
                grant = companions.authenticate(device.group(1))
                if grant is None:
                    raise HTTPException(401, 'Companion access is unavailable; operator enrollment required')
                if not companion_permitted(request.method, request.url.path, grant['scope'], grant.get('artifact_access', False), coordination_access=grant.get('coordination_access', False), coordination_control_access=grant.get('coordination_control_access', False), workspace_access=grant.get('workspace_access', False)):
                    raise HTTPException(403, 'Companion access is limited to the integrating conversation')
                return {**grant, 'native_decision_access': False}
            # A restricted WebView may omit cookies. Never downgrade an invalid
            # explicit credential to a different ambient cookie session.
            if len(headers) != 1 or not (match := re.fullmatch(
                    r'Bearer ([A-Za-z0-9_-]{43})', headers[0], re.IGNORECASE)):
                raise HTTPException(401, 'Invalid dashboard session credential')
            token = match.group(1)
        if not headers and not token and home_auth.enabled:
            try:
                shared = home_auth.authenticate(request)
            except PermissionError as exc:
                raise HTTPException(403, str(exc)) from None
            except (ValueError, KeyError, TypeError):
                raise HTTPException(401, 'Sign in to your conversation') from None
            except (OSError, http.client.HTTPException):
                raise HTTPException(503, 'Shared authentication unavailable; retry shortly') from None
            if shared is not None:
                return shared
        with database() as db:
            session = db.execute('SELECT * FROM sessions WHERE token_hash=? AND expires>?',
                                 (digest(token + binding), time.time())).fetchone()
        if not session or not provider.authorized(session['human']):
            raise HTTPException(401, 'Open the dashboard from this bot in Telegram')
        return session

    def check_binding():
        if hasattr(provider, 'assert_binding'):
            try:
                provider.assert_binding()
            except (ProviderUnavailable, OSError):
                raise HTTPException(503, 'Receiving control binding changed; operator must requalify Sessions') from None
        if alerts is not None:
            try:
                alerts.assert_binding()
            except (AlertsUnavailable, ProviderUnavailable, OSError):
                raise HTTPException(503, 'Alerts receiving binding changed; operator must requalify Sessions') from None

    async def authorize_async(request):
        if (home_auth.enabled and not request.headers.getlist('authorization')
                and not request.cookies.get('telecodex_dashboard')
                and request.headers.get('host') == home_auth.host
                and request.cookies.get('__Host-home')):
            from starlette.concurrency import run_in_threadpool
            return await run_in_threadpool(authorize, request)
        return authorize(request)

    from .voice_admission import VoiceAdmission, VoiceAdmissionMiddleware
    app.state.voice_admission=VoiceAdmission(config['state_dir'])
    app.add_middleware(VoiceAdmissionMiddleware,admission=app.state.voice_admission)
    app.state.voice_active=set()
    from .native_history import NativeHistory
    app.state.native_history=NativeHistory(database,binding)
    from .live_transcription import install as install_live_transcription
    can_stream_transcribe = install_live_transcription(app,config,provider,authorize_async,[origin,*additional_origins])
    can_openai_stream_transcribe = install_live_transcription(app,config,provider,authorize_async,[origin,*additional_origins],configuration='streaming_transcription_openai')
    from .codex_voice_api import install as install_codex_voice
    can_codex_voice=install_codex_voice(app,config,provider,authorize_async,[origin,*additional_origins])
    from .openai_live_api import install as install_openai_live
    can_public_live=install_openai_live(app,config,provider,authorize_async,[origin,*additional_origins])
    app.state.voice_preview_capacity=openai_speech.capacity if openai_speech else None
    from .avatar_workshop_api import install as install_avatar_workshop
    install_avatar_workshop(app,config,provider,authorize_async,[origin,*additional_origins])

    public = Path(__file__).parent / 'web'

    @app.get('/')
    def shell(request: Request):
        if computer_health.enabled and (request.query_params.get('view') == 'health'
                or computer_health.default_view and not request.query_params.get('view')):
            computer_health.assert_binding()
            return HTMLResponse(computer_health.shell)
        body = (public / 'index.html').read_text()
        body = body.replace('id="conversation-daimon">Daimon</span>', 'id="conversation-daimon">' + html.escape(daimon_name) + '</span>')
        shared_entry = home_auth.enabled and (request.query_params.get('view') == 'conversation'
            or request.headers.get('x-forwarded-prefix') == home_auth.entry.rstrip('/'))
        if shared_entry and (request.headers.get('host') != home_auth.host
                or request.query_params.get('view') != 'conversation'
                or request.query_params.get('client') != 'standalone'):
            query = {**dict(request.query_params), 'view': 'conversation', 'client': 'standalone'}
            return RedirectResponse(home_auth.origin + home_auth.entry + '?' + urlencode(query), status_code=307)
        if request.query_params.get('view') == 'conversation' and request.query_params.get('client') == 'standalone':
            if home_auth.enabled:
                if request.headers.get('host') != home_auth.host:
                    return RedirectResponse(home_auth.origin + home_auth.entry + '?view=conversation&client=standalone', status_code=307)
                body = body.replace('<html lang="en">', '<html lang="en" data-shared-auth="true">')
                body = body.replace('    <script src="assets/app.js" defer></script>',
                    '    <script src="/access-client.js" defer></script>\n    <script src="assets/app.js" defer></script>')
            body = body.replace('    <script src="https://telegram.org/js/telegram-web-app.js" defer></script>\n', '')
        client_build = hashlib.sha256((public / 'index.html').read_bytes())
        for name in ('app.js', 'live.js', 'requests.js', 'interface-appearance.js', 'voice-stream.js', 'voice-session.js', 'native-conversation.js', 'codex-conversation.js', 'openai-live.js', 'live-usage.js', 'webrtc-native-audio.js', 'voice-output-pcm.js', 'microphone.js', 'visual.js', 'files.js', 'routing_graph.js', 'companion.js', 'avatar-workshop.js', 'voice-studio.js', 'sonic.js', 'speech-stream.js', 'live-speech.js', 'markdown-it.min.js', 'markdown.js', 'conversation.js', 'conversation-header.js', 'session-workspace.js', 'heartbeat.js', 'timing.js', 'attention.js', 'voice-mode.js', 'style.css'):
            asset = (public / name).read_bytes()
            client_build.update(name.encode() + b'\0' + asset)
            version = hashlib.sha256(asset).hexdigest()[:16]
            body = body.replace('assets/'+name+'"', 'assets/'+name+'?v='+version+'"')
        for path in sorted((public / 'avatar-workshop').rglob('*')):
            if path.is_file():
                client_build.update(path.relative_to(public).as_posix().encode()+b'\0'+path.read_bytes())
        build_id = client_build.hexdigest()
        build_label = ''.join('<span>'+digit+'</span>' for digit in build_id[:12])
        body = body.replace('<div id="client-build" hidden></div>',
            '<div id="client-build" title="Client bundle '+build_id+'" aria-label="Client version '+build_id[:12]+'">ui <code>'+build_label+'</code></div>')
        standalone_entry = (request.query_params.get('view') == 'conversation'
                            and request.query_params.get('client') == 'standalone')
        if standalone_entry:
            body = body.replace('<title>Sessions · Telecodex</title>', '<title>Daimon Interaction</title>')
            # Select the initial visible shell before scripts or account reads.
            # This is presentation only: controls retain their existing grants.
            body = body.replace('<body>', '<body class="conversation-mode standalone-conversation">', 1)
            body = body.replace('<h1>Sessions</h1>', '<h1>Daimon</h1>', 1)
            body = body.replace('Connecting to Telegram…', 'Opening your conversation…', 1)
            body = body.replace('<section id="conversation" hidden', '<section id="conversation"', 1)
            body = body.replace('</head>', '<link rel="manifest" href="manifest.webmanifest">'
                '<meta name="theme-color" content="#0b1018">'
                '<link rel="apple-touch-icon" href="assets/interaction-192.png"></head>')
        if standalone_entry and conversation_appearance == 'authored':
            body = body.replace('<html lang="en"', '<html lang="en" data-style-policy="authored"', 1)
        if appearance and not (standalone_entry and conversation_appearance == 'authored'):
            base = html.escape(appearance, quote=True)
            body = body.replace('<html lang="en"', '<html lang="en" data-style-policy="inherit"', 1)
            body = body.replace('</head>', '<link rel="stylesheet" data-home-style href="'+base+
                '/style.css?surface=sessions"><script src="'+base+'/home-style.js" defer></script></head>')
        return HTMLResponse(body)

    @app.get('/manifest.webmanifest')
    def interaction_manifest():
        entry = home_auth.entry if home_auth.enabled else prefix + '/'
        return JSONResponse({'id': entry, 'name': 'Daimon Interaction', 'short_name': 'Daimon',
            'start_url': entry + '?view=conversation&client=standalone', 'scope': entry,
            'display': 'standalone', 'background_color': '#0b1018', 'theme_color': '#0b1018',
            'icons': [{'src':entry + 'assets/interaction-' + str(size) + '.png',
                       'sizes':str(size)+'x'+str(size), 'type':'image/png', 'purpose':'any'}
                      for size in (192,512)]}, media_type='application/manifest+json')

    @app.get('/api/interaction/foreground')
    async def foreground_history(request:Request,before:int=0):
        session=await authorize_async(request)
        if not 0<=before<=2**63-1:raise HTTPException(400,'Invalid foreground history cursor')
        value=await asyncio.to_thread(app.state.native_history.page,session['human'],before)
        await authorize_async(request)
        return value

    @app.get('/api/interaction/events')
    async def interaction_events(request: Request):
        session = await authorize_async(request)
        from .live import changes
        paths = [Path(provider.receiver['db_path'])]
        if config.get('activity_state_dir'):
            paths.append(Path(config['activity_state_dir']) / 'topics.json')
        alert_reads = dict(session).get('scope') is None or dict(session).get('alerts_access') is True
        alert_subscribe=getattr(alerts,'subscribe',None) if alert_reads else None
        def subscribe(notify):
            closers=[app.state.native_history.subscribe(notify)]
            try:
                if alert_subscribe:closers.append(alert_subscribe(notify))
            except BaseException:
                for close in closers:close()
                raise
            def close():
                for closer in closers:closer()
            return close
        async def stream():
            checked = time.monotonic()
            async for changed in changes(paths, subscribe=subscribe):
                if await request.is_disconnected():
                    break
                try:
                    if time.monotonic() - checked >= 15 or time.time() >= session['expires']:
                        current = await authorize_async(request)
                        checked = time.monotonic()
                        if current['human'] != session['human']:
                            break
                except HTTPException:
                    yield 'event: expired\ndata: {}\n\n'
                    break
                yield 'data: {}\n\n' if changed else ': keepalive\n\n'
        return StreamingResponse(stream(), media_type='text/event-stream',
            headers={'Cache-Control':'no-store', 'X-Accel-Buffering':'no'})

    @app.get('/api/interaction/access')
    def shared_access(request: Request):
        if not home_auth.enabled or request.headers.getlist('authorization'):
            raise HTTPException(401, 'Shared browser sign-in required')
        session = authorize(request)
        if dict(session).get('scope') != 'interaction_only':
            raise HTTPException(403, 'Shared conversation grant required')
        return {'csrf': session['csrf'], 'label': session.get('label', 'Your conversation')}

    @app.get('/assets/{name}')
    def asset(name: str, request: Request):
        if name in ('health.css', 'health-ui.js') and computer_health.enabled:
            computer_health.assert_binding()
            data, media = computer_health.assets[name]
            return Response(data, media_type=media)
        if name not in ('health-live.js', 'live.js', 'interaction-192.png', 'interaction-512.png', 'app.js', 'requests.js', 'interface-appearance.js', 'microphone.js', 'voice-stream.js', 'voice-session.js', 'native-conversation.js', 'codex-conversation.js', 'openai-live.js', 'live-usage.js', 'webrtc-native-audio.js', 'voice-output-pcm.js', 'voice-pcm.js', 'visual.js', 'files.js', 'routing_graph.js', 'companion.js', 'avatar-workshop.js', 'voice-studio.js', 'sonic.js', 'speech-stream.js', 'live-speech.js', 'markdown-it.min.js', 'markdown.js', 'conversation.js', 'conversation-header.js', 'session-workspace.js', 'heartbeat.js', 'timing.js', 'attention.js', 'voice-mode.js', 'style.css', 'markdown-it.LICENSE', 'markdown-it.SOURCE', 'space-grotesk-latin.woff2', 'OFL.txt'):
            raise HTTPException(404)
        version = hashlib.sha256((public / name).read_bytes()).hexdigest()[:16]
        immutable = list(request.query_params.multi_items()) == [('v',version)]
        headers = {'Cache-Control':'public, max-age=31536000, immutable' if immutable else 'public, max-age=0, must-revalidate',
                   'ETag':'"'+version+'"'}
        if request.headers.get('if-none-match') == headers['ETag']:
            return Response(status_code=304,headers=headers)
        return FileResponse(public / name, headers=headers)

    @app.get('/health')
    def health():
        from .voice_admission import HEADER
        return JSONResponse({'ok': True},headers={HEADER:app.state.voice_admission.header})

    @app.post('/api/session')
    async def exchange(request: Request):
        if not telegram_launch:
            raise HTTPException(403, 'Use this conversation’s shared sign-in')
        try:
            body = await request.json()
            raw = body['init_data']
            if not isinstance(raw, str):
                raise ValueError()
            human = validator(raw, config['bot_id'])
        except (ValueError, KeyError, TypeError):
            raise HTTPException(401, 'Invalid or expired Telegram launch') from None
        check_binding()
        if not provider.authorized(human):
            raise HTTPException(403, 'This account has no receiving session control grant')
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with database() as db:
            db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (digest(token + binding), human, time.time() + 3600, csrf))
        # Same short-lived, bot/config-bound session, carried explicitly by the
        # authenticated WebView in memory; never persisted in browser storage.
        response = JSONResponse({'ok': True, 'session_token': token})
        response.set_cookie('telecodex_dashboard', token, httponly=True, secure=True,
                            samesite='strict', path=prefix, max_age=3600)
        return response

    @app.get('/api/computer-health')
    def health_snapshot(request: Request):
        authorize(request)
        try:
            result = computer_health.snapshot()
        except HealthUnavailable:
            raise HTTPException(503, 'Computer health binding changed; operator must requalify') from None
        authorize(request)
        return result

    @app.get('/api/interaction/coordination')
    async def coordination_snapshot(request: Request):
        session = await authorize_async(request)
        if dict(session).get('scope') is not None and dict(session).get('coordination_access') is not True:
            raise HTTPException(403, 'This conversation has no budget read grant')
        try:
            result = await coordination.snapshot()
        except (CoordinationUnavailable, OSError, ValueError, KeyError, TypeError, asyncio.TimeoutError):
            raise HTTPException(503, 'Coordination budgets unavailable; no work was started') from None
        session = await authorize_async(request)
        if dict(session).get('scope') is not None and dict(session).get('coordination_access') is not True:
            raise HTTPException(403, 'Budget read grant changed')
        result['can_control'] = budget_control_permission(session)
        return result

    def budget_control_permission(session):
        value = dict(session)
        if (value.get('scope') is not None and
                (value.get('scope') != 'interaction_only' or value.get('coordination_control_access') is not True)):
            return False
        return (coordination_control is not None and coordination_control.permits(session['human'], coordination))

    @app.post('/api/interaction/coordination/control')
    async def coordination_action(request: Request):
        session = await authorize_async(request)
        if not budget_control_permission(session):
            raise HTTPException(403, 'No human funding-control authority is selected')
        if not secrets.compare_digest(request.headers.get('x-dashboard-csrf', ''), session['csrf']):
            raise HTTPException(403, 'Action token missing')
        try:
            body = await request.json()
            if (set(body) != {'nonce', 'account_id', 'expected_revision', 'paused'}
                    or not isinstance(body['nonce'], str) or not re.fullmatch('[A-Za-z0-9_-]{16,64}', body['nonce'])
                    or body['account_id'] not in {e['account_id'] for e in coordination.episodes}
                    or not isinstance(body['account_id'], str)
                    or type(body['expected_revision']) is not int or not 0 <= body['expected_revision'] < 2**53-1
                    or type(body['paused']) is not bool):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise HTTPException(400, 'Select an exact current episode control') from None
        # One retained slot per configured root/person (at most8), reusing actions.
        # The signed Matrix journal retains control history; UI receipts do not grow
        # once per click. An unknown slot is never replaced by another action.
        slot = 'coordination:' + digest(body['account_id'])
        def perform():
            current = authorize(request)
            if not budget_control_permission(current):
                raise HTTPException(403, 'Funding control grant changed')
            try:
                coordination.assert_binding()
            except (CoordinationUnavailable, OSError, ValueError):
                raise HTTPException(503, 'Budget binding changed; no control was submitted') from None
            with database() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT state,result FROM actions WHERE human=? AND nonce=?', (session['human'], slot)).fetchone()
                if row:
                    retained = json.loads(row['result'])
                    prior = retained['request']
                    if prior['nonce'] == body['nonce']:
                        if prior != body:
                            raise HTTPException(409, 'This action identity already binds another selection')
                        return retained['outcome']
                    if row['state'] in ('requested', 'unconfirmed'):
                        return {'state': 'unconfirmed', 'detail': 'Inspect the retained operator outcome before another control'}
                    if body['expected_revision'] < prior['expected_revision']:
                        raise HTTPException(409, 'Refresh the current control revision')
                # Retire only this adapter's terminal UI slots for roots no longer
                # configured. Signed history remains in the owning Matrix journal.
                active_slots = {'coordination:' + digest(e['account_id']) for e in coordination.episodes}
                for prior_slot in db.execute("SELECT nonce FROM actions WHERE human=? AND nonce LIKE 'coordination:%' AND state IN ('confirmed','rejected')", (session['human'],)):
                    if prior_slot['nonce'] not in active_slots:
                        db.execute('DELETE FROM actions WHERE human=? AND nonce=?', (session['human'], prior_slot['nonce']))
                if row is None and db.execute("SELECT count(*) FROM actions WHERE human=? AND nonce LIKE 'coordination:%'", (session['human'],)).fetchone()[0] >= 8:
                    raise HTTPException(409, 'Inspect retained controls before selecting another episode')
                envelope = {'request': body, 'outcome': {'state': 'unconfirmed'}}
                db.execute('INSERT OR REPLACE INTO actions VALUES(?,?,?,?)',
                           (session['human'], slot, 'requested', json.dumps(envelope)))
            try:
                # Authenticated single request, no provider/native/model operation.
                def reauthorize():
                    try:
                        return budget_control_permission(authorize(request))
                    except HTTPException:
                        return False
                outcome = coordination_control.apply(session['human'], coordination, body, reauthorize=reauthorize)
            except ControlRejected:
                outcome = {'state': 'rejected', 'detail': 'Refresh the selected budget and its authority'}
            except Exception:
                outcome = {'state': 'unconfirmed', 'detail': 'Inspect the retained operator outcome; do not replay'}
            with database() as db:
                db.execute('UPDATE actions SET state=?,result=? WHERE human=? AND nonce=?',
                           (outcome['state'], json.dumps({'request': body, 'outcome': outcome}), session['human'], slot))
            return outcome
        from .speech import retain_io
        result = await retain_io(perform)
        # An owned write finishes and is retained even when the HTTP caller leaves.
        session = await authorize_async(request)
        if not budget_control_permission(session):
            raise HTTPException(403, 'Funding control grant changed; inspect its retained outcome')
        return JSONResponse(result, status_code=202 if result['state'] == 'unconfirmed' else 200)

    @app.get('/api/state')
    def snapshot(request: Request):
        session = authorize(request)
        try:
            result = provider.snapshot()
        except (ProviderUnavailable, OSError, sqlite3.Error):
            raise HTTPException(503, 'Receiving metadata unavailable; retry shortly') from None
        # Recheck grants after native I/O, before any private response.
        authorize(request)
        return {**result, 'csrf': session['csrf']}

    @app.get('/api/traffic')
    def bot_traffic(request: Request):
        authorize(request)
        result = traffic.snapshot() if traffic is not None else {'state': 'not_configured'}
        authorize(request)
        return result

    @app.get('/api/interaction/heartbeat')
    async def heartbeat_status(request:Request):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            value=await run_in_threadpool(provider.heartbeat_status)
        except (ProviderUnavailable,OSError,ValueError):
            raise HTTPException(503,'Heartbeat status unavailable') from None
        await authorize_async(request)
        return value

    @app.post('/api/interaction/heartbeat')
    async def heartbeat_control(request:Request):
        session=await authorize_async(request)
        if not secrets.compare_digest(request.headers.get('x-dashboard-csrf',''),session['csrf']):
            raise HTTPException(403,'Action token missing')
        try:
            if len(raw:=await request.body())>1024:raise ValueError('Action too large')
            body=json.loads(raw)
            from starlette.concurrency import run_in_threadpool
            value=await run_in_threadpool(provider.heartbeat_control,body)
        except (ValueError,UnicodeError):
            raise HTTPException(409,'Heartbeat action refused. Refresh status before choosing another action') from None
        except (ProviderUnavailable,OSError):
            raise HTTPException(503,'Heartbeat action unconfirmed. Read current status; do not resend automatically') from None
        await authorize_async(request)
        return value

    @app.get('/api/interaction')
    async def interaction_sources(request: Request, delivery: int = 0, native: int = 0, direction: str = 'after', matrix: int | None = None, inbox: int | None = None, responses: int | None = None):
        session = await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            if inbox is not None or responses is not None:
                result=await run_in_threadpool(provider.presentation_list,delivery,native,direction,matrix,inbox,responses)
            else:
                result = await run_in_threadpool(provider.presentation_list, delivery, native, direction) if matrix is None else await run_in_threadpool(provider.presentation_list, delivery, native, direction, matrix)
        except (ProviderUnavailable, OSError, ValueError):
            raise HTTPException(503, 'Integrating conversation unavailable; refresh before continuing') from None
        can_files=bool(getattr(provider,'receiver',{}).get('interaction',{}).get('artifact_store')) and (dict(session).get('scope') is None or dict(session).get('scope')=='interaction_only' and dict(session).get('artifact_access') is True)
        files={}
        if can_files:
            try:
                files=await run_in_threadpool(provider.artifacts)
            except (ProviderUnavailable,OSError,ValueError):
                files={'state':'unavailable'}
        await authorize_async(request)
        return {**result, 'csrf':session['csrf'],
                'can_decide_requests':dict(session).get('scope') is None or dict(session).get('native_decision_access') is True,
                'presentation_profile':dict(session).get('presentation_profile', companions.default_profile),
                'can_view_coordination':coordination.enabled and (dict(session).get('scope') is None or dict(session).get('coordination_access') is True),
                'can_listen':default_speech is not None,
                'voice_services_default':services_default,
                'can_openai_conversation':bool(openai_speech and 'openai' in getattr(provider,'receiver',{}).get('voice',{}).get('transcription_profiles',{}) and dict(session).get('scope')!='monitor_readonly'),
                'openai_speech_live_response':bool(openai_speech and openai_speech.live_response),
                'can_openai_live_result':bool(can_openai_stream_transcribe and config.get('streaming_transcription_openai',{}).get('mode')=='prepared' and 'openai-live' in getattr(provider,'receiver',{}).get('voice',{}).get('transcription_profiles',{}) and dict(session).get('scope')!='monitor_readonly'),
                'can_previous_live_result':bool(can_stream_transcribe and config.get('streaming_transcription',{}).get('mode','prepared')=='prepared' and 'previous-live' in getattr(provider,'receiver',{}).get('voice',{}).get('transcription_profiles',{}) and dict(session).get('scope')!='monitor_readonly'),
                'can_stream_speech':bool(default_speech and default_speech.streaming),
                'can_speak_live_response':bool(default_speech and default_speech.live_response),
                'previous_can_stream_speech':bool(speech and speech.streaming),
                'previous_can_speak_live_response':bool(speech and speech.live_response),
                'can_download_files':can_files,'artifacts':files,
                'can_speak':bool(getattr(provider, 'receiver', {}).get('voice')),
                'can_converse_native':bool(getattr(app.state,'native_voice_enabled',False) and dict(session).get('scope')!='monitor_readonly'),
                'can_converse_codex':bool(can_codex_voice and dict(session).get('scope')!='monitor_readonly'),
                'can_converse_public_live':bool(can_public_live and dict(session).get('scope')!='monitor_readonly'),
                'can_converse_public_live_native':bool(can_public_live and config.get('openai_live',{}).get('native_backend_enabled') is True
                    and dict(session).get('scope')!='monitor_readonly'),
                'can_session_workspace':workspace_granted(session),
                'can_converse_continuous':bool(can_stream_transcribe and speech and getattr(provider,'receiver',{}).get('voice')
                    and config.get('streaming_transcription',{}).get('turn_detection',{}).get('enabled') is True
                    and config.get('streaming_transcription',{}).get('turn_detection',{}).get('continuous') is True
                    and dict(session).get('scope') != 'monitor_readonly'),
                'can_converse':bool(can_stream_transcribe and speech and getattr(provider,'receiver',{}).get('voice')
                    and config.get('streaming_transcription',{}).get('turn_detection',{}).get('enabled') is True
                    and dict(session).get('scope') != 'monitor_readonly'),
                'streaming_transcription_mode':config.get('streaming_transcription',{}).get('mode','prepared'),
                'previous_can_stream_transcribe':can_stream_transcribe and bool(getattr(provider,'receiver',{}).get('voice')) and dict(session).get('scope') != 'monitor_readonly',
                'openai_can_stream_transcribe':can_openai_stream_transcribe and bool(getattr(provider,'receiver',{}).get('voice')) and dict(session).get('scope') != 'monitor_readonly',
                'can_stream_transcribe':(can_openai_stream_transcribe if services_default=='openai' else can_stream_transcribe) and bool(getattr(provider,'receiver',{}).get('voice')) and dict(session).get('scope') != 'monitor_readonly'}

    @app.get('/api/interaction/inputs')
    async def conversation_inputs(request: Request, before: int = 0, direction: str = 'before'):
        session = await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(provider.conversation_inputs, before, direction)
        except ValueError:
            raise HTTPException(400, 'Invalid input history cursor') from None
        except (ProviderUnavailable, OSError):
            raise HTTPException(503, 'Message history unavailable; refresh to reconnect') from None
        await authorize_async(request)
        viewer = {}
        if isinstance(session, dict) and session.get('scope') in ('monitor_readonly','interaction_only'):
            label = session.get('label')
            if not isinstance(label, str) or not 1 <= len(label) <= 64 or any(ord(c) < 32 for c in label):
                label = 'Selected receiver'
            viewer = {'viewer': {'label': label, 'expires': session['expires']}}
        return {**result, 'csrf':session['csrf'], **viewer}

    @app.get('/api/interaction/telegram-inputs')
    async def conversation_telegram_inputs(request: Request, before: int = 0, direction: str = 'before'):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result=await run_in_threadpool(provider.conversation_telegram_inputs,before,direction)
        except ValueError:
            raise HTTPException(400,'Invalid Telegram observation cursor') from None
        except (ProviderUnavailable,OSError):
            raise HTTPException(503,'Telegram observation unavailable; no input was resent') from None
        await authorize_async(request)
        return result

    @app.get('/api/interaction/inputs/{ident}')
    async def conversation_input_status(request: Request, ident: str):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(provider.conversation_input_status, ident)
        except ValueError:
            raise HTTPException(400, 'Invalid message identity') from None
        except (ProviderUnavailable, OSError):
            raise HTTPException(503, 'Message status unconfirmed; check again without resending') from None
        await authorize_async(request)
        return result

    @app.get('/api/interaction/inputs/{ident}/trace')
    async def conversation_input_trace(request: Request, ident: str):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(provider.conversation_input_trace, ident)
        except ValueError:
            raise HTTPException(400, 'Invalid message identity') from None
        except (ProviderUnavailable, OSError):
            raise HTTPException(503, 'Routing observation unavailable; the input was not resent') from None
        await authorize_async(request)
        return result

    @app.get('/api/interaction/inputs/{ident}/trace/{source}')
    async def conversation_trace_text(request: Request, ident: str, source: str, offset: int = 0):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(provider.conversation_trace_text, ident, source, offset)
        except ValueError:
            raise HTTPException(400, 'Invalid trace text selection') from None
        except (ProviderUnavailable, OSError):
            raise HTTPException(503, 'Saved text unavailable; the input was not resent') from None
        await authorize_async(request)
        return result

    @app.post('/api/interaction/inputs')
    async def conversation_input_submit(request: Request):
        session = await authorize_async(request)
        if not secrets.compare_digest(request.headers.get('x-dashboard-csrf', ''), session['csrf']):
            raise HTTPException(403, 'Action token missing')
        try:
            body = await request.json()
            from starlette.concurrency import run_in_threadpool
            require_pin_grant(session,body.get('reply') if isinstance(body,dict) else None)
            result = await run_in_threadpool(provider.conversation_input_submit, body)
        except VisualSelectionInvalid:
            return JSONResponse({'detail':'Select the captured image again. This attempt did not submit a message.','code':'visual_reselection','submission_attempted':False},status_code=400)
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Provide one original message of at most 32 KiB') from None
        except (ProviderUnavailable, OSError):
            raise HTTPException(503, 'Submission unconfirmed. Check this message status before sending it again') from None
        await authorize_async(request)
        return result

    @app.post('/api/interaction/inputs/{ident}/route')
    async def conversation_input_route(request: Request, ident: str):
        session = await authorize_async(request)
        if not secrets.compare_digest(request.headers.get('x-dashboard-csrf', ''), session['csrf']):
            raise HTTPException(403, 'Action token missing')
        try:
            body = await request.json()
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(provider.conversation_input_route, ident, body)
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Select one destination for this retained message') from None
        except (ProviderUnavailable, OSError):
            raise HTTPException(409, 'Selection unconfirmed or no longer current. Inspect the retained message; nothing was replayed') from None
        await authorize_async(request)
        return result

    @app.post('/api/interaction/inputs/{ident}/retry')
    async def conversation_input_retry(request: Request, ident: str):
        session = await authorize_async(request)
        if not secrets.compare_digest(request.headers.get('x-dashboard-csrf', ''), session['csrf']):
            raise HTTPException(403, 'Action token missing')
        try:
            body = await request.json()
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(provider.conversation_input_retry, ident, body)
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Select one saved route that was not sent') from None
        except (ProviderUnavailable, OSError):
            raise HTTPException(409, 'Recovery unconfirmed or no longer current. Check saved status without creating another message') from None
        await authorize_async(request)
        return result

    @app.post('/api/interaction/files')
    async def conversation_file_upload(request: Request):
        session=await authorize_async(request)
        if not secrets.compare_digest(request.headers.get('x-dashboard-csrf',''),session['csrf']):raise HTTPException(403,'Action token missing')
        from .files import MAX_BYTES,FileCapacityError
        from urllib.parse import unquote
        try:
            ref=json.loads(unquote(request.headers.get('x-file-reference',''),errors='strict'))
            chunks=[];size=0
            async for chunk in request.stream():
                size+=len(chunk)
                if size>MAX_BYTES:raise ValueError('File exceeds twenty MiB')
                chunks.append(chunk)
            from starlette.concurrency import run_in_threadpool
            result=await run_in_threadpool(provider.conversation_file_upload,b''.join(chunks),ref)
        except FileCapacityError:raise HTTPException(507,'Original file storage reached its receiving limit; existing originals are preserved') from None
        except (ValueError,UnicodeError):raise HTTPException(400,'Original file unavailable, changed or above twenty MiB') from None
        except (ProviderUnavailable,OSError):raise HTTPException(503,'File upload unconfirmed; no work was admitted') from None
        await authorize_async(request)
        return result

    @app.get('/api/interaction/inputs/{ident}/files/{index}')
    async def conversation_file_download(request: Request,ident:str,index:int):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            ref,data=await run_in_threadpool(provider.conversation_file_read,ident,index)
        except (ValueError,ProviderUnavailable,OSError):raise HTTPException(404,'Original file unavailable') from None
        from urllib.parse import quote
        return Response(content=data,media_type='application/octet-stream',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Content-Disposition':"attachment; filename*=UTF-8''"+quote(ref['name'],safe='')})

    @app.post('/api/interaction/visual')
    async def conversation_visual(request: Request):
        session=await authorize_async(request)
        if not secrets.compare_digest(request.headers.get('x-dashboard-csrf',''),session['csrf']):
            raise HTTPException(403,'Action token missing')
        if request.headers.get('content-type')!='image/png':raise HTTPException(400,'Select one PNG image')
        try:
            from starlette.concurrency import run_in_threadpool
            result=await run_in_threadpool(provider.conversation_visual_upload,await request.body(),request.headers.get('x-image-sha256',''))
        except ValueError:raise HTTPException(400,'Image unavailable or invalid. Select a still image of at most 2 MiB and 4 megapixels.') from None
        except (ProviderUnavailable,OSError):raise HTTPException(503,'Image upload unconfirmed. No conversation work was admitted.') from None
        await authorize_async(request)
        return result

    @app.get('/api/interaction/inputs/{ident}/image')
    async def conversation_visual_image(request: Request,ident:str,index:int=0):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            data=await run_in_threadpool(provider.conversation_visual_image,ident,index)
        except (ValueError,ProviderUnavailable,OSError):raise HTTPException(409,'Selected image unavailable; do not substitute another view') from None
        await authorize_async(request)
        return Response(content=data,media_type='image/png')

    voice_recovery_lock=asyncio.Lock()

    @app.post('/api/interaction/voice/recover')
    async def conversation_voice_recover(request: Request):
        session=await authorize_async(request)
        if not secrets.compare_digest(request.headers.get('x-dashboard-csrf',''),session['csrf']):
            raise HTTPException(403,'Action token missing')
        if voice_recovery_lock.locked():
            raise HTTPException(503,'Another recording recovery is still running; check status')
        metadata={key:request.headers.get(header,'') for key,header in
            (('id','x-input-id'),('binding','x-input-binding'),('audio_sha256','x-audio-sha256'),('mime','content-type'))}
        dialogue=request.headers.get('x-foreground-dialogue','')
        try:
            scope=request.headers.get('x-capture-questions')
            if scope is not None:
                if len(scope)>4096:raise ValueError('Capture scope exceeds bound')
                metadata['capture_questions']=json.loads(scope)
                Provider.check_capture_questions(metadata['capture_questions'])
            data=await request.body()
            if not 0<len(data)<=20*1024*1024:raise ValueError('Original exceeds bound')
            from starlette.concurrency import run_in_threadpool
            if voice_recovery_lock.locked():raise ProviderUnavailable('Another original recovery is still running')
            async with voice_recovery_lock:
                plan=await run_in_threadpool(provider.conversation_voice_recover,metadata,data,dialogue)
                result=plan['current']
                if 'command' in plan:
                    from .native_caption_recovery import execute_asr
                    await execute_asr(plan['command'],plan['media'],plan['timeout'])
                    await authorize_async(request)
                    result=await run_in_threadpool(provider.conversation_foreground_complete,
                        metadata['id'],metadata['binding'],dialogue)
        except (ValueError,UnicodeError):
            raise HTTPException(400,'Recording interpretation unconfirmed; keep the same original') from None
        except (ProviderUnavailable,OSError,TimeoutError):
            raise HTTPException(503,'Recording recovery unconfirmed; keep the original and check status') from None
        await authorize_async(request)
        return result

    @app.post('/api/interaction/voice')
    @app.post('/api/interaction/voice/limited')
    @app.post('/api/interaction/voice/openai')
    @app.post('/api/interaction/voice/openai/limited')
    @app.post('/api/interaction/voice/previous')
    @app.post('/api/interaction/voice/previous/limited')
    @app.post('/api/interaction/voice/openai-live')
    @app.post('/api/interaction/voice/openai-live/limited')
    @app.post('/api/interaction/voice/previous-live')
    @app.post('/api/interaction/voice/previous-live/limited')
    async def conversation_voice(request: Request):
        session = await authorize_async(request)
        if not secrets.compare_digest(request.headers.get('x-dashboard-csrf', ''), session['csrf']):
            raise HTTPException(403, 'Action token missing')
        metadata = {key:request.headers.get(header, '') for key, header in
                    (('binding', 'x-input-binding'), ('id', 'x-input-id'),
                     ('audio_sha256', 'x-audio-sha256'), ('mime', 'content-type'))}
        selected_profile=request.url.path.split('/voice/',1)[-1].split('/')[0]
        profile=selected_profile if selected_profile in ('openai','previous','openai-live','previous-live') else None
        if profile:
            if profile not in getattr(provider,'receiver',{}).get('voice',{}).get('transcription_profiles',{}):
                raise HTTPException(409,'Selected transcription is unavailable; no fallback')
            metadata['transcription_profile']=profile
        capture_stop = request.headers.get('x-recording-stop')
        if request.url.path.endswith('/limited') and capture_stop not in ('duration_limit','audio_flush_unconfirmed'):
            raise HTTPException(400, 'Limited recording stop reason required')
        if capture_stop is not None:
            if capture_stop not in ('duration_limit','audio_flush_unconfirmed'):raise HTTPException(400, 'Invalid recording stop reason')
            metadata['capture_stop'] = capture_stop
        reply_source = request.headers.get('x-reply-source')
        reply_revision = request.headers.get('x-reply-revision')
        if reply_source is not None or reply_revision is not None:
            metadata['reply'] = {'source':reply_source, 'revision':reply_revision}
            if isinstance(reply_source,str) and reply_source.startswith('context:'):
                # Older receivers reject this source form before ASR rather
                # than silently interpreting context as an explicit answer.
                metadata['reply'].update(source=reply_source[8:], context_only=True)
        require_pin_grant(session,metadata.get('reply'))
        playback=request.headers.get('x-playback-context')
        if playback is not None:
            try:
                if len(playback.encode())>2048:raise ValueError('Playback context exceeds bound')
                metadata['playback']=json.loads(playback)
                Provider.check_playback(metadata['playback'])
            except (ValueError,TypeError):raise HTTPException(400,'Invalid device playback context') from None
        capture_questions=request.headers.get('x-capture-questions')
        if capture_questions is not None:
            try:
                if len(capture_questions.encode())>4096:raise ValueError('Capture questions exceed bound')
                metadata['capture_questions']=json.loads(capture_questions)
                Provider.check_capture_questions(metadata['capture_questions'])
            except (ValueError,TypeError):raise HTTPException(400,'Invalid capture question restriction') from None
        visual=request.headers.get('x-visual-reference')
        if visual is not None:
            try:metadata['visual']=json.loads(visual)
            except (ValueError,TypeError):raise HTTPException(400,'Select one captured visual reference') from None
        files=request.headers.get('x-file-references')
        if files is not None:
            try:
                from urllib.parse import unquote
                if len(files)>32000:raise ValueError('File metadata exceeds bound')
                metadata['files']=json.loads(unquote(files,errors='strict'))
            except (ValueError,TypeError,UnicodeError):raise HTTPException(400,'Select original files again') from None
        try:
            data = await request.body()
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(provider.conversation_voice_submit, metadata, data)
        except RetentionUnavailable as exc:
            raise HTTPException(507, str(exc)) from None
        except VisualSelectionInvalid:
            return JSONResponse({'detail':'Select the captured image again. This attempt did not submit a recording.','code':'visual_reselection','submission_attempted':False},status_code=400)
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Provide one finalized recording of at most 20 MiB') from None
        except (ProviderUnavailable, OSError):
            raise HTTPException(503, 'Voice capture unconfirmed; check its status before retrying this recording') from None
        await authorize_async(request)
        return result

    def workspace_granted(session):
        return dict(session).get('scope') is None or (dict(session).get('scope')=='interaction_only' and dict(session).get('workspace_access') is True)

    def require_pin_grant(session,reply):
        if isinstance(reply,dict) and str(reply.get('source','')).startswith('session:') and not workspace_granted(session):
            raise HTTPException(403,'This device has no session destination permission')

    @app.get('/api/interaction/sessions')
    async def conversation_session_workspace(request: Request):
        session=await authorize_async(request)
        if not workspace_granted(session):
            raise HTTPException(403,'This device has no complete session workspace grant')
        try:
            from starlette.concurrency import run_in_threadpool
            result=await run_in_threadpool(provider.session_workspace)
        except (ValueError,KeyError,ProviderUnavailable,OSError,sqlite3.Error):
            raise HTTPException(503,'Session list unavailable; no work was started') from None
        session=await authorize_async(request)
        if not workspace_granted(session):
            raise HTTPException(403,'Session workspace grant changed')
        return {**result,'default_filter':'all' if config.get('session_workspace',{}).get('default_filter')=='all' else 'recent'}

    @app.get('/api/interaction/sessions/{ident}')
    async def conversation_selected_session(request: Request,ident: str,technical: bool=False,
            revision: str|None=None,before: int|None=None,after: int|None=None,
            event: int|None=None,text_offset: int=0,scan: bool=False):
        session=await authorize_async(request)
        if not workspace_granted(session):
            raise HTTPException(403,'This device has no complete session workspace grant')
        try:
            from starlette.concurrency import run_in_threadpool
            result=await run_in_threadpool(provider.session_view,ident,technical=technical,
                revision=revision,before=before,after=after,event=event,text_offset=text_offset,scan=scan)
        except (ValueError,KeyError,ProviderUnavailable,OSError,sqlite3.Error):
            raise HTTPException(409,'Selected conversation changed or is unavailable; select it again') from None
        session=await authorize_async(request)
        if not workspace_granted(session):
            raise HTTPException(403,'Session workspace grant changed')
        return result

    @app.get('/api/interaction/sonic')
    async def conversation_sonic_state(request: Request):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result=await run_in_threadpool(provider.sonic_activity)
        except (ValueError,KeyError,ProviderUnavailable,OSError,sqlite3.Error):
            raise HTTPException(503,'Session sound state unavailable; conversation work is unchanged') from None
        await authorize_async(request)
        return result

    @app.get('/api/interaction/artifacts')
    async def conversation_artifacts(request: Request):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result=await run_in_threadpool(provider.artifacts)
        except (ValueError,ProviderUnavailable,OSError):
            raise HTTPException(409,'Files unavailable; conversation work was not repeated') from None
        await authorize_async(request)
        return result

    @app.get('/api/interaction/artifacts/{ident}')
    async def conversation_artifact_download(request: Request,ident: str):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            from datetime import datetime
            from urllib.parse import quote
            ref,stream=await run_in_threadpool(provider.artifact_open,ident)
        except (ValueError,ProviderUnavailable,OSError):
            raise HTTPException(409,'File unavailable, expired or changed; the text reply remains available') from None
        try:
            await authorize_async(request)
            deadline=datetime.fromisoformat(ref['expires_at']).timestamp()
            if time.time()>=deadline:
                raise HTTPException(409,'File expired')
        except BaseException:
            stream.close()
            raise
        def chunks():
            checked=0
            try:
                while True:
                    if time.time()>=deadline:
                        raise RuntimeError('Artifact expired during download')
                    if time.monotonic()-checked>=1:
                        authorize(request);checked=time.monotonic()
                    data=stream.read(65536)
                    if not data:break
                    yield data
            finally:
                stream.close()
        return StreamingResponse(chunks(),media_type='application/octet-stream',headers={
            'Content-Disposition':"attachment; filename*=UTF-8''"+quote(ref['name'],safe=''),
            'Content-Length':str(ref['bytes']),'X-Artifact-Sha256':ref['sha256'],
            'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})

    @app.get('/api/interaction/goals')
    async def conversation_goals(request: Request, before: int = 0):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(provider.goal_controls, before)
        except ValueError:
            raise HTTPException(400, 'Invalid control selection') from None
        except (ProviderUnavailable, OSError):
            raise HTTPException(503, 'Goal controls unavailable; nothing was changed') from None
        await authorize_async(request)
        return result

    @app.get('/api/interaction/goals/{ident}')
    async def conversation_goal_detail(request: Request, ident: str):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(provider.goal_control_detail, ident)
        except ValueError:
            raise HTTPException(400, 'Invalid control selection') from None
        except (ProviderUnavailable, OSError):
            raise HTTPException(409, 'Control changed or is unavailable; nothing was changed') from None
        await authorize_async(request)
        return result

    @app.get('/api/interaction/tasks')
    async def conversation_tasks(request: Request, after: int = 0):
        session=await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result=await run_in_threadpool(provider.conversation_tasks,after)
        except ValueError:
            raise HTTPException(400,'Invalid task cursor') from None
        except (ProviderUnavailable,OSError):
            raise HTTPException(503,'Human tasks unavailable; refresh to reconnect') from None
        await authorize_async(request)
        return {**result,'csrf':session['csrf']}

    @app.get('/api/interaction/tasks/{ident}')
    async def conversation_task_detail(request: Request, ident: str, offset: int = 0, revision: str | None = None):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result=await run_in_threadpool(provider.conversation_task_detail,ident,offset,revision)
        except ValueError:
            raise HTTPException(400,'Invalid task selection') from None
        except (ProviderUnavailable,OSError):
            raise HTTPException(409,'Task changed or is unavailable; refresh its current state') from None
        await authorize_async(request)
        return result

    @app.post('/api/interaction/tasks/{ident}')
    async def conversation_task_dismiss(request: Request, ident: str):
        session = await authorize_async(request)
        if not secrets.compare_digest(request.headers.get('x-dashboard-csrf',''),session['csrf']):
            raise HTTPException(403,'Action token missing')
        try:
            body = await request.json()
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(provider.conversation_task_dismiss,ident,body)
        except ValueError:
            raise HTTPException(400,'Select one current action to dismiss') from None
        except (ProviderUnavailable,OSError):
            raise HTTPException(409,'Dismissal unconfirmed or action changed; check its current state') from None
        await authorize_async(request)
        return result

    @app.get('/api/interaction/internal')
    async def internal_pending(request: Request, after: int = 0):
        session=await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result=await run_in_threadpool(provider.internal_pending,after)
        except ValueError:
            raise HTTPException(400,'Invalid internal pending cursor') from None
        except (ProviderUnavailable,OSError):
            raise HTTPException(503,'Session pending requests unavailable') from None
        await authorize_async(request)
        return {**result,'csrf':session['csrf']}

    @app.get('/api/interaction/internal/{kind}/{ident}')
    async def internal_pending_detail(request: Request, kind: str, ident: str, offset: int = 0, revision: str | None = None):
        await authorize_async(request)
        if kind not in ('requests','tasks'):raise HTTPException(404,'Unknown pending kind')
        try:
            from starlette.concurrency import run_in_threadpool
            method=provider.conversation_request_detail if kind=='requests' else provider.conversation_task_detail
            result=await run_in_threadpool(method,ident,offset,revision,True)
        except ValueError:
            raise HTTPException(400,'Invalid session pending selection') from None
        except (ProviderUnavailable,OSError):
            raise HTTPException(409,'Pending item changed; read its current state') from None
        await authorize_async(request)
        return result

    @app.get('/api/interaction/internal/requests/{ident}/receipt')
    async def internal_pending_receipt(request: Request, ident: str, revision: str):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result=await run_in_threadpool(provider.conversation_decision_receipt,ident,revision,True)
        except ValueError:
            raise HTTPException(400,'Invalid session pending receipt') from None
        except (ProviderUnavailable,OSError):
            raise HTTPException(409,'Decision receipt unavailable; nothing was repeated') from None
        await authorize_async(request)
        return result

    @app.post('/api/interaction/internal/{kind}/{ident}')
    async def internal_pending_decide(request: Request, kind: str, ident: str):
        session=await authorize_async(request)
        if kind not in ('requests','tasks'):raise HTTPException(404,'Unknown pending kind')
        if not secrets.compare_digest(request.headers.get('x-dashboard-csrf',''),session['csrf']):
            raise HTTPException(403,'Action token missing')
        try:
            body=await request.json()
            # Conversation-only devices keep their existing approval/cancellation restriction.
            if kind=='requests' and dict(session).get('scope')=='interaction_only' and dict(session).get('native_decision_access') is not True and (
                    not isinstance(body,dict) or not isinstance(body.get('action'),dict)
                    or body['action'].get('kind') not in ('answer','option')):
                raise HTTPException(403,'Use Sessions to review this approval or cancellation')
            from starlette.concurrency import run_in_threadpool
            method=provider.conversation_request_decide if kind=='requests' else provider.conversation_task_dismiss
            result=await run_in_threadpool(method,ident,body,True)
        except ValueError:
            raise HTTPException(400,'Select one exact session pending action') from None
        except (ProviderUnavailable,OSError):
            raise HTTPException(409,'Action unconfirmed or changed; inspect its current state before retrying') from None
        await authorize_async(request)
        return result

    @app.get('/api/interaction/requests')
    async def conversation_requests(request: Request, after: int = 0):
        session = await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(provider.conversation_requests, after)
        except ValueError:
            raise HTTPException(400, 'Invalid request cursor') from None
        except (ProviderUnavailable, OSError):
            raise HTTPException(503, 'Pending requests unavailable; refresh to reconnect') from None
        await authorize_async(request)
        return {**result, 'csrf':session['csrf']}

    @app.get('/api/interaction/requests/{ident}')
    async def conversation_request_detail(request: Request, ident: str, offset: int = 0, revision: str | None = None):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(provider.conversation_request_detail, ident, offset, revision)
        except ValueError:
            raise HTTPException(400, 'Invalid native request selection') from None
        except (ProviderUnavailable, OSError):
            raise HTTPException(409, 'Request changed or is unavailable; refresh its current state') from None
        await authorize_async(request)
        return result

    @app.get('/api/interaction/requests/{ident}/receipt')
    async def conversation_decision_receipt(request: Request, ident: str, revision: str):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(provider.conversation_decision_receipt, ident, revision)
        except ValueError:
            raise HTTPException(400, 'Invalid decision selection') from None
        except (ProviderUnavailable, OSError):
            raise HTTPException(409, 'Decision recording unconfirmed; no repeat was submitted') from None
        await authorize_async(request)
        return result

    @app.post('/api/interaction/requests/{ident}')
    async def conversation_request_decide(request: Request, ident: str):
        session = await authorize_async(request)
        if not secrets.compare_digest(request.headers.get('x-dashboard-csrf', ''), session['csrf']):
            raise HTTPException(403, 'Action token missing')
        try:
            body = await request.json()
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(provider.conversation_request_decide, ident, body)
        except ValueError:
            raise HTTPException(400, 'Select one exact native request decision') from None
        except (ProviderUnavailable, OSError):
            raise HTTPException(409, 'Decision unconfirmed or request changed. Check its current state before trying again') from None
        await authorize_async(request)
        return result

    @app.get('/api/interaction/part')
    async def interaction_part(request: Request, source: str, revision: str, offset: int = 0):
        await authorize_async(request)
        try:
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(provider.presentation_part, source, revision, offset)
        except (ProviderUnavailable, OSError, ValueError):
            raise HTTPException(409, 'Selected result changed or is unavailable; refresh the conversation') from None
        await authorize_async(request)
        return result

    @app.post('/api/interaction/audio')
    async def interaction_audio(request: Request):
        session = await authorize_async(request)
        if not secrets.compare_digest(request.headers.get('x-dashboard-csrf', ''), session['csrf']):
            raise HTTPException(403, 'Action token missing')
        if speech is None:
            raise HTTPException(503, 'Speech output is not configured')
        try:
            body = await request.json()
            if (not isinstance(body, dict) or not {'source','revision','offset'}<=set(body) or set(body)-{'source','revision','offset','stream','speech_provider'}
                    or type(body.get('stream',False)) is not bool):
                raise ValueError()
            profile = body.get('speech_provider',services_default)
            if profile not in ('current', 'openai'):
                raise ValueError('Unknown speech profile; no fallback')
            engine = openai_speech if profile == 'openai' else speech
            if engine is None:
                raise ValueError('Selected speech profile unavailable; no fallback')
            from starlette.concurrency import run_in_threadpool
            canonical = await run_in_threadpool(provider.presentation_part, body['source'], body['revision'], body['offset'])
            if canonical.get('kind')=='integrator_live' and not engine.live_response:
                raise ValueError('Live speech is not selected')
            selected = speech_part(canonical) if engine.incremental else canonical
        except (ProviderUnavailable, OSError, ValueError, KeyError):
            raise HTTPException(409, 'Selected result changed or is unavailable; refresh the conversation') from None
        await authorize_async(request)
        if body.get('stream'):
            if not engine.streaming or selected.get('kind')=='native_question':
                raise HTTPException(409,'Streaming speech unavailable; use the ordinary reader')
            async def audio_frames():
                try:
                    async with aclosing(engine.stream(selected)) as frames:
                        async for frame in frames:
                            await authorize_async(request)
                            latest=await run_in_threadpool(provider.presentation_part,body['source'],body['revision'],body['offset'])
                            if latest!=canonical:
                                raise SpeechUnavailable('Presentation source changed')
                            yield json.dumps(frame,separators=(',',':'))+'\n'
                except RetentionUnavailable:
                    yield json.dumps({'type':'error','message':'Original audio retention is full or unavailable. Protected originals remain saved; new speech was stopped.'})+'\n'
                except (SpeechUnavailable,RenderError,ProviderUnavailable,OSError,ValueError,KeyError,TimeoutError,HTTPException):
                    yield json.dumps({'type':'error','message':'Speech stopped. Text remains available; no automatic retry.'})+'\n'
            return StreamingResponse(audio_frames(),media_type='application/x-ndjson',headers={
                'Cache-Control':'no-store','X-Accel-Buffering':'no',
                'X-Speech-Provider':profile or 'default','X-Presentation-Source':body['source'],'X-Presentation-Revision':body['revision'],
                'X-Presentation-Offset':str(body['offset']),
                'X-Presentation-Next-Offset':str(selected['next_offset']) if selected['next_offset'] is not None else '',
                'X-Presentation-End-Offset':str(body['offset']+len(selected['text'])),
                'X-Presentation-Text-Sha256':hashlib.sha256(selected['text'].encode()).hexdigest(),
                'X-Presentation-Prefetch':'true','X-Audio-Encoding':'mp3','X-Playback-Observation':'not_observed'})
        try:
            data, rendered = await engine.render(selected)
            # Retained text, bindings and correction state are rechecked after synthesis.
            latest = await run_in_threadpool(provider.presentation_part, body['source'], body['revision'], body['offset'])
            if latest != canonical:
                raise SpeechUnavailable('Presentation source changed')
        except RetentionUnavailable as exc:
            raise HTTPException(507, str(exc)) from None
        except (SpeechUnavailable, RenderError, ProviderUnavailable, OSError, ValueError, KeyError, TimeoutError):
            raise HTTPException(409, 'Speech outcome retained; refresh before continuing') from None
        await authorize_async(request)
        return Response(data, media_type='audio/wav', headers={
            'X-Speech-Provider':profile or 'default','X-Presentation-Source':body['source'], 'X-Presentation-Revision':body['revision'],
            'X-Presentation-Offset':str(body['offset']),
            'X-Presentation-Next-Offset':str(selected['next_offset']) if selected['next_offset'] is not None else '',
            'X-Audio-Sha256':rendered['audio_sha256'], 'X-Playback-Observation':'not_observed',
            'X-Presentation-End-Offset':str(body['offset']+len(selected['text'])) if engine.incremental and selected.get('kind')!='native_question' else '',
            'X-Presentation-Text-Sha256':hashlib.sha256(selected['text'].encode()).hexdigest() if engine.incremental and selected.get('kind')!='native_question' else '',
            'X-Presentation-Prefetch':'true' if engine.incremental and selected.get('kind')!='native_question' else 'false'})

    @app.post('/api/alerts/attention')
    async def launcher_attention(request: Request):
        if not telegram_launch:
            raise HTTPException(403, 'Telegram launch is not configured')
        # Read-only signed-launch route. It mints no control/session credential.
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {'init_data'} or not isinstance(body['init_data'], str):
                raise ValueError()
            human = validator(body['init_data'], config['bot_id'])
        except (ValueError, KeyError, TypeError):
            raise HTTPException(401, 'Invalid or expired Telegram launch') from None
        check_binding()
        if not provider.authorized(human):
            raise HTTPException(403, 'This account has no receiving alert grant')
        view = alerts.snapshot() if alerts is not None else {'state':'not_configured'}
        result = attention_projection(view)
        check_binding()
        if not provider.authorized(human):
            raise HTTPException(403, 'Receiving grant unavailable')
        return {**result, 'app_url':sessions_selection(config)['web_app']['url'],
                'bot_username':config.get('bot_username')}

    @app.get('/api/interaction/alerts')
    def conversation_alerts(request: Request):
        session = authorize(request)
        if dict(session).get('scope') is not None and dict(session).get('alerts_access') is not True:
            raise HTTPException(403, 'This conversation has no alert read grant')
        try:
            result = alerts.snapshot() if alerts is not None else {'state': 'not_configured'}
        except (OSError, sqlite3.Error, ValueError):
            raise HTTPException(503, 'Alerts receiving state unavailable') from None
        authorize(request)
        return {**result, 'attention':attention_projection(result), 'read_only':True}

    @app.get('/api/alerts')
    def incidents(request: Request):
        session = authorize(request)
        try:
            result = alerts.snapshot() if alerts is not None else {'state': 'not_configured'}
        except (OSError, sqlite3.Error, ValueError):
            raise HTTPException(503, 'Alerts receiving state unavailable') from None
        authorize(request)
        return {**result, 'attention':attention_projection(result), 'csrf': session['csrf']}

    @app.post('/api/alerts/acknowledge')
    async def acknowledge(request: Request):
        session = await authorize_async(request)
        if not secrets.compare_digest(request.headers.get('x-dashboard-csrf', ''), session['csrf']):
            raise HTTPException(403, 'Action token missing')
        if alerts is None:
            raise HTTPException(503, 'Alerts are not configured')
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {'producer_id', 'incident_id', 'request_id'} or any(
                    not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value)
                    for value in body.values()):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(400, 'Invalid acknowledgment request') from None
        try:
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(alerts.acknowledge,
                body['producer_id'], body['incident_id'], body['request_id'])
        except (AlertsUnavailable, ProviderUnavailable, OSError, ValueError, sqlite3.Error):
            raise HTTPException(503, 'Acknowledgment unconfirmed; refresh before retrying') from None
        await authorize_async(request)
        return result

    @app.post('/api/stop')
    async def stop(request: Request):
        return await action(request, 'stop')

    @app.post('/api/resume')
    async def resume(request: Request):
        return await action(request, 'resume')

    async def action(request, kind):
        session = await authorize_async(request)
        if not secrets.compare_digest(request.headers.get('x-dashboard-csrf', ''), session['csrf']):
            raise HTTPException(403, 'Action token missing')
        try:
            body = await request.json()
            nonce = body['nonce']
            expected = {'nonce'} if kind == 'stop' else {'nonce', 'operation'}
            if set(body) != expected or not isinstance(nonce, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,64}', nonce):
                raise ValueError()
            operation = body.get('operation')
            if kind == 'resume' and (not isinstance(operation, str) or
                    not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', operation)):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise HTTPException(400, 'Invalid control request') from None
        # Separate action/operation namespaces; never reuse another intent's receipt.
        journal_nonce = nonce if kind == 'stop' else 'resume:' + digest(operation + ':' + nonce)
        with database() as db:
            # Claim before the first external effect; a concurrent retry cannot dispatch it twice.
            fresh = db.execute('INSERT OR IGNORE INTO actions VALUES(?,?,?,NULL)',
                               (session['human'], journal_nonce, 'requested')).rowcount == 1
            prior = db.execute('SELECT state,result FROM actions WHERE human=? AND nonce=?',
                               (session['human'], journal_nonce)).fetchone()
        if not fresh:
            return JSONResponse(json.loads(prior['result']) if prior['result'] else
                                {'state': 'unconfirmed', 'detail': 'Inspect control status before another action'},
                                status_code=200 if prior['result'] else 202)
        try:
            # Sync control runs off the event loop; reads stay available during recovery.
            from starlette.concurrency import run_in_threadpool
            if kind == 'stop':
                result = await run_in_threadpool(provider.stop, nonce)
            else:
                result = await run_in_threadpool(provider.resume, nonce, operation)
        except Exception:
            result = {'state': 'unconfirmed', 'detail': kind.title() + ' acknowledgement unavailable; inspect status before retrying'}
        with database() as db:
            db.execute('UPDATE actions SET state=?,result=? WHERE human=? AND nonce=?',
                       (result.get('state', 'unconfirmed'), json.dumps(result), session['human'], journal_nonce))
        return JSONResponse(result, status_code=202)

    return app
