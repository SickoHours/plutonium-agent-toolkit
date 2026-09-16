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

    What a plan can prove on its own: an `image` asset row whose file is missing or empty here
    delivers nothing at all. A row whose file *is* here is still only a header in the zone: the
    build stages the file under `packages/images/` as an artifact, but the engine does not read a
    mod folder's `images/`, so that staging delivers no pixels. The two routes that do are an image
    bank the zone header reads and Plutonium's global loose path `storage/t6/images`; neither is
    readable from a plan, so such a row is `not_counted`, never `passed`. Bank contents are not
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
        else:row_for(name,'not_counted',f'{who} roots {name} from a disk .iwi, so the zone carries its header; the header alone has no pixels. '
                                        'The build stages the file under packages/images/ as an artifact, and the engine never reads a mod folder\'s '
                                        'images/: the pixels load only from an image bank the header reads, or from Plutonium\'s global loose path '
                                        'storage/t6/images. Nothing offline can decide which, so this row is not a pass')
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
    elif unknown:summary='not_counted',(f'{len(embedded)} image(s) rooted from a disk .iwi (a header each; their pixels still need a bank or '
                                        f'storage/t6/images); {unknown-len(embedded)} referenced image(s) undecided offline, and the '
                                        'images a loaded zone resolves are not in the plan at all. Only a readback beside the banks decides them')
    elif rows:summary='passed',f'Every one of the {len(rows)} image(s) this plan can name has pixels the pack can load'
    else:summary='not_counted',('No member embeds or references an image by name. Images a loaded zone resolves for a member\'s models and '
                                'effects are not in the plan; a readback beside the banks is the only thing that counts them')
    return [{'id':'image-sources','outcome':summary[0],'detail':summary[1]}]+rows

SHADOW_SOURCE=re.compile(r'^Loaded (image|material) "(.*)" \(src: (.+)\)$')

def link_sources(text):
    """Every image and material the linker rooted, with the zone it took the copy from, read from a
    link log's `Loaded <type> "<name>" (src: <zone>)` rows. `src: disk` is the pack's own file."""
    rows=[]
    for line in text.splitlines():
        m=SHADOW_SOURCE.match(re.sub(r'\x1b\[[0-9;]*m','',line).strip())
        if m:rows.append((m.group(1),m.group(2),m.group(3)))
    return rows

def donor_shadowing(plan,shadowable=None,sources=None):
    """Whether the pack roots an image or material name its own base already carries.

    A composition loads donor zones from another game beside the target's own base zones, and the
    linker resolves every name a weapon's material closure reaches from whichever loaded zone offers
    it. A T6 fastfile carries an image's header and never its pixels, so a donor copy of a base-owned
    name puts a foreign header in front of the base's pixels and the shared camo and Pack-a-Punch
    textures render wrong on every weapon, the stock ones included, while the pack is selected.

    The composer's lever is the base's asset listings (``base_owned``, or derived from the loads with
    ``--base-listings``): every image and material name they carry is excluded from the pack's zone,
    so the closure reaches a reference to the base's copy instead of a donor's. Without listings the
    composer has nothing to exclude and this check refuses, naming how many donor zones are loaded.
    With them, the plan says how many names are excluded and ``sources`` -- the build's own link log,
    which names the zone every rooted asset's copy came from -- decides whether one got through. A
    name a member's own package roots is not judged here: that is the member's declared asset and
    the composition's collision decisions (``base-owned``) already own it."""
    loads=[Path(p).name[:-3] if Path(p).name.lower().endswith('.ff') else Path(p).stem for p in plan.get('loads',[])]
    base=set(plan.get('base_loads') or [])
    donors=[z for z in loads if z not in base]
    names={kind:set(v) for kind,v in (shadowable or {}).items()}
    total=sum(len(v) for v in names.values())
    def summary(outcome,detail,**extra):return [{'id':'donor-shadowing','outcome':outcome,'detail':detail,**extra}]
    if not donors:
        return summary('passed','Every zone this composition loads is part of its base'+(f' ({", ".join(sorted(base))})' if base else '')+
                                '; no donor zone can answer a base-owned name')
    if not plan.get('base_listings'):
        return summary('failed',
                       f'{len(donors)} zone(s) outside the base are loaded and no base listing says which image and material names the base owns, '
                       f'so the linker will root a donor copy of every base-owned name the members\' material closure reaches: '
                       +', '.join(donors[:10])+(', ...' if len(donors)>10 else ''),
                       count=len(donors),names=donors[:10],
                       hint='Pass --base-listings <dir> with the base zones\' <zone>-list.txt listings, or list them under base_owned in the composition.')
    if not total:
        return summary('not_counted',
                       f'The {len(plan["base_listings"])} base listing(s) carry no image or material row, so nothing is excluded and nothing here '
                       f'decides whether the {len(donors)} zone(s) outside the base answer a base-owned name',
                       count=0,names=[])
    if sources is not None:
        bad=[(kind,name,zone) for kind,name,zone in sources if zone in donors and name in names.get(kind,())]
        if bad:
            return summary('failed',
                           f'{len(bad)} asset(s) the base already carries were rooted from a donor zone: '
                           +', '.join(f'{k} {n} (src: {z})' for k,n,z in bad[:10])+(', ...' if len(bad)>10 else ''),
                           count=len(bad),names=[n for _,n,_ in bad[:10]])
        return summary('passed',
                       f'The link log roots no base-owned image or material from a donor zone; {total} base-owned name(s) '
                       f'({", ".join(f"{k} {len(v)}" for k,v in sorted(names.items()) if v)}) were excluded from the zone',
                       count=0,names=[])
    return summary('passed',
                   f'{total} base-owned name(s) ({", ".join(f"{k} {len(v)}" for k,v in sorted(names.items()) if v)}) are excluded from the pack\'s zone, '
                   f'so none of the {len(donors)} donor zone(s) can answer one; the build\'s link log is the proof',
                   count=0,names=[])

