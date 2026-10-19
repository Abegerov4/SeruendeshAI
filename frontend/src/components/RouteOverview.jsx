import React from 'react';
import {Clock3, Footprints, Car, ArrowRight, RotateCcw} from 'lucide-react';
import PlaceVisual from './PlaceVisual';
import {planTotals, formatDistance} from '../api';
import {t as tr} from '../i18n';

export default function RouteOverview({plan, selected, onSelect, onStart, loading, previous, onRestore}) {
 const places=(plan?.places||[]).filter(p=>!p.generated);
 const {total,sequence}=planTotals(plan);
 const ordered=sequence ? (plan.route.order||[]).map(s=>places.find(p=>p.id===(typeof s==='string'?s:s.poi_id))).filter(Boolean) : places;
 const rows=ordered.length?ordered:places;
 const Mode=plan?.used?.mode==='car'?Car:Footprints;
 const distance=sequence ? plan.route.legs?.reduce((n,l)=>n+(l.distance_m||0),0) : null;
 return <section className="reference-route" aria-label={tr('Твой маршрут')}>
  <div className="reference-route-title"><h2>{tr(sequence?'Твой маршрут':'Места рядом')}</h2><span>{tr('Мест: {n}', {n:places.length})}</span></div>
  {loading ? <p className="reference-route-status" role="status">{tr('Собираю прогулку…')}</p> : !places.length ? <p className="reference-route-status">{tr('Расскажи, чего хочется, — подберу места рядом.')}</p> : <>
  <ol className={sequence?'is-sequence':''}>{rows.map((p,i)=><li key={p.id}><button className={selected===p.id?'selected':''} onClick={()=>onSelect(p.id)}><span className="reference-stop">{i+1}</span><span className="reference-stop-photo"><PlaceVisual place={p} illustrative/></span><span className="reference-stop-copy"><b>{p.name}</b><small>{p.category}</small></span><span className="reference-stop-time">{p.visit} {tr('мин')}</span></button></li>)}</ol>
  <div className="reference-totals"><div><Mode size={20}/><span><b>{distance>0?formatDistance(distance):tr(plan?.used?.mode==='car'?'На авто':'Пешком')}</b><small>{tr(sequence?'Расстояние':'От точки старта')}</small></span></div><div><Clock3 size={20}/><span><b>{total} {tr('мин')}</b><small>{tr(sequence?'Общее время':'Дорога и посещение')}</small></span></div></div>
  <button className="reference-start" onClick={onStart}>{tr(sequence?'Начать прогулку':'Маршрут к месту')}<ArrowRight size={17}/></button>
  {previous&&<button className="reference-restore" onClick={onRestore}><RotateCcw size={13}/>{tr('Предыдущий вариант')}</button>}
  </>}
 </section>;
}
