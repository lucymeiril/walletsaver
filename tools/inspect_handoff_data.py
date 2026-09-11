"""Report schemas and suspicious field names, never secret values."""
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
for relative in ['.walletsavior/admin.sqlite', '.debug-artifacts/initial-catalog-20260910-pass41/staging.sqlite']:
    with sqlite3.connect((ROOT/relative).as_uri() + '?mode=ro', uri=True) as c:
        rows = []
        for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            columns = [r[1] for r in c.execute('PRAGMA table_info("'+name+'")')]
            count = c.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0]
            rows.append((name,count,columns))
        print(relative, json.dumps(rows,ensure_ascii=False))
source = ROOT/'.debug-artifacts/initial-catalog-20260910-pass41'
bad = re.compile(r'password|passwd|secret|access.?token|refresh.?token|authorization|cookie|api.?key|email|phone', re.I)
hits = set()
def scan(value, path):
    if isinstance(value, dict):
        for k,v in value.items():
            if bad.search(k) and v not in (None,'',[],{}): hits.add(path+'/'+k)
            scan(v,path+'/'+k)
    elif isinstance(value,list):
        for v in value: scan(v,path+'/*')
    elif isinstance(value,str) and value[:1] in '[{':
        try: scan(json.loads(value),path+'/decoded')
        except (ValueError,TypeError): pass
for name in ['source-ingestions.json','catalog-bundle.json','reviewed-decisions.json','classification-decisions.json']:
    scan(json.loads((source/name).read_text(encoding='utf-8')),name)
print('SUSPICIOUS_FIELD_PATHS', sorted(hits))
