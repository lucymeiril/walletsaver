"""Opt-in history compaction: preserve bytes, keep the current snapshot live."""
import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from catalog_harness import ROOT, preflight, read, require, sha


def candidates(root, baseline):
    base=(root/'.debug-artifacts').resolve()
    result=[]
    for directory in sorted(base.iterdir()):
        if not re.fullmatch(r'initial-catalog-.*-pass\d+[a-z]*(?:-.*)?',directory.name):continue
        require(not directory.is_symlink(),'Symlink run refused')
        if not directory.is_dir() or directory.resolve()==baseline.resolve():continue
        require(directory.resolve().parent==base,'Run escaped artifact root')
        for path in sorted(directory.rglob('*')):
            require(not path.is_symlink() and path.resolve().is_relative_to(directory.resolve()),'Escaping archive member')
            if path.is_file():result.append(path)
    return result


def pack(root, paths, output):
    """Exclusive archive; manifest maps original paths to verified SHA256 blobs."""
    rows=[]; seen=set()
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
        for path in paths:
            digest=sha(path)
            rows.append({'path':path.relative_to(root).as_posix(),'sha256':digest,'bytes':path.stat().st_size})
            if digest not in seen:
                archive.write(path,'blobs/'+digest);seen.add(digest)
        archive.writestr('manifest.json',json.dumps({'version':1,'files':rows},ensure_ascii=False,indent=2))
    verify(output)
    return rows


def verify(output):
    with zipfile.ZipFile(output) as archive:
        rows=json.loads(archive.read('manifest.json'))['files']; checked={}
        for row in rows:
            digest=row['sha256']
            if digest not in checked:
                with archive.open('blobs/'+digest) as stream:
                    calculated=hashlib.file_digest(stream,'sha256').hexdigest()
                require(calculated==digest,'Archive content mismatch')
                checked[digest]=archive.getinfo('blobs/'+digest).file_size
            require(checked[digest]==row['bytes'],'Archive length mismatch')
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    root=ROOT.resolve(); state,_,baseline,_,_=preflight(root)
    certificate=read(baseline/'checks-passed.json')
    require(certificate['status']=='checks_passed_not_published','Latest snapshot not certified')
    require(sha(baseline/'catalog-bundle.json')==certificate['bundle_sha256'],'Latest bundle changed')
    require(sha(baseline/'staging.sqlite')==certificate['staging_sha256'],'Latest DB changed')
    paths=candidates(root,baseline)
    output=root/'.debug-artifacts/catalog-archives'/(baseline.name+'-history.zip')
    suffix=2
    while output.exists():
        output=output.with_name(baseline.name+f'-history-{suffix}.zip');suffix+=1
    print(json.dumps({'files':len(paths),'bytes':sum(p.stat().st_size for p in paths),'keep':state['baseline'],'archive':str(output),'apply':args.apply}),flush=True)
    if not args.apply or not paths:return
    rows=pack(root,paths,output)
    print('Archive content verified; checking unchanged source files before removal.',flush=True)
    require(read(root/'docs/catalog-state.json')==state,'Checkpoint changed during archive')
    preflight(root)
    require(candidates(root,baseline)==paths,'Archive file set changed')
    for path,row in zip(paths,rows):require(sha(path)==row['sha256'],'Historical file changed')
    # No recursive removal: only individually validated, archived regular files.
    directories=set()
    for path in paths:
        parent=path.parent
        while parent != root/'.debug-artifacts':
            directories.add(parent);parent=parent.parent
        path.unlink()
    for directory in sorted(directories,key=lambda p:len(p.parts),reverse=True):
        if not any(directory.iterdir()):directory.rmdir()
    preflight(root)
    print(json.dumps({'archived_files':len(rows),'archive_bytes':output.stat().st_size,'freed_bytes':sum(r['bytes'] for r in rows)-output.stat().st_size,'latest_preserved':True}),flush=True)


if __name__=='__main__':main()
