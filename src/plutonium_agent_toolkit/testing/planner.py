"""Offline composition test-plan loading and deterministic stitching."""
import os
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

def scoped_decisions(composition,modules):
    """Pair each recipe decision with the sorted ids of the composition that recorded it.

    Walks the loaded composition tree in the same order ``flatten`` emits modules, so a nested
    recipe's decision can only govern its own members and never an outer collision. The scope is
    planner-local: it is not written back into the schema-closed composition decision."""
    cursor=0;rows=[]
    def walk(node):
        nonlocal cursor
        ids=[];children=[]
        for member in node['members']:
            inner=member.get('composition')
            if inner is None:ids.append(modules[cursor]['id']);cursor+=1
            else:
                inner_rows,inner_ids=walk(inner);children+=inner_rows;ids+=inner_ids
        scope=sorted(set(ids))
        return [dict(row,scope=scope) for row in node['decisions']]+children,ids
    rows,_=walk(composition)
    return rows

def load(args,job):
    path=Path(args.composition)
    if path.is_dir():path=path/'composition.json'
    composition=comp.load_composition(path,job)
    modules,loads,_,header=comp.flatten(composition,job)
    decisions=scoped_decisions(composition,modules)
    probe=prepare_probe(composition,modules,job);probe_active=probe['active']
    for index,m in enumerate(modules):
        if m['game']!=composition['game']:
            raise Failure(INPUT_INVALID,'Member targets a different game',field=f"/modules/{index}/game")
    resolved=comp.resolve(composition,modules)
    members=[];contracts={}
    by_id={m['id']:m for m in modules}
    declaration_index={m['id']:index for index,m in enumerate(modules)}
    for mid in resolved['order']:
        m=by_id[mid];field=f"/modules/{declaration_index[mid]}/tests"
        if not m.get('tests'):raise Failure(INPUT_MISSING,'Member has no test contract',field=field)
        try:c=tc.load_contract(m['directory'],m,probe=probe_active)
        except Failure as exc:
            exc.details['field']=f"/modules/{declaration_index[mid]}"+exc.details.get('field','/tests');raise
        contract_path=job.input(m['directory']/m['tests'])
        if job.inputs[str(contract_path)]!=c['sha256']:
            raise Failure('input_changed','Contract changed while loading',field=field)
        if composition['map'] not in c['maps']:raise Failure(INPUT_INVALID,'Member contract does not cover the composition map',field=field+'/maps/'+composition['map'])
        contracts[mid]=c
        members.append({'id':mid,'directory':str(m['directory']),'declaration_sha256':job.inputs[str(m['declaration'])],'provides':m['provides'],'tests':m['tests']})
    return dict(name=composition['name'],base=composition['base'],map=composition['map'],order=resolved['order'],modules=members,mode=args.mode,
                probe=probe_active,probe_module=(str(probe['added']['directory']) if probe['added'] else None),source=str(composition['source'])),contracts,decisions

def stitch(plan, contracts, decisions):
    """Merge in dependency order without reading files or executing actions."""
    decision_rows=([dict(row) for row in decisions] if isinstance(decisions,list)
                   else [dict(row,collision=row.get('collision',key)) for key,row in decisions.items()])
    result={'schema_version':1,'protocol':'pat.test-plan/1','composition':plan['name'],'base':plan['base'],
            'map':plan['map'],'mode':plan.get('mode','human'),'members':[],'preconditions':[],
            'phases':[],'human_steps':[],'conflicts':[],'not_covered':[],'excluded_steps':[],'probe':plan.get('probe',False)}
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
    for s in steps+result['human_steps']:
        ch=s.get('check',{})
        if ch.get('source')=='harness' and 'equals' in ch:equals.setdefault(ch['key'].casefold(),[]).append(s)
    for key,group in sorted(equals.items()):
        values={json.dumps(s['check']['equals'],sort_keys=True) for s in group}
        owners=sorted({s['id'].split('/')[0] for s in group})
        if len(values)<2 or len(owners)<2:continue
        collision='test:'+key
        decision=next((d for d in reversed(decision_rows)
                       if d['collision'].casefold()==collision.casefold() and d.get('owner') in owners and d.get('reason')
                       and (d.get('scope') is None or set(owners)<=set(d['scope']))),None)
        resolved=bool(decision)
        result['conflicts'].append({'collision':collision,'modules':owners,'resolution':'recorded decision' if resolved else 'undecided',**({'owner':decision['owner'],'reason':decision['reason']} if resolved else {})})
        if resolved:result['excluded_steps'] += [s['id'] for s in group if s['id'].split('/')[0]!=decision['owner']]
    if any(c['resolution']=='undecided' for c in result['conflicts']):
        raise Failure(INPUT_INVALID,'Conflicting member checks require an explicit owner',conflicts=result['conflicts'],field='/conflicts')
    steps=[s for s in steps if s['id'] not in result['excluded_steps']]
    result['human_steps']=[s for s in result['human_steps'] if s['id'] not in result['excluded_steps']]
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
        soak_steps=[{'id':'soak','actor':'agent' if plan.get('probe') else 'human','verifier':'agent','prompt':f'Advance {soak} additional rounds, then verify the log.',
                     'action':{'verb':'round_set','arg':'+'+str(soak)},'check':error}]
        if result['mode']=='background' and not plan.get('probe'):raise Failure(INPUT_INVALID,'Background soak needs a test probe',field='/phases/3/steps/0/actor')
    result['phases']=[{'name':'load','steps':[{'id':'load-clean','actor':'agent','verifier':'agent','action':{'verb':'check_load'},'check':error}]},
                      {'name':'members','steps':steps},{'name':'interactions','steps':pairs},{'name':'soak','steps':soak_steps}]
    for sid in result['excluded_steps']:result['not_covered'].append('Owner decision excluded check/action '+sid)
    return result

