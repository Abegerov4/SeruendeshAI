import React from 'react';
import { Clock3, Footprints, Car, RotateCcw, Presentation, Check, ArrowRight, LocateFixed, Flag } from 'lucide-react';
import { landmarks } from '../data';
import { MY_LOCATION, planTotals, diffPlans } from '../api';
import { describeContextChange } from '../planner';
import { t as tr } from '../i18n';

export function DemoPanel({ presenting, onToggle, onRun, onReset, simulateError, setSimulateError }) {
  return <section className="demo-controls"><div><span className="section-eyebrow">{tr('ЖИВЫЕ ЗАПРОСЫ К RAG-СЕРВЕРУ')}</span><h2>{tr('Покажи город за один запрос')}</h2></div>
    <div className="demo-buttons">{['Прогулка на 30 минут', 'Кофе поблизости', 'С ребёнком'].map((label, i) => <button key={label} onClick={() => onRun(i)}>{tr(label)}<ArrowRight size={14} /></button>)}</div>
    <div className="demo-tools"><button aria-pressed={presenting} onClick={onToggle}><Presentation size={16} />{tr('Для проектора')}</button><button onClick={onReset}><RotateCcw size={15} />{tr('Сбросить')}</button><label><input type="checkbox" checked={simulateError} onChange={e => setSimulateError(e.target.checked)} />{tr('Имитировать ошибку загрузки')}</label></div></section>;
}

export function ContextEditor({ context, onChange, onApply, onRefine, geoError }) {
  const set = patch => onChange({ ...context, ...patch });
  return <section className="context-editor" aria-label={tr('Контекст прогулки')}><strong>{tr('Контекст прогулки')}</strong>
    <div className="context-fields">
      <label>{tr('Район')}<select value={context.location} onChange={e => set({ location: e.target.value })}>{landmarks.map(l => <option key={l} value={l}>{l === MY_LOCATION ? '📍 ' : ''}{tr(l)}</option>)}</select></label>
      <label>{tr('Время на прогулку')}<select value={context.time} onChange={e => set({ time: Number(e.target.value), touched: { ...context.touched, time: true } })}>{[30, 60, 90, 120, 180].map(n => <option key={n} value={n}>{n} {tr('мин')}</option>)}</select></label>
      <label>{tr('Как добираться')}<select value={context.transport} onChange={e => set({ transport: e.target.value, touched: { ...context.touched, transport: true } })}><option value="walk">{tr('Пешком')}</option><option value="car">{tr('На авто')}</option><option value="transit">{tr('Транспорт')}</option></select></label>
    </div>
    {context.location === MY_LOCATION && <small><LocateFixed size={12} /> {context.coords ? tr('Локация округлена до ~100 м и не сохраняется.') : tr('Нажми «Применить» — браузер спросит разрешение на геолокацию.')}</small>}
    {geoError && <p className="geo-error">{tr(geoError)}</p>}
    <div className="context-refinements">{[['kid', 'С ребёнком'], ['accessible', 'Без ступенек']].map(([key, label]) => <button key={key} aria-pressed={!!context[key]} onClick={() => set({ [key]: !context[key] })}>{context[key] && <Check size={13} />} {tr(label)}</button>)}</div>
    <div className="context-refinements">{[['closer', 'Ближе'], ['noCoffee', 'Без кофе'], ['indoor', 'В помещении']].map(([key, label]) => <button key={key} aria-pressed={!!context[key]} onClick={() => onRefine(key)}>{context[key] && <Check size={13} />} {tr(label)}</button>)}</div>
    <button className="context-apply" onClick={onApply}>{tr('Применить контекст')}<ArrowRight size={15} /></button>
    <small>{tr('Уточнения пересчитывают подборку на сервере с тем же запросом.')}</small></section>;
}

export function RouteTimeline({ plan, previous, onRestore, onSelect }) {
  if (!plan) return null;
  const { total, sequence } = planTotals(plan);
  const budget = plan.used?.time_budget_min || plan.context.time;
  const diff = diffPlans(previous, plan);
  const changed = previous ? describeContextChange(previous.context, plan.context) : [];
  const byId = Object.fromEntries(plan.places.map(p => [p.id, p]));
  const Mode = plan.used?.mode === 'walk' ? Footprints : Car;
  const rows = sequence
    ? plan.route.legs.map(leg => ({ leg, place: byId[leg.to_id] }))
    : plan.places.filter(p => !p.generated).map(p => ({ leg: { travel_min: p.travel }, place: p }));
  return <section className="route-timeline"><div className="timeline-title"><div><span className="section-eyebrow">{tr('ТВОЙ ПЛАН')}</span><h2>{tr(sequence ? 'Прогулка по минутам' : 'Варианты рядом')}</h2></div><span><Clock3 size={17} />{total} / {budget} {tr('мин')}</span></div>
    <p className="applied-context">{plan.used?.location_label}{plan.used?.filters?.length ? ' · ' + plan.used.filters.join(' · ') : ''}</p>
    {diff && <div className="plan-diff" role="status"><span>{tr('Что изменилось')}: {changed.length ? changed.map(c => tr(c)).join(', ') + '. ' : ''}{diff.added.length ? tr('Добавлено') + ': ' + diff.added.join(', ') + '. ' : ''}{diff.removed.length ? tr('Убрано') + ': ' + diff.removed.join(', ') + '. ' : ''}{tr('Время')}: {diff.before} → {diff.after} {tr('мин')}.</span><button onClick={onRestore}><RotateCcw size={14} />{tr('Предыдущий вариант')}</button></div>}
    <ol>{rows.map(({ leg, place }, i) => place ? <li key={place.id + i}><span className="timeline-travel"><Mode size={14} />{leg.travel_min} {tr(plan.used?.mode === 'walk' ? 'мин пешком' : 'мин в пути')}</span><button onClick={() => onSelect(place.id)}><span className="timeline-number">{i + 1}</span><span>{place.name}{diff?.added.includes(place.name) && <em>{tr('Новое')}</em>}</span><strong>{place.visit} {tr('мин')}</strong></button></li>
      : <li key={'back' + i}><span className="timeline-travel"><Mode size={14} />{leg.travel_min} {tr(plan.used?.mode === 'walk' ? 'мин пешком' : 'мин в пути')}</span><button disabled><span className="timeline-number"><Flag size={12} /></span><span>{tr('Обратно к старту')}</span><strong /></button></li>)}</ol>
    {rows.length > 0 && <div className="time-budget"><span style={{ width: Math.min(100, total / budget * 100) + '%', background: total > budget ? '#c45a3c' : undefined }} /></div>}
    <small>{total > budget ? tr('Превышает твоё время — нажми «Ближе» или убери остановку.') : tr('Запас времени: {minutes} мин.', { minutes: Math.max(0, budget - total) })} {tr(sequence ? (plan.route.legs.some(l => l.geometry === 'network') ? 'Переходы посчитаны по графу улиц OSM.' : 'Переходы — оценка по прямой с поправкой на город.') : 'Каждый вариант: дорога + время на месте.')}</small></section>;
}
