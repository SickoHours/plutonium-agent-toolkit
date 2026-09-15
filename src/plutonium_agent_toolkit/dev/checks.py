"""Measured pool floors and compiler diagnostics; unknown coverage stays explicit."""
import json
import re
from types import SimpleNamespace
from pathlib import Path
from ..core.jobs import Job
from ..core.errors import Failure, INPUT_INVALID
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
    for seed in plan.get('seeds',[])+plan.get('adapters',[]):
        mid=seed['id']
        if mid in rows:rows[mid]['rawfiles']+=sum(1 for r in seed.get('roots',[]) if r.startswith('rawfile,'))
    return rows

def pool_checks(plan,limits,occupancy):
    rows=[];foot=footprint(plan)
    for limit in limits:
        source=limit.get('count_source');bound=limit.get('bound');base=get(occupancy,source) if source else None
        contribution=None;names=set();top=[];skipped=[]
        if source=='assets.soundbank':
            # The listing counts one row per `.all` bank; the engine also opens that bank's
            # localized companion (`<name>.<lang>`), which no listing shows. Every base bank is a
            # `.all`, so the measured count and each member's bank are counted twice: the floor
            # plus one companion per bank is the bound the pack is held to (docs/knowledge/engine-limits.md).
            for m in plan['modules']:names.update(m.get('provides',{}).get('soundbanks',[]))
            companions=sum(1 for n in names if n.endswith('.all'))
            contribution=len(names)+companions
            if type(base) in (int,float):base=base*2
            top=sorted(((len(f['soundbanks'])+sum(1 for n in f['soundbanks'] if n.endswith('.all')),mid) for mid,f in foot.items() if f['soundbanks']),reverse=True)
        elif source=='assets.rawfile':
            contribution=sum(f['rawfiles'] for f in foot.values())
            top=sorted(((f['rawfiles'],mid) for mid,f in foot.items() if f['rawfiles']),reverse=True)
        elif source=='ipak_slots':
            reads=[]
            for line in plan.get('zone_header',[]):
                if line.startswith('>level.ipak_read,'):
                    name=line.split(',',1)[1].strip()
                    if name and name not in IPAK_STARTUP_NAMES and name not in reads:reads.append(name)
            # Optional evidence: the bank names the client's `zone/all` folder actually carries for
            # this map. The engine skips a read naming a bank the folder lacks (`ipak file not
            # found`) and that read costs no slot, so counting it is pessimistic. Absent the
            # evidence every read counts, which is the conservative answer and the old behaviour.
            present=occupancy.get('banks_present')
            if isinstance(present,list):
                known={str(n) for n in present}
                skipped=[n for n in reads if n not in known];reads=[n for n in reads if n in known]
            contribution=len(reads);top=[(1,name) for name in reads]
        elif source=='clientfield_bits.actor.server':contribution=sum(m.get('resource_contract',{}).get('network_fields',0) for m in plan['modules'])
        elif source=='projectile_fx_distinct' and not any(m.get('provides',{}).get('weapons') for m in plan['modules']):contribution=0
        total=base+contribution if type(base) in (int,float) and contribution is not None else None
        outcome='not_counted';detail='No complete counting source/bound for this composition'
        if total is not None and type(bound) in (int,float):
            outcome='failed' if total>bound else 'passed'
            detail=f'Measured map count {base} + declared contribution {contribution} = {total}; observed bound {bound}'
            if source=='assets.soundbank':
                detail=f'Measured map banks {base//2 if type(base) is int else base} plus their localized companions = {base}; declared banks {len(names)} plus companions {companions} = {contribution}; total {total}; observed bound {bound}'
                if outcome=='failed':detail+='; banks: '+', '.join(sorted(names))[:600]
            if outcome=='passed' and occupancy.get('incomplete'):
                outcome='not_counted';detail+='; occupancy is a floor, not a complete runtime count'
            if outcome=='failed' and top:
                detail+='; largest contributors: '+', '.join(f'{mid} ({n})' for n,mid in top[:5])
        row={'id':'pool:'+limit['id'],'outcome':outcome,'detail':detail,'count':total,'bound':bound}
        if contribution is not None:row['contribution']=contribution;row['base']=base
        if source=='assets.soundbank' and names:row['banks']=sorted(names)
        if top:row['contributors']=[{'id':mid,'count':n} for n,mid in top[:16]]
        if skipped:
            row['not_counted_reads']=skipped
            row['detail']+=f'; {len(skipped)} header read(s) name no bank the recorded zone folder carries and cost no slot: '+', '.join(skipped)[:300]
        rows.append(row)
        for name in skipped:
            rows.append({'id':'pool:'+limit['id']+':'+name,'outcome':'not_counted',
                         'detail':f'The zone header reads {name}, which the recorded client zone folder does not carry: '
                                  'skipped by the engine, costs no slot'})
    return rows

