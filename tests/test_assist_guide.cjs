const test=require('node:test'), assert=require('node:assert/strict');
const Guide=require('../workbench/assist-guide.js');
const M=require('../workbench/replay-math.js');
const fs=require('node:fs'), vm=require('node:vm');

test('guided lines use eight bounded endpoints and isolate immutable requests',()=>{
  const g=new Guide();
  assert.match(g.message,/1\/8.*start.*A1/);
  assert.throws(()=>g.request({},null,{}),/eight/);
  for(let i=0;i<8;i++)assert.equal(g.add([100+i*20,300]),true);
  assert.equal(g.complete,true);assert.equal(g.add([500,400]),false);
  const r=g.request({source_run:'local'},null,{label:'Draft'});
  assert.equal(r.lines.length,4);
  g.points[0][0]=500;
  assert.equal(r.lines[0][0][0],100);
  g.undo();assert.equal(g.complete,false);assert.match(g.message,/8\/8.*end.*B2/);
  g.reset();assert.equal(g.points.length,0);
  for(const p of [[-1,2],[1280,2],[2,720],[NaN,2],[2]])assert.throws(()=>g.add(p),/inside/);
});
test('saved assistance remains visibly distinct from automatic camera estimates',()=>{
  const label=M.projectionStatus({assistance:{},refinement:{stale:true}});
  assert.match(label,/Operator-assisted/);
  assert.match(label,/not physical accuracy/);
  assert.match(label,/not replaced by automatic refinement/);
  assert.match(label,/Metres remain estimated/);
});

function editor(wasDirty=false) {
  const source=fs.readFileSync(require.resolve('../workbench/replay.js'),'utf8');
  const code=source.slice(source.indexOf('  function assistFields()'),source.indexOf('  $("editAutomaticRoad").onclick'));
  const elements={},requests=[],renders=[];
  const element=id=>elements[id] ||= {hidden:true,disabled:false,value:'',textContent:''};
  element('widthM').valueAsNumber=30;element('depthM').valueAsNumber=20;element('calibrationLabel').value='Existing draft';
  const original={width_m:30,depth_m:20,label:'Existing draft',road:[]};
  const context=vm.createContext({$:element,paint(){},fields(){},showRefinement(){},revisionText(){},
    assistGuide:new Guide(),assistPreview:null,assistGeneration:0,assistWasDirty:null,
    dirty:wasDirty,undo:[],draft:structuredClone(original),data:{binding:{source_run:'source'},revision:null,calibration:structuredClone(original),refinement:{}},
    run:'source',token:'test-token',refinementState:'idle',activeRefinement:()=>true,
    clone:value=>structuredClone(value),refine(){},
    currentGeometry(){return context.assistPreview?.result.calibration || context.data.calibration;},
    rebuild(value){renders.push(structuredClone(value));},
    async read(url,options){requests.push([url,JSON.parse(options.body)]);return {
      calibration:{...original,label:'Assisted result'},revision:'saved',assistance:{method:'operator-road-directions-v1'}};}
  });
  vm.runInContext(code,context);
  element('assistStart').onclick();
  for(let i=0;i<8;i++)context.assistGuide.add([100+i*30,300]);
  vm.runInContext('assistFields()',context);
  return {context,element,requests,renders,original};
}
test('actual preview/discard handlers preserve earlier manual edits and never save implicitly',async()=>{
  for(const wasDirty of [false,true]) {
    const f=editor(wasDirty);
    await f.element('assistPreview').onclick();
    assert.equal(f.element('assistPreviewBar').hidden,false);
    assert.equal(f.context.data.revision,null);
    assert.equal(f.renders.at(-1).label,'Assisted result');
    f.element('assistDiscard').onclick();
    assert.equal(f.context.dirty,wasDirty);
    assert.deepEqual(f.context.draft,f.original);
    assert.deepEqual(f.renders.at(-1),f.original);
    assert.equal(f.requests.length,1);
    assert.equal(f.context.assistPreview,null);
  }
});
test('actual save handler submits original selections and persists assisted identity',async()=>{
  const f=editor();await f.element('assistPreview').onclick();
  await f.element('assistSave').onclick();
  assert.match(f.requests[1][0],/\/assist\/save$/);
  assert.deepEqual(f.requests[1][1],f.requests[0][1]);
  assert.equal(f.requests[1][1].calibration.label,'Existing draft');
  assert.equal(f.context.data.assistance.method,'operator-road-directions-v1');
  assert.equal(f.context.dirty,false);
  assert.equal(f.context.data.refinement.stale,true);
  assert.equal(f.context.assistPreview,null);
});
test('a changed selection invalidates an in-flight preview',async()=>{
  const f=editor();let resolve;
  f.context.read=()=>new Promise(r=>resolve=r);
  const pending=f.element('assistPreview').onclick();
  f.element('assistUndo').onclick();
  resolve({calibration:{label:'Stale result'}});await pending;
  assert.equal(f.context.assistPreview,null);
  assert.equal(f.element('assistPreviewBar').hidden,true);
  assert.equal(f.renders.length,0);
});
test('save failures preserve the preview and allow retry without touching the saved scene',async()=>{
  const f=editor();await f.element('assistPreview').onclick();
  f.context.read=async()=>{throw Error('saved draft changed; reload');};
  await f.element('assistSave').onclick();
  assert.equal(f.context.data.revision,null);
  assert.ok(f.context.assistPreview);
  assert.equal(f.element('assistSave').disabled,false);
  assert.match(f.element('assistSaveStatus').textContent,/saved draft changed/);
});
