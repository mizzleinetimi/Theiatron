(function(root){
  "use strict";
  const RUN=/^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$/;
  function runId(value){if(typeof value!=="string"||!RUN.test(value))throw Error("Invalid demo source or experiment. No sample was substituted.");return value;}
  function reportForSource(report,source){
    if(report?.source_run!==source||!report.valid||report.demand_basis!=="generated-not-observed")
      throw Error("A valid, source-matched generated-demand experiment is required. No substitute result was loaded.");
    for(const name of ["fixed","adaptive"]){
      const m=report.metrics?.[name];
      if(!m||![m.mean_delay_s,m.p95_delay_s,m.offered].every(v=>Number.isFinite(v)&&v>=0))
        throw Error("The selected report has incomplete metrics.");
    }
    if(report.metrics.fixed.offered!==report.metrics.adaptive.offered)throw Error("The experiment does not compare identical population sizes.");
    return report;
  }
  function comparisonFromFrame(href,origin,source){
    const u=new URL(href,origin);
    if(u.origin!==origin||u.pathname!=="/workbench/demo.html"||u.searchParams.get("video")!==source)
      throw Error("The embedded demo changed source. Return to this showcase's prepared footage before continuing.");
    return runId(u.searchParams.get("compare"));
  }
  function tailMessage(report){
    const f=report.metrics.fixed.p95_delay_s,a=report.metrics.adaptive.p95_delay_s;
    return `Long-wait check (95th percentile): ${f.toFixed(1)}s → ${a.toFixed(1)}s. ${a>f?"Worse in this run: the average result does not improve every outcome.":a<f?"Lower in this run; this is still a modelled result.":"Unchanged in this run."}`;
  }
  const api={runId,reportForSource,comparisonFromFrame,tailMessage};
  if(typeof module!=="undefined")module.exports=api;else root.ShowcaseMath=api;
})(typeof window!=="undefined"?window:globalThis);
