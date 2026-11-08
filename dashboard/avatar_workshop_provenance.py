"""Check or refresh adapted workshop bytes without changing upstream provenance."""
import argparse
import hashlib
import json
from pathlib import Path


def receiving_hashes(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob('*'))
        if path.is_file() and path.name != 'PROVENANCE.json'
        and '__pycache__' not in path.parts and path.suffix != '.pyc'
    }


def discrepancies(root):
    declared = json.loads((root / 'PROVENANCE.json').read_text())['receiving_hashes']
    actual = receiving_hashes(root)
    return {name: ('unlisted' if name not in declared else
                   'missing' if name not in actual else 'changed')
            for name in sorted(declared.keys() | actual.keys())
            if declared.get(name) != actual.get(name)}


def refresh(root):
    path = root / 'PROVENANCE.json'
    document = json.loads(path.read_text())
    actual = receiving_hashes(root)
    # Keep the reviewed inventory order so a refresh highlights changed bytes.
    ordered = [name for name in document['receiving_hashes'] if name in actual]
    ordered.extend(name for name in actual if name not in document['receiving_hashes'])
    document['receiving_hashes'] = {name: actual[name] for name in ordered}
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1] / 'dashboard/web/avatar-workshop')
    parser.add_argument('--update', action='store_true', help='Refresh only adapted receiving hashes; retain original source and attribution')
    args = parser.parse_args()
    if args.update:
        refresh(args.root)
    differences = discrepancies(args.root)
    print(json.dumps({'state': 'mismatch' if differences else 'verified', 'differences': differences}, sort_keys=True))
    raise SystemExit(bool(differences))
