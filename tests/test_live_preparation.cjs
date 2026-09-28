const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');

async function fixture(search = '?video=upload', terminal = 'processing', session = null) {
  const elements = new Map(), requests = [], scheduled = [], scenes = [];
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      hidden: true, disabled: false, value: '', options: [], files: [], dataset: {},
      classList: {toggle(){}, add(){}, remove(){}}, replaceChildren(){},
      add(option){this.options.push(option);},
    });
    return elements.get(id);
  };
  element('duration').value = '30'; element('fps').value = '10';
  const state = {worker:{state:'ready'},session,busy:false,other_job_busy:false};
  const job = {id:'road', kind:'reconstruction',state:terminal,stage:'capturing',updated_at:10,progress:43,message:'Capturing'};
  const context = vm.createContext({
    URLSearchParams, AbortController, performance:{now:()=>3000},
    location:{search,href:''}, history:{replaceState(...args){requests.push(['history',args[2]]);}},
    document:{getElementById:element,querySelectorAll:()=>[],createElement:()=>({append(){}})},
    Option:function(text,value){this.text=text;this.value=value;},
    LiveMath:require('../workbench/live-math.js'),
    LiveSceneView:class {update(...args){scenes.push(args);}},
    setTimeout(fn,ms){if(ms===250)scheduled.push(fn);return 1;},clearTimeout(){},
    async fetch(path,options={}) {
      requests.push([path,options.method||'GET']);
      const body = path==='/api/health' ? {token:'local-token'}
        : path==='/api/live/sources' ? [{id:'upload',kind:'live-source',filename:'test.mp4'}]
        : path==='/api/live' ? state : path.endsWith('/cancel') ? {...job,state:'cancelled'} : job;
      return {ok:true,json:async()=>body};
    },
  });
  await vm.runInContext(fs.readFileSync(require.resolve('../workbench/live.js'),'utf8'),context);
  await new Promise(setImmediate);
  return {element,requests,context,job,state,scheduled,scenes};
}

test('prepare uses the visual endpoint and preserves progress after reload',async()=>{
  const f = await fixture();
  await f.element('prepareRoad').onclick();
  assert.ok(f.requests.some(([p])=>p==='/api/live/sources/upload/reconstruct'));
  assert.ok(!f.requests.some(([p])=>p.endsWith('/analyse')));
  assert.equal(f.element('roadPreparation').hidden,false);
  assert.equal(f.element('roadProgress').value,43);
  assert.equal(f.element('roadPreviewImage').src,'/out/road/preview.jpg?t=10');
  assert.equal(f.context.location.href,'');
  const restored = await fixture('?video=upload&prepare=road');
  assert.equal(restored.element('roadProgress').value,43);
  assert.equal(restored.element('roadCancel').hidden,false);
});

test('completed visual jobs open replay, never the experiment presenter',async()=>{
  const f = await fixture('?video=upload&prepare=road','complete');
  assert.equal(f.context.location.href,'/workbench/replay.html?video=road');
});

test('failed and cancelled preparation retains detection and has no success redirect',async()=>{
  const f = await fixture('?video=upload&prepare=road','failed');
  assert.equal(f.context.location.href,'');
  assert.match(f.element('roadStatus').textContent,/failed/);
  assert.equal(f.element('roadCancel').hidden,true);
  assert.equal(f.element('start').disabled,false);
  const active = await fixture('?video=upload&prepare=road');
  await active.element('roadCancel').onclick();
  assert.match(active.element('roadStatus').textContent,/cancelled/);
  assert.equal(active.context.location.href,'');
});
test('studio deep-link never inherits a different completed session or its preview',async()=>{
  const old={id:'old-session',source_run:'old-video',source_name:'old.mp4',state:'complete',published_at:10,finished_at:10,
    last_observation:{completed_at:10,detections:[]}};
  const f=await fixture('?video=upload','processing',old);
  assert.equal(f.element('source').value,'upload');
  assert.equal(f.element('sourceName').textContent,'test.mp4');
  assert.equal(f.element('preview').hidden,true);
  assert.equal(f.element('report').hidden,true);
  assert.equal(f.scenes.at(-1)[0],null);
  assert.equal(f.scenes.at(-1)[2],'upload');
  // A running session is real work, and cannot be hidden by a different link.
  const active=await fixture('?video=upload','processing',{...old,state:'running'});
  assert.equal(active.element('source').value,'old-video');
  assert.equal(active.scenes.at(-1)[0].id,'old-session');
  assert.equal(active.scenes.at(-1)[2],'old-video');
  // After it stops, selecting another clip also invalidates any late JPEG load.
  const onload=active.element('preview').onload;
  active.state.session.state='complete';
  active.element('source').value='upload';
  active.element('source').onchange();
  onload();
  assert.equal(active.element('preview').hidden,true);
  assert.equal(active.scenes.at(-1)[0],null);
  assert.equal(active.scenes.at(-1)[2],'upload');
});
