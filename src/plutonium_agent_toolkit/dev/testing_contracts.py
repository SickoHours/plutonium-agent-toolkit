"""Closed per-module test contracts. Validation executes no game commands."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re
from pathlib import Path
from ..core.errors import Failure, INPUT_INVALID, INPUT_MISSING
from .compositions import _fields, _pointer, _read_inspection, _recipe_path, MAP

AGENT_VERBS = frozenset(('weapon_give','weapon_equip','weapon_upgrade','weapon_remove','gum','gobblegum','recipe','mark','wait_s','fast_restart','check_load'))
PROBE_VERBS = frozenset(('power_on','doors_open','points_set','round_set','perk_give','god'))
VOCABULARY = AGENT_VERBS | PROBE_VERBS
ARG = re.compile(r'[A-Za-z0-9_./-]{0,64}\Z')
TOKEN = re.compile(r'[A-Za-z0-9_.-]{1,64}\Z')
KEY = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z')

def fail(field, message):
    raise Failure(INPUT_INVALID, message, field=field)

def text(value, field, maximum=2048):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum: fail(field,'Expected bounded non-empty text')

def rows(value, field, maximum):
    if not isinstance(value,list) or len(value)>maximum: fail(field,f'Expected at most {maximum} entries')

def role(value, field):
    if value not in ('agent','human'): fail(field,'Expected agent or human')

def number(value, field, maximum):
    if type(value) not in (int,float): fail(field,'Expected a bounded non-negative number')
    if type(value) is float and not math.isfinite(value): fail(field,'Expected a bounded non-negative number')
    if not 0<=value<=maximum: fail(field,'Expected a bounded non-negative number')

def action(value, field, actor, probe, precondition=False):
    allowed={'verb','arg'} | ({'actor','prompt'} if precondition else set())
    _fields(value,allowed,{'verb'},'action',field)
    verb=value['verb']
    if not isinstance(verb,str) or verb not in VOCABULARY: fail(field+'/verb','Unknown test verb')
    if 'arg' in value and (not isinstance(value['arg'],str) or not (ARG.fullmatch(value['arg']) or verb=='round_set' and re.fullmatch(r'\+[0-9]{1,3}',value['arg']))): fail(field+'/arg','Expected safe argument of at most 64 characters')
    if verb in PROBE_VERBS and actor=='agent' and not probe: fail(field+'/actor' if precondition else field.rsplit('/',1)[0]+'/actor','Probe verbs require a human until a test probe is present')
    if precondition:
        role(actor,field+'/actor');value['actor']=actor
        if actor=='human': text(value.get('prompt'),field+'/prompt')
        elif 'prompt' in value: text(value['prompt'],field+'/prompt')
    if verb=='wait_s':
        try: n=float(value.get('arg',''))
        except ValueError: fail(field+'/arg','wait_s requires seconds')
        number(n,field+'/arg',300)

def check(value, field):
    if not isinstance(value,dict): fail(field,'Expected a check object')
    source=value.get('source')
    shapes={'log':({'absent','present'},set()),'harness':({'key','equals','min','max'},{'key'}),'dvar':({'name','equals'},{'name','equals'}),'screenshot':(set(),set())}
    if not isinstance(source,str) or source not in shapes: fail(field+'/source','Unknown check source')
    allowed,required=shapes[source];_fields(value,allowed|{'source'},required|{'source'},'check',field)
    if source=='log':
        if not (set(value)&{'absent','present'}): fail(field,'Log checks need absent or present')
        for key in ('absent','present'):
            if key in value:
                text(value[key],field+'/'+key,200)
                try: re.compile(value[key])
                except re.error: fail(field+'/'+key,'Invalid regular expression')
    if source=='harness':
        if not isinstance(value['key'],str) or len(value['key'])>200 or not KEY.fullmatch(value['key']): fail(field+'/key','Expected dotted reply key')
        if not set(value)&{'equals','min','max'}: fail(field,'Harness checks need equals, min or max')
        for key in ('min','max'):
            if key not in value: continue
            bound=value[key]
            if type(bound) not in (int,float): fail(field+'/'+key,'Expected finite number')
            try: finite=math.isfinite(bound)
            except OverflowError: finite=False
            if not finite: fail(field+'/'+key,'Expected finite number')
        if 'min' in value and 'max' in value and value['min']>value['max']: fail(field+'/max','Maximum precedes minimum')
    if source=='dvar' and (not isinstance(value['name'],str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',value['name'])): fail(field+'/name','Expected dvar identifier')
    if 'equals' in value and (type(value['equals']) not in (str,int,float,bool) or isinstance(value['equals'],str) and len(value['equals'])>200 or type(value['equals']) is float and not math.isfinite(value['equals'])): fail(field+'/equals','Expected bounded scalar')

def validate_contract(data, *, declaration, probe=False):
    try:
        data=copy.deepcopy(data)
    except RecursionError as exc:
        raise Failure(INPUT_INVALID,'Invalid test contract structure',field='/') from exc
    _fields(data,{'schema','module','maps','steps','soak','human_only','not_covered'},{'schema','module','maps','steps','soak','human_only','not_covered'},'test contract')
    if type(data['schema']) is not int or data['schema']!=1: fail('/schema','Expected schema 1')
    if data['module']!=declaration['id']: fail('/module','Contract module must match declaration')
    if not isinstance(data['maps'],dict) or not 1<=len(data['maps'])<=64: fail('/maps','Expected map preconditions')
    for mid, value in data['maps'].items():
        field='/maps'+_pointer(mid)
        if not MAP.fullmatch(mid) or ('*' not in declaration['maps'] and mid not in declaration['maps']): fail(field,'Map is outside declaration')
        _fields(value,{'preconditions'},{'preconditions'},'map',field)
        rows(value['preconditions'],field+'/preconditions',16)
        for i,p in enumerate(value['preconditions']):
            f=field+f'/preconditions/{i}'
            action(p,f,p.get('actor','agent') if isinstance(p,dict) else 'agent',probe,True)
    rows(data['steps'],'/steps',64);ids=set();human=[]
    for i,s in enumerate(data['steps']):
        f=f'/steps/{i}'
        _fields(s,{'id','actor','verifier','action','check','prompt','evidence'},{'id','actor','verifier'},'step',f)
        if not isinstance(s['id'],str) or not TOKEN.fullmatch(s['id']) or s['id'] in ids: fail(f+'/id','Expected unique step id')
        ids.add(s['id']);role(s['actor'],f+'/actor');role(s['verifier'],f+'/verifier')
        if s['actor']=='human' or s['verifier']=='human': text(s.get('prompt'),f+'/prompt')
        elif 'prompt' in s: text(s['prompt'],f+'/prompt')
        if s['verifier']=='human': human.append(s['id'])
        else:
            if 'check' not in s: fail(f+'/check','Agent verifier needs check')
        if 'check' in s: check(s['check'],f+'/check')
        if 'action' in s: action(s['action'],f+'/action',s['actor'],probe)
        if 'evidence' in s:
            e=s['evidence'];_fields(e,{'screenshot','clip_before_s','clip_after_s'},set(),'evidence',f+'/evidence')
            for k,v in e.items():
                if k=='screenshot':
                    if type(v) is not bool: fail(f+'/evidence/'+k,'Expected boolean')
                else: number(v,f+'/evidence/'+k,60)
    _fields(data['soak'],{'rounds'},{'rounds'},'soak','/soak')
    if type(data['soak']['rounds']) is not int or not 0<=data['soak']['rounds']<=10: fail('/soak/rounds','Expected 0–10 rounds')
    rows(data['human_only'],'/human_only',64)
    if not all(isinstance(x,str) for x in data['human_only']) or len(set(data['human_only']))!=len(data['human_only']) or set(data['human_only'])!=set(human): fail('/human_only','List every human verifier exactly once')
    rows(data['not_covered'],'/not_covered',64)
    for i,item in enumerate(data['not_covered']):text(item,f'/not_covered/{i}',400)
    return data

def requires_probe(contract):
    """Report whether any agent-actor action uses a probe verb; this enforces no composition policy."""
    for value in contract['maps'].values():
        for p in value['preconditions']:
            if p['verb'] in PROBE_VERBS and p.get('actor','agent')=='agent': return True
    return any(s.get('action',{}).get('verb') in PROBE_VERBS and s['actor']=='agent' for s in contract['steps'])

def load_contract(directory, declaration, *, probe=False):
    path=declaration.get('tests')
    if not path: raise Failure(INPUT_MISSING,'Declaration does not name a test contract',field='/tests')
    _recipe_path(path)
    target=Path(directory)/path
    try: inside=target.resolve().is_relative_to(Path(directory).resolve())
    except RuntimeError as exc: raise Failure(INPUT_INVALID,'Contract path contains a symlink cycle',field='/tests') from exc
    if not inside: fail('/tests','Contract leaves module directory')
    try: raw=_read_inspection(target)
    except Failure as exc:
        exc.details['field']='/tests';raise
    try: data=json.loads(raw)
    except (ValueError,RecursionError) as exc: raise Failure(INPUT_INVALID,'Invalid test contract JSON',field='/tests') from exc
    result=validate_contract(data,declaration=declaration,probe=probe)
    return dict(result,sha256=hashlib.sha256(raw).hexdigest())
