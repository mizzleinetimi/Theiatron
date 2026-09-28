/* Cosmetic framing only. Existing app behaviour, evidence and error gates stay intact. */
if(new URLSearchParams(location.search).get('presentation')==='1'){
  const page=location.pathname.split('/').pop().replace('.html','');
  if(['live','replay','demo'].includes(page))document.documentElement.dataset.presenterPage=page;
}
