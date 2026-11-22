"""The existing client-build label and hash of actual selected public UI bytes."""
import hashlib
from pathlib import Path

MARKER = '<div id="client-build" hidden></div>'
CSS = '.client-build {display:block;font:9px/12px ui-monospace,monospace;letter-spacing:.02em;color:var(--muted,#82909c);margin:0 0 4px;white-space:nowrap} .client-build code {font:inherit}'


def fingerprint(shell, assets):
    digest = hashlib.sha256(shell)
    for name, raw in assets:
        digest.update(name.encode() + b'\0' + raw)
    return digest.hexdigest()


def stamp(body, build):
    label = ''.join('<span>'+digit+'</span>' for digit in build[:12])
    return body.replace(MARKER, '<div id="client-build" title="Client bundle '+build+'" aria-label="Client version '+build[:12]+'" class="client-build">ui <code>'+label+'</code></div>')


def workshop_assets(public, state_dir):
    from . import shared_asset_release as releases
    baseline = Path(public)/'avatar-workshop'
    root = Path(state_dir)/'shared-app-assets/avatar-workshop'
    selected = releases.current(root)
    if selected:
        release = selected['release']
        manifest = releases.manifest(root, release, baseline)
        result = []
        for name, expected in sorted(manifest['files'].items()):
            if name in ('PROVENANCE.json', 'validate-design.mjs') or Path(name).suffix not in releases.PUBLIC_SUFFIXES:
                continue
            raw = releases.read_beneath(root, release+'/'+name, 1024*1024)
            if releases.digest(raw) != expected:
                raise ValueError('Selected workshop asset bytes changed')
            result.append(('avatar-workshop/'+name, raw))
        return release, result
    return None, [(p.relative_to(public).as_posix(), p.read_bytes())
                  for p in sorted(baseline.rglob('*')) if p.is_file() and not p.is_symlink()
                  and p.suffix in releases.PUBLIC_SUFFIXES and p.name not in ('PROVENANCE.json', 'validate-design.mjs')]
