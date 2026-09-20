import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/p) for p in ('packages/shared','packages/db-admin/backend')]
import catalog_job as job


def test_job_copies_packet_hash_and_rejects_overwrite_stale_and_duplicates(tmp_path,monkeypatch):
    state={'baseline':'current','source_file_sha256':'source'}
    job.write_new(tmp_path/'docs/catalog-state.json',state)
    packet=job.named(tmp_path,'sample','.debug-artifacts/review-packets')
    job.write_new(packet,dict(state,rows=[]))
    monkeypatch.setattr(job,'ROOT',tmp_path)
    argv=['catalog_job.py','example','--packet','sample','--leaf-prefix','food.drinks.']
    monkeypatch.setattr(sys,'argv',argv)
    job.main()
    result=job.read(tmp_path/'.debug-artifacts/review-jobs/example.json')
    assert result['packets'][0]['sha256']==job.sha(packet)
    assert result['leaves'] and 'leaves' not in result['packets'][0]
    with pytest.raises(FileExistsError): job.main()
    monkeypatch.setattr(sys,'argv',argv+['--packet','sample'])
    with pytest.raises(ValueError,match='Duplicate'): job.main()
    monkeypatch.setattr(sys,'argv',argv)
    packet.write_text(json.dumps(dict(state,baseline='old')),encoding='utf-8')
    with pytest.raises(ValueError,match='Stale'): job.main()
