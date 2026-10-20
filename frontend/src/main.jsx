import { useLocale, t as tr } from "./i18n";
import React, { useEffect, useRef, useState } from 'react';
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
import './usability.css';
import './chat-only.css';
import {initPwa} from './pwa';
import PwaExperience from './components/PwaExperience';
initPwa();

function App() {
  const { user, ready } = useAuth();
  useEffect(() => { loadMe(); }, []);
  // A new owner gets a new workspace: no account data survives logout or account switches.
  return <Workspace key={user?.id ?? 'guest'} user={user} ready={ready} />;
}

function Workspace({user, ready}) {
  const language = useLocale();
  const path = usePath();
  const [saved, setSaved] = useState([]);
  const [saveError, setSaveError] = useState(null), [reload, setReload] = useState(0);
  const busy = useRef(false), loaded = useRef(!user);
  const lifetime = useRef(null);
  useEffect(() => {
    const ac = new AbortController(); lifetime.current = ac;
    loaded.current = !user;
    if (user) fetchSaved(ac.signal).then(server => {
      if (!ac.signal.aborted) { setSaved(server); loaded.current = true; setSaveError(null); }
    }).catch(() => { if (!ac.signal.aborted) setSaveError({load: true}); });
    return () => ac.abort();
  }, [user?.id, reload]);
  async function toggleSaved(place) {
    if (!ready || busy.current) return false;
    if (!loaded.current) { setSaveError({load: true}); return false; }
    const exists = saved.some(x => x.id === place.id), before = saved;
    setSaved(exists ? saved.filter(x => x.id !== place.id) : [...saved, place]);
    setSaveError(null);
    if (!user) return true;
    busy.current = true;
    const signal = lifetime.current.signal;
    try { await (exists ? deleteSaved(place.id, signal) : putSaved(place, signal)); return true; }
    catch { if (!signal.aborted) { setSaved(before); setSaveError({place}); } return false; }
    finally { busy.current = false; }
  }
  useEffect(() => {
    if (path === '/') document.title = tr('SeruendeshAI — открой свою Астану');
    if (path === '/saved') document.title = tr('Избранное — SeruendeshAI');
    if (path === '/insights') document.title = tr('Для города — SeruendeshAI');
  }, [path, language]);
  const authMode = { '/login': 'login', '/register': 'register', '/forgot-password': 'reset', '/reset-password': 'confirm' }[path];
  if (authMode) return <Auth key={path} mode={authMode} />;
  return <div className={"app " + (path === "/" ? "map-app" : "")}><a className="skip-link" href="#content">{tr("Перейти к содержимому")}</a><Header path={path} savedCount={saved.length} />{saveError && <div className="saved-feedback" role="alert"><span>{tr(saveError.load ? 'Не удалось загрузить избранное.' : 'Не удалось изменить избранное. Изменение отменено.')}</span><button onClick={() => saveError.load ? setReload(n => n + 1) : toggleSaved(saveError.place)}>{tr('Повторить')}</button><button aria-label={tr('Закрыть')} onClick={() => setSaveError(null)}>×</button></div>}<div id="content">{path === '/' ? <Explore saved={saved} toggleSaved={toggleSaved} /> : path === '/saved' ? <Saved saved={saved} toggleSaved={toggleSaved} /> : path === '/insights' ? <Insights /> : <main className="not-found"><span className="section-eyebrow">{tr("404 / НЕМНОГО СВЕРНУЛИ С МАРШРУТА")}</span><h1>{tr("Здесь пока тихо.")}</h1><p>{tr("Вернёмся туда, где начинаются открытия?")}</p><Link to="/" className="primary-button">{tr("На главную ↗")}</Link></main>}</div><Footer /></div>;
}
createRoot(document.getElementById('root')).render(<><App /><PwaExperience /></>);
