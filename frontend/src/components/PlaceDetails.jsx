import React, { useEffect, useRef, useId, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Heart, MapPin, Clock3, Footprints, Car, ArrowUpRight, Navigation, Globe, Phone, Instagram, Share2, Utensils, BookOpen, Check } from 'lucide-react';
import { t as tr } from '../i18n';
import { TrustList, hoursTone, shortHours } from './PlaceCard';
import PlaceVisual from './PlaceVisual';
import { externalMapLinks, routeUrl, telUrl, instagramUrl } from '../api';

export default function PlaceDetails({ place: p, saved, onSave, onClose, onMap, origin }) {
  const dialog = useRef(null), title = useId();
  const [shared, setShared] = useState(false);
  useEffect(() => { const previous = document.activeElement; const overflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; dialog.current.showModal(); return () => { document.body.style.overflow = overflow; if (previous?.isConnected) previous.focus({ preventScroll: true }); } }, []);
  const Mode = p.mode === 'walk' ? Footprints : Car;
  const route = routeUrl(p, origin), tel = telUrl(p.phone), insta = instagramUrl(p.instagram);
  async function share() {
    const url = route || location.href, text = `${p.name} — ${p.why || ''}`.trim();
    try {
      if (navigator.share) await navigator.share({ title: p.name, text, url });
      else { await navigator.clipboard.writeText(`${p.name}\n${url}`); setShared(true); setTimeout(() => setShared(false), 1800); }
    } catch { /* the user closed the share sheet */ }
  }
  return createPortal(<dialog ref={dialog} className="place-dialog" aria-labelledby={title} onCancel={e => { e.preventDefault(); onClose(); }} onClick={e => { if (e.target === e.currentTarget) { const r = e.currentTarget.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) onClose(); } }}>
    <div className="detail-hero"><PlaceVisual place={p} credit eager /><span className="detail-category"><p.icon size={15} />{p.category}</span></div>
    <button autoFocus className="detail-close" onClick={onClose} aria-label={tr('Закрыть подробности')}><X size={21} /></button>
    <div className="detail-body"><span className="section-eyebrow">{tr(p.generated ? 'ИДЕЯ ИИ' : 'МАЛЕНЬКОЕ ОТКРЫТИЕ')}</span><h2 id={title}>{p.name}</h2>
      {!p.generated && <div className="detail-actions">
        {route && <a className="primary" href={route} target="_blank" rel="noreferrer"><Navigation size={17} />{tr('Маршрут')}</a>}
        {tel && <a href={tel}><Phone size={17} />{tr('Позвонить')}</a>}
        {p.website && <a href={p.website} target="_blank" rel="noreferrer nofollow"><Globe size={17} />{tr('Сайт')}</a>}
        {insta && <a href={insta} target="_blank" rel="noreferrer nofollow"><Instagram size={17} />Instagram</a>}
        <button onClick={share}>{shared ? <Check size={17} /> : <Share2 size={17} />}{tr(shared ? 'Скопировано' : 'Поделиться')}</button>
      </div>}
      <p className="detail-lead">{p.why}</p>
      {!p.generated && <div className="detail-facts">
        <div><Mode size={18} /><span><b>{p.travel} {tr(p.mode === 'walk' ? 'мин пешком' : 'мин в пути')}</b><small>{p.distance}</small></span></div>
        <div><Clock3 size={18} /><span><b>{p.visitRange ? `${p.visitRange[0]}–${p.visitRange[1]}` : p.visit} {tr('мин на месте')}</b><small>{tr('рекомендуем')} ~{p.visit} {tr('мин')}</small></span></div>
        <div className={'hours-fact ' + hoursTone(p)}><i /><span><b>{shortHours(p)}</b><small>{p.status}</small></span></div>
        {p.address && <div><MapPin size={18} /><span><b>{tr('Адрес')}</b><small>{p.address}</small></span></div>}
        {p.cuisine?.length > 0 && <div><Utensils size={18} /><span><b>{tr('Кухня')}</b><small>{p.cuisine.join(', ')}</small></span></div>}
      </div>}
      {!p.generated && p.action && <section><h3>{tr('Что делать')}</h3><p>{p.action}</p>{p.leaveBy && <p><b>{tr('Выйти до')} {p.leaveBy}</b> — {tr('чтобы успеть обратно с запасом.')}</p>}</section>}
      {p.event && <section><h3>{tr('Событие поблизости')}</h3><p>🎟 {p.event.title} · {p.event.starts_at}{p.event.price_from ? ` · ${tr('от')} ${p.event.price_from} ₸` : ''}</p>{p.event.url && <a href={p.event.url} target="_blank" rel="noreferrer">{tr('Билеты и детали')} <ArrowUpRight size={15} /></a>}</section>}
      {p.description && !p.generated && <section className="detail-about"><h3>{tr('О месте')}</h3><p>{p.description}</p>
        {p.descriptionUrl && <a href={p.descriptionUrl} target="_blank" rel="noreferrer"><BookOpen size={15} />{tr('Читать в Википедии')}<small> · CC BY-SA 4.0</small></a>}</section>}
      <section className="detail-before"><h3>{tr('Перед выходом')}</h3><TrustList p={p} />{p.openingRaw && <p><small>{tr('Часы в данных:')} <code>{p.openingRaw}</code></small></p>}
        <p className="detail-links">{p.url && <a href={p.url} target="_blank" rel="noreferrer">{tr('Источник данных')} <ArrowUpRight size={14} /></a>}{externalMapLinks(p).map(l => <a key={l.label} href={l.href} target="_blank" rel="noreferrer">{l.label} <ArrowUpRight size={14} /></a>)}</p></section>
      <p className="detail-note">{tr(p.photo ? 'Время рассчитано по открытым данным; проверь часы перед визитом.' : 'Обложка — иллюстрация категории, не снимок места. Время рассчитано по открытым данным; проверь часы перед визитом.')}</p></div>
    <div className="detail-toolbar">{onSave && <button className={'detail-save ' + (saved ? 'is-saved' : '')} aria-pressed={saved} onClick={onSave}><Heart size={18} fill={saved ? 'currentColor' : 'none'} />{tr(saved ? 'В избранном' : 'Сохранить место')}</button>}{onMap && <button className="detail-map" onClick={() => { onClose(); onMap(); }}><MapPin size={18} />{tr('Показать на карте')}</button>}</div>
  </dialog>, document.body);
}
