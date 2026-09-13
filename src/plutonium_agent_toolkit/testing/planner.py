"""Offline composition test-plan loading and deterministic stitching."""
from pathlib import Path
from types import SimpleNamespace
import json
from ..core.errors import Failure, INPUT_INVALID, INPUT_MISSING
from ..dev import compositions as comp, testing_contracts as tc

def add_parser(sub,common):
    p=sub.add_parser('test');actions=p.add_subparsers(dest='action',required=True)
    q=actions.add_parser('plan');q.add_argument('--composition',required=True);q.add_argument('--mode',choices=['background','human','away'],default='human');common(q)
    for name in ('start','status','cancel','report'):
        q=actions.add_parser(name);q.add_argument('rest',nargs='*');q.add_argument('--json',action='store_true')

def load(args,job):
    path=Path(args.composition)
    if path.is_dir():path=path/'composition.json'
    composition=comp.load_composition(path,job)
    modules,loads,decisions,header=comp.flatten(composition,job)
    resolved=comp.resolve(composition,modules)
    members=[];contracts={}
    by_id={m['id']:m for m in modules}
    for index,mid in enumerate(resolved['order']):
        m=by_id[mid];field=f'/modules/{index}/tests'
        if not m.get('tests'):raise Failure(INPUT_MISSING,'Member has no test contract',field=field)
        try:c=tc.load_contract(m['directory'],m)
        except Failure as exc:
            exc.details['field']=f'/modules/{index}'+exc.details.get('field','/tests');raise
        job.input(m['directory']/m['tests'])
        if composition['map'] not in c['maps']:raise Failure(INPUT_INVALID,'Member contract does not cover the composition map',field=field+'/maps/'+composition['map'])
        contracts[mid]=c
        members.append({'id':mid,'directory':str(m['directory']),'declaration_sha256':job.inputs[str(m['declaration'])],'provides':m['provides'],'tests':m['tests']})
    return dict(name=composition['name'],base=composition['base'],map=composition['map'],order=resolved['order'],modules=members,mode=args.mode),contracts,decisions

def execute(args,job):
    plan,contracts,decisions=load(args,job)
    # The loader is independently useful; stitching is the next implementation task.
    raise Failure(INPUT_INVALID,'Contracts loaded; stitching is not implemented yet',field='/phases')
