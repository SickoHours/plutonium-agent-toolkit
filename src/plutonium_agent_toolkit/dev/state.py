"""Derived evidence state; hashes revoke claims without a mutable state file."""
import hashlib
import json
from pathlib import Path
from ..core.errors import Failure, INPUT_INVALID, INPUT_MISSING
from .compositions import _read_inspection

def read(path):
    p=Path(path)
    if not p.is_file() or p.is_symlink() or p.stat().st_size>16*1024**2:raise ValueError('Missing or oversized evidence: '+str(p))
    value=json.loads(p.read_text())
    if not isinstance(value,dict):raise ValueError('Evidence must be an object: '+str(p))
    return value

def sha(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file():raise ValueError('Missing or linked evidence: '+str(p))
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def same(path,expected,label):
    actual=sha(path)
    if actual!=expected:raise ValueError(f'{label}: expected {expected}; current {actual}')

def derive(args):
    result={'state':None,'evidence':{},'reasons':[]}
    root=Path(args.composition);root=root.parent if root.is_file() else root
    plan_path=Path(args.plan) if args.plan else root/'plan.json'
    try:plan=read(plan_path)
    except (ValueError,OSError) as e:result['reasons'].append(str(e));return result
    result['state']='composed';result['evidence']['composed']={'path':str(plan_path),'sha256':sha(plan_path)}
    try:
        modules=plan['modules'];ids={m['id'] for m in modules}
        for m in modules:same(Path(m['directory'])/'module.json',m['declaration_sha256'],'module '+m['id'])
        if plan.get('undecided'):raise ValueError('Composition has undecided collisions')
        if not args.verify:return result
        verify_path=Path(args.verify);verify=read(verify_path)
        if verify.get('status')!='succeeded' or verify.get('ok') is not True or verify.get('command') not in ('module build','project verify','project build'):
            raise ValueError('Offline receipt did not succeed')
        outputs=verify.get('outputs',{});summary=verify.get('result',{})
        mod=summary.get('mod_ff')
        if not isinstance(mod,str) or Path(mod).is_absolute() or '..' in Path(mod).parts:raise ValueError('Receipt has no relative package path')
        package=verify_path.parent/mod;digest=outputs.get(mod) or summary.get('mod_ff_sha256')
        if not digest:raise ValueError('Receipt has no package digest')
        same(package,digest,'package')
        # The built plan and the entire admitted source graph must still match.
        if outputs.get('plan.json'):same(plan_path,outputs['plan.json'],'built plan')
        elif not all(verify.get('inputs',{}).get(str(Path(m['directory'])/'module.json'))==m['declaration_sha256'] for m in modules):
            raise ValueError('Build receipt is not bound to these declarations')
        for path,expected in verify.get('inputs',{}).items():same(path,expected,'build input '+path)
        result['state']='offline_verified';result['evidence']['offline_verified']={'path':str(verify_path),'mod_ff_sha256':digest}
        if not args.test_plan:return result
        test_path=Path(args.test_plan);test=read(test_path)
        if test.get('protocol')!='pat.test-plan/1' or test.get('composition')!=plan['name'] or test.get('map')!=plan['map'] or test.get('base')!=plan['base']:raise ValueError('Test plan composition/base/map mismatch')
        if {m['id'] for m in test['members']}!=ids or len(test['members'])!=len(ids):raise ValueError('Test plan member set mismatch')
        if any(c.get('resolution')=='undecided' for c in test.get('conflicts',[])):raise ValueError('Undecided test conflict')
        by_id={m['id']:m for m in modules}
        for m in test['members']:
            directory=Path(by_id[m['id']]['directory']);decl=read(directory/'module.json');contract=decl.get('tests')
            if not isinstance(contract,str) or not (directory/contract).resolve().is_relative_to(directory.resolve()):raise ValueError('Invalid contract path for '+m['id'])
            same(directory/contract,m['contract_sha256'],'contract '+m['id'])
        test_digest=sha(test_path)
        result['state']='ready_for_game_testing';result['evidence']['ready_for_game_testing']={'path':str(test_path),'sha256':test_digest}
        if not args.run:return result
        run=read(args.run)
        if run.get('verdict')!='automated-passed':raise ValueError('Run has no completed automated-passed verdict')
        if run.get('package',{}).get('sha256')!=digest:raise ValueError('Run package digest mismatch')
        pin=run.get('test_plan',{})
        if pin.get('sha256')!=test_digest:raise ValueError('Run test-plan digest mismatch')
        if not pin.get('path'):raise ValueError('Run has no admitted test-plan artifact')
        same(pin['path'],test_digest,'run admitted plan')
        result['state']='game_tested';result['evidence']['game_tested']={'path':str(args.run),'mod_ff_sha256':digest,'test_plan_sha256':test_digest}
        if not args.verdict:return result
        accepted=read(args.verdict);verdicts=accepted.get('verdicts',[accepted]);scoped=[v for v in verdicts if v.get('build',{}).get('mod_ff_sha256')==digest and v.get('scope',{}).get('map')==plan['map'] and v.get('scope',{}).get('base',plan['base'])==plan['base']]
        if not scoped or scoped[-1].get('outcome')!='accepted':raise ValueError('No current accepted verdict for this package/map/base')
        result['state']='player_accepted';result['evidence']['player_accepted']={'path':str(args.verdict),'mod_ff_sha256':digest,'map':plan['map']}
    except (KeyError,ValueError,TypeError,OSError) as e:result['reasons'].append(str(e))
    return result
