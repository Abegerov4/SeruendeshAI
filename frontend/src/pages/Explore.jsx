import { t as tr, getLanguage } from "../i18n";
import React, { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, ArrowRight, MapPin, Clock3, Footprints, Car, SlidersHorizontal, Check, MessageCircle, Map, Compass, ShieldCheck, Sparkles, ChevronDown, Baby, Accessibility, Route } from 'lucide-react';
import Chat from '../components/Chat';
import Mascot from '../components/Mascot';
import MoodStories from '../components/MoodStories';
import CityMap from '../components/MapView';
import PlaceCard, { SkeletonCard } from '../components/PlaceCard';
import { RouteTimeline } from '../components/PlanPanel';
import { initialContext } from '../planner';
import { recommend, planTotals, roundCoord, externalMapLinks, MY_LOCATION } from '../api';
import { scenarios } from '../data';

function locate() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(Error('Геолокация недоступна в этом браузере.'));
    navigator.geolocation.getCurrentPosition(
      pos => resolve({ lat: roundCoord(pos.coords.latitude), lon: roundCoord(pos.coords.longitude) }),  // rounded before use (~100 m)
      () => reject(Error('Нет доступа к геолокации — выбери ориентир из списка.')),
      { enableHighAccuracy: false, timeout: 9000, maximumAge: 300000 });
  });
}

