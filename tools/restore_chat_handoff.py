"""Verify and unpack the public handoff into a NEW ignored directory."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--package', type=Path, default=ROOT/'handoff/2026-09-11')
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
package = args.package.resolve(strict=True)
manifest = json.loads((package/'manifest.json').read_text(encoding='utf-8'))
for relative, meta in manifest['files'].items():
    path = (package/relative).resolve(strict=True)
    assert path.is_relative_to(package)
    data = path.read_bytes()
    assert len(data)==meta['bytes'] and hashlib.sha256(data).hexdigest()==meta['sha256'], relative
out = args.out.resolve()
if out.exists(): raise ValueError('Destination must be new; never overwrite a checkpoint')
out.mkdir(parents=True)
for path in (package/'archives').glob('*.gz'):
    name = path.stem.replace('staging-pass41.sqlite','staging.sqlite')
    (out/name).write_bytes(gzip.decompress(path.read_bytes()))
(out/'reviewed-decisions.json').write_bytes((package/'reviewed-decisions-applied.json').read_bytes())
print('Verified all manifest files and restored:', out)
