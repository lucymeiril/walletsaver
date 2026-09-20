"""Create a bounded delegation job from existing review packets, never SQLite."""
import argparse
import sys
from catalog_review import ROOT, named, read, sha, write_new


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    parser.add_argument('--packet',action='append',required=True)
    parser.add_argument('--leaf-prefix',action='append',required=True)
    parser.add_argument('--constraint',action='append',default=[])
    args=parser.parse_args()
    sys.path[:0]=[str(ROOT/'packages/shared'),str(ROOT/'packages/db-admin/backend')]
    from services.initial_taxonomy import LEAVES
    leaves={x.id:' > '.join(x.path) for x in LEAVES if any(x.id.startswith(p) for p in args.leaf_prefix)}
    if not leaves: raise ValueError('No matching leaves')
    if len(set(args.packet)) != len(args.packet): raise ValueError('Duplicate packet')
    state=read(ROOT/'docs/catalog-state.json')
    packets=[]
    for name in args.packet:
        path=named(ROOT,name,'.debug-artifacts/review-packets')
        packet=read(path)
        if (packet['baseline'],packet['source_file_sha256']) != (state['baseline'],state['source_file_sha256']):
            raise ValueError('Stale packet')
        packets.append(dict(name=name,path=path.relative_to(ROOT).as_posix(),sha256=sha(path),
                            output=f'.debug-artifacts/review-proposals/{name}.json',leaves=leaves))
    output=named(ROOT,args.name,'.debug-artifacts/review-jobs')
    write_new(output,dict(packets=packets,constraints=args.constraint))
    print(output.relative_to(ROOT).as_posix())


if __name__=='__main__': main()
