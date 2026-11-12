"""Finite existing-desk projection, called after a completed intake reconciliation.

No Drive acquisition, scheduler, social publishing or source-media retirement.
"""
import hashlib
import argparse
import fcntl
import tempfile
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import importlib.util
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
DESK = Path.home() / '.config/daimon-social-identity/desk'
BUDGET = 8 * 1024 * 1024


def run(*args, pass_fds=()):
    return subprocess.check_output(args, text=True, pass_fds=pass_fds)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(snapshot_bytes=None):
    # Keep this whole-command lock outside actor-writable intake/desk paths.
    with (ROOT / '.refresh.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        source = (DESK / 'source-snapshot.json').read_bytes() if snapshot_bytes is None else snapshot_bytes
        if len(source) > 2 * 1024 * 1024:
            raise SystemExit('Projection input exceeds its existing 2MiB bound')
        source_doc = json.loads(source)
        # An anonymous host-owned file bounds interrupted staging too: no orphan
        # snapshots survive SIGKILL. Only the builder inherits this one descriptor.
        with tempfile.TemporaryFile(dir=ROOT) as pinned:
            pinned.write(source)
            pinned.flush()
            _refresh(Path('/proc/self/fd') / str(pinned.fileno()), pinned.fileno(),
                     hashlib.sha256(source).hexdigest(), source_doc['observed_at'])


def _refresh(snapshot, snapshot_fd, source_sha256, source_observed_at):
    binding = json.loads((Path.home() / '.config/daimon-home/binding.json').read_text())
    store = Path(binding['store'])
    state = json.loads((store / 'state.json').read_text())
    entry = next(e for e in state['entries'] if e['id'] == 'bitacora-desk' and e['visibility'] == 'human')
    render = DESK / 'render'
    run(sys.executable, str(ROOT / 'build.py'), '--snapshot', str(snapshot), '--output', str(render),
        '--style-consumer', str(store / 'objects' / entry['object'] / 'artifact-style.js'),
        '--media-manifest', str(DESK / 'media-manifest.json'),
        '--media-directory', str(DESK / 'media-assets'),
        '--editorial-plans', str(DESK / 'editorial-plans.json'),
        '--narration', str(DESK / 'guitar-narration.json'), pass_fds=(snapshot_fd,))
    # Observation-only changes must not accumulate immutable versions.
    candidate = json.loads((render / 'data.js').read_text().removeprefix('window.BITACORA_DATA=').rstrip(';\n'))
    selected = store / 'objects' / entry['object']
    old = json.loads((selected / 'data.js').read_text().removeprefix('window.BITACORA_DATA=').rstrip(';\n'))
    for item in (candidate, old):
        item.pop('observed_at', None)
    unchanged = candidate == old and all(
        (selected / name).exists() and digest(render / name) == digest(selected / name)
        for name in ('index.html', 'desk.js', 'desk.css', 'artifact-style.js'))
    checkpoint = DESK / 'projection-current.json'
    if unchanged and checkpoint.exists() and json.loads(checkpoint.read_text()).get('version_ref') == entry['version_ref']:
        print(json.dumps({'state': 'unchanged', 'version_ref': entry['version_ref'], 'source_sha256': source_sha256}))
        return
    retained = {}
    for version in [entry] + entry.get('versions', []):
        for path in (store / 'objects' / version['object']).rglob('*'):
            if path.is_file():
                retained[digest(path)] = path.stat().st_size
    for path in render.rglob('*'):
        if path.is_file():
            retained[digest(path)] = path.stat().st_size
    if sum(retained.values()) > BUDGET:
        raise SystemExit('Projection history at capacity; keep Drive sources and reconcile owning Home history before publication')
    if not unchanged:
        run('daimon-home', 'publish', str(render), '--id', 'bitacora-desk',
        '--visibility', 'human', '--title', 'Bitácora · Nuestro registro',
        '--summary', 'Lo que creamos, sus imágenes y audios, y las historias que estamos preparando.',
        '--reuse-identical', '--expected-current', entry['version_ref'],
            '--decision', 'Project the reconciled institutional intake into the existing private editorial view; preserve masters, audience and stable identity.')
    current = next(e for e in json.loads((store / 'state.json').read_text())['entries']
                   if e['id'] == 'bitacora-desk' and e['visibility'] == 'human')
    actual = store / 'objects' / current['object']
    for path in render.rglob('*'):
        if path.is_file() and digest(path) != digest(actual / path.relative_to(render)):
            raise SystemExit('Selected immutable projection differs from prepared content')
    # Own protected broker verifies serving without impersonating the human.
    # A being reader session does not confer the paired-human-only grant.
    helper = Path.home() / '.agents/skills/daimon-home/scripts/home.py'
    spec = importlib.util.spec_from_file_location('home_publisher', helper)
    home = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(home)
    token = home.private_token(binding['access']['gateway_token_file'])
    for path in render.rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(render).as_posix()
        url = ('http://127.0.0.1:' + str(binding['public_port']) + '/_home/artifact/'
               + current['artifact_ref'] + '/' + current['version_ref'] + '/' + relative)
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.headers.get('X-Home-Version') != current['version_ref']:
                raise SystemExit('Served version differs from selected projection')
            content = response.read(path.stat().st_size + 1)
            if hashlib.sha256(content).hexdigest() != digest(path):
                raise SystemExit('Served projection bytes differ')
    receipt = {'schema': 'bitacora.projection/v1', 'state': 'published_verified',
               'updated_at': datetime.now(timezone.utc).isoformat(),
               'source_observed_at': source_observed_at, 'source_sha256': source_sha256,
               'artifact_ref': current['artifact_ref'], 'version_ref': current['version_ref'],
               'audience': 'human', 'cards': len(candidate['cards']),
               'immutable_files_match': True, 'owner_broker_all_files_match': True,
               'human_browser_acceptance': 'not_tested', 'served_data_sha256': digest(render / 'data.js'),
               'retained_unique_bytes_upper_bound': sum(retained.values()),
               'first_automatic_execution': 'not_observed_by_this_command'}
    target = DESK / 'projection-current.json'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(receipt, indent=2) + '\n')
    temporary.replace(target)
    print(json.dumps(receipt))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-dir', type=Path)
    parser.add_argument('--snapshot-stdin', action='store_true')
    args = parser.parse_args()
    if args.project_dir is not None:
        ROOT = args.project_dir.resolve(strict=True)
    raw = sys.stdin.buffer.read(2 * 1024 * 1024 + 1) if args.snapshot_stdin else None
    main(raw)
