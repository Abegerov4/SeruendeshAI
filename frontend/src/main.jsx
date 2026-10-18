import { useLocale, t as tr } from "./i18n";
import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { usePath, Link } from './navigation';
import { Header, Footer } from './components/Layout';
import Explore from './pages/Explore';
import Auth from './pages/Auth';
import Saved from './pages/Saved';
import './design.css';
import './life.css';
import './motion.css';
import './details.css';
import './scrollbars.css';
import './planner.css';
import './live.css';
function App() {
  const language = useLocale();
  const path = usePath();
  const [saved, setSaved] = useState([]);
  const toggleSaved = place => setSaved(prev => prev.some(x => x.id === place.id) ? prev.filter(x => x.id !== place.id) : [...prev, place]);
  useEffect(() => {
    if (path === '/') document.title = tr('SeruendeshAI — открой свою Астану');
    if (path === '/saved') document.title = tr('Избранное — SeruendeshAI');
  }, [path, language]);
  if (['/login', '/register', '/forgot-password'].includes(path)) return <Auth key={path} mode={path === '/register' ? 'register' : path === '/forgot-password' ? 'reset' : 'login'} />;
  return <div className="app"><a className="skip-link" href="#content">{tr("Перейти к содержимому")}</a><Header path={path} savedCount={saved.length} /><div id="content">{path === '/' ? <Explore saved={saved} toggleSaved={toggleSaved} /> : path === '/saved' ? <Saved saved={saved} toggleSaved={toggleSaved} /> : <main className="not-found"><span className="section-eyebrow">{tr("404 / НЕМНОГО СВЕРНУЛИ С МАРШРУТА")}</span><h1>{tr("Здесь пока тихо.")}</h1><p>{tr("Вернёмся туда, где начинаются открытия?")}</p><Link to="/" className="primary-button">{tr("На главную ↗")}</Link></main>}</div><Footer /></div>;
}
createRoot(document.getElementById('root')).render(<App />);
