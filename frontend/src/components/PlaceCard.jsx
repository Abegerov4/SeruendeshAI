import { t as tr } from "../i18n";
import React, { useState } from 'react';
import PlaceDetails from './PlaceDetails';
import PlaceFacts from './PlaceFacts';
import { Heart, Footprints, Car, Clock3, MapPin, Sparkles, ChevronDown, Check } from 'lucide-react';
import { BADGE_LABELS } from '../api';

const SOURCE_NAMES = {osm: 'OpenStreetMap', wikidata: 'Wikidata', wikipedia: 'Wikipedia', overture: 'Overture Maps', ticketon: 'Ticketon', sxodim: 'Sxodim', citypass: 'CityPass Astana', khanshatyr: 'Хан Шатыр', mega_silkway: 'Mega Silk Way', llm: 'ИИ'};
const DESC_SOURCE = {wikipedia: 'описание из Википедии', osm: 'описание из OSM', template: 'описание собрано из тегов', generated: 'текст ИИ'};

export function TrustList({ p }) {
  const sources = [...new Set(p.dataSources.map(s => SOURCE_NAMES[s] || s))].join(', ');
  return <ul className="trust-list">
    <li><b>{tr('Источник')}</b><span>{p.generated ? tr('Идея ИИ без привязки к фактам') : sources || tr('Данные POI')}</span></li>
    {!p.generated && <li><b>{tr('Часы')}</b><span className={p.openConfidence === 'none' ? 'unknown' : ''}>{p.status}</span></li>}
    {!p.generated && <li><b>{tr('Удобства')}</b><span className={p.features.length ? '' : 'unknown'}>{p.features.length ? p.features.join(', ') : tr('Не подтверждены данными')}</span></li>}
    {!p.generated && p.accessibility !== 'unknown' && <li><b>{tr('Доступность')}</b><span>{tr({yes: 'Доступно для колясок (по данным источника)', limited: 'Доступно частично (по данным источника)', no: 'Недоступно для колясок (по данным источника)'}[p.accessibility])}</span></li>}
    {p.description && !p.generated && (p.descriptionAttribution?.length ? p.descriptionAttribution.map((entry, i) =>
      <li key={entry.url + i}><b>{tr('Описание')}</b><span><a href={entry.url} target="_blank" rel="noreferrer">{entry.title}</a>{' · '}{entry.attribution}{' · '}<a href={entry.license_url} target="_blank" rel="noreferrer">{entry.license}</a><br /><small>{entry.notice}</small></span></li>) :
      p.descriptionSource && <li><b>{tr('Описание')}</b><span>{tr(DESC_SOURCE[p.descriptionSource] || p.descriptionSource)}</span></li>)}
  </ul>;
}

function shortHours(p) {
  const label = (p.status || '').replace(/\s*\(.*?\)\s*/g, ' ').replace(/\s*·.*$/, '').trim();
  if (p.openingKind === 'always') return tr('Открытая территория');
  if (p.openConfidence === 'none') return tr('Часы уточняй');
  return label.length > 26 ? label.slice(0, 26) + '…' : label;
}

export default function PlaceCard({ place: p, index = 0, selected, onSelect, saved, onSave, onHover, isNew = false }) {
  const [expanded, setExpanded] = useState(false);
  const tags = p.badges.filter(b => BADGE_LABELS[b] && b !== 'outdoor' && b !== 'indoor').slice(0, 2);
  const Mode = p.mode === 'walk' ? Footprints : Car;
  return <><article onMouseEnter={() => onHover?.(p.id)} onMouseLeave={() => onHover?.(null)} onFocus={() => onHover?.(p.id)} onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget)) onHover?.(null) }} data-place-id={p.id} className={'place-card ' + (selected ? 'selected' : '')} style={{ '--order': index }}>
    <div className="place-image-wrap"><button className="place-image-button" onClick={() => setExpanded(true)} aria-haspopup="dialog" aria-label={tr('Подробнее: ') + p.name}><img src={p.image} alt={tr(p.imageNote)} loading="lazy" /><span className="image-shade" /><span className="place-category"><p.icon size={13} />{p.category}</span><span className="place-number">{p.generated ? '✦' : '0' + (index + 1)}</span></button>
      {onSave && <button className={'save-button ' + (saved ? 'saved' : '')} aria-label={saved ? tr('Убрать из избранного') : tr('Сохранить ') + p.name} aria-pressed={saved} onClick={onSave}><Heart size={17} fill={saved ? 'currentColor' : 'none'} /></button>}
    </div>
    <div className="place-content">
      <div className="place-title-row"><button onClick={() => setExpanded(true)} aria-haspopup="dialog"><h3>{p.name}</h3></button></div>
      {isNew && <span className="new-place-badge">{tr("Новое")}</span>}
      {tags.length > 0 && <div className="story-tags">{tags.map(b => <span key={b}>✦ {tr(BADGE_LABELS[b])}</span>)}</div>}
      {!p.generated && <div className="place-meta"><span><Mode size={13} />{p.distance} · {p.travel}{tr(" мин")}</span><span><Clock3 size={13} />{p.visitRange ? `${p.visitRange[0]}–${p.visitRange[1]}` : p.visit}{tr(" мин на месте")}</span></div>}
      <p className="place-why"><span>{tr(p.generated ? "Идея" : "Почему тебе подойдёт")}</span>{p.why}</p>
      {!p.generated && <div className="place-action"><span><Check size={12} />{tr("Что делать")}</span><p>{p.action}</p></div>}
      {!p.generated && <PlaceFacts place={p} />}
      {(p.leaveBy || p.event) && <div className="badge-row">{p.leaveBy && <span className="leave">{tr('Выйти до')} {p.leaveBy}</span>}{p.event && <span className="event">{tr('Событие в')} {p.event.starts_at}</span>}</div>}
      {p.event && <p className="event-line">🎟 {p.event.title}{p.event.url && <> · <a href={p.event.url} target="_blank" rel="noreferrer">{p.event.source === 'sxodim' ? 'Sxodim' : 'Ticketon'}</a></>}</p>}
      <div className="place-bottom"><div className="card-chips">{!p.generated && <span className={'hours-chip ' + (p.openingKind === 'always' ? 'open' : p.openStatus === 'open' && p.openConfidence === 'high' ? 'open' : p.openConfidence === 'none' ? 'unknown' : 'maybe')}><Clock3 size={12} />{shortHours(p)}</span>}<span className={'source ' + (p.generated ? 'ai-source' : '')}>{p.generated ? <Sparkles size={12} /> : <MapPin size={12} />} {tr(p.generated ? 'Идея Серу' : 'Из базы мест')}</span></div><button className="detail-toggle" onClick={() => setExpanded(true)} aria-haspopup="dialog">{tr("Подробнее")}<ChevronDown size={13} /></button></div>
    </div></article>{expanded && <PlaceDetails place={p} saved={saved} onSave={onSave} onClose={() => setExpanded(false)} onMap={onSelect} />}</>;
}

export function SkeletonCard() {
  return <div className="skeleton-card" aria-hidden="true"><div className="sk-img" /><div className="sk-line" /><div className="sk-line short" /><div className="sk-line" /></div>;
}
