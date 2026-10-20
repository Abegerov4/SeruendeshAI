import { t as tr, getLanguage, useLocale } from "../i18n";
import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowUpRight, ArrowRight, MapPin, Clock3, Footprints, Car, SlidersHorizontal, Check, MessageCircle, Map, Compass, ShieldCheck, Sparkles, ChevronDown, Baby, Accessibility, Route, LocateFixed, Navigation, X } from 'lucide-react';
import RouteOverview from '../components/RouteOverview';
import PlaceDetails from '../components/PlaceDetails';
import Chat from '../components/Chat';
import Mascot from '../components/Mascot';
import MoodStories from '../components/MoodStories';
import CityMap from '../components/MapView';
import PlaceCard, { SkeletonCard } from '../components/PlaceCard';
import PlaceVisual from '../components/PlaceVisual';
import {PocketButton} from '../components/PwaExperience';
import { RouteTimeline } from '../components/PlanPanel';
import { initialContext, forTypedMessage } from '../planner';
import { geocode, recommend, recommendPhoto, planTotals, roundCoord, externalMapLinks, MY_LOCATION, routeTo, inAstana, formatDistance, LANDMARK_KEYS, routeIdeas, toPlan } from '../api';
import { scenarios } from '../data';

const NO_PLACES = [];

// Geolocation is the start of every answer and route; the position is rounded to ~100 m before use
// A link like /?q=кофе%20и%20прогулка&from=expo&now=2026-10-20T15:00 opens that request right away:
// the chat shows it as the user's message, the answer is computed live for that place and moment.
function urlPreset() {
  try {
    const u = new URLSearchParams(location.search), q = (u.get('q') || '').trim().slice(0, 300);
    if (!q) return null;
    const from = u.get('from'), label = Object.keys(LANDMARK_KEYS).find(k => LANDMARK_KEYS[k] === from);
    const now = u.get('now');
    return { q, ctx: { ...initialContext, ...(label ? { location: label, coords: null } : {}), ...(now && !isNaN(Date.parse(now)) ? { now } : {}) } };
  } catch { return null; }
}

function position(options) {
  return new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(
    pos => resolve({ lat: roundCoord(pos.coords.latitude), lon: roundCoord(pos.coords.longitude), at: Date.now(), acc: Math.round(pos.coords.accuracy || 0) }),
    err => reject(Object.assign(Error('denied'), { code: err.code === 1 ? 'denied' : 'unavailable' })), options));
}
// Safari on a Mac often misses the high-accuracy fix within the timeout (Wi-Fi positioning only):
// one more try with a normal fix and a recent cached position before giving up.
async function locate() {
  if (!navigator.geolocation) throw Object.assign(Error('unsupported'), { code: 'unsupported' });
  try { return await position({ enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }); }
  catch (e) {
    if (e.code === 'denied') throw e;
    return position({ enableHighAccuracy: false, timeout: 20000, maximumAge: 120000 });
  }
}

const GEO_TEXT = {
  asking: 'Определяю, где ты… Разреши доступ к геопозиции — маршруты строятся от тебя.',
  denied: 'Нет доступа к геопозиции — маршрут от тебя не построить. Разреши доступ для этого сайта или напиши, возле чего ты.',
  unavailable: 'Не получилось определить местоположение. В Safari: Системные настройки → Конфиденциальность → Службы геолокации → Safari. Или напиши, возле чего ты.',
  unsupported: 'Браузер не умеет определять местоположение. Напиши, возле чего ты, или выбери точку старта.',
  outside: 'Похоже, ты не в Астане. Напиши, возле чего ты в городе, или выбери точку старта.',
  coarse: 'Телефон дал неточную геопозицию (по сети, а не по GPS) — старт может быть не там. Включи точное местоположение или напиши, возле чего ты.',
};
// a network fix (no GPS) can be kilometres off: used, but the user is told and can correct it
const COARSE_M = 1500;

function StartChooser({onChoose, onGeo, locating, onClose}) {
  const [address, setAddress] = useState(''), [finding, setFinding] = useState(false), [notFound, setNotFound] = useState(false);
  const inputId = useId();
  async function findAddress() {
    if (!address.trim() || finding) return;
    setFinding(true); setNotFound(false);
    const ok = await onChoose(address.trim(), false);
    setFinding(false); setNotFound(!ok);
  }
  return <section className="start-chooser" aria-label={tr('Откуда начнём?')}>
    {onClose && <button type="button" className="start-close" onClick={onClose} aria-label={tr('Закрыть')} title={tr('Закрыть')}><X size={18} /></button>}
    <h2>{tr('Откуда начнём?')}</h2><p>{tr('Укажи место в Астане — подберём прогулку рядом.')}</p>
    <button className="start-geo" disabled={locating} onClick={onGeo}><LocateFixed size={17}/>{tr(locating ? 'Определяю точку старта…' : 'Моё местоположение')}</button>
    <div className="start-landmarks">{['Район Байтерека', 'Mega Silk Way', 'ЭКСПО'].map(label => <button key={label} onClick={() => onChoose(label, true)}>{tr(label)}</button>)}</div>
    <form onSubmit={e => { e.preventDefault(); findAddress(); }}>
      <label htmlFor={inputId}>{tr('Или адрес / ориентир')}</label><div><input id={inputId} data-start-input value={address} onChange={e=>{setAddress(e.target.value); setNotFound(false);}} maxLength={160} placeholder={tr('Например: Кенесары 40')} autoComplete="off" aria-invalid={notFound || undefined}/><button disabled={!address.trim() || finding} aria-label={tr('Найти места')}><ArrowRight size={18}/></button></div>
      {notFound && <p className="start-error" role="alert">{tr('Не нашёл такой адрес в Астане. Попробуй «улица, дом» или выбери ориентир.')}</p>}
    </form>
  </section>;
}

