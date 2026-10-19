import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
export const STATIC_FILES=['/manifest.webmanifest','/brand/secret-path.svg','/mascot/seru-wave.webp','/icons/icon-192.png','/icons/icon-512.png','/icons/maskable-512.png','/icons/apple-touch-icon.png'];
export function pwa(){return {name:'seru-pwa',apply:'build',generateBundle(_,bundle){
 const files=['/',...Object.keys(bundle).filter(f=>/\.(js|css)$/.test(f)).map(f=>'/'+f),...STATIC_FILES];
 const template=readFileSync(new URL('./service-worker.js',import.meta.url),'utf8');
 const hash=createHash('sha256').update(JSON.stringify(files)+String(bundle['index.html']?.source)+template);
 for(const file of STATIC_FILES)hash.update(readFileSync(new URL('../public'+file,import.meta.url)));
 const version=hash.digest('hex').slice(0,12);
 this.emitFile({type:'asset',fileName:'sw.js',source:template.replace('__VERSION__',JSON.stringify(version)).replace('__FILES__',JSON.stringify(files))});
}};}
