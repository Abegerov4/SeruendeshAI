import React, { useState } from 'react';
import { Sparkles } from 'lucide-react';
import { coverGroup } from '../api';
import { t as tr } from '../i18n';

// A real photo (Wikimedia Commons, credited) or a designed cover for the category.
// Covers are deliberately abstract so nobody mistakes them for the place itself.
export default function PlaceVisual({ place: p, credit = false, eager = false, illustrative = false }) {
  const [broken, setBroken] = useState(false);
  const Icon = p.icon || Sparkles;
  if (p.photo && !broken) return <span className="place-visual has-photo">
    <img src={p.photo.url} alt={p.name} loading={eager ? 'eager' : 'lazy'} decoding="async" onError={() => setBroken(true)} />
    {credit && <a className="photo-credit" href={p.photo.page || p.photo.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}>
      {tr('Фото')}: {p.photo.author} · {p.photo.license}</a>}
  </span>;
  const group = p.cover || coverGroup(p.categoryKey);
  const art = {green:'/images/stories/walk.webp',coffee:'/images/stories/coffee.webp',food:'/images/stories/coffee.webp',culture:'/images/astana-hero.webp',landmark:'/images/astana-hero.webp'}[group];
  if(illustrative && art && !p.generated) return <span className="place-visual concept-photo"><img src={art} alt={tr('AI-визуализация')} loading="lazy"/><span className="concept-photo-label">{tr('AI-визуализация')}</span></span>;
  return <span className={'place-visual place-cover cover-' + (p.generated ? 'idea' : group)} role="img" aria-label={tr('Обложка категории')}>
    <svg className="cover-pattern" viewBox="0 0 400 240" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <circle cx="330" cy="40" r="120" /><circle cx="330" cy="40" r="80" /><circle cx="330" cy="40" r="40" />
      <path d="M0 200 C80 170 140 230 220 196 S340 150 400 180" /><path d="M0 222 C90 196 150 246 230 216 S350 176 400 204" />
    </svg>
    <span className="cover-icon"><Icon size={34} strokeWidth={1.6} /></span>
  </span>;
}
