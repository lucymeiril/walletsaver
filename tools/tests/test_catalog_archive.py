import sys
from pathlib import Path
import zipfile
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import catalog_archive as archive


def test_archive_deduplicates_and_roundtrips_without_removing_input(tmp_path):
    base=tmp_path/'.debug-artifacts'; old=base/'initial-catalog-test-pass2b'; old.mkdir(parents=True)
    current=base/'initial-catalog-test-pass3'; current.mkdir()
    (current/'protected').write_bytes(b'current')
    for name in ('proposal.json','hold.json'):(old/name).write_bytes(b'same bytes')
    paths=archive.candidates(tmp_path,current)
    assert len(paths)==2
    output=base/'catalog-archives/history.zip'
    rows=archive.pack(tmp_path,paths,output)
    assert all(p.exists() for p in paths)
    with zipfile.ZipFile(output) as z:
        assert len([name for name in z.namelist() if name.startswith('blobs/')])==1
        for row in rows:assert z.read('blobs/'+row['sha256'])==(tmp_path/row['path']).read_bytes()
    assert archive.verify(output)==rows
    with pytest.raises(FileExistsError):archive.pack(tmp_path,paths,output)


def test_archive_detects_corrupt_manifest_digest(tmp_path):
    output=tmp_path/'bad.zip'
    with zipfile.ZipFile(output,'w') as z:
        z.writestr('manifest.json','{"files":[{"sha256":"bad","bytes":3}]}')
        z.writestr('blobs/bad',b'abc')
    with pytest.raises(ValueError,match='content mismatch'):archive.verify(output)
