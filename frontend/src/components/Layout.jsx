import { t as tr } from "../i18n";
import React from 'react';
import LanguageSwitcher from './LanguageSwitcher';
import { MapPin, ArrowUpRight, Compass, Heart, ArrowLeft } from 'lucide-react';
import { Link } from '../navigation';
export function Logo() {
  return <Link className="brand" to="/" aria-label={tr("SeruendeshAI — главная")}><img src="/brand/secret-path.svg" alt="" /><span>Seruendesh<span className="brand-ai">AI</span></span></Link>;
}
export function Header({
  path,
  savedCount
}) {
  return <header className="site-header"><Logo /><nav aria-label={tr("Основная навигация")}><Link to="/" className={path === '/' ? 'active' : ''}><Compass size={16} />{tr("Открыть город")}</Link><Link to="/saved" className={path === '/saved' ? 'active' : ''}><Heart size={16} />{tr("Избранное")}{savedCount > 0 && <span className="nav-count">{savedCount}</span>}</Link></nav><div className="header-actions"><LanguageSwitcher/><span className="header-city"><MapPin size={15} />{tr("Астана")}</span><Link to="/login" className="login-link">{tr("Войти")}<ArrowUpRight size={15} /></Link></div></header>;
}
export function Footer() {
  return <footer className="site-footer"><Logo /><span>{tr("Меньше планирования. Больше открытий.")}</span><span className="footer-stamp">{tr("С любовью к Астане ")}<span>✳</span></span></footer>;
}
export function AuthHeader() {
  return <header className="auth-header"><Logo /><div className="auth-header-actions"><LanguageSwitcher/><Link to="/" className="back-link"><ArrowLeft size={16} /><span>{tr("Назад к городу")}</span></Link></div></header>;
}
