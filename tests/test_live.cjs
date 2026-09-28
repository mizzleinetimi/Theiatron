const test=require('node:test'),assert=require('node:assert/strict');
const M=require('../workbench/live-math.js');
test('stopped and disconnected-age previews cannot be labelled current',()=>{
  assert.equal(M.freshness(null).stale,true);
  assert.equal(M.freshness({state:'running',last_observation:{completed_at:10}},10.2).stale,false);
  assert.equal(M.freshness({state:'running',last_observation:{completed_at:10}},12).stale,true);
  const stopped=M.freshness({state:'stopped',last_observation:{completed_at:10}},10.2);
  assert.equal(stopped.stale,true);assert.match(stopped.text,/saved final preview/);
  assert.equal(M.value(null),'—');assert.equal(M.value(10,' ms'),'10.0 ms');
});