export default function Explore({ saved, toggleSaved }) {
  const [ctx, setCtx] = useState(initialContext);
  const [plan, setPlan] = useState(null), [previous, setPrevious] = useState(null), [loading, setLoading] = useState(true), [loadError, setLoadError] = useState('');
  const [selected, setSelected] = useState(null), [hovered, setHovered] = useState(null), [route, setRoute] = useState(true);
  const [filters, setFilters] = useState(false), [tab, setTab] = useState('chat'), [sheetOpen, setSheetOpen] = useState(false), [resultVersion, setResultVersion] = useState(0);
  const [mascotMood, setMascotMood] = useState('wave'), [quip, setQuip] = useState(0), [starter, setStarter] = useState(null);
  const [chatKey, setChatKey] = useState(0), [geoError, setGeoError] = useState(''), [why, setWhy] = useState(false);
  const moodTimer = useRef(null);
  useEffect(() => () => clearTimeout(moodTimer.current), []);
  function reactToSearch(state) { clearTimeout(moodTimer.current); setMascotMood(state); if (state === 'happy') moodTimer.current = setTimeout(() => setMascotMood('idle'), 2200); }
  function greet() { setQuip(n => n + 1); reactToSearch('happy'); }
  const quips = ['Покажу город с другой стороны.', 'Пойдём туда, где ещё не были?', 'Кофе в руки — и навстречу городу!', 'Маленькая прогулка — большая перезагрузка.'];

  async function withCoords(c) {
    if (c.location !== MY_LOCATION || c.coords) return c;
    try { const coords = await locate(); setGeoError(''); return { ...c, coords }; }
    catch (e) { setGeoError(e.message); return { ...c, location: initialContext.location, coords: null }; }
  }
  async function requestPlan(text, override, signal) {
    setLoading(true); setLoadError('');
    try {
      const c = await withCoords(override || ctx);
      setCtx(c);
      const next = await recommend(text, c, getLanguage(), { signal });
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      setPrevious(plan); setPlan(next); setResultVersion(n => n + 1); setHovered(null); setSheetOpen(false);
      setSelected(next.places.find(p => !p.generated)?.id ?? null);
      return next;
    } finally { setLoading(false); }
  }
  useEffect(() => {  // first screen: a live answer for the default context (no chat message is faked)
    const ac = new AbortController();
    requestPlan(tr(scenarios[0].query), initialContext, ac.signal).catch(e => { if (!ac.signal.aborted) setLoadError('Сервер не ответил. Попробуй запрос в чате.'); });
    return () => ac.abort();
  }, []);

  const lastQuery = plan?.query || tr(scenarios[0].query);
  function startMood(i) { setStarter({ index: i, text: tr(scenarios[i].query), id: Date.now() }); showTab('chat'); document.getElementById('chat-input')?.focus({ preventScroll: true }); }
  function changeContext(c) { setCtx(c); if (c.location === MY_LOCATION && !c.coords) withCoords(c).then(setCtx); }
  function applyContext(c = ctx) { setStarter({ text: lastQuery, display: tr('Обнови прогулку с моими условиями'), context: c, id: Date.now() }); showTab('chat'); }
  function refine(key) { const next = { ...ctx, [key]: !ctx[key] }; setCtx(next); applyContext(next); }
  function restore() { if (!previous) return; setPlan(previous); setCtx(previous.context); setSelected(previous.places.find(p => !p.generated)?.id ?? null); setPrevious(null); setResultVersion(n => n + 1); reactToSearch('idle'); }
  function showTab(next, scroll = true) {
    setTab(next);
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

  return <div className="explore-page">
    <section className="explore-hero"><img src="/images/astana-hero.webp" alt={tr("AI-визуализация вечернего бульвара Нуржол")} fetchPriority="high" /><div className="hero-copy"><span className="hero-eyebrow"><i />{tr("ГОРОД БЛИЖЕ, ЧЕМ КАЖЕТСЯ")}</span><h1>{tr("Сверни с привычного.")}<br /><em>{tr("Открой свою Астану.")}</em></h1><p>{tr("Твой ритм. Твоё настроение. Твой маленький маршрут.")}</p><button onClick={() => { showTab('chat'); document.getElementById('chat-input')?.focus({ preventScroll: true }); }}>{tr("Давай начнём")}<ArrowUpRight size={17} /></button></div><button className="hero-seru" onClick={greet} aria-label={tr("Поговорить с Серу")}><span className="seru-bubble"><strong>{tr("Сәлем! Я Серу 👋")}</strong><span className="seru-quip" aria-live="polite">{tr(quips[quip % quips.length])}</span></span><Mascot decorative priority mood={mascotMood} key={quip} /><span className="seru-name-tag">{tr("ТВОЙ МЕСТНЫЙ ДРУГ ")}<span>↗</span></span></button><span className="hero-address"><MapPin size={13} />{tr("Нуржол, Астана")}<span>{tr("AI-визуализация")}</span></span></section>
    <MoodStories onChoose={startMood} />
    <div className="workspace-intro"><div><span className="section-eyebrow">{tr("НЕ НУЖНО ДОЛГО ПЛАНИРОВАТЬ")}</span><h2>{tr("Хороший день начинается с «куда?»")}</h2></div><span className="workspace-tip"><Sparkles size={15} />{tr("2300+ мест Астаны")}</span></div>
    <div className="mobile-tabs" role="tablist" aria-label={tr("Разделы прогулки")}>{[{ id: 'chat', icon: MessageCircle, label: tr('Чат') }, { id: 'places', icon: Compass, label: tr('Места') }, { id: 'map', icon: Map, label: tr('Карта') }].map(t => <button key={t.id} role="tab" tabIndex={tab === t.id ? 0 : -1} onKeyDown={e => { const ids = ['chat', 'places', 'map']; if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) { e.preventDefault(); const next = e.key === 'Home' ? 0 : e.key === 'End' ? 2 : (ids.indexOf(t.id) + (e.key === 'ArrowRight' ? 1 : 2)) % 3; showTab(ids[next], false); e.currentTarget.parentElement.children[next].focus(); } }} aria-selected={tab === t.id} aria-controls={t.id === 'chat' ? 'chat-panel' : t.id + '-section'} onClick={() => showTab(t.id, false)}><t.icon size={17} />{t.label}{t.id === 'places' && <span>{real.length}</span>}</button>)}</div>
    <main className={'explore-workspace tab-' + tab}>
      <div className="conversation-column">
        <Chat key={chatKey} requestPlan={requestPlan} onMood={reactToSearch} starter={starter} location={ctx.location} setLocation={l => changeContext({ ...ctx, location: l, coords: l === ctx.location ? ctx.coords : null })} onResult={() => showTab('places')} />
        <div className="seru-tip"><span className="tip-doodle" aria-hidden="true">✳</span><div><span>{tr("СОВЕТ ОТ СЕРУ")}</span><p>{tr("Лучшие планы иногда начинаются")}<br />{tr("с «а давай просто выйдем».")}</p></div><button onClick={() => startMood(Math.floor(Math.random() * scenarios.length))}>{tr("Удиви меня")}<ArrowUpRight size={14} /></button></div>
        <section className="preferences" aria-label={tr("Предпочтения")}><div className="preferences-heading"><span>{tr("Подстроимся под тебя")}</span><button onClick={() => setFilters(!filters)} aria-expanded={filters} aria-label={tr("Дополнительные фильтры")}><SlidersHorizontal size={15} />{(ctx.kid || ctx.accessible) && <i />}</button></div><div className="preference-controls"><div className="time-selector" aria-label={tr("Время на прогулку")}>{[30, 60, 120].map(t => <button key={t} aria-pressed={ctx.time === t} className={ctx.time === t ? 'active' : ''} onClick={() => setTime(t)}>{t === 120 ? tr('2 часа') : t + tr(' мин')}</button>)}</div><button className="transport-toggle" onClick={toggleTransport}>{ctx.transport === 'walk' ? <Footprints size={16} /> : <Car size={16} />} {ctx.transport === 'walk' ? tr('Пешком') : tr('На авто')}<ChevronDown size={12} /></button></div><div className={"filter-reveal " + (filters ? "open" : "")} inert={!filters}><div><div className="extra-preferences"><button aria-pressed={ctx.kid} className={ctx.kid ? 'active' : ''} onClick={() => update({ kid: !ctx.kid })}><Baby size={15} />{tr("С ребёнком")}{ctx.kid && <Check size={13} />}</button><button aria-pressed={ctx.accessible} className={ctx.accessible ? 'active' : ''} onClick={() => update({ accessible: !ctx.accessible })}><Accessibility size={15} />{tr("Без ступенек")}{ctx.accessible && <Check size={13} />}</button><p>{tr("Подборка обновится сразу.")}</p></div></div></div></section>
        <div className="used-context used-live"><span><ShieldCheck size={16} />{tr("Что я учёл")}</span>
          {used ? <>
            <div className="chips"><span>📍 {used.location_label}</span><span>⏱ {used.time_budget_min} {tr('мин')}</span><span>{used.mode === 'walk' ? '🚶 ' + tr('пешком') : used.mode === 'transit' ? '🚌 ' + tr('на транспорте') : '🚕 ' + tr('на машине')}</span><span>{used.is_dark ? '🌙 ' + tr('вечер') : '☀️ ' + tr('день')}</span>{used.weather && <span>🌡 {Math.round(used.weather.temperature_c)}°C{used.weather.max_outdoor_min < 60 ? ' · ' + tr('холодно') : ''}</span>}{(used.filters || []).filter(f => !/^[А-ЯA-ZӘҒҚҢӨҰҮҺІ]/.test(f)).map(f => <span key={f}>✓ {f}</span>)}</div>
            {plan.notes?.[0] && <p className="friendly-note">💡 {plan.notes[0]}</p>}
            {(plan.notes?.length > 1 || plan.considered?.length > 0) && <button className="why-toggle" aria-expanded={why} onClick={() => setWhy(!why)}>{tr(why ? 'Скрыть детали' : 'Почему именно эти места?')}<ChevronDown size={13} /></button>}
            {why && <div className="why-details">{plan.notes.slice(1).map(n => <p key={n}>• {n}</p>)}{plan.considered?.length > 0 && <p className="muted">{tr('Не предложил')}: {plan.considered.map(c => c.name + ' (' + c.reason + ')').join('; ')}</p>}</div>}
            {geoError && <p className="geo-error">{tr(geoError)}</p>}
            <small>🔒 {tr('Локация примерная, ничего не храним.')}</small></> : <small>{loading ? tr('Смотрю, что рядом…') : tr(loadError || 'Расскажи, чего хочется, — подберу места рядом.')}</small>}
        </div>
      </div>
      <div className="discovery-column">
        <RouteTimeline plan={plan} previous={previous} onRestore={restore} onSelect={choosePlace} />
        {!loading && plan && !real.length && <div className="empty-plan" role="status"><h3>{tr("Подходящих мест пока нет")}</h3><p>{plan.notes?.[0] || tr("Попробуй снять ограничения или увеличить время.")}</p><button onClick={() => { const next = { ...ctx, time: Math.max(120, ctx.time), indoor: false, noCoffee: false, accessible: false, closer: false, touched: { ...ctx.touched, time: true } }; setCtx(next); applyContext(next); }}>{tr("Расширить условия")}</button></div>}
        {loadError && !loading && !plan && <div className="empty-plan" role="alert"><h3>{tr('Не получилось загрузить подборку')}</h3><p>{tr(loadError)}</p><button onClick={() => requestPlan(lastQuery).catch(() => setLoadError('Сервер не ответил. Попробуй ещё раз.'))}>{tr('Повторить')}</button></div>}
        <section className="map-section" id="map-section" aria-label={tr("Карта прогулки")}><CityMap places={places} origin={origin} route={plan?.route} showRoute={route} setRoute={setRoute} selected={selected} setSelected={id => { setSelected(id); setSheetOpen(false); }} hovered={hovered} resultVersion={resultVersion} />
          {sel && <div className={"selected-map-place " + (sheetOpen ? "sheet-open" : "")}><img src={sel.image} alt="" /><div><span>{tr("ТВОЯ СЛЕДУЮЩАЯ ОСТАНОВКА")}</span><h3>{sel.name}</h3><p>{sel.mode === 'walk' ? <Footprints size={12} /> : <Car size={12} />}{sel.distance} · {sel.travel}{tr(sel.mode === 'walk' ? " мин пешком" : " мин в пути")}{sel.leaveBy ? ' · ' + tr('выйти до') + ' ' + sel.leaveBy : ''}</p></div><button className="map-sheet-toggle" aria-label={tr("Подробнее")} aria-expanded={sheetOpen} aria-controls="map-place-details" onClick={() => setSheetOpen(!sheetOpen)}><ChevronDown size={19} /></button><div className="map-sheet-details" id="map-place-details" hidden={!sheetOpen}><p>{sel.why}</p><p>{sel.action}</p><p>{externalMapLinks(sel).map(l => <a key={l.label} href={l.href} target="_blank" rel="noreferrer">{tr('Открыть в')} {l.label} ↗ </a>)}</p><button onClick={() => showTab('places')}>{tr("Посмотреть карточки мест")}<ArrowUpRight size={15} /></button></div></div>}
          <div className="route-strip"><span className="route-symbol"><Route size={18} /></span><div><strong>{plan?.route ? tr('Мини-маршрут') : tr('Небольшое приключение')}</strong><span>{plan?.route ? plan.route.summary : real.length + tr(' мест · ') + (total > budget ? tr('Дольше твоего плана — выбери часть мест') : tr('Можно идти без спешки'))}</span></div><span className="route-total"><Clock3 size={13} />≈ {total}{tr(" мин")}</span></div></section>
        <section className="places-section" id="places-section"><div className="section-heading"><div><span className="section-eyebrow">{tr("ПОД ТВОЁ НАСТРОЕНИЕ")}</span><h2>{tr("Твои маленькие открытия")}<span>{real.length}</span></h2></div></div>
          {plan?.summary && !loading && <p className="summary-line">{plan.summary}</p>}
          {plan && !loading && <div className="refine-chips" role="group" aria-label={tr('Уточнить подборку')}><span>{tr('Уточнить')}:</span>{[['closer', 'Ближе'], ['noCoffee', 'Без кофе'], ['indoor', 'В помещении']].map(([key, label]) => <button key={key} aria-pressed={!!ctx[key]} className={ctx[key] ? 'on' : ''} onClick={() => refine(key)}>{ctx[key] && <Check size={13} />}{tr(label)}</button>)}</div>}
          <div className="place-grid">{loading ? [0, 1, 2].map(i => <SkeletonCard key={i} />) : places.map((p, i) => <PlaceCard key={resultVersion + '-' + p.id} place={p} index={i} onHover={setHovered} isNew={!!previous && !previous.places.some(x => x.id === p.id) && !p.generated} selected={selected === p.id} onSelect={() => choosePlace(p.id)} saved={savedIds.includes(p.id)} onSave={() => toggleSaved(p)} />)}
            <article className="seru-discovery-card"><span className="discovery-sticker">{tr("ПЛАНЫ? ЕСТЬ ИДЕЯ!")}</span><Mascot decorative /><h3>{tr("А может,")}<br />{tr("что-нибудь неожиданное?")}</h3><p>{tr("Оставь немного места")}<br />{tr("для спонтанных открытий.")}</p><button onClick={() => startMood(Math.floor(Math.random() * scenarios.length))}>{tr("Серу, удиви меня")}<ArrowUpRight size={16} /></button><span className="discovery-doodle" aria-hidden="true">✳</span></article></div>
          <p className="results-disclaimer">{tr("Подборку собрал Серу по открытым данным о городе. Часы работы лучше уточнить перед выходом.")}</p></section>
      </div></main>
    <div className="mobile-bottom-bar"><span><span className="tiny-dot" />{tab === 'chat' ? tr('Город начинается с разговора') : tab === 'places' ? tr('Нашлось ') + real.length + tr(' идеи для тебя') : tr('Твой маршрут рядом')}</span><button onClick={() => showTab(tab === 'chat' ? 'places' : 'chat')}>{tab === 'chat' ? tr('Смотреть места') : tr('К спутнику')}<ArrowRight size={15} /></button></div></div>;
}
