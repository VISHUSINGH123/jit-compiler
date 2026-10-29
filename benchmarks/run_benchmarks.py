"""Repeatable split cold/warm timings for the Python bytecode tier."""
import pathlib, statistics, time, sys, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from parser import Parser
from runtime import Runtime

WORKLOADS = {
 "compute-heavy": "fn work(x){ let y=x; let i=0; while(i<300){ y=(y*3+7)%1000003; i=i+1; } return y; }",
 "loop-heavy": "fn work(x){ let i=0; let s=0; while(i<1200){ s=s+i; i=i+1; } return s+x; }",
 "function-call-heavy": "fn add(x){return x+1;} fn work(x){let i=0; while(i<120){x=add(x); i=i+1;} return x;}",
 "branch-heavy": "fn work(x){let i=0; let s=0; while(i<350){if((i%2)==0){s=s+i;}else{s=s-i;} i=i+1;} return s+x;}",
 "deoptimization": "fn work(x){return x+1;}"
}
TRIALS=9; WARMUPS=2; CALLS=8

def _one(name, guarded, warm, calls=CALLS):
    source=WORKLOADS[name]
    t=time.perf_counter_ns(); program=Parser(source).parse(); parse_ns=time.perf_counter_ns()-t
    rt=Runtime(program, hot_threshold=1 if guarded else 10**9)
    warmup_ns=0
    if warm:
        t=time.perf_counter_ns()
        rt.call('work',[10])
        if name=='deoptimization': rt.call('work',[True])
        warmup_ns=time.perf_counter_ns()-t
    t=time.perf_counter_ns()
    outputs=[]
    for i in range(calls):
        value=rt.call('work',[True if name=='deoptimization' and i%7==0 else 10])
        outputs.append(value)
    elapsed=time.perf_counter_ns()-t
    return parse_ns/1e6, warmup_ns/1e6, elapsed/1e6, outputs, rt

def measure(name, guarded, warm):
    for _ in range(WARMUPS):_one(name,guarded,warm)
    rows=[_one(name,guarded,warm) for _ in range(TRIALS)]
    return {"parse_median_ms":statistics.median(r[0] for r in rows),
      "warmup_median_ms":statistics.median(r[1] for r in rows),
      "execution_median_ms":statistics.median(r[2] for r in rows),
      "end_to_end_median_ms":statistics.median(r[0]+r[1]+r[2] for r in rows),
      "outputs":rows[-1][3],"compile_median_ms":statistics.median(r[4].profile['work']['compile_ns'] for r in rows)/1e6,
      "deopts":rows[-1][4].profile['work']['deopts'],"compiles":rows[-1][4].profile['work']['compile_count']}

def run_benchmark():
    report={"trials":TRIALS,"warmups":WARMUPS,"calls_per_trial":CALLS,"workloads":{}}
    for name in WORKLOADS:
        report['workloads'][name]={}
        for label,guarded,warm in [('interpreted-cold',False,False),('guarded-cold',True,False),('interpreted-warm',False,True),('guarded-warm',True,True)]:
            report['workloads'][name][label]=measure(name,guarded,warm)
        base=report['workloads'][name]['interpreted-warm']['outputs']
        jit=report['workloads'][name]['guarded-warm']['outputs']
        report['workloads'][name]['equivalent']=base==jit
        a=report['workloads'][name]['interpreted-warm']['execution_median_ms']; b=report['workloads'][name]['guarded-warm']['execution_median_ms']
        report['workloads'][name]['warm_speedup_pct']=(a/b-1)*100 if b else 0
    return report

def main():
    result=run_benchmark()
    print('Python bytecode-plan benchmark; medians, no native-code claim')
    print(f"Trials={TRIALS}, warmups={WARMUPS}, timed calls/trial={CALLS}")
    for name,row in result['workloads'].items():
        print(f"\n{name}: equivalent={row['equivalent']} warm speedup={row['warm_speedup_pct']:+.2f}%")
        for phase in ('interpreted-cold','guarded-cold','interpreted-warm','guarded-warm'):
            r=row[phase]; print(f"  {phase}: end-to-end={r['end_to_end_median_ms']:.4f}ms parse={r['parse_median_ms']:.4f}ms warmup={r['warmup_median_ms']:.4f}ms execution={r['execution_median_ms']:.4f}ms compile={r['compile_median_ms']:.4f}ms deopts={r['deopts']}")
        if not row['equivalent']:raise SystemExit('semantic mismatch: '+name)
    pathlib.Path(__file__).with_name('latest_results.json').write_text(json.dumps(result,indent=2))
if __name__=='__main__':main()
