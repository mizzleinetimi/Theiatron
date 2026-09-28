const test=require('node:test'),assert=require('node:assert/strict');
const M=require('../workbench/showcase-math.js');
const report=()=>({source_run:'clip',valid:true,demand_basis:'generated-not-observed',metrics:{
  fixed:{mean_delay_s:35,p95_delay_s:69.2,offered:107},adaptive:{mean_delay_s:32.3,p95_delay_s:73.8,offered:107}}});
test('showcase never substitutes another source, invalid experiment or observed-demand benefit claim',()=>{
  assert.equal(M.reportForSource(report(),'clip').valid,true);
  for(const change of [{source_run:'other'},{valid:false},{demand_basis:'observed'}])
    assert.throws(()=>M.reportForSource({...report(),...change},'clip'),/source-matched/);
});
test('missing metrics and unequal populations are not displayed as evidence',()=>{
  for(const value of [null,NaN,-1,undefined]){
    const r=report();r.metrics.adaptive.mean_delay_s=value;
    assert.throws(()=>M.reportForSource(r,'clip'),/metrics/);
  }
  const r=report();r.metrics.adaptive.offered=108;
  assert.throws(()=>M.reportForSource(r,'clip'),/population/);
});
test('the selected embedded experiment is source-bound and same-origin',()=>{
  const origin='http://127.0.0.1:8766';
  assert.equal(M.comparisonFromFrame(origin+'/workbench/demo.html?video=clip&compare=new-run',origin,'clip'),'new-run');
  for(const url of ['https://evil.test/workbench/demo.html?video=clip&compare=run',
    origin+'/workbench/demo.html?video=other&compare=run',origin+'/workbench/demo.html?video=clip',
    origin+'/workbench/demo.html?video=clip&compare=../private'])
    assert.throws(()=>M.comparisonFromFrame(url,origin,'clip'));
});
test('negative long-wait outcomes remain visible despite an improved mean',()=>{
  assert.match(M.tailMessage(report()),/69\.2s → 73\.8s.*Worse/);
  const r=report();r.metrics.adaptive.p95_delay_s=60;
  assert.match(M.tailMessage(r),/Lower.*modelled/);
  r.metrics.adaptive.p95_delay_s=69.2;
  assert.match(M.tailMessage(r),/Unchanged/);
});
test('run selectors reject paths, missing identities and unexpected punctuation',()=>{
  for(const id of [null,'','../source','a/b','x?query','a'.repeat(122)])assert.throws(()=>M.runId(id));
  assert.equal(M.runId('ui-20260924-demo'),'ui-20260924-demo');
});