IMAGE_REPORT_KEYS=('images','images_without_pixels','rows')

def read_image_report(path):
    """A readback measurement of which of a package's images have pixels no bank the client opens
    carries. Two shapes are read. The documented one names every image it checked:
    ``{"pack": "<name>", "images": [{"name": "x", "pixels": "missing"|"present", "located": "hint"}]}``.
    A tool that reports only what it could not resolve is read too: ``images_without_pixels`` or
    ``rows`` as a list of names, or of objects with ``image``/``name`` and an optional ``located``
    hint; every image the same readback did resolve is absent from that list by construction.
    Only names and hints are taken, never paths: a measurement is made on someone's machine and
    its file paths are theirs."""
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data,dict) or not any(k in data for k in IMAGE_REPORT_KEYS):
        raise Failure(INPUT_INVALID,f'{path} is not an image readback report',
                      'A report is one JSON object with "images" (every image checked) or '
                      '"images_without_pixels"/"rows" (the ones with no pixels).')
    missing,present,enumerated={},set(),False
    rows=data.get('images')
    if isinstance(rows,list):
        enumerated=True
        for row in rows:
            if not isinstance(row,dict):continue
            name=row.get('name') or row.get('image')
            if not name:continue
            if str(row.get('pixels','missing')).lower()=='present':present.add(name)
            else:missing[name]=str(row.get('located') or '') or None
    for key in ('images_without_pixels','rows'):
        rows=data.get(key)
        if not isinstance(rows,list):continue
        for row in rows:
            if isinstance(row,str):missing.setdefault(row,None)
            elif isinstance(row,dict):
                name=row.get('image') or row.get('name')
                if name:missing.setdefault(name,str(row.get('located') or '') or None)
    return {'pack':data.get('pack'),'missing':missing,'present':sorted(present),'enumerated':enumerated,
            'banks':sorted(data['banks_opened']) if isinstance(data.get('banks_opened'),dict) else data.get('banks') or []}

