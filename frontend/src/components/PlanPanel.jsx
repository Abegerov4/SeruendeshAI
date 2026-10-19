import React from 'react';
import { Clock3, Footprints, Car, RotateCcw, Flag } from 'lucide-react';
import { planTotals, diffPlans } from '../api';
import { describeContextChange } from '../planner';
import { t as tr } from '../i18n';

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
    <small>{total > budget ? tr('Превышает твоё время — нажми «Ближе» или убери остановку.') : tr('Запас времени: {minutes} мин.', { minutes: Math.max(0, budget - total) })} {tr(sequence ? 'Время в пути — по реальным улицам.' : 'Для каждого места: дорога + время на месте.')}</small></section>;
}
