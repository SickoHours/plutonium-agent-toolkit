"""Measured pool floors and compiler diagnostics; unknown coverage stays explicit."""
import re
from types import SimpleNamespace
from pathlib import Path
from ..core.jobs import Job
from ..core.errors import Failure
from . import knowledge, scripts

def get(data,key):
    for part in key.split('.'):
        if not isinstance(data,dict):return None
        data=data.get(part)
    return data

IPAK_STARTUP_NAMES={'patch_zm','base','zm','en_base','mp','dlczm0_load_zm','dlczm0','dlczm1','dlczm2','dlczm3','dlczm4','dlc1'}

def footprint(plan):
    """Per member, what it adds to each counted pool: rawfiles (recipe scripts and delivered
    rawfile assets, or seed rawfile roots), soundbanks (provided bank names), image-bank reads
    (none per member; the composition header carries them). The generated entry counts as one
    rawfile under the pack itself."""
    rows={}
    by_id={m.get('id',f'module-{i}'):m for i,m in enumerate(plan.get('modules',[]))}
    for mid,m in by_id.items():
        rows[mid]={'rawfiles':0,'soundbanks':sorted(set(m.get('provides',{}).get('soundbanks',[]))),'scripts':0}
    for row in plan.get('scripts',[]):
        owner=row.get('module')
        if owner in rows:rows[owner]['rawfiles']+=1;rows[owner]['scripts']+=1
        else:rows.setdefault('(pack)',{'rawfiles':0,'soundbanks':[],'scripts':0});rows['(pack)']['rawfiles']+=1;rows['(pack)']['scripts']+=1
    for row in plan.get('assets',[]):
        owner=row.get('module')
        if row.get('type')=='rawfile' and row.get('deliver',True) is not False and owner in rows:rows[owner]['rawfiles']+=1
    for seed in plan.get('seeds',[]):
        mid=seed['id']
        if mid in rows:rows[mid]['rawfiles']+=sum(1 for r in seed.get('roots',[]) if r.startswith('rawfile,'))
    return rows

def pool_checks(plan,limits,occupancy):
    rows=[];foot=footprint(plan)
    for limit in limits:
        source=limit.get('count_source');bound=limit.get('bound');base=get(occupancy,source) if source else None
        contribution=None;names=set();top=[]
        if source=='assets.soundbank':
            for m in plan['modules']:names.update(m.get('provides',{}).get('soundbanks',[]))
            contribution=len(names)
            top=sorted(((len(f['soundbanks']),mid) for mid,f in foot.items() if f['soundbanks']),reverse=True)
        elif source=='assets.rawfile':
            contribution=sum(f['rawfiles'] for f in foot.values())
            top=sorted(((f['rawfiles'],mid) for mid,f in foot.items() if f['rawfiles']),reverse=True)
        elif source=='ipak_slots':
            reads=[]
            for line in plan.get('zone_header',[]):
                if line.startswith('>level.ipak_read,'):
                    name=line.split(',',1)[1].strip()
                    if name and name not in IPAK_STARTUP_NAMES and name not in reads:reads.append(name)
            contribution=len(reads);top=[(1,name) for name in reads]
        elif source=='clientfield_bits.actor.server':contribution=sum(m.get('resource_contract',{}).get('network_fields',0) for m in plan['modules'])
        elif source=='projectile_fx_distinct' and not any(m.get('provides',{}).get('weapons') for m in plan['modules']):contribution=0
        total=base+contribution if type(base) in (int,float) and contribution is not None else None
        outcome='not_counted';detail='No complete counting source/bound for this composition'
        if total is not None and type(bound) in (int,float):
            outcome='failed' if total>bound else 'passed'
            detail=f'Measured map count {base} + declared contribution {contribution} = {total}; observed bound {bound}'
            if outcome=='passed' and (occupancy.get('incomplete') or source=='assets.soundbank'):
                outcome='not_counted';detail+='; occupancy/bank listing is a floor, not a complete runtime count'
            if outcome=='failed' and top:
                detail+='; largest contributors: '+', '.join(f'{mid} ({n})' for n,mid in top[:5])
        row={'id':'pool:'+limit['id'],'outcome':outcome,'detail':detail,'count':total,'bound':bound}
        if contribution is not None:row['contribution']=contribution;row['base']=base
        if top:row['contributors']=[{'id':mid,'count':n} for n,mid in top[:16]]
        rows.append(row)
    return rows

