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

CALL=re.compile(r'(?<![\w\\:.\[])([a-z_][a-z0-9_]*)\s*\(')
DEF=re.compile(r'^([a-z_][a-z0-9_]*)\s*\([^)]*\)\s*\{',re.M)
INCLUDE=re.compile(r'^#include\s+([^;]+);',re.M)
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

def external_symbols(name,text):
    """Unqualified calls resolved against the stock export table: failed when the call needs an
    #include the script lacks or names a builtin witnessed only on the other VM; passed when every
    known call resolves on this script's VM; not_counted when a call is neither a local function,
    a builtin witnessed on this VM, nor a stock export (the engine decides), including when the
    target suffix does not name a VM."""
    exports=knowledge.load('stock-exports.json')['exports']
    text=mask_noncode(text)
    vm=_script_vm(name)
    includes={inc.strip().replace(chr(92),'/').lower() for inc in INCLUDE.findall(text)}
    defined=set(DEF.findall(text));missing=[];wrong=[];unknown=[]
    for call in sorted(set(CALL.findall(text))-defined-KEYWORDS):
        owners=[path for path,names in exports.items() if call in names]
        if owners:
            if not any(o in includes for o in owners):missing.append(f'{call} ({" or ".join(owners)})')
            continue
        if vm is None:unknown.append(call);continue
        witness=knowledge.builtin(call,vm)
        if witness.get('verdict')=='builtin':continue
        if witness.get('also_on'):wrong.append(f'{call} (witnessed on {", ".join(witness["also_on"])} only)')
        else:unknown.append(call)
    if missing or wrong:
        detail=[]
        if missing:detail.append('Unqualified stock calls without #include: '+'; '.join(missing))
        if wrong:detail.append(f'Calls not available on the {vm} script VM: '+'; '.join(wrong))
        return [{'id':'externals:'+name,'outcome':'failed','detail':'; '.join(detail)[:800]}]
    if unknown:return [{'id':'externals:'+name,'outcome':'not_counted','detail':'Calls not in the stock export table or builtin witness list: '+', '.join(unknown)[:400]}]
    return [{'id':'externals:'+name,'outcome':'passed','detail':'Every unqualified call is local, a witnessed builtin, or covered by an #include'}]

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