LOOSE_IMAGE_SUFFIX='.iwi'
# One row per shadowing file up to this many; the summary always carries the true count.
MAX_LOOSE_ROWS=64
# A flat texture folder, not a tree to walk: stop reading rather than enumerate an unbounded one.
MAX_LOOSE_FILES=20000

def loose_images_dir():
    """Plutonium's global loose texture path, ``<plutonium storage t6>/images``.

    The directory is not guessed: it is derived from the storage folder the user configured with
    ``pat configure --plutonium-storage-t6``, read from the ``config.json`` under whichever home
    ``PAT_HOME`` selects, which is the same key ``game install-mod`` and the game routes use.
    ``None`` when no storage is configured, or when the configuration cannot be read at all -- and
    ``None`` means *not counted*, never *clean*."""
    from ..core import config
    try:
        storage=config.load().get('plutonium_storage_t6')
    except Failure:
        return None
    return Path(storage)/'images' if storage else None

def loose_overrides(plan,shadowable=None,directory=None):
    """Every loose global texture file whose name a base zone also carries.

    Plutonium loads an image's pixels from an image bank the zone header reads *or* from the global
    loose path ``storage/t6/images``, and a loose file there wins: it applies to every mod folder on
    the machine and to the bare game with no mod selected. So a loose ``<name>.iwi`` whose name one of
    the base's own zones carries repaints that name everywhere -- the Pack-a-Punch and camo textures a
    stock weapon binds render from the loose file, on a pack that never touched them and on the bare
    foundation alike. It is machine state, so no composition change can cause it and none can cure it;
    the only reason a plan is where it surfaces is that a plan is the last place that knows which names
    the base owns.

    That makes it refusal-grade for the same reason ``donor-shadowing`` is: the rendering is wrong and
    the pack is not the cause, and a build that ships under those textures buys a diagnosis nobody can
    make from the package. Each shadowing file is a ``failed`` row naming it, and the summary refuses.

    The base's names are the ``image`` half of the same listings ``donor-shadowing`` excludes from the
    zone (``shadowable``); with no listing nothing is compared and the summary is ``not_counted``.
    ``directory`` is the configured loose path (``loose_images_dir``). Not configured, and absent from
    this machine, are both ``not_counted`` and say which they are: an uncounted directory and a counted
    empty one are different facts, and neither is a pass."""
    owned={name for name in (shadowable or {}).get('image',()) if name and not name.startswith(',')}
    def summary(outcome,detail,**extra):return [{'id':'loose-overrides','outcome':outcome,'detail':detail,**extra}]
    if not owned:
        return summary('not_counted',
                       'No base listing says which image names the base owns, so no loose file in Plutonium\'s global '
                       'storage/t6/images can be shown to shadow one. Pass --base-listings <dir> with the base zones\' '
                       'listings, or list them under base_owned in the composition',
                       count=0,names=[])
    if directory is None:
        return summary('not_counted',
                       'Plutonium\'s global loose texture path is not counted: no T6 storage folder is configured, so '
                       f'nothing here reads it. {len(owned)} base-owned image name(s) went unchecked against it, which is '
                       'not the same as checking them and finding none',
                       count=0,names=[],counted=False,
                       hint='Run: pat configure --plutonium-storage-t6 <absolute path to storage\\t6>; the loose path is its images/ folder.')
    directory=Path(directory)
    if not directory.is_dir():
        return summary('not_counted',
                       f'Plutonium\'s global loose texture path is not counted: {directory} is configured but is not a directory '
                       f'on this machine. {len(owned)} base-owned image name(s) went unchecked against it. An absent loose path '
                       'is the common case and is not a failure, but it is not a pass either',
                       count=0,names=[],counted=False)
    files=[];truncated=False
    try:
        # Lazy: the bound is on directory entries read, before any is sorted or stat-ed.
        for index,entry in enumerate(directory.iterdir()):
            if index>=MAX_LOOSE_FILES:truncated=True;break
            if entry.is_file():files.append(entry.name)
    except OSError as error:
        return summary('not_counted',
                       f'Plutonium\'s global loose texture path is not counted: {directory} could not be read ({error.strerror or error}). '
                       f'{len(owned)} base-owned image name(s) went unchecked against it',
                       count=0,names=[],counted=False)
    images={}
    for name in files:
        if name.lower().endswith(LOOSE_IMAGE_SUFFIX):images.setdefault(name[:-len(LOOSE_IMAGE_SUFFIX)].casefold(),name)
    by_fold={name.casefold():name for name in sorted(owned)}
    hits=sorted((by_fold[fold],images[fold]) for fold in sorted(set(images)&set(by_fold)))
    scanned=len(images)
    if truncated and not hits:
        # An incomplete scan that found nothing proves nothing: the file that shadows may be one
        # the bound stopped short of.
        return summary('not_counted',
                       f'Plutonium\'s global loose texture path is not counted: {directory} holds more than {MAX_LOOSE_FILES} entries, '
                       f'so the scan stopped before reading all of them and found no hit among the first {scanned} texture(s). '
                       f'{len(owned)} base-owned image name(s) may still be shadowed by a file it never reached',
                       count=0,names=[],counted=False,path=str(directory),loose_images=scanned)
    if not hits:
        return summary('passed',
                       f'None of the {scanned} loose texture(s) in {directory} carries one of the {len(owned)} image name(s) the base owns, '
                       'so no loose file repaints a base image for this pack or for the bare game',
                       count=0,names=[],counted=True,path=str(directory),loose_images=scanned)
    rows=[{'id':'loose-overrides:'+asset,'outcome':'failed',
           'detail':f'{filename} is in Plutonium\'s global loose texture path {directory} and the base carries the image {asset}. '
                    'A loose file wins over every image bank, for every mod folder on this machine and for the bare game with none '
                    'selected, so this name renders from that file whatever is loaded. Move it out of the folder (or accept it '
                    'deliberately and say so), then load the bare foundation as a control before any render is blamed on a pack'}
          for asset,filename in hits[:MAX_LOOSE_ROWS]]
    more=f' (first {MAX_LOOSE_ROWS} listed)' if len(hits)>MAX_LOOSE_ROWS else ''
    return summary('failed',
                   f'{len(hits)} of the {scanned} loose texture(s) in {directory} carry an image name the base owns{more}: '
                   +', '.join(asset for asset,_ in hits[:10])+(', ...' if len(hits)>10 else '')+
                   ('. Scanning stopped at the file bound, so there may be more' if truncated else '')+
                   '. They render over the base\'s own copies for every mod and for the bare game, so a wrong texture here is '
                   'machine state and no change to this composition can fix it',
                   count=len(hits),names=[asset for asset,_ in hits[:10]],counted=True,path=str(directory),
                   loose_images=scanned)+rows

