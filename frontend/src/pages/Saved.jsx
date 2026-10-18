import { t as tr } from "../i18n";
import React from 'react';
import { Heart, ArrowUpRight, MapPin } from 'lucide-react';
import PlaceCard from '../components/PlaceCard';
import Mascot from '../components/Mascot';
import { Link } from '../navigation';
export default function Saved({
  saved,
  toggleSaved
}) {
  return <main className="saved-page"><div className="saved-heading"><div><span className="section-eyebrow">{tr("ТВОЯ ЛИЧНАЯ КАРТА ВПЕЧАТЛЕНИЙ")}</span><h1>{tr("Хочется вернуться.")}</h1><p>{tr("Сохраняй места, которые откликнулись. Планы могут подождать.")}</p></div><span className="saved-count"><Heart size={19} />{saved.length}{tr(" места")}</span></div>{saved.length ? <><div className="saved-grid">{saved.map((p, i) => <PlaceCard key={p.id} place={p} index={i} saved onSave={() => toggleSaved(p)} />)}</div><p id="saved-tip" className="saved-session-note">{tr("Избранное хранится только до перезагрузки страницы. ")}<Link to="/">{tr("Вернуться к карте ")}<ArrowUpRight size={12} /></Link></p></> : <section className="saved-empty"><div className="saved-seru"><span className="saved-seru-orbit" /><Mascot /><span className="saved-seru-heart"><Heart size={22} fill="currentColor" /></span><span className="saved-seru-note">{tr("Тут будут твои любимые ♡")}</span></div><span className="section-eyebrow">{tr("МЕСТО ДЛЯ БУДУЩИХ ОТКРЫТИЙ")}</span><h2>{tr("Я уже присмотрел")}<br />{tr("кое-что для тебя.")}</h2><p>{tr("Нажми на сердечко в карточке.")}<br />{tr("Здесь соберётся твоя маленькая коллекция города.")}</p><Link to="/" className="primary-button">{tr("Найти своё место")}<ArrowUpRight size={17} /></Link></section>}<div className="saved-signup"><div><h3>{tr("Планы на большее?")}</h3><p>{tr("Скоро любимые места будут рядом на любом устройстве.")}</p></div><Link to="/register">{tr("Посмотреть регистрацию")}<ArrowUpRight size={16} /></Link></div></main>;
}
