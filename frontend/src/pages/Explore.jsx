import { t as tr, getLanguage } from "../i18n";
import React, { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, ArrowRight, MapPin, Clock3, Footprints, Car, SlidersHorizontal, Check, MessageCircle, Map, Compass, ShieldCheck, Sparkles, ChevronDown, Baby, Accessibility, Route, LocateFixed, Navigation, X } from 'lucide-react';
import PlaceDetails from '../components/PlaceDetails';
import Chat from '../components/Chat';
import Mascot from '../components/Mascot';
import MoodStories from '../components/MoodStories';
import CityMap from '../components/MapView';
import PlaceCard, { SkeletonCard } from '../components/PlaceCard';
import PlaceVisual from '../components/PlaceVisual';
import {PocketButton} from '../components/PwaExperience';
import { RouteTimeline } from '../components/PlanPanel';
import { initialContext } from '../planner';
import { recommend, recommendPhoto, planTotals, roundCoord, externalMapLinks, MY_LOCATION, routeTo, inAstana, formatDistance } from '../api';
import { scenarios } from '../data';

const FALLBACK_LANDMARK = 'Район Байтерека';

// Geolocation is the start of every answer and route; the position is rounded to ~100 m before use
function locate() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(Object.assign(Error('unsupported'), { code: 'unsupported' }));
    navigator.geolocation.getCurrentPosition(
      pos => resolve({ lat: roundCoord(pos.coords.latitude), lon: roundCoord(pos.coords.longitude), at: Date.now() }),
      err => reject(Object.assign(Error('denied'), { code: err.code === 1 ? 'denied' : 'unavailable' })),
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 });
  });
}

const GEO_TEXT = {
  asking: 'Определяю, где ты… Разреши доступ к геопозиции — маршруты строятся от тебя.',
  denied: 'Без геолокации маршрут строится от ориентира. Разреши доступ к геопозиции для этого сайта.',
  unavailable: 'Не получилось определить местоположение. Пока считаю от ориентира.',
  unsupported: 'Браузер не умеет определять местоположение. Пока считаю от ориентира.',
  outside: 'Похоже, ты не в Астане — пока считаю от ориентира.',
};

