const test = require('node:test'), assert = require('node:assert/strict');
const { LivePoses, registeredPoint } = require('../workbench/live-scene-math.js');
const identity = [[1,0,0],[0,1,0],[0,0,1]];
function geometry() {
  return { schema_version: 1, image_size: [1280,720], binding: { source_run: 'source', source_sha256: 'a'.repeat(64) },
    calibration: { anchors: [[100,100],[1100,100],[1100,650],[100,650]], width_m: 50, depth_m: 30,
                   road: [[100,100],[1100,100],[1100,650],[100,650]] },
    registration: Array.from({length: 100}, (_, i) => ({ frame_index: i*3+2, status: 'accepted', H: identity })) };
}
function session(sequence = 1, x = 600, extra = {}) {
  return { id: 'session', state: 'running', source_kind: 'paced-file', source_run: 'source', source_sha256: 'a'.repeat(64),
    last_observation: { sequence, frame_index: sequence*3-1, namespace: 'session:0', source_time_s: sequence*.1,
      completed_at: 10+sequence*.1, age_ms: 50, detections: [{ track_id: 1, x, y: 400, cls: 2, conf: .9 }], ...extra } };
}
test('live world positions depend on fresh detections and registered camera anchors', () => {
  const g = geometry();
  g.tracks = { forbidden: 'The adapter must never consume old vehicle trajectories' };
  const m = new LivePoses(g), s = session();
  const poses = m.update(s, 10.1).poses;
  assert.equal(poses.length, 1);
  assert.ok(Math.abs(poses[0].x) < 1e-8);
  assert.equal(poses[0].id, 'session:0:1');
  assert.equal(poses[0].headingKnown, false);
  assert.equal(m.update(session(2, 620), 10.2).poses[0].x > poses[0].x, true);
  assert.deepEqual(registeredPoint([[1,0,10],[0,1,20],[0,0,1]], [100,200]), [110,220]);
  assert.equal(registeredPoint([[1,0,0],[0,1,0],[0,0,-1]], [100,200]), null);
});
test('source mismatch, no frame identity, rejected mappings and stale observations fail closed', () => {
  const g = geometry(), m = new LivePoses(g);
  const cases = [
    {...session(), source_sha256: 'wrong'}, {...session(), source_run: 'wrong'},
    {...session(), source_kind: 'rtsp'}, session(1,600,{frame_index: null}),
    session(1,600,{frame_index: 3}), session(1,600,{completed_at: 1}),
    session(1,600,{age_ms: 1500}), session(1,600,{age_ms: null}),
    {...session(), state: 'stopped'}, {...session(), state: 'complete'},
  ];
  for (const s of cases) {
    assert.equal(m.update(session(),10.1).poses.length,1);
    const rejected = m.update(s,10.2);
    assert.equal(rejected.poses.length,0);
    assert.equal(rejected.hidden,1);
    assert.equal(m.tracks.size,0);
  }
  g.registration[0].status='rejected';
  assert.equal(new LivePoses(g).update(session(),10.1).poses.length,0);
});
test('missing detections, source-time gaps and namespaces do not bridge identities', () => {
  const m = new LivePoses(geometry());
  m.update(session(),10.1);
  assert.equal(m.update(session(2,600,{detections: []}),10.2).poses.length,0);
  assert.equal(m.update(session(3),10.3).poses[0].from,null);
  assert.equal(m.update(session(9,650),10.9).poses[0].from,null);
  const loop = session(10,600,{source_time_s: .1, namespace: 'session:1'});
  assert.equal(m.update(loop,11).poses[0].id,'session:1:1');
  assert.equal(m.result.poses[0].from,null);
});
test('outside-road detections and large position jumps are hidden', () => {
  const m = new LivePoses(geometry());
  m.update(session(),10.1);
  const jump = m.update(session(2,900),10.2);
  assert.equal(jump.poses.length,0); assert.equal(jump.jumps,1);
  assert.equal(m.update(session(3,900),10.3).poses[0].from,null);
  const outside=m.update(session(4,20),10.4);
  assert.equal(outside.poses.length,0); assert.equal(outside.hidden,1);
});
test('visual easing never extrapolates and repeated polling never grows histories', () => {
  const m = new LivePoses(geometry());
  m.update(session(),10.1);
  const result=m.update(session(2,620),10.2), target=result.poses[0].x;
  assert.ok(m.sample(10.25)[0].x < target);
  assert.equal(m.sample(100)[0].x,target);
  for(let i=0;i<1000;i++) m.update(session(2,620),10.3);
  assert.equal(m.tracks.get('session:0:1').history.length,2);
  assert.equal(m.tracks.size,1);
});
test('retained identities and history have hard memory bounds', () => {
  const m = new LivePoses(geometry());
  for(let i=1;i<=99;i++) {
    const detections=Array.from({length: 300}, (_,n) => ({ track_id: n, x:600, y:400, cls:2 }));
    const result=m.update(session(i,600,{detections}),10+i*.1);
    assert.equal(result.poses.length,256);
    assert.equal(result.hidden,44);
    assert.ok([...m.tracks.values()].every(t=>t.history.length<=8));
  }
});
test('duplicate frame mappings are rejected rather than guessed', () => {
  const g=geometry();g.registration.push(g.registration[0]);
  assert.throws(()=>new LivePoses(g),/Ambiguous/);
});
test('assisted geometry projects fresh observations, labels uncertainty and retains every source gate', () => {
  const g=geometry();g.projection_kind='operator-assisted-estimate';
  const m=new LivePoses(g);
  assert.match(m.update(session(),10.1).reason,/Operator-assisted perspective.*unvalidated/);
  assert.equal(m.result.poses.length,1);
  assert.equal(m.update({...session(),source_sha256:'other'},10.1).poses.length,0);
  assert.equal(m.update(session(1,600,{frame_index:3}),10.1).poses.length,0);
  assert.equal(m.update(session(1,600,{completed_at:1}),10.1).poses.length,0);
  assert.throws(()=>new LivePoses({...g,projection_kind:'unrectified-image-plane'}),/Unsupported ground/);
});
