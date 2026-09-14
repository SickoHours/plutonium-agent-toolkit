"""Offline composition test-plan loading and deterministic stitching."""
import copy
import hashlib
from itertools import combinations
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
    declaration_index={m['id']:index for index,m in enumerate(modules)}
    for mid in resolved['order']:
        m=by_id[mid];field=f"/modules/{declaration_index[mid]}/tests"
        if not m.get('tests'):raise Failure(INPUT_MISSING,'Member has no test contract',field=field)
        try:c=tc.load_contract(m['directory'],m)
        except Failure as exc:
            exc.details['field']=f"/modules/{declaration_index[mid]}"+exc.details.get('field','/tests');raise
        contract_path=job.input(m['directory']/m['tests'])
        if job.inputs[str(contract_path)]!=c['sha256']:
            raise Failure('input_changed','Contract changed while loading',field=field)
        if composition['map'] not in c['maps']:raise Failure(INPUT_INVALID,'Member contract does not cover the composition map',field=field+'/maps/'+composition['map'])
        contracts[mid]=c
        members.append({'id':mid,'directory':str(m['directory']),'declaration_sha256':job.inputs[str(m['declaration'])],'provides':m['provides'],'tests':m['tests']})
    return dict(name=composition['name'],base=composition['base'],map=composition['map'],order=resolved['order'],modules=members,mode=args.mode),contracts,decisions

def stitch(plan, contracts, decisions):
    """Merge in dependency order without reading files or executing actions."""
    decisions={r['collision'].casefold():r for r in decisions} if isinstance(decisions,list) else {k.casefold():v for k,v in decisions.items()}
    result={'schema_version':1,'protocol':'pat.test-plan/1','composition':plan['name'],'base':plan['base'],
            'map':plan['map'],'mode':plan.get('mode','human'),'members':[],'preconditions':[],
            'phases':[],'human_steps':[],'conflicts':[],'not_covered':[],'excluded_steps':[]}
    members={m['id']:m for m in plan['modules']};member_steps={};steps=[];seen=set();soak=0
    for index,mid in enumerate(plan['order']):
        if mid not in contracts:raise Failure(INPUT_MISSING,'Member has no test contract',field=f'/modules/{index}/tests')
        c=contracts[mid]
        if plan['map'] not in c['maps']:raise Failure(INPUT_INVALID,'Contract does not cover map',field=f'/modules/{index}/tests/maps/'+plan['map'])
        digest=c.get('sha256') or hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        result['members'].append({'id':mid,'contract_sha256':digest,**{k:members[mid][k] for k in ('directory','tests','declaration_sha256') if k in members[mid]}})
        for pre in c['maps'][plan['map']]['preconditions']:
            key=(pre['verb'],pre.get('arg',''))
            if key not in seen:
                result['preconditions'].append(copy.deepcopy(pre));seen.add(key)
            else:
                existing=next(p for p in result['preconditions'] if (p['verb'],p.get('arg',''))==key)
                if existing.get('actor','agent')!=pre.get('actor','agent'):
                    raise Failure(INPUT_INVALID,'Duplicate preconditions disagree about actor',field='/preconditions')
        for s in c['steps']:
            s=copy.deepcopy(s);s['id']=mid+'/'+s['id']
            member_steps.setdefault(mid,[]).append(s)
            if s['actor']=='human' or s['verifier']=='human':result['human_steps'].append(s)
            else:steps.append(s)
        for item in c['not_covered']:
            if item not in result['not_covered']:result['not_covered'].append(item)
        soak=max(soak,c['soak']['rounds'])
    if result['mode']=='background':
        for i,pre in enumerate(result['preconditions']):
            if pre.get('actor','agent')=='human':raise Failure(INPUT_INVALID,'Background plan requires automated preconditions',field=f'/preconditions/{i}/actor')
    equals={}
    for s in steps:
        ch=s.get('check',{})
        if ch.get('source')=='harness' and 'equals' in ch:equals.setdefault(ch['key'],[]).append(s)
    for key,group in sorted(equals.items()):
        values={json.dumps(s['check']['equals'],sort_keys=True) for s in group}
        owners=sorted({s['id'].split('/')[0] for s in group})
        if len(values)<2 or len(owners)<2:continue
        collision='test:'+key;decision=decisions.get(collision.casefold())
        resolved=bool(decision and decision.get('owner') in owners and decision.get('reason'))
        result['conflicts'].append({'collision':collision,'modules':owners,'resolution':'recorded decision' if resolved else 'undecided',**({'owner':decision['owner'],'reason':decision['reason']} if resolved else {})})
        if resolved:result['excluded_steps'] += [s['id'] for s in group if s['id'].split('/')[0]!=decision['owner']]
    if any(c['resolution']=='undecided' for c in result['conflicts']):
        raise Failure(INPUT_INVALID,'Conflicting member checks require an explicit owner',conflicts=result['conflicts'],field='/conflicts')
    steps=[s for s in steps if s['id'] not in result['excluded_steps']]
    excluded=set(result['excluded_steps'])
    # A pair step must exercise its provider: pick the first surviving step with an action, whether
    # the actor is an agent or a human. A check-only step cannot stand in for a provider.
    first={mid:next((s for s in member_steps.get(mid,()) if s['id'] not in excluded and s.get('action')),None) for mid in plan['order']}
    pairs=[]
    kinds={'gobblegums','perks','powerups','weapons'}
    for a,b in combinations(plan['order'],2):
        if not (set(members[a]['provides']) & set(members[b]['provides']) & kinds) or not first[a] or not first[b]:continue
        # b then a observes a after b; a then b observes b after a. Each action is explicit.
        for target,other in ((a,b),(b,a)):
            for prefix,mid in (('setup',other),('check',target)):
                s=copy.deepcopy(first[mid]);s['id']=f'pair/{a}+{b}/{target}/{prefix}/'+s['id'];pairs.append(s)
    error={'source':'log','absent':'script error|Unresolved external|out of space'}
    soak_steps=[]
    if soak:
        soak_steps=[{'id':'soak','actor':'human','verifier':'agent','prompt':f'Advance {soak} additional rounds, then verify the log.',
                     'action':{'verb':'round_set','arg':'+'+str(soak)},'check':error}]
        if result['mode']=='background':raise Failure(INPUT_INVALID,'Background soak needs a test probe',field='/phases/3/steps/0/actor')
    result['phases']=[{'name':'load','steps':[{'id':'load-clean','actor':'agent','verifier':'agent','action':{'verb':'check_load'},'check':error}]},
                      {'name':'members','steps':steps},{'name':'interactions','steps':pairs},{'name':'soak','steps':soak_steps}]
    for sid in result['excluded_steps']:result['not_covered'].append('Owner decision excluded check/action '+sid)
    return result

def execute(args,job):
    plan,contracts,decisions=load(args,job)
    result=stitch(plan,contracts,decisions)
    (job.root/'test-plan.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return {'test_plan':'test-plan.json','composition':result['composition'],'members':len(result['members']),
            'steps':sum(len(p['steps']) for p in result['phases']),'human_steps':len(result['human_steps']),
            'verification':'Contracts stitched offline; no game action, capture or player acceptance'}