def image_sources(plan,report=None):
    """Whether every image the pack references will have pixels the client can load.

    A T6 material names its images. The fastfile carries each image's header, and its pixels only
    when the linker read the image from a disk `.iwi` the pack's own zone declares. An image the
    linker resolved from a zone the composition loads travels as a header alone, and the client
    streams its pixels from an image bank (`.ipak`) a `>level.ipak_read` header line names. A pack
    that references such an image with no bank carrying it renders it without pixels, loads
    without an error and looks like a success.

    What a plan can prove on its own: an `image` asset row whose file is on this machine is a
    complete delivery, because the build stages that file beside the package; a row whose file is
    missing or empty delivers nothing. Bank contents are not
    readable without the banks, so an image a member's zone listing only references is
    ``not_counted`` with that reason, never ``passed``, unless ``report`` — a readback taken with
    the client's banks beside the package — decides it. Every image that readback found no pixels
    for is a ``failed`` row naming the image, the member that brought it in when a member declares
    it, and the measurement's hint for where its pixels are."""
    embedded,referenced={},{}
    for row in plan.get('assets',[]):
        if row.get('type')!='image':continue
        name=row.get('name') or Path(row.get('target','')).stem
        embedded.setdefault(name,[]).append((row.get('module'),row.get('source')))
    for member in plan.get('seeds',[])+plan.get('adapters',[]):
        for root in member.get('roots',[]):
            kind,_,name=root.partition(',')
            if kind=='image' and name:referenced.setdefault(name,[]).append(member['id'])
    header=[line.split(',',1)[1].strip() for line in plan.get('zone_header',[]) if line.startswith('>level.ipak_read,')]
    banks='the startup set'+(' and the header reads '+', '.join(header) if header else ' and no header read')
    rows=[]
    if report is not None and report.get('pack') and plan.get('name') and report['pack']!=plan['name']:
        return [{'id':'image-sources','outcome':'not_counted',
                 'detail':f'The readback report was measured on {report["pack"]!r}, not on this composition; it decides nothing here'}]
    def row_for(name,outcome,detail):rows.append({'id':'image-sources:'+name,'outcome':outcome,'detail':detail})
    for name,owners in sorted(embedded.items()):
        who=', '.join(sorted({m for m,_ in owners if m})) or 'a member'
        absent=[source for _,source in owners if not source or not Path(source).is_file() or Path(source).stat().st_size==0]
        if absent:row_for(name,'failed',f'{who} declares image {name} but its file is missing or empty here, so the zone carries a header with no pixels')
        else:row_for(name,'passed',f'{who} ships {name} as its own image asset; the linker reads the file from disk and the build stages it beside the package, where the client reads its pixels')
    decided=set(embedded)
    for name,owners in sorted(referenced.items()):
        if name in decided:continue
        who=', '.join(sorted(owners))
        if report is None:
            row_for(name,'not_counted',f"{who} references {name} without embedding it; whether {banks} carries its pixels cannot be read offline. "
                                       'Measure it with a readback taken beside the client\'s banks and pass --image-report')
        elif name in report['missing']:
            hint=report['missing'][name]
            row_for(name,'failed',f'{who} references {name} and no bank the pack opens carries its pixels ({banks}), so it renders without them'+(f'; located: {hint}' if hint else ''))
        elif report['enumerated'] and name not in report['present']:
            row_for(name,'not_counted',f'{who} references {name} and the readback report does not name it at all, so nothing here decides whether {banks} carries its pixels')
        else:
            row_for(name,'passed',f'{who} references {name} and the readback resolved its pixels from {banks}')
        decided.add(name)
    for name,hint in sorted((report or {'missing':{}})['missing'].items()):
        if name in decided:continue
        row_for(name,'failed',f'No member declares {name}; it is resolved from a zone the composition loads and no bank the pack opens carries its pixels ({banks}), so it renders without them'+(f'; located: {hint}' if hint else ''))
        decided.add(name)
    failed=sum(1 for r in rows if r['outcome']=='failed');unknown=sum(1 for r in rows if r['outcome']=='not_counted')
    if failed:summary='failed',f'{failed} of {len(rows)} image(s) the pack references have pixels nowhere it can load them'
    elif unknown:summary='not_counted',(f'{len(embedded)} image(s) embedded with their pixels; {unknown} referenced image(s) undecided offline, and the '
                                        'images a loaded zone resolves are not in the plan at all. Only a readback beside the banks decides them')
    elif rows:summary='passed',f'Every one of the {len(rows)} image(s) this plan can name has pixels the pack can load'
    else:summary='not_counted',('No member embeds or references an image by name. Images a loaded zone resolves for a member\'s models and '
                                'effects are not in the plan; a readback beside the banks is the only thing that counts them')
    return [{'id':'image-sources','outcome':summary[0],'detail':summary[1]}]+rows

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

def stock_exports(vm):
    """The stock export rows that resolve on ``vm``. A call links only against a script the engine
    loads on the same VM, so the server rows never judge a `.csc` and the client rows never judge a
    `.gsc`; without a VM nothing is resolved."""
    if vm is None:return {}
    return {path:row['functions'] for path,row in knowledge.load('stock-exports.json')['exports'].items() if row.get('vm')==vm}

