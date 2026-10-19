import {useSyncExternalStore} from 'react';
import messages from './locales/messages.json';
const supported=['ru','kk','en'];
const listeners=new Set();
let language='ru';
try{const saved=localStorage.getItem('seruendesh.language');if(supported.includes(saved))language=saved}catch{}
const aliases=new Map();
for(const [key,values] of Object.entries(messages))for(const value of Object.values(values))if(!aliases.has(value))aliases.set(value,key);
export function t(value,params={}){if(typeof value!=='string')return value;const trimmed=value.trim();const key=messages[value]?value:(messages[trimmed]?trimmed:(aliases.get(value)||value));const result=language==='ru'?key:(messages[key]?.[language]??key);const spaced=key===trimmed&&value!==trimmed?value.slice(0,value.indexOf(trimmed))+result+value.slice(value.indexOf(trimmed)+trimmed.length):result;return spaced.replace(/\{(\w+)\}/g,(match,name)=>params[name]??match)}
export function getLanguage(){return language}
function syncDocument(){document.documentElement.lang=language}
export function setLanguage(next){if(!supported.includes(next)||next===language)return;language=next;try{localStorage.setItem('seruendesh.language',next)}catch{}syncDocument();listeners.forEach(fn=>fn())}
function subscribe(fn){listeners.add(fn);return()=>listeners.delete(fn)}
export function useLocale(){return useSyncExternalStore(subscribe,getLanguage,()=> 'ru')}
syncDocument();
