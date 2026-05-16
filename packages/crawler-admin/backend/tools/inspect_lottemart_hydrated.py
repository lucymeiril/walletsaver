"""Inspect captured lottemart hydrated state and extract productEntities."""
import json
import pathlib
import re
import sys

P = pathlib.Path("tests/fixtures/live_probe/lottemart_hydrated_promotions.html")
h = P.read_text(encoding="utf-8")
m = re.search(r"__INITIAL_STATE__\s*=\s*", h)
i = m.end()
assert h[i] == "{"
depth = 0
in_str = False
esc = False
end = None
for j in range(i, len(h)):
    c = h[j]
    if esc:
        esc = False
        continue
    if c == "\\":
        esc = True
        continue
    if c == '"':
        in_str = not in_str
        continue
    if in_str:
        continue
    if c == "{":
        depth += 1
    elif c == "}":
        depth -= 1
        if depth == 0:
            end = j + 1
            break

raw = h[i:end]
print("raw_len", len(raw))
s = json.loads(raw)
print("top keys", list(s.keys())[:10])

# Walk to find productEntities-like dicts
def walk(node, path=""):
    if isinstance(node, dict):
        if "productEntities" in node:
            yield path + ".productEntities", node["productEntities"]
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for idx, v in enumerate(node):
            yield from walk(v, f"{path}[{idx}]")

hits = list(walk(s, "$"))
for p, v in hits[:5]:
    if isinstance(v, dict):
        print(p, "type=dict len=", len(v))
        if v:
            k = next(iter(v))
            print("  sample key:", k)
            sample = v[k]
            if isinstance(sample, dict):
                print("  keys:", list(sample.keys())[:40])
                print("  sample:", json.dumps(sample, ensure_ascii=False)[:800])

# Save first productEntities
if hits:
    pe = hits[0][1]
    if isinstance(pe, dict) and pe:
        keep = dict(list(pe.items())[:5])
        outp = pathlib.Path("tests/fixtures/live_probe/lottemart_hydrated_productEntities_sample.json")
        outp.write_text(json.dumps(keep, ensure_ascii=False, indent=2), encoding="utf-8")
        print("saved sample to", outp, "rows", len(keep))
