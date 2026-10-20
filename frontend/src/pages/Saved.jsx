import { t as tr } from "../i18n";
import React from 'react';
import { Heart, ArrowUpRight, MapPin } from 'lucide-react';
import PlaceCard from '../components/PlaceCard';
import Mascot from '../components/Mascot';
import { Link } from '../navigation';
import { useAuth } from '../auth';
// 1 место, 2–4 места, 0/5+ мест
const placesWord = n => (n % 10 === 1 && n % 100 !== 11) ? ' место' : ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) ? ' места' : ' мест';
export default function Saved({
  saved,
  toggleSaved
}) {
  const { user } = useAuth();
  return <main className="saved-page"><div className="saved-heading"><div><span className="section-eyebrow">{tr("ТВОЯ ЛИЧНАЯ КАРТА ВПЕЧАТЛЕНИЙ")}</span><h1>{tr("Хочется вернуться.")}</h1><p>{tr("Сохраняй места, которые откликнулись. Планы могут подождать.")}</p></div><span className="saved-count"><Heart size={19} />{saved.length}{tr(placesWord(saved.length))}</span></div>{saved.length ? <><p className="saved-session-note">{tr("Сохранённые данные могут устареть. Проверь часы перед выходом.")}</p><div className="saved-grid">{saved.map((p, i) => <PlaceCard key={p.id} place={p} index={i} saved onSave={() => toggleSaved(p)} />)}</div><p id="saved-tip" className="saved-session-note">{user ? tr("Избранное сохранено в твоём аккаунте. ") : tr("Войди, чтобы избранное сохранилось на любом устройстве. ")}<Link to={user ? '/' : '/login'}>{user ? tr("Вернуться к карте ") : tr("Войти ")}<ArrowUpRight size={12} /></Link></p></> : <section className="saved-empty"><div className="saved-seru"><span className="saved-seru-orbit" /><Mascot /><span className="saved-seru-heart"><Heart size={22} fill="currentColor" /></span><span className="saved-seru-note">{tr("Тут будут твои любимые ♡")}</span></div><span className="section-eyebrow">{tr("МЕСТО ДЛЯ БУДУЩИХ ОТКРЫТИЙ")}</span><h2>{tr("Я уже присмотрел")}<br />{tr("кое-что для тебя.")}</h2><p>{tr("Нажми на сердечко в карточке.")}<br />{tr("Здесь соберётся твоя маленькая коллекция города.")}</p><Link to="/" className="primary-button">{tr("Найти своё место")}<ArrowUpRight size={17} /></Link></section>}{!user && <div className="saved-signup"><div><h3>{tr("Планы на большее?")}</h3><p>{tr("Создай аккаунт — любимые места будут с тобой на любом устройстве.")}</p></div><Link to="/register">{tr("Создать аккаунт")}<ArrowUpRight size={16} /></Link></div>}</main>;
}
