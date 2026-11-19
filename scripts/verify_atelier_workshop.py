"""Verify the deliberately selected, licensed receiving editor bytes."""
import hashlib
import json
from pathlib import Path
import re


def verify():
    root = Path(__file__).resolve().parents[1] / 'dashboard/web/atelier-workshop'
    manifest = json.loads((root / 'PROVENANCE.json').read_text())
    assert manifest['schema'] == 'daimon.atelier-assets/v1'
    assert manifest['workingCopy'] is False, 'Export a committed source revision'
    assert re.fullmatch('[a-f0-9]{40}', manifest['sourceCommit'])
    assert set(manifest['files']) == {'index.html', 'host.js', 'project.js', 'corner-contract.js', 'LICENSE'}
    for name, expected in manifest['files'].items():
        raw = (root / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected, name
        assert len(raw) <= 1024 * 1024, name
    html = (root / 'index.html').read_text()
    assert 'data-atelier-account="true"' in html
    assert f'name="sculpt-build" content="{manifest["build"]}"' in html
    assert 'MIT License' in (root / 'LICENSE').read_text()
    print('Committed generic Atelier editor assets and license verified')


if __name__ == '__main__':
    verify()
