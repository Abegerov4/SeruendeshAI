const VERSION=__VERSION__;
const FILES=__FILES__;
const CACHE='seru-shell-'+VERSION;
const allowed=new Set(FILES);
self.addEventListener('install',event=>event.waitUntil((async()=>{
 const cache=await caches.open(CACHE);
 try{await cache.addAll(FILES);}catch(error){await caches.delete(CACHE);throw error;}
})()));
self.addEventListener('activate',event=>event.waitUntil((async()=>{
 for(const key of await caches.keys())if(key.startsWith('seru-shell-')&&key!==CACHE)await caches.delete(key);
 await self.clients.claim();
})()));
self.addEventListener('message',event=>{if(event.data?.type==='ACTIVATE_UPDATE')self.skipWaiting();});
self.addEventListener('fetch',event=>{
 const req=event.request,url=new URL(req.url);
 // Never store API responses, credentials, photos submitted by users, or external map tiles.
 if(req.method!=='GET'||url.origin!==self.location.origin||url.pathname.startsWith('/api/'))return;
 if(req.mode==='navigate'){
  event.respondWith(fetch(req).then(async response=>response.ok?response:(await caches.match('/'))||response).catch(()=>caches.match('/')));return;
 }
 if(!allowed.has(url.pathname)||url.search)return;
 event.respondWith(caches.match(url.pathname).then(cached=>cached||fetch(req)));
});
