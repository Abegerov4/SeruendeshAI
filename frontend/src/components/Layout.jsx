import { t as tr } from "../i18n";
import React, { useEffect, useRef, useState } from 'react';
import LanguageSwitcher from './LanguageSwitcher';
import { MapPin, ArrowUpRight, Compass, Heart, ArrowLeft, LogOut, UserRound, Trash2, Smartphone, BarChart3, CalendarDays } from 'lucide-react';
import { Link, navigate } from '../navigation';
import { useAuth, logout, deleteAccount } from '../auth';

export function Logo() {
  return <Link className="brand" to="/" aria-label={tr("SeruendeshAI — главная")}><img src="/brand/secret-path.svg" alt="" /><span>Seruendesh<span className="brand-ai">AI</span></span></Link>;
}

function AccountMenu({ user }) {
  const [open, setOpen] = useState(false), box = useRef(null);
  useEffect(() => {
    if (!open) return;
    const close = e => { if (!box.current?.contains(e.target)) setOpen(false); };
    const esc = e => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('pointerdown', close); document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('pointerdown', close); document.removeEventListener('keydown', esc); };
  }, [open]);
  async function remove() {
    if (!confirm(tr('Удалить аккаунт и всё избранное? Это нельзя отменить.'))) return;
    await deleteAccount(); navigate('/');
  }
  return <div className="account-menu" ref={box}>
    <button className="login-link account-button" aria-expanded={open} onClick={() => setOpen(!open)}><UserRound size={15} />{user.name.split(' ')[0]}</button>
    {open && <div className="account-dropdown" role="menu">
      <span className="account-email">{user.email}</span>
      <Link to="/saved" role="menuitem" onClick={() => setOpen(false)}><Heart size={15} />{tr('Избранное')}</Link>
      <button role="menuitem" onClick={async () => { setOpen(false); await logout(); }}><LogOut size={15} />{tr('Выйти')}</button>
      <button role="menuitem" className="danger" onClick={remove}><Trash2 size={15} />{tr('Удалить аккаунт')}</button>
    </div>}
  </div>;
}

export function Header({ path, savedCount }) {
  const { user } = useAuth();
  return <header className="site-header"><Logo /><div id="header-slot" className="header-slot" /><nav aria-label={tr("Основная навигация")}><Link to="/" className={path === '/' ? 'active' : ''}><Compass size={16} />{tr("Прогулки")}</Link><Link to="/saved" className={path === '/saved' ? 'active' : ''}><Heart size={16} />{tr("Избранное")}{savedCount > 0 && <span className="nav-count">{savedCount}</span>}</Link><Link to="/insights" className={"nav-insights" + (path === "/insights" ? " active" : "")}><BarChart3 size={16} />{tr("Для города")}</Link><Link to="/events" className={"nav-events" + (path === "/events" || path.startsWith("/events/") ? " active" : "")} aria-current={path === "/events" || path.startsWith("/events/") ? "page" : undefined}><CalendarDays size={16} />{tr("События")}</Link></nav><div className="header-actions"><button className="app-install-trigger" aria-label={tr("Приложение и офлайн-прогулка")} title={tr("Приложение и офлайн-прогулка")} onClick={()=>window.dispatchEvent(new Event("seru-open-app"))}><Smartphone size={18}/></button><LanguageSwitcher /><span className="header-city"><MapPin size={15} />{tr("Астана")}</span>{user ? <AccountMenu user={user} /> : <Link to="/login" className="login-link">{tr("Войти")}<ArrowUpRight size={15} /></Link>}</div></header>;
}
export function Footer() {
  return <footer className="site-footer"><Logo /><span>{tr("Меньше планирования. Больше открытий.")}</span><Link to="/insights" className="footer-link">{tr("Для города: спрос и пробелы")}</Link><span className="footer-stamp">{tr("С любовью к Астане ")}<span>✳</span></span></footer>;
}
export function AuthHeader() {
  return <header className="auth-header"><Logo /><div className="auth-header-actions"><LanguageSwitcher /><Link to="/" className="back-link"><ArrowLeft size={16} /><span>{tr("Назад к городу")}</span></Link></div></header>;
}
