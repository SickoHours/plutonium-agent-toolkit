"""Measured pool floors and compiler diagnostics; unknown coverage stays explicit."""
import re
from types import SimpleNamespace
from ..core.jobs import Job
from ..core.errors import Failure
from . import knowledge, scripts

def get(data,key):
    for part in key.split('.'):
        if not isinstance(data,dict):return None
        data=data.get(part)
    return data

def pool_checks(plan,limits,occupancy):
    rows=[]
    for limit in limits:
        source=limit.get('count_source');bound=limit.get('bound');base=get(occupancy,source) if source else None
        contribution=None;names=set()
        if source=='assets.soundbank':
            for m in plan['modules']:names.update(m.get('provides',{}).get('soundbanks',[]))
            contribution=len(names)
        elif source=='clientfield_bits.actor.server':contribution=sum(m.get('resource_contract',{}).get('network_fields',0) for m in plan['modules'])
        elif source=='projectile_fx_distinct' and not any(m.get('provides',{}).get('weapons') for m in plan['modules']):contribution=0
        total=base+contribution if type(base) in (int,float) and contribution is not None else None
        outcome='not_counted';detail='No complete counting source/bound for this composition'
        if total is not None and type(bound) in (int,float):
            outcome='failed' if total>bound else 'passed'
            detail=f'Measured map count {base} + declared contribution {contribution} = {total}; observed bound {bound}'
            if outcome=='passed' and (occupancy.get('incomplete') or source=='assets.soundbank'):
                outcome='not_counted';detail+='; occupancy/bank listing is a floor, not a complete runtime count'
        rows.append({'id':'pool:'+limit['id'],'outcome':outcome,'detail':detail,'count':total,'bound':bound})
    return rows

def script_result(name,text,passed):
    errors=re.findall(r'(?im)^.*(?:unresolved external|\berror\b|\bfatal\b).*$',text)
    return {'id':'symbols:'+name,'outcome':'failed' if errors or not passed else 'not_counted',
            'detail':('; '.join(errors)[:800] or ('gsc check failed' if not passed else 'gsc check passed syntax/compilation; runtime external resolution is not proven'))}

def evaluate(plan):
    limits=knowledge.load('engine-limits.json')['rows'];maps=knowledge.load('occupancy.json')['maps']
    occupancy=maps.get(plan['map'],{})
    if occupancy.get('foundation')!=plan['base']:occupancy={}
    return pool_checks(plan,limits,occupancy)

def check_scripts(compiled,args,job,game):
    rows=[]
    for index,(source,target,instance) in enumerate(compiled):
        job.check_deadline()
        remaining=max(1,int(job.deadline-__import__('time').monotonic()))
        child=Job(job.root/'checks'/f'script-{index:03d}','gsc check',[],timeout=remaining);child.deadline=job.deadline
        try:
            result=scripts.execute(SimpleNamespace(input=str(source),instance=instance,game=game,action='check',includes=str(source.parent),timeout=min(args.timeout,remaining)),child)
            child.finish(result);text='';passed=True
        except Failure as error:
            child.fail(error);passed=False;text=error.message+' '+str(error.details.get('first_error',''))
            if error.details.get('log'):
                log=child.root/error.details['log']
                if log.is_file():text=log.read_bytes()[:4*1024**2].decode(errors='replace')
        rows.append(script_result(target.as_posix(),text,passed))
    return rows
