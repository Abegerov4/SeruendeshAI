import React, { useEffect, useRef, useId } from 'react';
import { createPortal } from 'react-dom';
import { X, Heart, MapPin, Clock3, Footprints, Car, ArrowUpRight } from 'lucide-react';
import { t as tr } from '../i18n';
import { TrustList } from './PlaceCard';
import { externalMapLinks } from '../api';

export default function PlaceDetails({ place: p, saved, onSave, onClose, onMap }) {
  const dialog = useRef(null), title = useId();
  useEffect(() => { const previous = document.activeElement; const overflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; dialog.current.showModal(); return () => { document.body.style.overflow = overflow; if (previous?.isConnected) previous.focus({ preventScroll: true }); } }, []);
  const Mode = p.mode === 'walk' ? Footprints : Car;
  return createPortal(<dialog ref={dialog} className="place-dialog" aria-labelledby={title} onCancel={e => { e.preventDefault(); onClose(); }} onClick={e => { if (e.target === e.currentTarget) { const r = e.currentTarget.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) onClose(); } }}>
    <div className="detail-hero"><img src={p.image} alt={tr(p.imageNote)} /><span className="detail-category"><p.icon size={15} />{p.category}</span><span className="detail-image-note">{tr('Иллюстрация категории')}</span></div>
    <button autoFocus className="detail-close" onClick={onClose} aria-label={tr('Закрыть подробности')}><X size={21} /></button>
    <div className="detail-body"><span className="section-eyebrow">{tr(p.generated ? 'ИДЕЯ ИИ' : 'МАЛЕНЬКОЕ ОТКРЫТИЕ')}</span><h2 id={title}>{p.name}</h2><p className="detail-lead">{p.why}</p>
      {!p.generated && <div className="detail-facts"><span><Mode size={17} />{p.distance} · {p.travel} {tr(p.mode === 'walk' ? 'мин пешком' : 'мин в пути')}</span><span><Clock3 size={17} />{p.visitRange ? `${p.visitRange[0]}–${p.visitRange[1]}` : p.visit} {tr('мин на месте')}</span></div>}
      {!p.generated && <section><h3>{tr('Что делать')}</h3><p>{p.action}</p>{p.leaveBy && <p><b>{tr('Выйти до')} {p.leaveBy}</b> — {tr('чтобы успеть обратно с запасом.')}</p>}</section>}
      {p.event && <section><h3>{tr('Событие поблизости')}</h3><p>🎟 {p.event.title} · {p.event.starts_at}{p.event.price_from ? ` · ${tr('от')} ${p.event.price_from} ₸` : ''}</p>{p.event.url && <a href={p.event.url} target="_blank" rel="noreferrer">{tr('Билеты и детали')} <ArrowUpRight size={15} /></a>}</section>}
      {p.description && !p.generated && <section><h3>{tr('О месте')}</h3><p>{p.description}</p></section>}
      <section className="detail-before"><h3>{tr('Перед выходом')}</h3><TrustList p={p} />{p.openingRaw && <p><small>{tr('Часы в данных:')} <code>{p.openingRaw}</code></small></p>}{p.address && <p><MapPin size={13} /> {p.address}</p>}
        <p className="detail-links">{p.url && <a href={p.url} target="_blank" rel="noreferrer">{tr('Посмотреть источник ')}<ArrowUpRight size={15} /></a>}{externalMapLinks(p).map(l => <a key={l.label} href={l.href} target="_blank" rel="noreferrer"> · {tr('Открыть в')} {l.label} <ArrowUpRight size={13} /></a>)}</p></section>
      <p className="detail-note">{tr('Фото — иллюстрация категории, не снимок этого места. Время рассчитано по открытым данным; проверь часы перед визитом.')}</p></div>
    <div className="detail-toolbar">{onSave && <button className={'detail-save ' + (saved ? 'is-saved' : '')} aria-pressed={saved} onClick={onSave}><Heart size={18} fill={saved ? 'currentColor' : 'none'} />{tr(saved ? 'В избранном' : 'Сохранить место')}</button>}{onMap && <button className="detail-map" onClick={() => { onClose(); onMap(); }}><MapPin size={18} />{tr('Показать на карте')}</button>}</div>
  </dialog>, document.body);
}