function GeoNotice({ state, label, onRetry }) {
  if (state === 'ok') return null;
  return <div className={'geo-notice geo-' + state} role="status"><LocateFixed size={16} /><span>{tr(GEO_TEXT[state])}{state !== 'asking' && label ? ' ' + tr('Сейчас') + ': ' + tr(label) + '.' : ''}</span>
    {state !== 'asking' && state !== 'unsupported' && <button onClick={onRetry}>{tr('Включить геолокацию')}</button>}</div>;
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
  const [plan, setPlan] = useState(null), [previous, setPrevious] = useState(null), [loading, setLoading] = useState(true), [loadError, setLoadError] = useState('');
  const [selected, setSelected] = useState(null), [hovered, setHovered] = useState(null), [route, setRoute] = useState(true);
  const [filters, setFilters] = useState(false), [tab, setTab] = useState(['chat','map','places','plan'].includes(new URLSearchParams(location.search).get('view')) ? new URLSearchParams(location.search).get('view') : phone ? 'chat' : 'map'), [sheetOpen, setSheetOpen] = useState(false), [resultVersion, setResultVersion] = useState(0);
  const [mascotMood, setMascotMood] = useState('wave'), [quip, setQuip] = useState(0), [starter, setStarter] = useState(null);
  const [chatKey, setChatKey] = useState(0), [geoError, setGeoError] = useState(''), [why, setWhy] = useState(false);
  const [geo, setGeo] = useState('asking'), [focusRoute, setFocusRoute] = useState(null), [detailPlace, setDetailPlace] = useState(null), [routeError, setRouteError] = useState('');
  useEffect(() => {  // phones: the app follows the visual viewport (iOS keyboard), chrome hides while typing
    if (!phone) return;
    const vv = window.visualViewport, root = document.documentElement;
    const fit = () => {
      const h = vv?.height || innerHeight;
      root.style.setProperty('--mobile-vh', h + 'px');
      root.style.setProperty('--mobile-vt', (vv?.offsetTop || 0) + 'px');
      root.classList.toggle('kb-open', h < innerHeight * 0.78);
    };
    fit(); vv?.addEventListener('resize', fit); vv?.addEventListener('scroll', fit); addEventListener('orientationchange', fit);
    return () => { vv?.removeEventListener('resize', fit); vv?.removeEventListener('scroll', fit); removeEventListener('orientationchange', fit);
      root.style.removeProperty('--mobile-vh'); root.style.removeProperty('--mobile-vt'); root.classList.remove('kb-open'); };
  }, [phone]);
  const moodTimer = useRef(null);
  useEffect(() => () => clearTimeout(moodTimer.current), []);
  function reactToSearch(state) { clearTimeout(moodTimer.current); setMascotMood(state); if (state === 'happy') moodTimer.current = setTimeout(() => setMascotMood('idle'), 2200); }
  function greet() { setQuip(n => n + 1); reactToSearch('happy'); }
  const quips = ['Покажу город с другой стороны.', 'Пойдём туда, где ещё не были?', 'Кофе в руки — и навстречу городу!', 'Маленькая прогулка — большая перезагрузка.'];

  async function withCoords(c) {
    if (c.location !== MY_LOCATION) return c;
    if (c.coords && Date.now() - (c.coords.at || 0) < 120000) return c;  // fresh enough
    try {
      const coords = await locate();
      if (!inAstana(coords)) { setGeo('outside'); return { ...c, location: FALLBACK_LANDMARK, coords: null }; }
      setGeo('ok'); setGeoError(''); return { ...c, coords };
    } catch (e) { setGeo(e.code || 'unavailable'); return { ...c, location: FALLBACK_LANDMARK, coords: null }; }
  }
  async function retryGeo() {
    setGeo('asking');
    const c = await withCoords({ ...ctx, location: MY_LOCATION, coords: null });
    setCtx(c);
    if (c.location === MY_LOCATION && plan) applyContext(c);  // redo the current answer from the real position
  }
  // tap on a place (chat card, details): the route from the user to it, drawn on the map
  async function showRouteTo(p, c = ctx, current = plan) {
    setSelected(p.id); setRouteError('');
    const gps = c.location === MY_LOCATION && c.coords && inAstana(c.coords) ? c.coords : null;
    const from = gps || (current?.used?.location ? { lat: current.used.location.lat, lon: current.used.location.lon } : null);
    try { const r = await routeTo(p, c, from); setFocusRoute({ ...r, place: p, origin_source: gps ? r.origin_source : 'landmark' }); }
    catch { setRouteError('Не получилось построить маршрут. Попробуй ещё раз.'); }
    showTab('map', false);
  }
  async function requestPlan(text, override, signal, photo) {
    setLoading(true); setLoadError('');
    try {
      const c = photo ? (override || ctx) : await withCoords(override || ctx);
      setCtx(c);
      const next = photo ? await recommendPhoto(photo, text, c, getLanguage(), { signal }) : await recommend(text, c, getLanguage(), { signal });
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      if (next.offTopic || (photo && !next.places.length)) return next;  // keep the current picks; the chat explains
      setPrevious(plan); setPlan(next); setResultVersion(n => n + 1); setHovered(null); setSheetOpen(false); setFocusRoute(null);
      if (next.navigateTo) { const p = next.places.find(x => x.id === next.navigateTo); if (p) showRouteTo(p, c, next); }  // «маршрут до …»
      setSelected(next.places.find(p => !p.generated)?.id ?? null);
      return next;
    } finally { setLoading(false); }
  }
  const [photoOn, setPhotoOn] = useState(false);
  useEffect(() => { fetch('/api/meta').then(r => r.json()).then(m => setPhotoOn(!!m.features?.photo)).catch(() => {}); }, []);
  useEffect(() => {  // first screen: a live answer for the default context (no chat message is faked)
    const ac = new AbortController();
    requestPlan(tr(scenarios[0].query), initialContext, ac.signal).catch(e => { if (!ac.signal.aborted) setLoadError('Сервер не ответил. Попробуй запрос в чате.'); });
    return () => ac.abort();
  }, []);

  const lastQuery = plan?.query || tr(scenarios[0].query);
  function startMood(i) { setStarter({ index: i, text: tr(scenarios[i].query), id: Date.now() }); showTab('chat'); document.getElementById('chat-input')?.focus({ preventScroll: true }); }
  function changeContext(c) { setCtx(c); if (c.location === MY_LOCATION && !c.coords) withCoords(c).then(setCtx); }
  function applyContext(c = ctx) { setStarter({ text: lastQuery, display: tr('Обнови прогулку с моими условиями'), context: c, id: Date.now() }); }
  function refine(key) { const next = { ...ctx, [key]: !ctx[key] }; setCtx(next); applyContext(next); }
  function restore() { if (!previous) return; setPlan(previous); setCtx(previous.context); setSelected(previous.places.find(p => !p.generated)?.id ?? null); setPrevious(null); setResultVersion(n => n + 1); reactToSearch('idle'); }
  function showTab(next, scroll = true) {
    if (phone) { setTab(next); return; }  // phones: the chat is a full-screen sheet
    if (next !== 'chat') setTab(next);
    if (scroll) requestAnimationFrame(() => document.getElementById(next === 'places' ? 'places-section' : next === 'map' ? 'map-section' : 'chat-panel')?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' }));
  }
  function choosePlace(id) { setSelected(id); showTab('map'); }

  const places = plan?.places || [];
  const real = places.filter(p => !p.generated);
  const sel = places.find(p => p.id === selected);
  const { total } = planTotals(plan);
  const budget = plan?.used?.time_budget_min || ctx.time;
  const used = plan?.used;
  const origin = used?.location ? { lat: used.location.lat, lon: used.location.lon } : null;
  const savedIds = saved.map(p => p.id);
  // preferences re-run the last request right away (no separate "apply" step)
  const update = patch => { const next = { ...ctx, ...patch }; setCtx(next); if (plan) applyContext(next); };
  const setTime = t => update({ time: t, touched: { ...ctx.touched, time: true } });
  const toggleTransport = () => update({ transport: ctx.transport === 'walk' ? 'car' : 'walk', touched: { ...ctx.touched, transport: true } });

  return <div className={"explore-page map-first mobile-view-" + tab}>
    <main className={'explore-workspace tab-' + tab}>
      <div className="conversation-column"><div className="companion-intro"><div><span className="companion-eyebrow">{tr('ТВОЙ МЕСТНЫЙ ДРУГ ')}</span><h1>{tr('Куда пойдём сегодня?')}</h1><p>{tr('Твой AI-спутник для прогулок по Астане')}</p></div><button className="companion-mascot" onClick={greet} aria-label={tr('Поговорить с Серу')}><Mascot decorative priority mood={mascotMood} key={quip}/></button><span className="companion-quip" aria-live="polite">{tr(quips[quip % quips.length])}</span></div>
        <Chat key={chatKey} notice={<GeoNotice state={geo} label={ctx.location === MY_LOCATION ? null : ctx.location} onRetry={retryGeo} />} onRoute={showRouteTo} onDetails={setDetailPlace} routed={focusRoute?.poi_id} requestPlan={requestPlan} onMood={reactToSearch} starter={starter} location={ctx.location} setLocation={l => changeContext({ ...ctx, location: l, coords: l === ctx.location ? ctx.coords : null })} onResult={() => { setChatOpen(false); showTab('places'); }} photoEnabled={photoOn} sheet={false} open={true} onOpen={() => showTab('chat')} onClose={() => setChatOpen(false)} />
        <div className="seru-tip"><span className="tip-doodle" aria-hidden="true">✳</span><div><span>{tr("СОВЕТ ОТ СЕРУ")}</span><p>{tr("Лучшие планы иногда начинаются")}<br />{tr("с «а давай просто выйдем».")}</p></div><button onClick={() => startMood(Math.floor(Math.random() * scenarios.length))}>{tr("Удиви меня")}<ArrowUpRight size={14} /></button></div>
        <section className="preferences" aria-label={tr("Предпочтения")}><div className="preferences-heading"><span>{tr("Подстроимся под тебя")}</span><button onClick={() => setFilters(!filters)} aria-expanded={filters} aria-label={tr("Дополнительные фильтры")}><SlidersHorizontal size={15} />{(ctx.kid || ctx.accessible) && <i />}</button></div><div className="preference-controls"><div className="time-selector" aria-label={tr("Время на прогулку")}>{[30, 60, 120].map(t => <button key={t} aria-pressed={ctx.time === t} className={ctx.time === t ? 'active' : ''} onClick={() => setTime(t)}>{t === 120 ? tr('2 часа') : t + tr(' мин')}</button>)}</div><button className="transport-toggle" onClick={toggleTransport}>{ctx.transport === 'walk' ? <Footprints size={16} /> : <Car size={16} />} {ctx.transport === 'walk' ? tr('Пешком') : tr('На авто')}<ChevronDown size={12} /></button></div><div className={"filter-reveal " + (filters ? "open" : "")} inert={!filters}><div><div className="extra-preferences"><button aria-pressed={ctx.kid} className={ctx.kid ? 'active' : ''} onClick={() => update({ kid: !ctx.kid })}><Baby size={15} />{tr("С ребёнком")}{ctx.kid && <Check size={13} />}</button><button aria-pressed={ctx.accessible} className={ctx.accessible ? 'active' : ''} onClick={() => update({ accessible: !ctx.accessible })}><Accessibility size={15} />{tr("Без ступенек")}{ctx.accessible && <Check size={13} />}</button><p>{tr("Подборка обновится сразу.")}</p></div></div></div></section>
        <details className="sidebar-route" open={!phone || tab === 'plan'}><summary>{tr("ТВОЙ ПЛАН")}</summary><RouteTimeline plan={plan} previous={previous} onRestore={restore} onSelect={choosePlace} /><PocketButton plan={plan}/><button className="pocket-open" onClick={()=>window.dispatchEvent(new Event("seru-open-app"))}>{tr("Моя прогулка")} ↗</button></details><details className="context-disclosure"><summary>{tr("Что я учёл")}</summary><div className="used-context used-live"><span><ShieldCheck size={16} />{tr("Что я учёл")}</span>
          {used ? <>
            <div className="chips"><span>📍 {used.location_label}</span><span>⏱ {used.time_budget_min} {tr('мин')}</span><span>{used.mode === 'walk' ? '🚶 ' + tr('пешком') : used.mode === 'transit' ? '🚌 ' + tr('на транспорте') : '🚕 ' + tr('на машине')}</span><span>{used.is_dark ? '🌙 ' + tr('вечер') : '☀️ ' + tr('день')}</span>{used.weather && <span>🌡 {Math.round(used.weather.temperature_c)}°C{used.weather.max_outdoor_min < 60 ? ' · ' + tr('холодно') : ''}</span>}{(used.filters || []).filter(f => !/^[А-ЯA-ZӘҒҚҢӨҰҮҺІ]/.test(f)).map(f => <span key={f}>✓ {f}</span>)}</div>
            {plan.notes?.[0] && <p className="friendly-note">💡 {plan.notes[0]}</p>}
            {(plan.notes?.length > 1 || plan.considered?.length > 0) && <button className="why-toggle" aria-expanded={why} onClick={() => setWhy(!why)}>{tr(why ? 'Скрыть детали' : 'Почему именно эти места?')}<ChevronDown size={13} /></button>}
            {why && <div className="why-details">{plan.notes.slice(1).map(n => <p key={n}>• {n}</p>)}{plan.considered?.length > 0 && <p className="muted">{tr('Не предложил')}: {plan.considered.map(c => c.name + ' (' + c.reason + ')').join('; ')}</p>}</div>}
            {geoError && <p className="geo-error">{tr(geoError)}</p>}
            <small>🔒 {tr('Локация примерная, ничего не храним.')}</small></> : <small>{loading ? tr('Смотрю, что рядом…') : tr(loadError || 'Расскажи, чего хочется, — подберу места рядом.')}</small>}
        </div></details><details className="mood-disclosure"><summary>{tr("А что, если сегодня…")}</summary><MoodStories onChoose={startMood}/></details>
      </div>
      <div className="discovery-column">
        <div className="mobile-tabs" role="tablist" aria-label={tr("Разделы прогулки")}>{[{ id: 'places', icon: Compass, label: tr('Места') }, { id: 'map', icon: Map, label: tr('Карта') }].map((t, k) => <button key={t.id} role="tab" tabIndex={tab === t.id ? 0 : -1} onKeyDown={e => { if (['ArrowLeft', 'ArrowRight'].includes(e.key)) { e.preventDefault(); const next = 1 - k; showTab(next ? 'map' : 'places', false); e.currentTarget.parentElement.children[next].focus(); } }} aria-selected={tab === t.id} aria-controls={t.id + '-section'} onClick={() => showTab(t.id, false)}><t.icon size={17} />{t.label}{t.id === 'places' && <span>{real.length}</span>}</button>)}</div>
        
        {!loading && plan && !real.length && <div className="empty-plan" role="status"><h3>{tr("Подходящих мест пока нет")}</h3><p>{plan.notes?.[0] || tr("Попробуй снять ограничения или увеличить время.")}</p><button onClick={() => { const next = { ...ctx, time: Math.max(120, ctx.time), indoor: false, noCoffee: false, accessible: false, closer: false, touched: { ...ctx.touched, time: true } }; setCtx(next); applyContext(next); }}>{tr("Расширить условия")}</button></div>}
        {loadError && !loading && !plan && <div className="empty-plan" role="alert"><h3>{tr('Не получилось загрузить подборку')}</h3><p>{tr(loadError)}</p><button onClick={() => requestPlan(lastQuery).catch(() => setLoadError('Сервер не ответил. Попробуй ещё раз.'))}>{tr('Повторить')}</button></div>}
        <section className="map-section" id="map-section" aria-label={tr("Карта прогулки")}>{(!phone || tab === 'map') && <CityMap places={places} origin={origin} route={plan?.route} showRoute={route} setRoute={setRoute} selected={selected} setSelected={id => { setSelected(id); setSheetOpen(false); }} hovered={hovered} resultVersion={resultVersion} focusRoute={focusRoute} />}
          {focusRoute && <div className="focus-route-bar" role="status"><Navigation size={16} /><div><b>{focusRoute.name}</b><span>{formatDistance(focusRoute.distance_m)} · {focusRoute.travel_min} {tr(focusRoute.mode === 'car' ? 'мин в пути' : 'мин пешком')}{focusRoute.origin_source === 'landmark' ? ' · ' + tr('от ориентира') : ' · ' + tr('от тебя')}{focusRoute.geometry === 'straight' ? ' · ' + tr('оценка') : ''}</span></div><a href={focusRoute.links['2gis']} target="_blank" rel="noreferrer">2GIS ↗</a><button aria-label={tr('Скрыть маршрут')} onClick={() => setFocusRoute(null)}><X size={16} /></button></div>}
          {routeError && <div className="focus-route-bar error" role="alert">{tr(routeError)}</div>}
          {sel && <div className={"selected-map-place " + (sheetOpen ? "sheet-open" : "")}><PlaceVisual place={sel} illustrative /><div><span>{tr("ТВОЯ СЛЕДУЮЩАЯ ОСТАНОВКА")}</span><h3>{sel.name}</h3><p>{sel.mode === 'walk' ? <Footprints size={12} /> : <Car size={12} />}{sel.distance} · {sel.travel}{tr(sel.mode === 'walk' ? " мин пешком" : " мин в пути")}{sel.leaveBy ? ' · ' + tr('выйти до') + ' ' + sel.leaveBy : ''}</p></div><button className="map-sheet-toggle" aria-label={tr("Подробнее")} aria-expanded={sheetOpen} aria-controls="map-place-details" onClick={() => setSheetOpen(!sheetOpen)}><ChevronDown size={19} /></button><div className="map-sheet-details" id="map-place-details" hidden={!sheetOpen}><p>{sel.why}</p><p>{sel.action}</p><p>{externalMapLinks(sel).map(l => <a key={l.label} href={l.href} target="_blank" rel="noreferrer">{tr('Открыть в')} {l.label} ↗ </a>)}</p><button onClick={() => showTab('places')}>{tr("Посмотреть карточки мест")}<ArrowUpRight size={15} /></button></div></div>}
          <div className="route-strip"><span className="route-symbol"><Route size={18} /></span><div><strong>{plan?.route ? tr('Мини-маршрут') : tr('Небольшое приключение')}</strong><span>{plan?.route ? plan.route.summary : real.length + tr(' мест · ') + (total > budget ? tr('Дольше твоего плана — выбери часть мест') : tr('Можно идти без спешки'))}</span></div><span className="route-total"><Clock3 size={13} />≈ {total}{tr(" мин")}</span></div></section>
        <section className="places-section" id="places-section"><div className="section-heading"><div><span className="section-eyebrow">{tr("ПОД ТВОЁ НАСТРОЕНИЕ")}</span><h2>{tr("Твои маленькие открытия")}<span>{real.length}</span></h2></div></div>
          {plan?.summary && !loading && <p className="summary-line">{plan.summary}</p>}
          {plan && !loading && <div className="refine-chips" role="group" aria-label={tr('Уточнить подборку')}><span>{tr('Уточнить')}:</span>{[['closer', 'Ближе'], ['noCoffee', 'Без кофе'], ['indoor', 'В помещении']].map(([key, label]) => <button key={key} aria-pressed={!!ctx[key]} className={ctx[key] ? 'on' : ''} onClick={() => refine(key)}>{ctx[key] && <Check size={13} />}{tr(label)}</button>)}</div>}
          <div className="place-grid">{loading ? [0, 1, 2].map(i => <SkeletonCard key={i} />) : places.map((p, i) => <PlaceCard key={resultVersion + '-' + p.id} place={p} index={i} illustrative onHover={setHovered} isNew={!!previous && !previous.places.some(x => x.id === p.id) && !p.generated} selected={selected === p.id} onSelect={() => choosePlace(p.id)} saved={savedIds.includes(p.id)} onSave={() => toggleSaved(p)} origin={origin} />)}
            <article className="seru-discovery-card"><span className="discovery-sticker">{tr("ПЛАНЫ? ЕСТЬ ИДЕЯ!")}</span><Mascot decorative /><div><h3>{tr("А может,")} {tr("что-нибудь неожиданное?")}</h3><p>{tr("Оставь немного места")} {tr("для спонтанных открытий.")}</p></div><button onClick={() => startMood(Math.floor(Math.random() * scenarios.length))}>{tr("Серу, удиви меня")}<ArrowUpRight size={16} /></button><span className="discovery-doodle" aria-hidden="true">✳</span></article></div>
          <p className="results-disclaimer">{tr("Подборку собрал Серу по открытым данным о городе. Часы работы лучше уточнить перед выходом.")}</p></section>
      </div></main>
    {detailPlace && <PlaceDetails place={detailPlace} saved={savedIds.includes(detailPlace.id)} onSave={() => toggleSaved(detailPlace)} onClose={() => setDetailPlace(null)} onMap={() => showRouteTo(detailPlace)} origin={ctx.coords && inAstana(ctx.coords) ? ctx.coords : origin} />}
    {phone && <nav className="mobile-app-nav" aria-label={tr('Основная навигация')}>{[['chat',MessageCircle,'Чат'],['map',Map,'Карта'],['places',Compass,'Места'],['plan',Route,'План']].map(([id,Icon,label])=><button key={id} aria-current={tab===id?'page':undefined} onClick={()=>showTab(id,false)}><Icon size={21}/><span>{tr(label)}</span>{id==='places'&&real.length>0&&<i>{real.length}</i>}</button>)}</nav>}</div>;
}