BOX_LIST=re.compile(r'strtok\(\s*"([^"]+)"\s*,\s*" "\s*\)',re.I)
BOX_CALL=re.compile(r'\baddzombieboxweapon\s*\(',re.I)

def box_registrations(name,text,provided):
    """A client script that calls addzombieboxweapon registers weapon names in the mystery-box
    display pool. The engine faults at the first box use when a registered name is not a loaded
    WeaponDef (`AddZombieBoxWeapon: Failed to find weapon <name>`, then an access violation).
    Every `_zm` name in a strtok list of such a script must be provided by a member of the pack or
    be a stock weapon; a name nobody provides fails naming the script and the name. Scripts that
    never call addzombieboxweapon say nothing. Stock names are not judged here (the pack cannot
    see the map's own list offline), so only names ending in `_zm` that no member provides and
    that carry a module-style prefix are refused; the rest stay not_counted."""
    if not name.lower().endswith('.csc') or not BOX_CALL.search(mask_noncode(text)):return []
    masked=mask_noncode(text);names=set()
    for lst in BOX_LIST.findall(text):
        names|={w for w in lst.split() if w.endswith('_zm')}
    if not names:return []
    missing=sorted(n for n in names if n not in provided)
    if missing:
        return [{'id':'box-registration:'+name,'outcome':'failed',
                 'detail':f'{name} registers {", ".join(missing)} in the mystery box and no member of this pack provides that weapon; the engine faults at the first box use (crash signature box-weapon-not-found). Register only weapons the pack provides'}]
    return [{'id':'box-registration:'+name,'outcome':'passed','detail':f'{name} registers only weapons a member provides: {", ".join(sorted(names))}'}]

def external_symbols(name,text,game='t6'):
    """Unqualified calls resolved against the stock export rows of this script's own VM: failed when
    the call needs an #include the script lacks; passed when every known call resolves on this
    script's VM; not_counted when the title is not T6 (the tables are T6-only), when the export
    table holds no row for this VM, when a call is neither a local function, a builtin witnessed on
    this VM, nor a stock export of this VM, or when the target suffix does not name a VM. A builtin
    witnessed only on the other VM stays not_counted, never passed: the witness table is an absence
    of evidence, not proof the other VM lacks the call. Resolving across VMs would refuse a correct
    client script for lacking a server include no stock `.csc` carries."""
    if game != 't6':
        return [{'id':'externals:'+name,'outcome':'not_counted',
                 'detail':f'External stock and builtin witness data is T6-only; {game} calls are not judged'}]
    text=mask_noncode(text)
    vm=_script_vm(name)
    exports=stock_exports(vm)
    if vm is not None and not exports:
        return [{'id':'externals:'+name,'outcome':'not_counted',
                 'detail':f'The stock export table is empty for the {vm} VM, so unqualified calls here are judged against no exports rather than against another VM'}]
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

def map_script_externals(name,text,map_id,foundation,game='t6',provided=()):
    """Every script this source includes or calls with a qualified path must be carried by the zones
    the target map loads on this foundation. A path the map lacks is an unresolved external at load
    (`COM_ERROR ... Unresolved external`), which the compiler cannot see. not_counted when the map is
    not in the table or the title is not T6. Only stock-looking paths (maps/, clientscripts/,
    common_scripts/, codescripts/) are judged, and a path another member of the same pack
    provides (``provided``: every script target the pack stages or a seed roots) is carried by
    the pack itself, not missing."""
    if game!='t6':
        return [{'id':'map-scripts:'+name,'outcome':'not_counted','detail':'Per-map script tables are T6-only'}]
    table=knowledge.load('map-scripts.json')['maps'].get(map_id)
    if not table or table.get('foundation')!=foundation:
        return [{'id':'map-scripts:'+name,'outcome':'not_counted','detail':f'No script table for {map_id} on {foundation}'}]
    carried=set(table['scripts'])|{p.lower() for p in provided}
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
