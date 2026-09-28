const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');

function fixture() {
  let pending=[],draw,disposed=0;
  const element={replaceChildren(){},dataset:{}}, status={textContent:''},details={textContent:''};
  class Scene {
    constructor(){this.renderer={setPixelRatio(){}};this.groundGrid={};this.cars=new Map();}
    setRoad(){} setGroundGrid(){} preset(){} render(){}
    frame(poses){this.cars=new Map(poses.map(p=>[p.id,p]));}
    dispose(){disposed++;}
  }
  class Adapter {
    constructor(g){this.points=[];this.binding=g.binding;this.poses=[];this.projectionLabel=g.projection_kind==='operator-assisted-estimate'?'Operator-assisted perspective · unvalidated':'Automatic perspective · unvalidated';}
    clear(){this.poses=[];}
    update(s){this.poses=s?.state==='running'?[{id:'car'}]:[];return {reason:'fresh',poses:this.poses,hidden:0};}
    sample(){return this.poses;}
  }
  const context=vm.createContext({ AbortController, setTimeout, clearTimeout, devicePixelRatio:1,
    document:{hidden:false}, addEventListener(){},removeEventListener(){},
    requestAnimationFrame(fn){draw=fn;return 1;},cancelAnimationFrame(){},
    fetch(path,options){return new Promise(resolve=>pending.push({path,options,resolve}));},
    TrafficScene:Scene,LiveSceneMath:{LivePoses:Adapter},ReplayMath:{groundGrid(){return [];}} });
  vm.runInContext(fs.readFileSync(require.resolve('../workbench/live-scene.js'),'utf8')+'\nthis.View=LiveSceneView;',context);
  const view=new context.View(element,status,details);
  const response=(source,extra={})=>({ok:true,async json(){return {binding:{source_run:source},...extra};}});
  return {view,element,status,details,pending,response,draw:t=>draw(t),disposed:()=>disposed};
}
test('late geometry responses cannot replace a newly selected source',async()=>{
  const f=fixture();
  const first=f.view.load('first'),second=f.view.load('second');
  assert.equal(f.pending[0].options.signal.aborted,true);
  f.pending[1].resolve(f.response('second'));await second;
  f.pending[0].resolve(f.response('first'));await first;
  assert.equal(f.view.source,'second');
  assert.equal(f.view.adapter.binding.source_run,'second');
  f.view.dispose();
});
test('disconnect and pause clear cars, and a hidden document does not render',async()=>{
  const f=fixture(),load=f.view.load('source');f.pending[0].resolve(f.response('source'));await load;
  f.view.session={id:'session',source_run:'source',state:'running'};
  f.view.update(f.view.session,true);f.draw(100);
  assert.equal(f.element.dataset.vehicleCount,'1');
  f.view.update(f.view.session,false);f.draw(200);
  assert.equal(f.element.dataset.vehicleCount,'0');assert.match(f.status.textContent,/Disconnected/);
  f.view.update(f.view.session,true);f.draw(300);assert.equal(f.element.dataset.vehicleCount,'1');
  f.view.setEnabled(false);f.draw(400);
  assert.equal(f.element.dataset.vehicleCount,'0');assert.match(f.status.textContent,/paused/);
  f.view.dispose();
});
test('failed geometry preserves detection UI and stale fetches are aborted on disposal',async()=>{
  const f=fixture(),load=f.view.load('source');
  f.pending[0].resolve({ok:false,async json(){return {error:'no road estimate'};}});await load;
  f.draw(100);assert.match(f.status.textContent,/Detection remains available/);
  const retry=f.view.load('source');f.view.dispose();
  assert.equal(f.pending[1].options.signal.aborted,true);
  f.pending[1].resolve(f.response('source'));await retry;
  assert.equal(f.view.adapter,null);
});
test('back-forward caching preserves the view, final page exit disposes it',async()=>{
  const f=fixture(),load=f.view.load('source');f.pending[0].resolve(f.response('source'));await load;
  f.view.onPageHide({persisted:true});assert.equal(f.disposed(),0);
  f.view.onPageHide({persisted:false});assert.equal(f.disposed(),1);
});
test('each new session reloads same-source geometry and keeps assisted provenance visible while paused',async()=>{
  const f=fixture();
  f.view.update({id:'one',source_run:'source',state:'starting'});
  assert.equal(f.pending.length,1);
  f.pending[0].resolve(f.response('source',{projection_kind:'operator-assisted-estimate',geometry_revision:'assisted-1',
    registration_cadence_s:.1,registration:[{status:'accepted',H:[[1,0,0],[0,1,0],[0,0,1]]},{status:'rejected',H:null}]}));
  await new Promise(setImmediate);
  assert.equal(f.element.dataset.geometryRevision,'assisted-1');
  assert.match(f.details.textContent,/Operator-assisted.*unvalidated.*scale estimated/);
  assert.match(f.details.textContent,/1\/2.*10\.0 FPS/);
  f.view.setEnabled(false);f.draw(100);
  assert.match(f.details.textContent,/Operator-assisted/);
  f.view.update({id:'one',source_run:'source',state:'running'});
  assert.equal(f.pending.length,1);
  f.view.update({id:'two',source_run:'source',state:'starting'});
  assert.equal(f.pending.length,2);
  assert.equal(f.element.dataset.geometryRevision,'');
  assert.equal(f.element.dataset.vehicleCount,'0');
  f.pending[1].resolve(f.response('source',{projection_kind:'automatic-estimate',geometry_revision:'auto-2'}));
  await new Promise(setImmediate);
  assert.equal(f.element.dataset.geometryRevision,'auto-2');
  assert.match(f.details.textContent,/Automatic perspective/);
  f.view.dispose();
});
test('selected road can be inspected before detection without displaying historical cars',async()=>{
  const f=fixture();
  f.view.update(null,true,'selected');
  f.pending[0].resolve(f.response('selected'));
  await new Promise(setImmediate);
  f.draw(100);
  assert.equal(f.view.adapter.binding.source_run,'selected');
  assert.equal(f.element.dataset.vehicleCount,'0');
  f.view.update(null,true,null);f.draw(200);
  assert.equal(f.view.adapter,null);
  assert.equal(f.view.scene,null);
  assert.equal(f.element.dataset.sourceRun,'');
  assert.match(f.status.textContent,/Choose footage/);
  f.view.dispose();
});