def script_result(name,text,passed):
    errors=re.findall(r'(?im)^.*(?:unresolved external|\berror\b|\bfatal\b).*$',text)
    return {'id':'symbols:'+name,'outcome':'failed' if errors or not passed else 'not_counted',
            'detail':('; '.join(errors)[:800] or ('gsc check failed' if not passed else 'gsc check passed syntax/compilation; runtime external resolution is not proven'))}

CALL=re.compile(r'(?<![\w\\:.\[])([A-Za-z_][A-Za-z0-9_]*)\s*\(')
DEF=re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*\{',re.M)
INCLUDE=re.compile(r'^\s*#include\s+([^;]+);',re.M|re.I)
KEYWORDS=frozenset(('if','while','for','foreach','switch','return','wait','waittill','waittillmatch','endon','notify','thread','spawn','array','assert'))

def mask_noncode(text):
    """Blank comments and string literals, keeping every newline, so the line-anchored scans see
    only executable GSC. A quote inside a string is backslash-escaped; `//` or `/*` inside a
    string is text, not a comment."""
    output=list(text);i=0;size=len(text);state='code'
    while i<size:
        char=text[i]
        if state=='code':
            if char=='/' and i+1<size and text[i+1]=='/':output[i]=output[i+1]=' ';i+=2;state='line'
            elif char=='/' and i+1<size and text[i+1]=='*':output[i]=output[i+1]=' ';i+=2;state='block'
            elif char=='"':output[i]=' ';i+=1;state='string'
            else:i+=1
        elif state=='line':
            if char=='\n':state='code';i+=1
            else:output[i]=' ';i+=1
        elif state=='block':
            if char=='*' and i+1<size and text[i+1]=='/':output[i]=output[i+1]=' ';i+=2;state='code'
            else:
                if char!='\n':output[i]=' '
                i+=1
        else:
            if char=='\\' and i+1<size:
                if text[i]!='\n':output[i]=' '
                if text[i+1]!='\n':output[i+1]=' '
                i+=2
            elif char=='"':output[i]=' ';i+=1;state='code'
            else:
                if char!='\n':output[i]=' '
                i+=1
    return ''.join(output)

def _script_vm(name):
    """The script VM a target path belongs to; None when the suffix does not name one, which keeps
    the check conservative instead of passing."""
    lowered=name.lower()
    if lowered.endswith('.csc'):return 'client'
    if lowered.endswith('.gsc'):return 'server'
    return None

def external_symbols(name,text,game='t6'):
    """Unqualified calls resolved against the stock export table: failed when the call needs an
    #include the script lacks; passed when every known call resolves on this script's VM;
    not_counted when the title is not T6 (the tables are T6-only), when a call is neither a local
    function, a builtin witnessed on this VM, nor a stock export, or when the target suffix does
    not name a VM. A builtin witnessed only on the other VM stays not_counted, never passed: the
    witness table is an absence of evidence, not proof the other VM lacks the call."""
    if game != 't6':
        return [{'id':'externals:'+name,'outcome':'not_counted',
                 'detail':f'External stock and builtin witness data is T6-only; {game} calls are not judged'}]
    exports=knowledge.load('stock-exports.json')['exports']
    text=mask_noncode(text)
    vm=_script_vm(name)
    includes={inc.strip().replace(chr(92),'/').lower() for inc in INCLUDE.findall(text)}
    defined={match.lower() for match in DEF.findall(text)}
    calls={match.lower() for match in CALL.findall(text)}
    missing=[];unknown=[]
    for call in sorted(calls-defined-KEYWORDS):
        owners=[path for path,names in exports.items() if call in names]
        if owners:
            if not any(o in includes for o in owners):missing.append(f'{call} ({" or ".join(owners)})')
            continue
        if vm is None:unknown.append(call);continue
        witness=knowledge.builtin(call,vm)
        if witness.get('verdict')=='builtin':continue
        if witness.get('also_on'):unknown.append(f'{call} (witnessed on {", ".join(witness["also_on"])} only)')
        else:unknown.append(call)
    if missing:return [{'id':'externals:'+name,'outcome':'failed','detail':'Unqualified stock calls without #include: '+'; '.join(missing)[:800]}]
    if unknown:return [{'id':'externals:'+name,'outcome':'not_counted','detail':'No witness on this script VM (absence of evidence, not evidence of absence): '+', '.join(unknown)[:400]}]
    return [{'id':'externals:'+name,'outcome':'passed','detail':'Every unqualified call is local, a witnessed builtin, or covered by an #include'}]

# A composition names its base by profile prefix token; the occupancy table names the foundation.
# Without this map every pool check on a `b2` composition ran against empty occupancy and passed.
BASE_FOUNDATIONS={'stock':'stock','b1':'dlc5-beta1','b2':'dlc5-beta2'}

def foundation_of(base,root=None):
    if root is not None:
        from . import targets
        found=targets.foundation_for_base(Path(root),base)
        if found:return found
    return BASE_FOUNDATIONS.get(base,base)

INCLUDE_PATH=re.compile(r'^\s*#include\s+([^;]+);',re.M|re.I)
QUALIFIED=re.compile(r'([A-Za-z_][A-Za-z0-9_\\/]*[\\/][A-Za-z0-9_\\/]+)::[A-Za-z_]')

def map_script_externals(name,text,map_id,foundation,game='t6'):
    """Every script this source includes or calls with a qualified path must be carried by the zones
    the target map loads on this foundation. A path the map lacks is an unresolved external at load
    (`COM_ERROR ... Unresolved external`), which the compiler cannot see. not_counted when the map is
    not in the table or the title is not T6; the module's own targets in the same pack are not
    visible here, so only stock-looking paths (maps/, clientscripts/, common_scripts/, codescripts/)
    are judged."""
    if game!='t6':
        return [{'id':'map-scripts:'+name,'outcome':'not_counted','detail':'Per-map script tables are T6-only'}]
    table=knowledge.load('map-scripts.json')['maps'].get(map_id)
    if not table or table.get('foundation')!=foundation:
        return [{'id':'map-scripts:'+name,'outcome':'not_counted','detail':f'No script table for {map_id} on {foundation}'}]
    carried=set(table['scripts'])
    vm=_script_vm(name);suffix='.csc' if vm=='client' else '.gsc'
    masked=mask_noncode(text)
    wanted=set()
    for inc in INCLUDE_PATH.findall(masked):wanted.add(inc.strip().replace(chr(92),'/').lower())
    for path in QUALIFIED.findall(masked):wanted.add(path.replace(chr(92),'/').lower())
    judged={p for p in wanted if p.startswith(('maps/','clientscripts/','common_scripts/','codescripts/'))}
    missing=sorted(p for p in judged if p+suffix not in carried and p+'.gsc' not in carried and p+'.csc' not in carried)
    if missing:
        return [{'id':'map-scripts:'+name,'outcome':'failed','detail':f'{map_id} on {foundation} does not carry: '+', '.join(missing)[:800],'missing':missing[:32]}]
    if judged:
        return [{'id':'map-scripts:'+name,'outcome':'passed','detail':f'Every included or qualified stock script path is carried by {map_id} on {foundation}'}]
    return [{'id':'map-scripts:'+name,'outcome':'not_counted','detail':'No stock script path is included or called'}]

def evaluate(plan,root=None):
    limits=knowledge.load('engine-limits.json')['rows'];maps=knowledge.load('occupancy.json')['maps']
    occupancy=maps.get(plan['map'],{})
    if occupancy.get('foundation')!=foundation_of(plan['base'],root):occupancy={}
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