function GeoNotice({ state, label, onRetry }) {
  if (state === 'ok') return label ? <p className="resolved-start"><MapPin size={14}/>{tr('Старт')}: {label}</p> : null;
  if (state === 'idle') return null;
  return <details className={'geo-notice geo-compact geo-' + state}><summary><MapPin size={14}/>{tr(state === 'asking' ? 'Определяю точку старта…' : state === 'coarse' ? 'Неточная геопозиция' : 'Геолокация не включена')}<ChevronDown size={12}/></summary><div role="status"><LocateFixed size={16} /><span>{tr(GEO_TEXT[state])}{state !== 'asking' && label ? ' ' + tr('Сейчас') + ': ' + tr(label) + '.' : ''}</span>
    {state !== 'asking' && state !== 'unsupported' && <button onClick={onRetry}>{tr('Включить геолокацию')}</button>}</div></details>;
}

// the settings a result depends on: when they differ from the shown result, «Найти с этими условиями» appears
const prefKey = c => [c.time, c.transport, !!c.kid, !!c.accessible].join('|');

// a popover anchored to its button: closes on a tap outside or Escape
function usePopover() {
  const [open, setOpen] = useState(false), box = useRef(null);
  useEffect(() => {
    if (!open) return;
    const close = e => { if (!box.current?.contains(e.target)) setOpen(false); };
    const esc = e => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('pointerdown', close); document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('pointerdown', close); document.removeEventListener('keydown', esc); };
  }, [open]);
  return [open, setOpen, box];
}

// every setting behind one button in the composer: duration, transport, kid / no steps.
// Picking only changes the setting; the search runs on «Найти с этими условиями» or the next message.
function FilterMenu({ ctx, setTime, setTransport, update, pending, onApply }) {
  const [open, setOpen, box] = usePopover();
  const extra = ctx.kid || ctx.accessible;
  return <div className="filter-menu" ref={box}>
    <button type="button" className={'filter-trigger' + (open ? ' open' : '')} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(!open)}
      aria-label={tr('Длительность и фильтры')} title={tr('Длительность и фильтры')}>
      <SlidersHorizontal size={15} /><span>{ctx.time + tr(' мин')}</span>{ctx.transport === 'car' && <Car size={14} />}{(extra || pending) && <i />}</button>
    {open && <div className="filter-popover" role="dialog" aria-label={tr('Длительность и фильтры')}>
      <p className="filter-label">{tr('Длительность')}</p>
      <div className="filter-row">{[30, 60, 120].map(t => <button type="button" key={t} aria-pressed={ctx.time === t} className={ctx.time === t ? 'active' : ''} onClick={() => setTime(t)}><b>{t + tr(' мин')}</b><small>{tr(t === 30 ? 'Лёгкая' : t === 60 ? 'Оптимально' : 'Подольше')}</small></button>)}</div>
      <p className="filter-label">{tr('Как добираться')}</p>
      <div className="filter-row">{[['walk', Footprints, 'Пешком'], ['car', Car, 'На авто']].map(([key, I, label]) => <button type="button" key={key} aria-pressed={ctx.transport === key} className={ctx.transport === key ? 'active' : ''} onClick={() => setTransport(key)}><I size={15} />{tr(label)}</button>)}</div>
      <p className="filter-label">{tr('Условия')}</p>
      <div className="filter-row">
        <button type="button" aria-pressed={ctx.kid} className={ctx.kid ? 'active' : ''} onClick={() => update({ kid: !ctx.kid })}><Baby size={15} />{tr('С ребёнком')}</button>
        <button type="button" aria-pressed={ctx.accessible} className={ctx.accessible ? 'active' : ''} onClick={() => update({ accessible: !ctx.accessible })}><Accessibility size={15} />{tr('Без ступенек')}</button>
      </div>
      {pending && <button type="button" className="context-apply" onClick={() => { onApply(); setOpen(false); }}><Sparkles size={15} />{tr('Найти с этими условиями')}</button>}
    </div>}
  </div>;
}

// «Места рядом» in the header (laptop): opens the place cards floating over the map, a second tap goes back to the map
function NearbyButton({ count, sequence, open, onToggle }) {
  const [slot, setSlot] = useState(null);
  useEffect(() => setSlot(document.getElementById('header-slot')), []);
  if (!slot) return null;
  return createPortal(<button className={'nearby-trigger' + (open ? ' open' : '')} aria-pressed={open} disabled={!count} onClick={onToggle}>
    <Compass size={16} />{tr(sequence ? 'Твой маршрут' : 'Места рядом')}{count > 0 && <span className="nav-count">{count}</span>}</button>, slot);
}

