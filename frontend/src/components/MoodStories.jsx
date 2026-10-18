import { t as tr } from "../i18n";
import React from 'react';
import { ArrowUpRight, Sun, Coffee, Footprints } from 'lucide-react';
const stories = [{
  title: 'Просто выдохнуть',
  subtitle: 'Город, прогулка и никакой спешки',
  image: '/images/stories/walk.webp',
  icon: Footprints,
  scenario: 0,
  tag: 'ПОЙМАТЬ МОМЕНТ'
}, {
  title: 'На чашку счастья',
  subtitle: 'Тёплый кофе. Хорошая компания.',
  image: '/images/stories/coffee.webp',
  icon: Coffee,
  scenario: 1,
  tag: 'МАЛЕНЬКИЕ РАДОСТИ'
}, {
  title: 'Остаться до заката',
  subtitle: 'Когда знакомый город становится другим',
  image: '/images/astana-hero.webp',
  icon: Sun,
  scenario: 4,
  tag: 'ЗОЛОТОЙ ЧАС'
}];
export default function MoodStories({
  onChoose
}) {
  return <section className="mood-stories" aria-labelledby="moods-title"><div className="mood-heading"><h2 id="moods-title">{tr("А что, если сегодня…")}</h2><span>{tr("Выбери настроение ")}<span aria-hidden="true">↘</span></span></div><div className="mood-grid">{stories.map(s => <button className="mood-card" key={tr(s.title)} onClick={() => onChoose(s.scenario)}><img src={s.image} alt="" loading="lazy" /><span className="mood-shade" /><span className="mood-tag"><s.icon size={12} />{tr(s.tag)}</span><span className="mood-copy"><strong>{tr(s.title)}</strong><span>{tr(s.subtitle)}</span></span><span className="mood-arrow"><ArrowUpRight size={17} /></span></button>)}</div><span className="mood-disclaimer">{tr("Визуальные истории · AI-иллюстрации настроения")}</span></section>;
}