def execute(args,job):
    plan,contracts,decisions=load(args,job)
    result=stitch(plan,contracts,decisions)
    if plan.get('probe'):
        emit_composition(plan,job)
    (job.root/'test-plan.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return {'test_plan':'test-plan.json','composition':result['composition'],'members':len(result['members']),
            'steps':sum(len(p['steps']) for p in result['phases']),'human_steps':len(result['human_steps']),
            'verification':'Contracts stitched offline; no game action, capture or player acceptance'}


def prepare_probe(composition,modules,job):
    """Add a declared local test probe before both test planning and package building.

    Returns ``{"active": bool, "added": declaration or None}`` so the caller can tell whether the
    probe was newly admitted and must be written into an emitted composition."""
    needed=False
    for i,m in enumerate(modules):
        if not m.get('tests'):continue
        # Validate with probe scope to discover the requested capability; scope is then admitted below.
        try:contract=tc.load_contract(m['directory'],m,probe=True)
        except Failure as exc:
            # Keep the declaration-order index the planner loop (and the module routes) report.
            exc.details['field']=f"/modules/{i}"+exc.details.get('field','/tests');raise
        path=job.input(m['directory']/m['tests'])
        if job.inputs[str(path)]!=contract['sha256']:raise Failure('input_changed','Probe contract changed during admission')
        for row in [p for map_row in contract['maps'].values() for p in map_row.get('preconditions',[])]+contract['steps']:
            a=row.get('action',row)
            if a.get('verb') in tc.PROBE_VERBS and row.get('actor','agent')=='agent':needed=True
    existing=next((m for m in modules if m['id']=='test_probe'),None)
    if needed or existing:
        if not composition['name'].endswith(('_test','_probe')):raise Failure(INPUT_INVALID,'Test probe is forbidden in release profiles',field='/modules')
        added=None
        if not existing:
            candidates={m['directory'].parent/'test_probe' for m in modules}
            candidates.add(composition['source'].parent.parent.parent/'modules/test_probe')
            found=sorted({p.resolve() for p in candidates if (p/'module.json').is_file()})
            if len(found)!=1:raise Failure(INPUT_MISSING,'Provide exactly one sibling test_probe module',field='/modules/test_probe')
            existing=comp.load_declaration(found[0],job);modules.append(existing);added=existing
            if existing.get('game')!=composition['game'] or composition['base'] not in existing.get('bases',()) \
                    or ('*' not in existing.get('maps',()) and composition['map'] not in existing.get('maps',())):
                raise Failure(INPUT_INVALID,'Test probe does not cover this composition game, base and map',field='/modules/test_probe')
        if existing['id']!='test_probe' or 'test-only' not in existing['tags']:raise Failure(INPUT_INVALID,'Probe declaration must be test-only',field='/modules/test_probe')
        return {'active':True,'added':added}
    return {'active':False,'added':None}

def _relative_posix(path,root):
    return str(os.path.relpath(path,root)).replace('\\','/')

def emit_composition(plan,job):
    """Copy the source recipe into the job, keeping its nested members intact.

    The flattened member list would drop each member's role and pinned reference and detach a
    nested recipe's decisions; rewriting the top-level paths relative to the job keeps every
    nested composition, its decisions and its scope exactly as authored. A newly admitted probe
    is appended once as a top-level member."""
    source=Path(plan['source']);data=json.loads(source.read_text(encoding='utf-8'))
    modules=[]
    for entry in data.get('modules',[]):
        row={'path':entry} if isinstance(entry,str) else dict(entry)
        row['path']=_relative_posix((source.parent/row['path']).resolve(),job.root)
        modules.append(row if isinstance(entry,dict) else row['path'])
    data['modules']=modules
    for key in ('loads','base_owned'):
        data[key]=[_relative_posix((source.parent/p).resolve(),job.root) for p in data.get(key,[])]
    added=plan.get('probe_module')
    if added:data['modules'].append(_relative_posix(Path(added).resolve(),job.root))
    (job.root/'composition.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
