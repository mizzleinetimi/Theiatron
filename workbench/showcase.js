(async function(){
  "use strict";
  const $=id=>document.getElementById(id),M=ShowcaseMath,q=new URLSearchParams(location.search);
  const chapters=[
    {kind:"",title:"",boundary:"",cue:"0:00–0:25 · Introduce the problem",action:"Say your name. Introduce Theiatron as a working software prototype, not a deployed traffic-light system.",speech:"Good evening. I’m [your name], founder of Theiatron. Traffic changes throughout the day, but a fixed timer cannot see a growing queue. We are developing camera-based traffic intelligence to help signals respond better. Today I’ll show what our software can do, and what still needs validation."},
    {kind:"REAL FOOTAGE / FRESH INFERENCE",title:"See the vehicles. Follow their movement.",boundary:"RECORDED SOURCE · FRESH DETECTION",cue:"0:25–1:10 · Start fresh detection; point to boxes and IDs",action:"Press Start fresh detection. Wait for moving boxes before claiming inference is running. The road beside it is a prepared estimate. Next stops this source's detection session.",speech:"This is recorded junction footage being processed now on this computer. The boxes and tracking IDs are fresh detector output, not a prerecorded detection animation. The software follows visible vehicles as frames arrive. This is the perception foundation for traffic measurement. Missed detections and ID changes still need independent evaluation. We have not yet demonstrated this on roadside Raspberry Pi hardware."},
    {kind:"SOURCE-SPECIFIC RECONSTRUCTION",title:"Inspect the same observations in 3D.",boundary:"RECORDED TRACKS · ESTIMATED GEOMETRY",cue:"1:10–1:30 · Press Play, then drag gently to orbit",action:"Press Play and orbit gently once. This chapter replays saved observations. Do not call it live detection or a surveyed digital twin.",speech:"Here, saved observations are reconstructed in an adjustable 3D view. This helps us inspect movement from another angle. The road geometry, scale and vehicle sizes are estimates, not a surveyed digital twin. That distinction matters before making real traffic decisions."},
    {kind:"ONE DEMAND SET / TWO CONTROLLER WORLDS",title:"Test a different signal decision.",boundary:"GENERATED TRAFFIC · REAL SUMO COMPUTATION",cue:"1:30–2:30 · Press Compute new comparison; let it finish",action:"Press Compute new comparison. Both worlds receive identical generated demand. Wait for the final result; this takes roughly 30 seconds plus startup. Do not call these arrivals measured from the video. A saved replay is available if fresh computation fails; say so explicitly.",speech:"Now I’m starting a new traffic simulation. Both worlds receive the same generated vehicles, routes and timing. One uses an actuated, presence-responsive comparator; the other uses Theiatron’s experimental control policy. SUMO computes the vehicle motion and delays independently in each world. We measure the difference instead of building in a promised percentage. This tests a junction hypothesis; it is not a claim that we have already improved traffic on this road."},
    {kind:"",title:"",boundary:"",cue:"2:30–3:00 · Show the result, caveat and pilot request",action:"Read the result currently displayed, not a rehearsed percentage if it differs. Show the long-wait check. Point to the evidence link and finish with the observation-only pilot request.",speech:"The result is traceable to its inputs, controller settings and simulation logs. In this example the average delay improves, but the longer-wait metric is worse—so more validation and controller work are necessary. We are seeking support for a supervised, observation-only pilot: validate with traffic engineers and labelled footage, then benchmark affordable edge hardware. Theiatron is a working software foundation with a clear path to testing its real-world value."}
  ];
  let source,comparison,token,step=-1,busy=false,ready=false;
  const active=new Set(["uploading","queued","processing","cancelling"]);
  async function read(path,options={}){
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
    try{const r=await fetch(path,{cache:"no-store",...options,signal:controller.signal});const body=await r.json();if(!r.ok)throw Error(body.error||`Request failed (${r.status})`);return body;}finally{clearTimeout(timeout);}
  }
  const write=(path,body)=>read(path,{method:"POST",headers:{"Content-Type":"application/json","X-Theiatron-Token":token},body:JSON.stringify(body)});
  function error(message){$("error").textContent=message;$("error").hidden=!message;}
  function controls(){document.querySelectorAll("[data-chapter]").forEach(b=>b.disabled=!ready||busy);$("previous").disabled=!ready||busy||step<=0;$("next").disabled=!ready||busy||step===4;}
  async function finishCurrent(){
    if(step===1){
      const state=await read("/api/live");
      if(state.busy){
        if(state.session?.source_run!==source)throw Error("Another source is running. Stop it in its live lab before continuing; this page will not interrupt it.");
        await write("/api/live/stop",{id:state.session.id});
        for(let i=0;i<20;i++){
          if(!(await read("/api/live")).busy)return;
          await new Promise(r=>setTimeout(r,250));
        }
        throw Error("Detection is still stopping. Wait a moment and choose the next chapter again.");
      }
    }
    if(step===3){
      const id=M.comparisonFromFrame($("demoFrame").contentWindow.location.href,location.origin,source);
      const job=await read(`/api/runs/${id}`);
      if(active.has(job.state))throw Error("The comparison is still computing. Wait for the final result before leaving this chapter.");
      if(job.state!=="complete")throw Error("This experiment did not complete. Select a completed saved experiment or retry; no previous result will be substituted.");
      M.reportForSource(job.results,source);comparison=id;
    }
  }
  async function evidence(){
    const job=await read(`/api/runs/${comparison}`);
    if(job.state!=="complete")throw Error("No completed experiment is available for this evidence chapter.");
    const r=M.reportForSource(job.results,source),names=DemoMath.policyNames(r.scenario);
    $("resultHeadline").textContent=DemoMath.outcome(r);
    $("resultBasis").textContent=`${r.metrics.fixed.offered} generated vehicles · ${r.scenario.duration} simulated seconds · seed ${r.scenario.seed}. ${names.candidate} versus ${names.baseline}.`;
    $("baselineDelay").textContent=`${r.metrics.fixed.mean_delay_s.toFixed(2)}s`;
    $("candidateDelay").textContent=`${r.metrics.adaptive.mean_delay_s.toFixed(2)}s`;
    $("baselineName").textContent=`${names.baseline} mean delay`;
    $("longWait").textContent=M.tailMessage(r);
    $("bundle").href=`/api/runs/${comparison}/evidence.zip`;
    $("report").href=`/out/${comparison}/report.json`;
    $("runIdentity").textContent=`Run ${comparison}`;
  }
  async function chapter(next){
    if(busy||next===step)return;busy=true;controls();error("");
    try{
      await finishCurrent();
      if(next===4)await evidence();
      $("demoFrame").removeAttribute("src");
      step=next;const c=chapters[step];
      $("opening").hidden=step!==0;$("application").hidden=![1,2,3].includes(step);$("evidence").hidden=step!==4;
      $("stageKind").textContent=c.kind;$("stageTitle").textContent=c.title;$("stageBoundary").textContent=c.boundary;
      $("stageHint").textContent=step===1?"Press Start fresh detection. Camera geometry is prepared; vehicles are inferred now. Next stops this session.":step===2?"Saved observations, original timing. Press Play; drag to orbit. Shape and scale remain estimated.":"Press Compute new comparison for fresh work. The preloaded result is explicitly a saved simulation, not a live run.";
      $("operatorAction").textContent=c.action;$("spoken").textContent=c.speech;$("cue").textContent=c.cue;
      $("next").textContent=step===0?"Show the working prototype →":step===3?"Show evidence & next step →":"Next chapter →";
      document.querySelectorAll("[data-chapter]").forEach(b=>b.setAttribute("aria-current",Number(b.dataset.chapter)===step?"step":"false"));
      $("demoFrame").hidden=![1,2,3].includes(step);
      if([1,2,3].includes(step)){
        const page=step===1?"live":step===2?"replay":"demo",params=new URLSearchParams({video:source,presentation:"1"});
        if(step===3){params.set("step","compare");params.set("compare",comparison);}
        $("demoFrame").src=`/workbench/${page}.html?${params}`;
      }
      const url=new URLSearchParams({video:source,compare:comparison,chapter:String(step)});
      history.replaceState({},"",`?${url}`);$("director").open=false;
      window.scrollTo(0,0);
    }catch(e){error(e.message);}finally{busy=false;controls();}
  }
  document.querySelectorAll("[data-chapter]").forEach(b=>b.onclick=()=>chapter(Number(b.dataset.chapter)));
  $("next").onclick=()=>chapter(Math.min(4,step+1));$("previous").onclick=()=>chapter(Math.max(0,step-1));
  try{
    source=M.runId(q.get("video")||"ui-20260912-162811-img-0635-ddba8b2c");
    comparison=M.runId(q.get("compare")||"ui-20260913-211331-img-0635-5f1625c9");
    const [health,recorded,job]=await Promise.all([read("/api/health"),read(`/api/runs/${source}/reconstruction`),read(`/api/runs/${comparison}`)]);
    token=health.token;
    if(!health.sumo?.ready)throw Error("SUMO is not ready. Run the local preflight before recording.");
    if(recorded.binding?.source_run!==source||job.state!=="complete")throw Error("The prepared source or completed comparison is unavailable.");
    M.reportForSource(job.results,source);
    $("cover").src=`/out/${source}/plate.jpg`;$("footageName").textContent=recorded.source_name;
    $("readiness").textContent="LOCAL DEMO READY";ready=true;
    const requested=Number(q.get("chapter")||0);await chapter(Number.isInteger(requested)&&requested>=0&&requested<=4?requested:0);
  }catch(e){error(e.message);$("readiness").textContent="DEMO NEEDS ATTENTION";controls();}
})();