function useMedia(query) {
  const [match, setMatch] = useState(() => typeof matchMedia !== 'undefined' && matchMedia(query).matches);
  useEffect(() => { const m = matchMedia(query); const on = () => setMatch(m.matches); m.addEventListener('change', on); return () => m.removeEventListener('change', on); }, [query]);
  return match;
}

export default function Explore({ saved, toggleSaved }) {
  const phone = useMedia('(max-width: 899px)');
  const [chatOpen, setChatOpen] = useState(false);
  const [ctx, setCtx] = useState(initialContext);
  const [appliedKey, setAppliedKey] = useState(prefKey(initialContext));  // the settings behind the result on screen
  const [walking, setWalking] = useState(false);
  const lang = useLocale(), shownLang = useRef(lang);
  const [plan, setPlan] = useState(null), [previous, setPrevious] = useState(null), [loading, setLoading] = useState(false), [loadError, setLoadError] = useState('');
  const [selected, setSelected] = useState(null), [hovered, setHovered] = useState(null), [route, setRoute] = useState(true);
  const [tab, setTab] = useState(['chat','map','places','plan'].includes(new URLSearchParams(location.search).get('view')) ? new URLSearchParams(location.search).get('view') : phone ? 'chat' : 'map'), [sheetOpen, setSheetOpen] = useState(false), [resultVersion, setResultVersion] = useState(0);
  const [mascotMood, setMascotMood] = useState('wave'), [quip, setQuip] = useState(0), [starter, setStarter] = useState(null);
  const [startClosed, setStartClosed] = useState(false);
  const [chatKey, setChatKey] = useState(0), [geoError, setGeoError] = useState(''), [why, setWhy] = useState(false);
  const [geo, setGeo] = useState('idle'), [focusRoute, setFocusRoute] = useState(null), [detailPlace, setDetailPlace] = useState(null), [routeError, setRouteError] = useState('');
  useEffect(() => {
    if (!phone) return;
    const vv = window.visualViewport, root = document.documentElement;
    let baseline = vv?.height || innerHeight, frame = 0, sawShrink = false, focusTimer = 0, openingUntil = 0;
    const fit = () => {
      const height = vv?.height || innerHeight;
      const focused = document.activeElement?.matches?.('#chat-input, [data-start-input]');
      const shrunk = baseline - height > 120 && (!vv || vv.scale < 1.15);
      if (focused && shrunk) sawShrink = true;
      const keyboard = shrunk || (focused && !sawShrink && Date.now() < openingUntil);
      if (!focused && !shrunk) { baseline = height; sawShrink = false; }
      root.style.setProperty('--mobile-vh', height + 'px');
      root.style.setProperty('--mobile-vt', (vv?.offsetTop || 0) + 'px');
      root.classList.toggle('kb-open', keyboard);
      const nav = document.querySelector('.mobile-app-nav');
      if (nav) { nav.inert = keyboard; nav.setAttribute('aria-hidden', String(keyboard)); }
    };
    const schedule = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(fit); };
    const focus = e => { if(e.target?.matches?.('#chat-input, [data-start-input]')) { sawShrink = false; openingUntil = Date.now() + 900; clearTimeout(focusTimer); focusTimer = setTimeout(schedule, 920); } schedule(); };
    const rotate = () => { baseline = vv?.height || innerHeight; sawShrink = false; schedule(); };
    fit(); vv?.addEventListener('resize', schedule); vv?.addEventListener('scroll', schedule);
    document.addEventListener('focusin', focus); document.addEventListener('focusout', schedule);
    addEventListener('resize', schedule); addEventListener('orientationchange', rotate);
    return () => { clearTimeout(focusTimer); cancelAnimationFrame(frame); vv?.removeEventListener('resize', schedule); vv?.removeEventListener('scroll', schedule);
      document.removeEventListener('focusin', focus); document.removeEventListener('focusout', schedule);
      removeEventListener('resize', schedule); removeEventListener('orientationchange', rotate);
      root.style.removeProperty('--mobile-vh'); root.style.removeProperty('--mobile-vt'); root.classList.remove('kb-open');
      const nav = document.querySelector('.mobile-app-nav'); if(nav){nav.inert=false;nav.removeAttribute('aria-hidden');}
    };
  }, [phone]);
  const moodTimer = useRef(null);
  useEffect(() => () => clearTimeout(moodTimer.current), []);
  function reactToSearch(state) { clearTimeout(moodTimer.current); setMascotMood(state); if (state === 'happy') moodTimer.current = setTimeout(() => setMascotMood('idle'), 2200); }
  function greet() { setQuip(n => n + 1); reactToSearch('happy'); }
  const quips = ['Покажу город с другой стороны.', 'Пойдём туда, где ещё не были?', 'Кофе в руки — и навстречу городу!', 'Маленькая прогулка — большая перезагрузка.'];

  async function withCoords(c) {
    if (c.location !== MY_LOCATION) return c;
    if (c.coords && Date.now() - (c.coords.at || 0) < 120000) return c;  // fresh enough
    setGeo('asking');
    try {
      const coords = await locate();
      if (!inAstana(coords)) { setGeo('outside'); return { ...c, coords: null }; }
      setGeo(coords.acc > COARSE_M ? 'coarse' : 'ok'); setGeoError(''); return { ...c, coords };
    } catch (e) { setGeo(e.code || 'unavailable'); return { ...c, coords: null }; }  // no silent landmark: the next request asks again
  }
  async function retryGeo() {
    setGeo('asking');
    const c = await withCoords({ ...ctx, location: MY_LOCATION, coords: null });
    setCtx(c);
    if (c.coords) { applyContext(c); showTab('chat'); }  // redo the current answer from the real position
  }
  // tap on a place (chat card, details): the route from the user to it, drawn on the map
  // themed walks: computed for the current start; showing one puts its stops and route on the map
  async function fetchIdeas() {
    setStartClosed(true);  // the chat answers with themed walks: the «Откуда начнём?» card would only be in the way
    const c = await withCoords(ctx); setCtx(c);  // the user asked: the position is requested (or refreshed) now
    if (c.location === MY_LOCATION && !c.coords) throw Error('no-start');  // no GPS and no chosen start: ask, never guess
    return routeIdeas(c, getLanguage());
  }
  function showIdea(idea) {
    const next = toPlan(idea.response, ctx, idea.query);
    setPrevious(plan); setPlan(next); setResultVersion(n => n + 1); setHovered(null); setSheetOpen(false); setFocusRoute(null);
    setRoute(true); setSelected(next.places.find(p => !p.generated)?.id ?? null);
    showTab('map', false);
  }
  async function showRouteTo(p, c = ctx, current = plan) {
    setSelected(p.id); setRouteError('');
    // a start named in the text («с AITU до ботсада») wins over GPS; otherwise the user's position, then the answer's origin
    const textStart = current?.used?.location?.source === 'text_landmark' ? current.used.location : null;
    const gps = !textStart && c.location === MY_LOCATION && c.coords && inAstana(c.coords) ? c.coords : null;
    const from = gps || (current?.used?.location ? { lat: current.used.location.lat, lon: current.used.location.lon } : null);
    try { const r = await routeTo(p, c, from); setFocusRoute({ ...r, place: p, origin_source: gps ? r.origin_source : 'landmark', origin_label: gps ? null : (textStart?.label || current?.used?.location?.label || null) }); }
    catch (e) { setRouteError(e.message === 'no-path' ? 'Не нашёл пути по улицам до этого места — прямой линией через реку или здания не рисую. Открой его в 2GIS.' : 'Не получилось построить маршрут. Попробуй ещё раз.'); }
    showTab('map', false);
  }
  async function requestPlan(text, override, signal, photo) {
    setLoading(true); setLoadError('');
    try {
      // a typed message (no override) wins over the settings for the time / transport it states itself
      const base = override || forTypedMessage(ctx, text);
      // GPS is asked for when the user sends a request (never on first render), refreshed every 2 minutes as they walk
      const c = photo ? base : await withCoords(base);
      setCtx(c);
      const next = photo ? await recommendPhoto(photo, text, c, getLanguage(), { signal }) : await recommend(text, c, getLanguage(), { signal });
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      if (next.offTopic || (photo && !next.places.length)) return next;  // keep the current picks; the chat explains
      setPrevious(plan); setPlan(next); setResultVersion(n => n + 1); setHovered(null); setSheetOpen(false); setFocusRoute(null);
      // the settings now show what this result used («на час» -> 60), and the next message carries them
      const u = next.used, shown = { ...c, ...(u?.time_budget_min ? { time: u.time_budget_min } : {}),
        ...(u?.mode === 'walk' || u?.mode === 'car' ? { transport: u.mode } : {}), touched: { ...c.touched, time: true, transport: true } };
      setCtx(shown); setAppliedKey(prefKey(shown));
      if (next.navigateTo) { const p = next.places.find(x => x.id === next.navigateTo); if (p) showRouteTo(p, c, next); }  // «маршрут до …»
      setSelected(next.places.find(p => !p.generated)?.id ?? null);
      return next;
    } finally { setLoading(false); }
  }
  const [photoOn, setPhotoOn] = useState(false);
  const [tiles, setTiles] = useState(null);
  useEffect(() => { fetch('/api/meta').then(r => r.json()).then(m => { setPhotoOn(!!m.features?.photo); setTiles(m.map || null); }).catch(() => {}); }, []);
  useEffect(() => {  // A fresh visit asks for a start; explicit demo links still execute their query.
    const preset = urlPreset();
    if (preset) { setCtx(preset.ctx); if (preset.ctx.location !== MY_LOCATION) setGeo('ok'); setStarter({ text: preset.q, context: preset.ctx, id: Date.now() }); return; }

  }, []);

  const lastQuery = plan?.query || tr(scenarios[0].query);
  // a landmark is a known key; a typed address goes to the geocoder (Astana only, rounded to ~100 m), never to the AI
  async function chooseStart(value, landmark) {
    let next;
    if (landmark) next = {...ctx, location: value, coords: null, address: null};
    else {
      const hit = await geocode(value).then(r => r.find(x => inAstana(x)), () => null);
      if (!hit) return false;
      next = {...ctx, location: value, coords: null, address: {label: value, lat: hit.lat, lon: hit.lon}};
    }
    setCtx(next); setGeo('ok');
    setStarter({text: tr('Хочу прогулку рядом'), context: next, id: Date.now()});
    showTab('chat');
    return true;
  }
  function startMood(i) { setStarter({ index: i, text: tr(scenarios[i].query), id: Date.now() }); showTab('chat'); document.getElementById('chat-input')?.focus({ preventScroll: true }); }
  function changeContext(c) { setCtx(c); if (c.location === MY_LOCATION && !c.coords) withCoords(c).then(setCtx); }
  function applyContext(c = ctx) { setStarter({ text: lastQuery, display: tr('Обнови прогулку с моими условиями'), context: c, id: Date.now() }); }
  function refine(key) { const next = { ...ctx, [key]: !ctx[key] }; setCtx(next); applyContext(next); }
  useEffect(() => setWalking(false), [plan]);
  useEffect(() => {  // the cards speak the language they were asked in: switching it asks again
    if (lang === shownLang.current) return;
    shownLang.current = lang;
    if (plan && !loading) applyContext(ctx);
  }, [lang]);
  // «Новый диалог»: the settings and the result on the map start over too (the chosen start stays)
  function resetAll() {
    const next = { ...initialContext, location: ctx.location, coords: ctx.coords, address: ctx.address };
    setCtx(next); setAppliedKey(prefKey(next)); setPlan(null); setPrevious(null); setFocusRoute(null); setWalking(false);
    setSelected(null); setRouteError(''); showTab('chat', false);
  }
  function restore() { if (!previous) return; setPlan(previous); setCtx(previous.context); setSelected(previous.places.find(p => !p.generated)?.id ?? null); setPrevious(null); setResultVersion(n => n + 1); reactToSearch('idle'); }
  function showTab(next, scroll = true) {
    if (phone) { setTab(next); return; }  // phones: the chat is a full-screen sheet
    if (next !== 'chat') setTab(next);
    if (scroll) requestAnimationFrame(() => document.getElementById(next === 'places' ? 'places-section' : next === 'map' ? 'map-section' : 'chat-panel')?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' }));
  }
  function choosePlace(id) { setSelected(id); showTab('map'); }

  const places = plan?.places || NO_PLACES;  // a stable empty list: a new [] each render re-fits the map
  const real = places.filter(p => !p.generated);
  const sel = places.find(p => p.id === selected);
  // «Уточнить» offers what this answer can change (Aslan's idea): «Без кофе» when a café is in it, «В помещении»
  // when a stop is outdoors, «Ближе» when a stop is more than 10 min away; a chosen one stays so it can be undone
  const refineOptions = [['closer', 'Ближе', real.some(p => (p.travel ?? 0) > 10)],
    ['noCoffee', 'Без кофе', real.some(p => p.categoryKey === 'cafe')],
    ['indoor', 'В помещении', real.some(p => p.badges?.includes('outdoor'))]].filter(([key, , fits]) => fits || ctx[key]);
  const { total } = planTotals(plan);
  const budget = plan?.used?.time_budget_min || ctx.time;
  const used = plan?.used;
  // memoised: a new object on every render (hover, typing) made the map snap back to the route
  const loc = used?.location;
  const origin = useMemo(() => loc ? { lat: loc.lat, lon: loc.lon, label: loc.source === 'gps_rounded' ? null : loc.label } : null, [loc]);
  // «Начать прогулку»: the whole walk in a navigator, the stops in the planned order (back to the start if it returns)
  const walkLinks = useMemo(() => {
    const r = plan?.route;
    if (!r?.order?.length || !origin) return null;
    const byId = Object.fromEntries(places.map(p => [p.id, p]));
    const stops = r.order.map(id => byId[id]).filter(p => p?.lat != null);
    if (!stops.length) return null;
    const pts = [origin, ...stops, ...(r.legs?.at(-1)?.to_id === 'start' ? [origin] : [])];
    const ll = p => `${p.lat},${p.lon}`;
    const travel = plan?.context?.transport === 'car' ? 'driving' : 'walking';
    return {
      gis: 'https://2gis.kz/astana/directions/points/' + pts.map(p => `${p.lon}%2C${p.lat}`).join('%7C'),
      google: `https://www.google.com/maps/dir/?api=1&travelmode=${travel}&origin=${ll(pts[0])}&destination=${ll(pts.at(-1))}`
        + (pts.length > 2 ? '&waypoints=' + pts.slice(1, -1).map(ll).join('%7C') : ''),
      metres: (r.legs || []).reduce((sum, l) => sum + (l.distance_m || 0), 0), total: r.total_min, n: stops.length,
    };
  }, [plan, places, origin]);
  function toggleRoute() {  // one switch for everything drawn: the walk and a route to a single place
    if ((route && plan?.route) || focusRoute) { setRoute(false); setFocusRoute(null); setWalking(false); } else setRoute(true);
  }
  // «Начать прогулку»: the whole walk on the map with navigator links; without a route, the way to the chosen place
  function startWalk() { if (plan?.route) { setRoute(true); setFocusRoute(null); setWalking(true); setResultVersion(n => n + 1); showTab('map'); } else if (sel || real[0]) showRouteTo(sel || real[0]); }
  const savedIds = saved.map(p => p.id);
  // preferences re-run the last request right away (no separate "apply" step)
  const update = patch => setCtx({ ...ctx, ...patch });  // only picks the setting; the search runs on «Найти» or the next message
  const pending = !!plan && !loading && prefKey(ctx) !== appliedKey;
  const setTime = t => update({ time: t, touched: { ...ctx.touched, time: true } });
  const setTransport = t => update({ transport: t, touched: { ...ctx.touched, transport: true } });

  return <div className={"explore-page map-first reference-layout mobile-view-" + tab}>
    <main className={'explore-workspace tab-' + tab}>
      <div className="conversation-column"><div className="companion-intro"><div><span className="companion-eyebrow">{tr('ТВОЙ МЕСТНЫЙ ДРУГ ')}</span><h1>{tr('Твой AI-помощник для прогулок по Астане')}</h1><p>{tr('Найдём интересные места и построим маршрут. Куда пойдём сегодня?')}</p></div><button className="companion-mascot" onClick={greet} aria-label={tr('Поговорить с Серу')}><Mascot decorative priority mood={mascotMood} key={quip}/></button><span className="companion-quip" aria-live="polite">{tr(quips[quip % quips.length])}</span></div>
        <Chat key={chatKey} notice={<><GeoNotice state={plan?.used?.location?.source && plan.used.location.source !== 'none' && geo !== 'asking' ? 'ok' : geo} label={plan?.used?.location?.label || (ctx.location === MY_LOCATION ? null : ctx.location)} onRetry={retryGeo} />{phone && !plan && !loading && !startClosed && <StartChooser onChoose={chooseStart} onGeo={retryGeo} locating={geo==='asking'} onClose={() => setStartClosed(true)}/>}</>} onRoute={showRouteTo} onDetails={setDetailPlace} routed={focusRoute?.poi_id} onIdeas={fetchIdeas} onShowIdea={showIdea} requestPlan={requestPlan} onMood={reactToSearch} starter={starter} location={ctx.location} startLabel={!pending && ctx.location === MY_LOCATION ? plan?.used?.location?.label : null} setLocation={l => changeContext({ ...ctx, location: l, coords: l === ctx.location ? ctx.coords : null })} onResult={() => { setChatOpen(false); showTab('places'); }} photoEnabled={photoOn} onReset={resetAll} tools={<FilterMenu ctx={ctx} setTime={setTime} setTransport={setTransport} update={update} pending={pending} onApply={() => applyContext(ctx)} />} sheet={false} open={true} onOpen={() => showTab('chat')} onClose={() => setChatOpen(false)} />
        <div className="seru-tip"><span className="tip-doodle" aria-hidden="true">✳</span><div><span>{tr("СОВЕТ ОТ СЕРУ")}</span><p>{tr("Лучшие планы иногда начинаются")}<br />{tr("с «а давай просто выйдем».")}</p></div><button onClick={() => startMood(Math.floor(Math.random() * scenarios.length))}>{tr("Удиви меня")}<ArrowUpRight size={14} /></button></div>
        {phone && <RouteOverview plan={plan} selected={selected} onSelect={choosePlace} loading={loading} previous={previous} onRestore={restore} onStart={startWalk}/>}
        <details className="sidebar-route" open={!phone || tab === 'plan'}><summary>{tr("ТВОЙ ПЛАН")}</summary><RouteTimeline plan={plan} previous={previous} onRestore={restore} onSelect={choosePlace} /><PocketButton plan={plan}/><button className="pocket-open" onClick={()=>window.dispatchEvent(new Event("seru-open-app"))}>{tr("Моя прогулка")} ↗</button></details><details className="context-disclosure"><summary>{tr("Что я учёл")}</summary><div className="used-context used-live"><span><ShieldCheck size={16} />{tr("Что я учёл")}</span>
          {used ? <>
            <div className="chips"><span>📍 {used.location_label}</span><span>⏱ {used.time_budget_min} {tr('мин')}</span><span>{used.mode === 'walk' ? '🚶 ' + tr('пешком') : used.mode === 'transit' ? '🚌 ' + tr('на транспорте') : '🚕 ' + tr('на машине')}</span><span>{used.is_dark ? '🌙 ' + tr('вечер') : '☀️ ' + tr('день')}</span>{used.weather && <span>🌡 {Math.round(used.weather.temperature_c)}°C{used.weather.max_outdoor_min < 60 && !(used.weather.us_aqi >= 101) ? ' · ' + tr('холодно') : ''}</span>}{used.weather?.us_aqi >= 101 && <span>💨 {tr('воздух')} AQI {Math.round(used.weather.us_aqi)}</span>}{(used.filters || []).filter(f => !/^[А-ЯA-ZӘҒҚҢӨҰҮҺІ]/.test(f)).map(f => <span key={f}>✓ {f}</span>)}</div>
            {plan.notes?.[0] && <p className="friendly-note">💡 {plan.notes[0]}</p>}
            {(plan.notes?.length > 1 || plan.considered?.length > 0) && <button className="why-toggle" aria-expanded={why} onClick={() => setWhy(!why)}>{tr(why ? 'Скрыть детали' : 'Почему именно эти места?')}<ChevronDown size={13} /></button>}
            {why && <div className="why-details">{plan.notes.slice(1).map(n => <p key={n}>• {n}</p>)}{plan.considered?.length > 0 && <p className="muted">{tr('Не предложил')}: {plan.considered.map(c => c.name + ' (' + c.reason + ')').join('; ')}</p>}</div>}
            {geoError && <p className="geo-error">{tr(geoError)}</p>}
            <small>🔒 {tr('Локация примерная, ничего не храним.')}</small></> : <small>{loading ? tr('Смотрю, что рядом…') : tr(loadError || 'Расскажи, чего хочется, — подберу места рядом.')}</small>}
        </div></details><details className="mood-disclosure"><summary>{tr("А что, если сегодня…")}</summary><MoodStories onChoose={startMood}/></details>
      </div>
      {!phone && <NearbyButton count={real.length} sequence={!!plan?.route} open={tab === 'places'} onToggle={() => showTab(tab === 'places' ? 'map' : 'places', false)} />}
      <div className="discovery-column">
        <div className="mobile-tabs" role="tablist" aria-label={tr("Разделы прогулки")}>{[{ id: 'places', icon: Compass, label: tr('Места') }, { id: 'map', icon: Map, label: tr('Карта') }].map((t, k) => <button key={t.id} role="tab" tabIndex={tab === t.id ? 0 : -1} onKeyDown={e => { if (['ArrowLeft', 'ArrowRight'].includes(e.key)) { e.preventDefault(); const next = 1 - k; showTab(next ? 'map' : 'places', false); e.currentTarget.parentElement.children[next].focus(); } }} aria-selected={tab === t.id} aria-controls={t.id + '-section'} onClick={() => showTab(t.id, false)}><t.icon size={17} />{t.label}{t.id === 'places' && <span>{real.length}</span>}</button>)}</div>
        
        {!loading && !plan && !loadError && !startClosed && <div className="map-welcome"><StartChooser onChoose={chooseStart} onGeo={retryGeo} locating={geo==='asking'} onClose={() => setStartClosed(true)}/></div>}
        {!loading && plan && !real.length && <div className="empty-plan" role="status"><h3>{tr("Подходящих мест пока нет")}</h3><p>{plan.notes?.[0] || tr("Попробуй снять ограничения или увеличить время.")}</p><button onClick={() => { const next = { ...ctx, time: Math.max(120, ctx.time), indoor: false, noCoffee: false, accessible: false, closer: false, touched: { ...ctx.touched, time: true } }; setCtx(next); applyContext(next); }}>{tr("Расширить условия")}</button></div>}
        {loadError && !loading && !plan && <div className="empty-plan" role="alert"><h3>{tr('Не получилось загрузить подборку')}</h3><p>{tr(loadError)}</p><button onClick={() => requestPlan(lastQuery).catch(() => setLoadError('Сервер не ответил. Попробуй ещё раз.'))}>{tr('Повторить')}</button></div>}
        <section className="map-section" id="map-section" aria-label={tr("Карта прогулки")}>{(!phone || tab === 'map') && <CityMap tiles={tiles} places={places} origin={origin} route={plan?.route} showRoute={route} setRoute={setRoute} selected={selected} setSelected={id => { setSelected(id); setSheetOpen(false); }} hovered={hovered} resultVersion={resultVersion} focusRoute={focusRoute} routeVisible={(route && !!plan?.route) || !!focusRoute} onToggleRoute={toggleRoute} />}
          {walking && walkLinks && !focusRoute && <div className="focus-route-bar walk-bar" role="status"><Footprints size={16} /><div><b>{tr('Прогулка')} · {walkLinks.n} {tr(walkLinks.n === 1 ? 'место' : 'места')}</b><span>{formatDistance(walkLinks.metres)} · ≈ {walkLinks.total} {tr('мин')} · {tr('открой навигацию и иди по точкам')}</span></div><a href={walkLinks.gis} target="_blank" rel="noreferrer">2GIS ↗</a><a className="secondary" href={walkLinks.google} target="_blank" rel="noreferrer">Google ↗</a><button aria-label={tr('Закрыть')} onClick={() => setWalking(false)}><X size={16} /></button></div>}
          {focusRoute && <div className="focus-route-bar" role="status"><Navigation size={16} /><div><b>{focusRoute.place?.name || focusRoute.name}</b><span>{formatDistance(focusRoute.distance_m)} · {focusRoute.travel_min} {tr(focusRoute.mode === 'car' ? 'мин в пути' : 'мин пешком')}{focusRoute.origin_source === 'landmark' ? ' · ' + (focusRoute.origin_label ? tr('от') + ' ' + focusRoute.origin_label : tr('от ориентира')) : ' · ' + tr('от тебя')}{focusRoute.geometry === 'straight' ? ' · ' + tr('оценка') : ''}</span></div><a href={focusRoute.links['2gis']} target="_blank" rel="noreferrer">2GIS ↗</a><button aria-label={tr('Скрыть маршрут')} onClick={() => setFocusRoute(null)}><X size={16} /></button></div>}
          {routeError && <div className="focus-route-bar error" role="alert">{tr(routeError)}</div>}
          {sel && <article className="reference-place"><div className="reference-place-photo"><PlaceVisual place={sel} illustrative/><button className="reference-close" onClick={()=>setSelected(null)} aria-label={tr('Закрыть карточку')}><X size={18}/></button></div><div className="reference-place-copy"><h2>{sel.name}</h2>{sel.rating!=null&&<p className="reference-rating">★ {sel.rating}</p>}<div className="reference-place-meta"><span><MapPin size={15}/>{sel.address||sel.category}</span><span><Clock3 size={15}/>{sel.visit} {tr('мин')}</span></div><p className="reference-place-description">{sel.why||sel.description}</p><button className="reference-more" onClick={()=>setDetailPlace(sel)}>{tr('Подробнее')}<ArrowRight size={16}/></button></div></article>}
          {real.length > 0 && <button className="reference-all-places" onClick={()=>showTab(tab==='places'?'map':'places')}><Compass size={16}/>{tr(tab==='places'?'К карте':'Все места')} · {real.length}</button>}
          <div className="route-strip"><span className="route-symbol"><Route size={18} /></span><div><strong>{plan?.route ? tr('Мини-маршрут') : tr('Небольшое приключение')}</strong><span>{plan?.route ? plan.route.summary : real.length + tr(' мест · ') + (total > budget ? tr('Дольше твоего плана — выбери часть мест') : tr('Можно идти без спешки'))}</span></div><span className="route-total"><Clock3 size={13} />≈ {total}{tr(" мин")}</span></div></section>
        <section className="places-section" id="places-section"><div className="section-heading"><div><span className="section-eyebrow">{tr("ПОД ТВОЁ НАСТРОЕНИЕ")}</span><h2>{tr("Твои маленькие открытия")}<span>{real.length}</span></h2></div></div>
          {plan?.summary && !loading && <p className="summary-line">{plan.summary}</p>}
          <div className="places-float-bar">{plan && !loading && refineOptions.length > 0 && <div className="refine-chips" role="group" aria-label={tr('Уточнить подборку')}><span>{tr('Уточнить')}:</span>{refineOptions.map(([key, label]) => <button key={key} aria-pressed={!!ctx[key]} className={ctx[key] ? 'on' : ''} onClick={() => refine(key)}>{ctx[key] && <Check size={13} />}{tr(label)}</button>)}</div>}
            {!phone && plan?.route && !loading && <button className="places-start" onClick={startWalk}><Footprints size={15} />{tr('Начать прогулку')} · ≈ {plan.route.total_min} {tr('мин')}<ArrowRight size={15} /></button>}</div>
          <div className="place-grid">{loading ? [0, 1, 2].map(i => <SkeletonCard key={i} />) : places.map((p, i) => <PlaceCard key={resultVersion + '-' + p.id} place={p} index={i} illustrative onHover={setHovered} isNew={!!previous && !previous.places.some(x => x.id === p.id) && !p.generated} selected={selected === p.id} onSelect={() => choosePlace(p.id)} saved={savedIds.includes(p.id)} onSave={() => toggleSaved(p)} origin={origin} />)}
            <article className="seru-discovery-card"><span className="discovery-sticker">{tr("ПЛАНЫ? ЕСТЬ ИДЕЯ!")}</span><Mascot decorative /><div><h3>{tr("А может,")} {tr("что-нибудь неожиданное?")}</h3><p>{tr("Оставь немного места")} {tr("для спонтанных открытий.")}</p></div><button onClick={() => startMood(Math.floor(Math.random() * scenarios.length))}>{tr("Серу, удиви меня")}<ArrowUpRight size={16} /></button><span className="discovery-doodle" aria-hidden="true">✳</span></article></div>
          <p className="results-disclaimer">{tr("Подборку собрал Серу по открытым данным о городе. Часы работы лучше уточнить перед выходом.")}</p></section>
      </div></main>
    {detailPlace && <PlaceDetails place={detailPlace} saved={savedIds.includes(detailPlace.id)} onSave={() => toggleSaved(detailPlace)} onClose={() => setDetailPlace(null)} onMap={() => {showRouteTo(detailPlace);setDetailPlace(null);}} origin={ctx.coords && inAstana(ctx.coords) ? ctx.coords : origin} />}
    {phone && <nav className="mobile-app-nav" aria-label={tr('Основная навигация')}>{[['chat',MessageCircle,'Чат'],['map',Map,'Карта'],['places',Compass,'Места'],['plan',Route,'План']].map(([id,Icon,label])=><button key={id} aria-current={tab===id?'page':undefined} onClick={()=>showTab(id,false)}><Icon size={21}/><span>{tr(label)}</span>{id==='places'&&real.length>0&&<i>{real.length}</i>}</button>)}</nav>}</div>;
}
