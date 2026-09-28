const test=require('node:test'),assert=require('node:assert/strict');
const {LiveUpload}=require('../workbench/live-upload.js');
function fixture({reserve}={}) {
  const calls=[],requests=[],progress=[];
  class XHR {
    constructor(){this.upload={};this.headers={};requests.push(this);}
    open(method,url){this.method=method;this.url=url;}
    setRequestHeader(k,v){this.headers[k]=v;}
    send(body){this.body=body;}
    abort(){this.onabort?.();}
    finish(status,body){this.status=status;this.responseText=JSON.stringify(body);this.onload();}
  }
  const write=async(path,body)=>{calls.push({path,body});return path==='/api/live/uploads'?(reserve?await reserve:{id:'reserved'}):{busy:false};};
  const client=new LiveUpload({write,token:'local-token',XHR,onProgress:(...args)=>progress.push(args)});
  return {client,calls,requests,progress};
}
const file={name:'new.mov',size:123};
test('uploads only after reservation, carries token and reports real progress',async()=>{
  const f=fixture(),result=f.client.start(file,{fps:10,duration:30,loop:false});
  await Promise.resolve();await Promise.resolve();
  assert.equal(f.calls[0].body.size_bytes,123);
  assert.equal(f.requests[0].url,'/api/live/uploads/reserved/content');
  assert.equal(f.requests[0].headers['X-Theiatron-Token'],'local-token');
  assert.equal(f.requests[0].body,file);
  f.requests[0].upload.onprogress({loaded:50,total:123});
  assert.deepEqual(f.progress,[[50,123]]);
  f.requests[0].finish(202,{source:{id:'reserved'},live:{busy:true}});
  assert.equal((await result).live.busy,true);
});
test('cancellation before reservation returns cancels the slot without sending bytes',async()=>{
  let resolve;const reservation=new Promise(r=>resolve=r),f=fixture({reserve:reservation});
  const outcome=assert.rejects(f.client.start(file,{}),/cancelled/);
  await f.client.cancel();resolve({id:'late'});await outcome;
  assert.equal(f.requests.length,0);
  assert.equal(f.calls[1].path,'/api/live/uploads/late/cancel');
});
test('cancellation during transfer aborts bytes and cancels its owned server job',async()=>{
  const f=fixture(),outcome=assert.rejects(f.client.start(file,{}),/cancelled/);
  await Promise.resolve();await Promise.resolve();
  await f.client.cancel();await outcome;
  assert.equal(f.calls.at(-1).path,'/api/live/uploads/reserved/cancel');
});
test('late cancellation after transfer stops its source-specific session server-side',async()=>{
  const f=fixture(),result=f.client.start(file,{});
  await Promise.resolve();await Promise.resolve();
  f.requests[0].finish(202,{source:{id:'reserved'},live:{busy:true}});
  await result;await f.client.cancel();
  assert.equal(f.calls.at(-1).path,'/api/live/uploads/reserved/cancel');
});
test('invalid size and transfer errors never masquerade as a running detector',async()=>{
  const f=fixture();
  await assert.rejects(f.client.start({...file,size:0},{}),/nonempty/);
  assert.equal(f.calls.length,0);
  const outcome=assert.rejects(f.client.start(file,{}),/busy/);
  await Promise.resolve();await Promise.resolve();
  f.requests[0].finish(409,{error:'worker busy'});await outcome;
});
