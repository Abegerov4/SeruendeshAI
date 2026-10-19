let installEvent=null,registration=null;
const emit=()=>window.dispatchEvent(new Event('seru-pwa'));
export function initPwa(){
 window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();installEvent=e;emit();});
 window.addEventListener('appinstalled',()=>{installEvent=null;emit();});
 if(import.meta.env.PROD&&'serviceWorker' in navigator&&window.isSecureContext){
  navigator.serviceWorker.register('/sw.js',{updateViaCache:'none'}).then(r=>{
   registration=r;emit();r.addEventListener('updatefound',()=>{const worker=r.installing;worker?.addEventListener('statechange',emit);});
   window.addEventListener('online',()=>r.update().catch(()=>{}));
  }).catch(()=>{});
 }
}
export const pwaState=()=>({canInstall:!!installEvent,update:!!registration?.waiting,installed:matchMedia('(display-mode: standalone)').matches||navigator.standalone===true});
export async function installApp(){if(!installEvent)return false;const event=installEvent;installEvent=null;await event.prompt();const result=await event.userChoice;emit();return result.outcome==='accepted';}
export function applyUpdate(){if(!registration?.waiting)return;navigator.serviceWorker.addEventListener('controllerchange',()=>location.reload(),{once:true});registration.waiting.postMessage({type:'ACTIVATE_UPDATE'});}
export const POCKET_KEY='seru.walk-pocket.v1';
export function readPocket(){try{const p=JSON.parse(localStorage.getItem(POCKET_KEY));return p?.version===1&&Array.isArray(p.places)&&p.places.every(x=>typeof x.name==='string')?p:null;}catch{return null;}}
export function savePocket(plan){
 const places=plan.places.filter(p=>!p.generated).slice(0,3).map(p=>({name:p.name,why:p.why,action:p.action,travel:p.travel,visit:p.visit,source:p.source,status:p.status}));
 const pocket={version:1,savedAt:Date.now(),places};localStorage.setItem(POCKET_KEY,JSON.stringify(pocket));emit();return pocket;
}
