"""Reproducible controller development and locked synthetic evaluation.

Development chooses a fixed split using ONLY fixed-world delay. Evaluation
requires the sealed development manifest and unchanged code. Every result is
retained, including regressions. No site calibration or field benefit is implied.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path

from .io import atomic_json
from .site_profiles import load_profile, revise
from .sumo_demo import ROOT, Scenario, digest, object_hash, run

DEVELOPMENT_SEEDS=(42,43)
EVALUATION_SEEDS=(103,107,109)
PATTERNS=('balanced','tidal','heavy')
FIXED_SPLITS=(12,20,30)
CODE=('theiatron/sumo_demo.py','theiatron/site_profiles.py','theiatron/junction_control.py',
      'theiatron/controller.py','theiatron/observations.py','theiatron/config.py','theiatron/benchmark.py')


def code_identity():return {p:digest(ROOT/p) for p in CODE}


def summarize(rows):
    groups=defaultdict(list)
    for r in rows:groups[r['comparison']].append(r)
    result={}
    for name,items in groups.items():
        baseline=sum(r['baseline']['total_delay_s'] for r in items)
        candidate=sum(r['candidate']['total_delay_s'] for r in items)
        result[name]={'cases':len(items),'improved':sum(r['candidate']['mean_delay_s']<r['baseline']['mean_delay_s']-1e-4 for r in items),
            'worsened':sum(r['candidate']['mean_delay_s']>r['baseline']['mean_delay_s']+1e-4 for r in items),
            'total_delay_reduction_pct':round(100*(baseline-candidate)/baseline,3) if baseline else None,
            'baseline_finished':sum(r['baseline']['arrived'] for r in items),
            'candidate_finished':sum(r['candidate']['arrived'] for r in items),
            'candidate_p95_worse_cases':sum(r['candidate']['p95_delay_s']>r['baseline']['p95_delay_s']+1e-4 for r in items)}
    return result


def experiment(out,profile,pattern,seed,baseline,candidate):
    scenario=Scenario(duration=180,seed=seed,demand=pattern,pace=0,site_revision=profile['revision'],
                      generated_demand=True,baseline_policy=baseline,adaptive_policy=candidate)
    report=run(out,scenario,profile)
    if not report['valid']:raise ValueError('Invalid simulator diagnostics: '+str(out))
    frames=[json.loads(line) for line in (out/'frames.jsonl').read_text().splitlines()]
    switches={name:sum(a['worlds'][name]['signal']=='GREEN' and b['worlds'][name]['signal']=='YELLOW'
                       for a,b in zip(frames,frames[1:])) for name in ('fixed','adaptive')}
    clearance={name:sum(.5 for f in frames if f['worlds'][name]['signal']!='GREEN') for name in ('fixed','adaptive')}
    row={'run':out.name,'artifact_id':report['artifact_id'],'comparison':candidate+' vs '+baseline,
         'pattern':pattern,'seed':seed,'fixed_split':profile['signal']['fixed_split'],
         'baseline':report['metrics']['fixed'],'candidate':report['metrics']['adaptive'],
         'switches':switches,'clearance_seconds':clearance,'demand_sha256':report['files']['demand.json'],
         'network_sha256':report['files']['network.net.xml']}
    print('BENCHMARK '+json.dumps({k:row[k] for k in ('comparison','pattern','seed','switches','clearance_seconds')}),flush=True)
    return row


def execute(out,phase,revision=None,development=None):
    code=code_identity()
    if phase=='develop':
        profile=load_profile(ROOT,revision)
    else:
        manifest=json.loads((development/'benchmark.json').read_text())
        expected=manifest.pop('artifact_id')
        if object_hash(manifest)!=expected or manifest['phase']!='develop':
            raise ValueError('development manifest is not intact')
        if manifest['code_sha256']!=code:
            raise ValueError('code changed after development; create a new development benchmark before evaluation')
        profile=load_profile(ROOT,manifest['selected_profile_revision'])
    out.mkdir(parents=True,exist_ok=False)
    rows=[]
    def case(p,pattern,seed,b,c,label):
        row=experiment(out/label,p,pattern,seed,b,c);rows.append(row)
        atomic_json(out/'progress.json',{'phase':phase,'rows':rows,'summary':summarize(rows)})
        return row
    if phase=='develop':
        candidates={}
        for split in FIXED_SPLITS:
            p=revise(ROOT,profile['revision'],{'signal':{**profile['signal'],'fixed_split':split}})
            candidates[split]=p
            for pattern in PATTERNS:
                for seed in DEVELOPMENT_SEEDS:
                    case(p,pattern,seed,'fixed','pressure-v1',f'tune-{split}-{pattern}-{seed}')
        totals={split:sum(r['baseline']['total_delay_s'] for r in rows if r['fixed_split']==split) for split in FIXED_SPLITS}
        profile=candidates[min(FIXED_SPLITS,key=lambda s:(totals[s],s))]
        for baseline in ('fixed','actuated'):
            for pattern in PATTERNS:
                for seed in DEVELOPMENT_SEEDS:
                    case(profile,pattern,seed,baseline,'service-v2',f'dev-{baseline}-{pattern}-{seed}')
    else:
        totals=manifest['fixed_tuning_total_delay']
        for pattern in PATTERNS:
            for seed in EVALUATION_SEEDS:
                common=[]
                for baseline,candidate in [('fixed','pressure-v1'),('fixed','service-v2'),('actuated','service-v2')]:
                    common.append(case(profile,pattern,seed,baseline,candidate,f'eval-{baseline}-{candidate}-{pattern}-{seed}'))
                if len({(r['demand_sha256'],r['network_sha256']) for r in common})!=1:
                    raise ValueError('benchmark comparisons did not share identical inputs')
                if common[0]['baseline']!=common[1]['baseline']:
                    raise ValueError('fixed-world results were not reproducible across candidate comparisons')
    if code_identity()!=code:raise ValueError('code changed during benchmark')
    # Keep every tuning row, but do not mix three baseline configurations into
    # the final development comparison against the selected configuration.
    comparison_rows=[r for r in rows if r['fixed_split']==profile['signal']['fixed_split']]
    result={'schema_version':1,'phase':phase,'selected_profile_revision':profile['revision'],
            'fixed_tuning_total_delay':totals,'selected_fixed_split':profile['signal']['fixed_split'],
            'development_seeds':list(DEVELOPMENT_SEEDS),'evaluation_seeds':list(EVALUATION_SEEDS),
            'patterns':list(PATTERNS),'duration_s':180,'code_sha256':code,'rows':rows,'summary':summarize(comparison_rows),
            'scope':'Synthetic software benchmark on one estimated network; not field evaluation. Empty initial state, ideal lane sensing, homogeneous cars. Actuated baseline is a software gap-out comparator, not an incumbent installation.',
            'tuning_rule':'Minimum aggregate fixed-world delay over development patterns/seeds; candidate results do not choose the fixed split.',
            'development_artifact':None if phase=='develop' else expected}
    result['artifact_id']=object_hash(result)
    atomic_json(out/'benchmark.json',result)
    print(json.dumps(result['summary'],indent=2),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--phase',choices=['develop','evaluate'],required=True)
    parser.add_argument('--profile')
    parser.add_argument('--development',type=Path)
    args=parser.parse_args()
    if args.phase=='develop' and not args.profile:parser.error('development needs --profile')
    if args.phase=='evaluate' and not args.development:parser.error('evaluation needs --development')
    execute(args.out,args.phase,args.profile,args.development)


if __name__=='__main__':main()
