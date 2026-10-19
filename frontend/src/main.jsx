import { useLocale, t as tr } from "./i18n";
import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { usePath, Link } from './navigation';
import { Header, Footer } from './components/Layout';
import Explore from './pages/Explore';
import Auth from './pages/Auth';
import Saved from './pages/Saved';
import Insights from './pages/Insights';
import { useAuth, loadMe, fetchSaved, putSaved, deleteSaved } from './auth';
import './design.css';
import './life.css';
import './motion.css';
import './details.css';
import './scrollbars.css';
import './planner.css';
import './live.css';
import './polish.css';
import './map-first.css';
import './mobile-app.css';
import './shapes.css';
import './pwa.css';
import './mobile-fit.css';
import './chat-places.css';
import './insights.css';
import './keyboard.css';
import './interaction-fixes.css';
import './chat-clean.css';
import './reference-layout.css';
import './page-frame.css';
import {initPwa} from './pwa';
import PwaExperience from './components/PwaExperience';
initPwa();

function App() {
  const language = useLocale();
  const path = usePath();
  const { user } = useAuth();
  const [saved, setSaved] = useState([]);
  useEffect(() => { loadMe(); }, []);
  useEffect(() => {  // logged in: favourites live in the account; guests keep them for this tab only
    if (!user) return;
    fetchSaved().then(server => setSaved(prev => {
      const ids = new Set(server.map(p => p.id));
      prev.filter(p => !ids.has(p.id)).forEach(p => putSaved(p).catch(() => {}));  // keep what a guest saved before logging in
      return [...server, ...prev.filter(p => !ids.has(p.id))];
    })).catch(() => {});
  }, [user?.id]);
  const toggleSaved = place => setSaved(prev => {
    const exists = prev.some(x => x.id === place.id);
    if (user) (exists ? deleteSaved(place.id) : putSaved(place)).catch(() => {});
    return exists ? prev.filter(x => x.id !== place.id) : [...prev, place];
  });
  useEffect(() => {
    if (path === '/') document.title = tr('SeruendeshAI — открой свою Астану');
    if (path === '/saved') document.title = tr('Избранное — SeruendeshAI');
    if (path === '/insights') document.title = tr('Для города — SeruendeshAI');
  }, [path, language]);
  const authMode = { '/login': 'login', '/register': 'register', '/forgot-password': 'reset', '/reset-password': 'confirm' }[path];
  if (authMode) return <Auth key={path} mode={authMode} />;
  return <div className={"app " + (path === "/" ? "map-app" : "")}><a className="skip-link" href="#content">{tr("Перейти к содержимому")}</a><Header path={path} savedCount={saved.length} /><div id="content">{path === '/' ? <Explore saved={saved} toggleSaved={toggleSaved} /> : path === '/saved' ? <Saved saved={saved} toggleSaved={toggleSaved} /> : path === '/insights' ? <Insights /> : <main className="not-found"><span className="section-eyebrow">{tr("404 / НЕМНОГО СВЕРНУЛИ С МАРШРУТА")}</span><h1>{tr("Здесь пока тихо.")}</h1><p>{tr("Вернёмся туда, где начинаются открытия?")}</p><Link to="/" className="primary-button">{tr("На главную ↗")}</Link></main>}</div><Footer /></div>;
}
createRoot(document.getElementById('root')).render(<><App /><PwaExperience /></>);
