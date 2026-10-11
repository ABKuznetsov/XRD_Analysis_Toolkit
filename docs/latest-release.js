(function(){
 'use strict';
 const endpoint='https://api.github.com/repos/ABKuznetsov/XRD_Analysis_Toolkit/releases/latest';
 const classifiers={mac:name=>/\.pkg$/i.test(name),windows:name=>/\.exe$/i.test(name),linux:name=>/amd64\.deb$/i.test(name)};
 function apply(assets){
  for(const link of document.querySelectorAll('[data-platform],a[data-eid^="installer-link-"]')){
   const index=Number((link.dataset.eid||'').replace('installer-link-',''));
   const platform=link.dataset.platform||['mac','windows','linux'][index];
   const asset=assets.find(a=>classifiers[platform]?.(a.name||'')&&!/secure/i.test(a.name||''));
   if(asset&&/^https:\/\/github\.com\/ABKuznetsov\/XRD_Analysis_Toolkit\/releases\/download\//.test(asset.browser_download_url||'')){
    link.href=asset.browser_download_url;link.dataset.releaseResolved='true';
   }
  }
 }
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),4000);
 let assets=[];
 new MutationObserver(()=>{if(assets.length)apply(assets)}).observe(document.body,{childList:true,subtree:true});
 fetch(endpoint,{signal:controller.signal,headers:{Accept:'application/vnd.github+json'},credentials:'omit',referrerPolicy:'no-referrer'})
  .then(response=>response.ok?response.json():null).then(release=>{assets=release?.assets||[];apply(assets)})
  .catch(()=>{}).finally(()=>clearTimeout(timer));
})();