def script_result(name,text,passed):
    errors=re.findall(r'(?im)^.*(?:unresolved external|\berror\b|\bfatal\b).*$',text)
    return {'id':'symbols:'+name,'outcome':'failed' if errors or not passed else 'not_counted',
            'detail':('; '.join(errors)[:800] or ('gsc check failed' if not passed else 'gsc check passed syntax/compilation; runtime external resolution is not proven'))}

CALL=re.compile(r'(?<![\w\\:.\[])([A-Za-z_][A-Za-z0-9_]*)\s*\(')
DEF=re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*\{',re.M)
INCLUDE=re.compile(r'^\s*#include\s+([^;]+);',re.M|re.I)
KEYWORDS=frozenset(('if','while','for','foreach','switch','return','wait','waittill','waittillmatch','endon','notify','thread','spawn','array','assert'))

def scan_noncode(text):
    """Yield ``(kind, start, end)`` for every comment and string literal in ``text``, in order.
    ``kind`` is 'line', 'block' or 'string' and the span covers the whole token, delimiters
    included. One lexer serves both the masker below and the literal reader further down, so the
    two can never disagree about where a string ends and a comment begins."""
    i=0;size=len(text)
    while i<size:
        char=text[i]
        if char=='/' and i+1<size and text[i+1]=='/':
            stop=text.find(chr(10),i+2);stop=size if stop<0 else stop
            yield ('line',i,stop);i=stop;continue
        if char=='/' and i+1<size and text[i+1]=='*':
            stop=text.find('*/',i+2);stop=size if stop<0 else stop+2
            yield ('block',i,stop);i=stop;continue
        if char=='"':
            stop=i+1
            while stop<size:
                if text[stop]==chr(92) and stop+1<size:stop+=2;continue
                if text[stop]=='"':stop+=1;break
                stop+=1
            yield ('string',i,stop);i=stop;continue
        i+=1

def mask_noncode(text):
    """Blank comments and string literals, keeping every newline, so the line-anchored scans see
    only executable GSC. A quote inside a string is backslash-escaped; `//` or `/*` inside a
    string is text, not a comment."""
    output=list(text)
    for _,start,stop in scan_noncode(text):
        for i in range(start,stop):
            if output[i]!=chr(10):output[i]=' '
    return ''.join(output)

def string_spans(text):
    """The ``(start, end)`` span of every string literal, quotes included."""
    return [(start,stop) for kind,start,stop in scan_noncode(text) if kind=='string']

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

# Stock helpers that register a clientfield without the pack ever writing `registerclientfield`.
# One row per helper: `set` is the clientfield set it registers into, `name_arg` the zero-based
# argument that carries the field name as a literal on each VM, and `id_arg`/`id_format` render
# the name the helper derives itself when that argument is absent or is not a literal
# (`add_zombie_powerup("tesla", ...)` registers `powerup_tesla`). The qualified path in front of
# the call does not change what it registers, so only the call name is keyed. The next helper is
# one row.
CLIENTFIELD_HELPERS={'add_zombie_powerup':{'set':'toplayer','name_arg':{'server':8,'client':1},
                                           'id_arg':0,'id_format':'powerup_{}'}}

REGISTER_CALL=re.compile(r'\b(registerclientfield|'+'|'.join(sorted(CLIENTFIELD_HELPERS))+r')\s*\(',re.I)
IF_HEADER=re.compile(r'\bif\s*\(',re.I)
# A guard the other VM can mirror without reading state it does not have: an isdefined() test, or
# a bare `level` field. Anything else is a fact one VM knows and the other does not.
TRIVIAL_GUARD=re.compile(r'^(?:isdefined\s*\(.*\)|level(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[^\]]*\])+)$',re.I)

def _close_paren(text,index):
    """The index of the `)` matching the `(` at ``index``, or None. Read from masked text, where a
    paren inside a string or comment is already blank."""
    depth=0
    for i in range(index,len(text)):
        if text[i]=='(':depth+=1
        elif text[i]==')':
            depth-=1
            if depth==0:return i
    return None

def _call_arguments(masked,open_index):
    """The ``(start, end)`` offsets of each argument of the call whose `(` sits at ``open_index``.
    Structure comes from the masked copy, where a comma or paren inside a string or comment is
    already blank, so the offsets are safe to read back against the original text."""
    depth=0;start=None;args=[]
    for i in range(open_index,len(masked)):
        char=masked[i]
        if char in '([':
            depth+=1
            if depth==1:start=i+1
        elif char in ')]':
            depth-=1
            if depth==0:
                if args or masked[start:i].strip():args.append((start,i))
                return args
        elif char==',' and depth==1:
            args.append((start,i));start=i+1
    return []

def _literal(masked,text,span,strings):
    """The value of a string-literal argument, or None. An argument may carry comments around its
    literal (`registerclientfield(/* set */ "toplayer", ...)`), and the masked copy shows a comment
    as blanks, so the argument is a literal exactly when one string span lies inside it and
    everything else in the masked copy is whitespace. A variable, a concatenation of two literals
    and a localized `&"..."` all read as not-a-literal, which leaves the registration unread rather
    than guessed at."""
    if span is None:return None
    start,end=span
    inside=[(s,e) for s,e in strings if s>=start and e<=end]
    if len(inside)!=1:return None
    s,e=inside[0]
    if e-s<2 or text[s]!='"' or text[e-1]!='"':return None
    if masked[start:s].strip() or masked[e:end].strip():return None
    return text[s+1:e-1]

def _bare(term):
    """A term with its outer parentheses and leading `!` removed, so `!(isdefined(x))` reads as
    the isdefined test it is."""
    term=term.strip()
    while True:
        if term.startswith('(') and _close_paren(term,0)==len(term)-1:term=term[1:-1].strip();continue
        if term.startswith('!'):term=term[1:].strip();continue
        return term

def _terms(condition):
    """Top-level `&&`/`||` terms; a term inside parentheses stays whole."""
    rows=[];depth=0;start=0;i=0
    while i<len(condition):
        char=condition[i]
        if char in '([':depth+=1
        elif char in ')]':depth-=1
        elif depth==0 and condition[i:i+2] in ('&&','||'):
            rows.append(condition[start:i]);i+=2;start=i;continue
        i+=1
    rows.append(condition[start:])
    return [row for row in (r.strip() for r in rows) if row]

def _guards(masked,offset):
    """Every `if` condition governing the code at ``offset``: one per enclosing braced `if` block,
    plus a brace-less `if` whose single statement this is. Read from the masked copy, so a brace or
    semicolon inside a string or comment is already blank. `else`, loops and switches carry no
    condition here and leave the code unguarded, which keeps the check conservative."""
    stack=[];pending=[];carried=None;i=0
    while i<offset:
        char=masked[i]
        if char=='{':
            # A brace-less `if` governs the next statement, and that statement may itself be the
            # braced `if` this `{` opens. Carrying the pendings into the frame keeps the outer
            # condition on a nested chain and drops them again when the block closes.
            stack.append(pending+([carried] if carried else []));carried=None;pending=[];i+=1;continue
        if char=='}':
            if stack:stack.pop()
            carried=None;pending=[];i+=1;continue
        if char==';':
            pending=[];i+=1;continue
        header=IF_HEADER.match(masked,i)
        if header:
            close=_close_paren(masked,header.end()-1)
            if close is None or close>=offset:i=header.end();continue
            condition=' '.join(masked[header.end():close].split())
            after=close+1
            while after<len(masked) and masked[after].isspace():after+=1
            if after<len(masked) and masked[after]=='{':carried=condition
            else:pending.append(condition)
            i=close+1;continue
        if char=='(':
            close=_close_paren(masked,i)
            if close is not None and close<offset:i=close+1;continue
        i+=1
    return [row for frame in stack for row in frame]+pending

def _condition_of(masked,offset):
    """The first governing `if` condition that is not a plain isdefined/level guard, or None."""
    for condition in _guards(masked,offset):
        if any(not TRIVIAL_GUARD.match(_bare(term)) for term in _terms(condition)):return condition
    return None

def _registrations(name,text):
    """Every clientfield this script registers: ``(set, field, condition)``, where ``condition`` is
    the non-trivial `if` the registration sits under, or None. A call whose set or name is not a
    string literal is not read: the check refuses what it can prove, not what it guesses."""
    vm=_script_vm(name)
    if vm is None:return []
    masked=mask_noncode(text);strings=string_spans(text);rows=[]
    def literal(args,index):
        return _literal(masked,text,args[index],strings) if index is not None and index<len(args) else None
    for match in REGISTER_CALL.finditer(masked):
        call=match.group(1).lower()
        args=_call_arguments(masked,match.end()-1)
        if not args:continue
        if call=='registerclientfield':
            field_set=literal(args,0);field=literal(args,1)
        else:
            helper=CLIENTFIELD_HELPERS[call];field_set=helper['set']
            field=literal(args,helper['name_arg'].get(vm))
            if field is None:
                ident=literal(args,helper['id_arg'])
                field=helper['id_format'].format(ident) if ident else None
        if not field_set or not field:continue
        rows.append((field_set,field,_condition_of(masked,match.start()),call))
    return rows

REMEDY=('ship the other half as a loose scripts/zm script (a .csc for a server registration, a '
        '.gsc for a client one) that registers the same name with the same width and version, '
        'unconditionally')

def clientfield_symmetry(sources,game='t6'):
    """A clientfield the pack registers on one script VM and not on the other is
    `EXE_CLIENT_FIELD_MISMATCH` at map load: the engine compares the server's registration list
    with the client's and refuses the map before a script runs, so no compile, link or readback
    sees it (crash signature `clientfield-registrations-mismatch`). This is a property of the
    pack's two halves together, so it is read once per composition rather than per script.

    ``sources`` is ``(target, text, module)`` per compiled `.gsc` and `.csc`. Every direct
    `registerclientfield("<set>", "<name>", ...)` and every ``CLIENTFIELD_HELPERS`` call is
    grouped by ``(set, name)``: a pair on both VMs passes, a name on exactly one VM fails naming
    the field, the set, the VM, the script and the module, and a pack that registers nothing on
    either VM is not_counted. Registrations the stock map already makes on both VMs are outside
    the pack and are never read here; only what the pack's own scripts register is compared.

    A registration under a condition is still a registration, so it counts for the pairing, and a
    condition the other VM cannot evaluate adds its own failed `:conditional` row: the tesla
    lesson is that guarding one half on state only that VM holds inverts the mismatch instead of
    curing it."""
    if game!='t6':
        return [{'id':'clientfield-symmetry','outcome':'not_counted',
                 'detail':f'clientfield registrations are a T6 two-VM property; {game} runs one script VM and its '
                          f'registrations are not judged here'}]
    found={};conditions={}
    for name,text,module in sources:
        for field_set,field,condition,call in _registrations(name,text):
            vm=_script_vm(name)
            found.setdefault((field_set,field),{}).setdefault(vm,[]).append((name,module,call))
            if condition:conditions.setdefault((field_set,field),[]).append((vm,name,module,condition))
    if not found:
        return [{'id':'clientfield-symmetry','outcome':'not_counted',
                 'detail':'No clientfield registration read: no compiled script in this pack calls registerclientfield '
                          'or a helper that registers a field, so there is nothing to compare across the two VMs'}]
    rows=[]
    for key in sorted(found):
        field_set,field=key;vms=found[key]
        if 'server' in vms and 'client' in vms:
            rows.append({'id':'clientfield-symmetry:'+field,'outcome':'passed',
                         'detail':f'"{field}" in set {field_set} is registered on both script VMs: '
                                  f'{_owners(vms["server"])} on the server and {_owners(vms["client"])} on the client'})
        else:
            vm=next(iter(vms));missing='client' if vm=='server' else 'server'
            suffix='.csc' if missing=='client' else '.gsc'
            rows.append({'id':'clientfield-symmetry:'+field,'outcome':'failed','field':field,'set':field_set,'vm':vm,
                         'detail':f'"{field}" in set {field_set} is registered on the {vm} VM only, by {_owners(vms[vm])}, '
                                  f'and by no {suffix} in this pack; the engine compares the two registration lists at map '
                                  f'load and refuses the map with EXE_CLIENT_FIELD_MISMATCH before a script runs (crash '
                                  f'signature clientfield-registrations-mismatch). Remedy: {REMEDY}'})
        for vm,name,module,condition in conditions.get(key,()):
            rows.append({'id':f'clientfield-symmetry:{field}:conditional','outcome':'failed',
                         'detail':f'{_owner(name,module)} registers "{field}" in set {field_set} on the {vm} VM under '
                                  f'`if ({condition})`: registered under a condition on one VM; the other VM cannot read '
                                  f'that fact, so the registration must be unconditional'})
    return rows

def _owner(name,module):
    return f'{name} (module {module})' if module else name

def _owners(rows):
    return ', '.join(sorted({f'{_owner(name,module)} through {call}' if call!='registerclientfield' else _owner(name,module)
                             for name,module,call in rows}))

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

# A ported script that still asks whether it is on its donor map. The test reads either the
# `mapname` dvar or `level.script`, in single or double quotes, with `!=` (the body returns) or
# `==` (the else returns); both say the same thing. Several tests in one condition name a set of
# maps (`!= "a" && != "b"`, or the `== ... || ...` dual), which is one guard over that set.
MAP_GUARD=re.compile(r'''(?:getdvar\s*\(\s*(["\'])mapname\1\s*\)|level\s*\.\s*script)\s*(?P<op>!=|==)\s*(["\'])(?P<map>[A-Za-z0-9_]{1,64})\3''',re.I)
IF_OPEN=re.compile(r'\bif\s*\(')
ELSE_AT=re.compile(r'\s*else\b')
# The statements a guard may sit behind, and the statements its returning branch may hold beside
# the return: setup that cannot decide anything. A call to anything else, a `thread`, or a nested
# block means this conditional is program logic, not an entry guard, and is left unread.
RETURN_AT=re.compile(r'^return\b')
PRINT_CALL=re.compile(r'^i?print(ln)?(bold)?\s*\(',re.I)
ASSIGN=re.compile(r'^[A-Za-z_][A-Za-z0-9_.\[\]\s]*(?<![=!<>])=(?!=)')
WAIT_AT=re.compile(r'^wait\b',re.I)
GUARD_ENTRIES=('main','init')

def _statements(text):
    """Top-level statements in a block body, split at `;` outside parentheses. ``None`` when the
    body holds a brace block of its own, which no bare guard and no bare setup line does."""
    if '{' in text or '}' in text:return None
    rows=[];depth=0;start=0
    for i,char in enumerate(text):
        if char=='(':depth+=1
        elif char==')':depth-=1
        elif char==';' and depth==0:rows.append(text[start:i].strip());start=i+1
    rows.append(text[start:].strip())
    return [row for row in rows if row]

def _block(masked,pos):
    """The statement or brace block that starts at ``pos``, and the offset just past it."""
    while pos<len(masked) and masked[pos].isspace():pos+=1
    if pos<len(masked) and masked[pos]=='{':
        depth=0
        for i in range(pos,len(masked)):
            if masked[i]=='{':depth+=1
            elif masked[i]=='}':
                depth-=1
                if depth==0:return masked[pos:i+1],i+1
        return masked[pos:],len(masked)
    end=masked.find(';',pos)
    if end<0:return masked[pos:],len(masked)
    return masked[pos:end+1],end+1

def _returns_unconditionally(block):
    """Does this branch always return? A bare `return;`, or a brace block whose own statements are
    only returns, prints and assignments. A nested `if (...) return;` returns only sometimes, so
    the conditional around it is not an entry guard and this says no."""
    body=block.strip()
    if body.startswith('{'):body=body[1:-1] if body.endswith('}') else body[1:]
    rows=_statements(body)
    if rows is None:return False
    returned=False
    for row in rows:
        if RETURN_AT.match(row):returned=True
        elif not (PRINT_CALL.match(row) or ASSIGN.match(row)):return False
    return returned

def _is_first_statement(masked,body_start,if_start):
    """Is this conditional the entry point's first statement? Prints, waits and assignments may
    come before it -- none of them can decide anything -- but a thread, a call to another function
    or a block of any kind means the entry point has already begun its work, and a map conditional
    after that is program logic rather than a guard on the whole script."""
    rows=_statements(masked[body_start:if_start])
    if rows is None:return False
    return all('thread' not in row.lower() and (WAIT_AT.match(row) or PRINT_CALL.match(row) or ASSIGN.match(row))
               for row in rows)

def _enclosing_if(masked,start):
    """``(if offset, offset just past its `)`)`` for the innermost `if (...)` holding ``start``."""
    for opener in reversed(list(IF_OPEN.finditer(masked,0,start))):
        depth=0;close=None
        for i in range(opener.end()-1,len(masked)):
            if masked[i]=='(':depth+=1
            elif masked[i]==')':
                depth-=1
                if depth==0:close=i;break
        if close is not None and opener.end()<=start<close:return opener.start(),close+1
    return None

def _entry_of(masked,start):
    """The function ``start`` sits in: its name, where its body begins, and whether ``start`` is at
    that function's top level rather than inside a block of it."""
    enclosing=None
    for match in DEF.finditer(masked):
        if match.end()>start:break
        enclosing=match
    if enclosing is None:return None,0,False
    body=masked[enclosing.end():start]
    return enclosing.group(1).lower(),enclosing.end(),body.count('{')==body.count('}')

def map_guards(name,text,map_id):
    """One row per script: does this source return unless the map is one of a named few?

    A module ported from another map often keeps its donor's entry guard -- a
    `if ( getdvar( "mapname" ) != "zm_transit" ) return;` as the first statement of `main()` or
    `init()`, the `level.script` form of the same test, or the `==` form whose `else` returns. It
    compiles, links and loads on any map; on a map the guard does not name, the entry point returns
    and the member does nothing, with no compiler diagnostic, no unresolved external and no
    load-time line to read. One condition may name several maps (`!= "a" && != "b"`); that is one
    guard over that set, and only a target outside the set fails.

    Read narrowly on purpose, because a failed row refuses the plan: the conditional must be the
    entry point's first real statement, and its branch must return unconditionally. A map
    conditional after the entry point has started working, or one whose branch returns only
    sometimes, is program logic and is left `not_counted` -- which means unread, never clean."""
    masked=mask_noncode(text)
    groups={}
    for match in MAP_GUARD.finditer(text):
        if masked[match.start()]==' ':continue  # a guard inside a comment or a string is text
        entry,body_start,top_level=_entry_of(masked,match.start())
        if entry not in GUARD_ENTRIES or not top_level:continue
        found=_enclosing_if(masked,match.start())
        if found is None:continue
        if_start,close=found
        group=groups.setdefault(if_start,{'close':close,'body':body_start,'ops':[],'maps':[]})
        group['ops'].append(match.group('op'))
        if match.group('map') not in group['maps']:group['maps'].append(match.group('map'))
    guarded=[]
    for if_start,group in sorted(groups.items()):
        if len(set(group['ops']))!=1:continue  # a condition mixing == and != is not read as a guard
        if not _is_first_statement(masked,group['body'],if_start):continue
        body,after=_block(masked,group['close'])
        if group['ops'][0]=='!=':
            returns=_returns_unconditionally(body)
        else:
            otherwise=ELSE_AT.match(masked,after)
            returns=bool(otherwise and _returns_unconditionally(_block(masked,otherwise.end())[0]))
        if returns:guarded.append(group['maps'])
    for named in guarded:
        if map_id not in named:
            names=named[0] if len(named)==1 else 'one of '+', '.join(named)
            return [{'id':'map-guard:'+name,'outcome':'failed','guard':named[0],'guards':named,
                     'detail':f'returns unless mapname is {names}; this composition targets {map_id}, '
                              f'so the script does nothing on it'}]
    if guarded:
        named=guarded[0]
        return [{'id':'map-guard:'+name,'outcome':'passed','guard':map_id,'guards':named,
                 'detail':f'the entry guard names {", ".join(named)}, which this composition targets'}]
    return [{'id':'map-guard:'+name,'outcome':'not_counted','detail':'no map guard read'}]

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
