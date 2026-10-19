import { t as tr } from "../i18n";
import React, { useState } from 'react';
import PlaceDetails from './PlaceDetails';
import PlaceVisual from './PlaceVisual';
import { Heart, Footprints, Car, Clock3, MapPin, Sparkles, ChevronRight, Check, Navigation, Globe, Phone } from 'lucide-react';
import { BADGE_LABELS, routeUrl, telUrl } from '../api';

const SOURCE_NAMES = {osm: 'OpenStreetMap', wikidata: 'Wikidata', wikipedia: 'Wikipedia', overture: 'Overture Maps', ticketon: 'Ticketon', sxodim: 'Sxodim', citypass: 'CityPass Astana', khanshatyr: 'Хан Шатыр', mega_silkway: 'Mega Silk Way', llm: 'ИИ'};
const DESC_SOURCE = {wikipedia: 'описание из Википедии', osm: 'описание из OSM', template: 'описание собрано из фактов о месте', generated: 'текст ИИ'};

export function TrustList({ p }) {
  const sources = [...new Set((p.dataSources || []).map(s => SOURCE_NAMES[s] || s))].join(', ');
  return <ul className="trust-list">
    <li><b>{tr('Источник')}</b><span>{p.generated ? tr('Идея ИИ без привязки к фактам') : sources || tr('Данные POI')}</span></li>
    {!p.generated && <li><b>{tr('Удобства')}</b><span className={p.features?.length ? '' : 'unknown'}>{p.features?.length ? p.features.join(', ') : tr('Не подтверждены данными')}</span></li>}
    {!p.generated && p.accessibility && p.accessibility !== 'unknown' && <li><b>{tr('Доступность')}</b><span>{tr({yes: 'Без ступенек (по данным OSM)', limited: 'Частично доступно (OSM)', no: 'Есть ступени (OSM)'}[p.accessibility])}</span></li>}
    {p.descriptionSource && !p.generated && <li><b>{tr('Описание')}</b><span>{tr(DESC_SOURCE[p.descriptionSource] || p.descriptionSource)}</span></li>}
    {p.photo && <li><b>{tr('Фото')}</b><span><a href={p.photo.page || p.photo.url} target="_blank" rel="noreferrer">{p.photo.author}</a>, {p.photo.license}, Wikimedia Commons</span></li>}
  </ul>;
}

export function hoursTone(p) {
  if (p.openingKind === 'always') return 'open';
  if (p.openConfidence === 'none') return 'unknown';
  if (p.openStatus === 'closed') return 'closed';
  return p.openStatus === 'open' && p.openConfidence === 'high' ? 'open' : 'maybe';
}

export function shortHours(p) {
  const label = (p.status || '').replace(/\s*\(.*?\)\s*/g, ' ').replace(/\s*[·—].*$/, '').trim();
  if (p.openingKind === 'always') return tr('Открытая территория');
  if (p.openConfidence === 'none') return tr('Часы уточняй');
  return label.length > 28 ? label.slice(0, 28) + '…' : label;
}

export default function PlaceCard({ place: p, index = 0, selected, onSelect, saved, onSave, onHover, isNew = false, origin }) {
  const [expanded, setExpanded] = useState(false);
  const tags = (p.badges || []).filter(b => BADGE_LABELS[b] && b !== 'outdoor' && b !== 'indoor').slice(0, 2);
  const Mode = p.mode === 'walk' ? Footprints : Car;
  const open = () => setExpanded(true);
  const route = routeUrl(p, origin), tel = telUrl(p.phone);
  return <><article onMouseEnter={() => onHover?.(p.id)} onMouseLeave={() => onHover?.(null)} onFocus={() => onHover?.(p.id)} onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget)) onHover?.(null) }} data-place-id={p.id} className={'place-card ' + (selected ? 'selected ' : '') + (p.generated ? 'idea-card' : '')} style={{ '--order': index }}>
    <div className="place-image-wrap"><button className="place-image-button" onClick={open} aria-haspopup="dialog" aria-label={tr('Подробнее: ') + p.name}><PlaceVisual place={p} /><span className="image-shade" /><span className="place-category"><p.icon size={13} />{p.category}</span><span className="place-number">{p.generated ? '✦' : String(index + 1).padStart(2, '0')}</span></button>
      {onSave && <button className={'save-button ' + (saved ? 'saved' : '')} aria-label={saved ? tr('Убрать из избранного') : tr('Сохранить ') + p.name} aria-pressed={saved} onClick={onSave}><Heart size={17} fill={saved ? 'currentColor' : 'none'} /></button>}
      {p.photo && <span className="photo-badge">{tr('Фото')} · {p.photo.license}</span>}
    </div>
    <div className="place-content">
      <div className="place-title-row"><button onClick={open} aria-haspopup="dialog"><h3>{p.name}</h3></button>{isNew && <span className="new-place-badge">{tr("Новое")}</span>}</div>
      {!p.generated && <div className="place-meta"><span><Mode size={14} />{p.distance} · {p.travel}{tr(" мин")}</span><span><Clock3 size={14} />{p.visitRange ? `${p.visitRange[0]}–${p.visitRange[1]}` : p.visit}{tr(" мин на месте")}</span></div>}
      {!p.generated && <div className="card-status"><span className={'hours-chip ' + hoursTone(p)}><i />{shortHours(p)}</span>{tags.map(b => <span key={b} className="story-tag">{tr(BADGE_LABELS[b])}</span>)}</div>}
      <p className="place-why"><span>{tr(p.generated ? "Идея" : "Почему тебе подойдёт")}</span>{p.why}</p>
      {!p.generated && p.action && <div className="place-action"><span><Check size={12} />{tr("Что делать")}</span><p>{p.action}</p></div>}
      {(p.leaveBy || p.event) && <div className="badge-row">{p.leaveBy && <span className="leave">{tr('Выйти до')} {p.leaveBy}</span>}{p.event && <span className="event">🎟 {p.event.title} · {p.event.starts_at}</span>}</div>}
      <div className="place-bottom">
        <div className="quick-actions">
          {!p.generated && route && <a href={route} target="_blank" rel="noreferrer" aria-label={tr('Маршрут в 2GIS')} title={tr('Маршрут в 2GIS')}><Navigation size={15} /><span>{tr('Маршрут')}</span></a>}
          {p.website && <a href={p.website} target="_blank" rel="noreferrer nofollow" aria-label={tr('Сайт места')} title={tr('Сайт места')}><Globe size={15} /></a>}
          {tel && <a href={tel} aria-label={tr('Позвонить')} title={tr('Позвонить')}><Phone size={15} /></a>}
          <span className={'source ' + (p.generated ? 'ai-source' : '')}>{p.generated ? <Sparkles size={12} /> : <MapPin size={12} />} {tr(p.generated ? 'Идея Серу' : 'Из базы мест')}</span>
        </div>
        <button className="detail-toggle" onClick={open} aria-haspopup="dialog">{tr("Подробнее")}<ChevronRight size={14} /></button>
      </div>
    </div></article>{expanded && <PlaceDetails place={p} saved={saved} onSave={onSave} onClose={() => setExpanded(false)} onMap={onSelect} origin={origin} />}</>;
}

export function SkeletonCard() {
  return <div className="skeleton-card" aria-hidden="true"><div className="sk-img" /><div className="sk-line" /><div className="sk-line short" /><div className="sk-line" /></div>;
}
