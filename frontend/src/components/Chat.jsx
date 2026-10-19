import { t as tr, getLanguage } from "../i18n";
import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowUpRight, ArrowUp, MapPin, ChevronDown, Check, ShieldCheck, RotateCcw, Sparkles, Camera, MessageCircle, Navigation, Footprints, Car, Info, Mic, House, Map as MapIcon, Pencil, Plus, Clock3, ArrowRight } from 'lucide-react';
import PlaceVisual from './PlaceVisual';
import { hoursTone, shortHours } from './PlaceCard';
import { landmarks, scenarios } from '../data';
import { MY_LOCATION, HOME, loadHome, saveHome, geocode, roundCoord, visitText } from '../api';
import Mascot from './Mascot';

const welcome = {
  id: 0,
  role: 'assistant',
  text: 'Привет! Куда хочешь сходить? Напиши пожелания — подберу места рядом.'
};

// On phones the chat is a full-screen sheet (like a messenger): the composer sits above the keyboard,
// the system back button closes it. On wider screens it stays a panel next to the results.
function useSheetViewport(active, onClose) {
  useEffect(() => {
    if (!active) return;
    const vv = window.visualViewport, root = document.documentElement;
    const fit = () => { root.style.setProperty('--vvh', (vv ? vv.height : innerHeight) + 'px'); root.style.setProperty('--vvtop', (vv ? vv.offsetTop : 0) + 'px'); };
    fit(); vv?.addEventListener('resize', fit); vv?.addEventListener('scroll', fit);
    const overflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
    history.scrollRestoration = 'manual';
    if (!history.state?.seruChat) history.pushState({ ...(history.state || {}), seruChat: 1 }, '');
    const back = () => onClose();
    addEventListener('popstate', back);
    return () => { vv?.removeEventListener('resize', fit); vv?.removeEventListener('scroll', fit); removeEventListener('popstate', back); document.body.style.overflow = overflow; };
  }, [active]);
}

// Places right inside Seru's answer: tap a card -> the route from where you are, or the details.
function ChatPlaces({ places, route, onRoute, onDetails, routed }) {
  const byId = Object.fromEntries(places.map(p => [p.id, p]));
  return <div className="chat-places">{places.map((p, i) => {
    const Mode = p.mode === 'car' ? Car : Footprints;
    const leg = route?.legs?.find(l => l.from_id === p.id && byId[l.to_id]);  // the next stop of a mini-route
    return <article key={p.id} className={'chat-place' + (routed === p.id ? ' routed' : '')}>
      <button className="chat-place-main" onClick={() => onRoute?.(p)} aria-label={tr('Маршрут до места') + ': ' + p.name}>
        <span className="chat-place-thumb"><PlaceVisual place={p} /><i>{i + 1}</i></span>
        <span className="chat-place-text"><b>{p.name}</b><small>{p.category}</small>
          <small className="chat-place-meta"><Mode size={12} />{p.distance} · {p.travel} {tr('мин')}<span className={'chat-hours ' + hoursTone(p)}>{shortHours(p)}</span></small></span>
      </button>
      {(p.action || visitText(p)) && <p className="chat-place-plan">
        {visitText(p) && <span className="chat-place-time"><Clock3 size={12} />{visitText(p)} {tr('мин на месте')}</span>}
        {p.action && <span><b>{tr('Что делать')}:</b> {p.action}</span>}
        {leg && <span className="chat-place-next"><ArrowRight size={12} />{tr('Дальше')}: {byId[leg.to_id].name} · {leg.travel_min} {tr(p.mode === 'car' ? 'мин в пути' : 'мин пешком')}</span>}
      </p>}
      <div className="chat-place-actions">
        <button className="primary" onClick={() => onRoute?.(p)}><Navigation size={14} />{tr(routed === p.id ? 'Маршрут на карте' : 'Маршрут')}</button>
        <button onClick={() => onDetails?.(p)}><Info size={14} />{tr('Подробнее')}</button>
      </div>
    </article>;
  })}</div>;
}

// What Seru took into account and what it left out: the reasoning at a glance, the details on tap.
function ChatReasoning({ used, considered = [], notes = [] }) {
  const [open, setOpen] = useState(false);
  if (!used) return null;
  const q = used.parsed_from_query || {}, f = used.funnel || {};
  const chips = [
    used.location_label && '📍 ' + used.location_label,
    used.time_budget_min && '⏱ ' + used.time_budget_min + ' ' + tr('мин') + ' ' + tr(used.mode === 'walk' ? 'пешком' : used.mode === 'transit' ? 'на транспорте' : 'на машине'),
    used.local_time && (used.is_dark ? '🌙 ' : '☀️ ') + used.local_time,
    used.weather && '🌡 ' + Math.round(used.weather.temperature_c) + '°C' + (used.weather.max_outdoor_min < 60 && !(used.weather.us_aqi >= 101) ? ' · ' + tr('холодно') : ''),
    used.weather?.us_aqi >= 101 && '💨 ' + tr('воздух') + ' AQI ' + Math.round(used.weather.us_aqi),
    ...(used.filters || []).filter(x => !/^[А-ЯA-ZӘҒҚҢӨҰҮҺІ]/.test(x)).map(x => '✓ ' + x),
    ...(q.avoid_labels || []).map(x => '✕ ' + x),
  ].filter(Boolean);
  const funnel = f.within_reach > 0 && f.after_filters != null ? tr('Проверил {n} мест рядом → {k} подходят под условия', { n: f.within_reach, k: f.after_filters }) : null;
  const more = considered.length > 0 || notes.length > 0;
  return <div className="chat-reasoning">
    <span className="chat-reasoning-title">{tr('Что я учёл')}</span>
    <div className="chat-chips">{chips.map(c => <span key={c}>{c}</span>)}</div>
    {funnel && <p className="chat-funnel">{funnel}</p>}
    {notes[0] && <p className="chat-funnel">💡 {notes[0]}</p>}
    {more && <button className="chat-why-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>{tr(open ? 'Скрыть детали' : 'Почему не другие?')}<ChevronDown size={13} /></button>}
    {open && <div className="chat-why">{notes.slice(1).map(n => <p key={n}>• {n}</p>)}
      {considered.length > 0 && <p><b>{tr('Не предложил')}:</b> {considered.map(c => c.name + ' — ' + c.reason).join('; ')}</p>}</div>}
  </div>;
}

// «🏠 Дом»: find the address (OpenStreetMap) or use the current position; kept only on this device.
function HomePicker({ onPick }) {
  const [home, setHome] = useState(loadHome), [editing, setEditing] = useState(!loadHome());
  const [q, setQ] = useState(''), [results, setResults] = useState(null), [busy, setBusy] = useState(false), [err, setErr] = useState('');
  function keep(h) { const v = { lat: roundCoord(h.lat), lon: roundCoord(h.lon), label: h.label }; saveHome(v); setHome(v); setEditing(false); onPick(); }
  async function find() {
    if (q.trim().length < 3) return;
    setBusy(true); setErr('');
    try { const r = await geocode(q.trim()); setResults(r); if (!r.length) setErr('Не нашёл такой адрес в Астане. Попробуй «улица, дом».'); }
    catch { setErr('Поиск адреса сейчас недоступен.'); } finally { setBusy(false); }
  }
  function here() {
    if (!navigator.geolocation) { setErr('Геолокация недоступна.'); return; }
    navigator.geolocation.getCurrentPosition(p => keep({ lat: p.coords.latitude, lon: p.coords.longitude, label: tr('Мой дом') }),
      () => setErr('Нет доступа к геолокации.'), { enableHighAccuracy: true, timeout: 8000 });
  }
  if (home && !editing) return <div className="home-row">
    <button type="button" className="home-choice" onClick={onPick}><House size={14} />{tr('Дом')}<small>{home.label}</small></button>
    <button type="button" className="home-edit" aria-label={tr('Изменить адрес дома')} onClick={() => setEditing(true)}><Pencil size={13} /></button>
  </div>;
  return <div className="home-setup" role="group" aria-label={tr('Адрес дома')}>
    <span><House size={14} />{tr('Адрес дома')}</span>
    <div><input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); find(); } }}
      placeholder={tr('Например: Кенесары 40')} aria-label={tr('Адрес дома')} enterKeyHint="search" />
      <button type="button" onClick={find} disabled={busy}>{tr(busy ? '…' : 'Найти')}</button></div>
    {results?.map(r => <button type="button" key={r.lat + ',' + r.lon} className="home-result" onClick={() => keep({ ...r, label: q.trim() || r.label })}>{r.label}</button>)}
    <button type="button" className="home-here" onClick={here}><MapPin size={13} />{tr('Мой дом — здесь (геолокация)')}</button>
    {err && <small className="home-err">{tr(err)}</small>}
    <small className="home-privacy">{tr('Хранится только на этом устройстве, округлено до ~100 м.')}</small>
    {home && <button type="button" className="home-remove" onClick={() => { saveHome(null); setHome(null); setResults(null); }}>{tr('Удалить адрес дома')}</button>}
  </div>;
}

// Ready-made themed walks: tap one to see it on the map with its stops.
function RouteIdeas({ ideas, onShow }) {
  return <div className="route-ideas">{ideas.map(i => <button key={i.key} className="route-idea" onClick={() => onShow(i)}>
    <span className="route-idea-emoji" aria-hidden="true">{i.emoji}</span>
    <span className="route-idea-text"><b>{i.title}</b><small>≈ {i.total_min} {tr('мин')} · {i.stops.length} {tr(i.stops.length === 1 ? 'место' : 'места')}</small>
      <span>{i.stops.join(' → ')}</span></span>
    <MapIcon size={16} className="route-idea-go" />
  </button>)}</div>;
}

const Speech = typeof window !== 'undefined' ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null;

// Speak instead of typing: the words appear in the box as you talk and are sent when you stop.
function VoiceButton({ disabled, onText, onFinal }) {
  const [on, setOn] = useState(false), rec = useRef(null);
  useEffect(() => () => rec.current?.abort(), []);
  if (!Speech) return null;
  function toggle() {
    if (on) { rec.current?.stop(); return; }
    const r = new Speech(); rec.current = r;
    r.lang = { ru: 'ru-RU', kk: 'kk-KZ', en: 'en-US' }[getLanguage()] || 'ru-RU';
    r.interimResults = true; r.maxAlternatives = 1;
    let text = '';
    r.onresult = e => { text = Array.from(e.results).map(x => x[0].transcript).join(' ').trim(); onText(text); };
    r.onend = () => { setOn(false); if (text) onFinal(text); };
    r.onerror = () => setOn(false);
    setOn(true); r.start();
  }
  return <button type="button" className={'photo-button voice-button' + (on ? ' listening' : '')} disabled={disabled} onClick={toggle}
    aria-pressed={on} aria-label={tr(on ? 'Остановить запись' : 'Сказать голосом')} title={tr(on ? 'Остановить запись' : 'Сказать голосом')}><Mic size={18} /></button>;
}

const STAGES = ['Понимаю запрос…', 'Ищу места рядом…', 'Проверяю часы работы и погоду…', 'Пишу, почему именно они…'];

function useStage(loading) {
  const [stage, setStage] = useState(0);
  useEffect(() => {
    setStage(0); if (!loading) return;
    const id = setInterval(() => setStage(s => Math.min(s + 1, STAGES.length - 1)), 1300);
    return () => clearInterval(id);
  }, [loading]);
  return STAGES[stage];
}

export default function Chat({ requestPlan, onMood, location, setLocation, onResult, starter, sheet = false, open = true, onOpen, onClose, photoEnabled = false, onRoute, onDetails, routed, notice, onIdeas, onShowIdea }) {
  const [messages, setMessages] = useState([welcome]),
    [query, setQuery] = useState(''),
    [loading, setLoading] = useState(false),
    [locationOpen, setLocationOpen] = useState(false),
    [error, setError] = useState('');
  const controller = useRef(null), lastRequest = useRef(null), log = useRef(null), sequence = useRef(0), locationBox = useRef(null), input = useRef(null);
  const asSheet = sheet && open;
  const stage = useStage(loading);
  const close = () => { if (history.state?.seruChat) history.back(); else onClose?.(); };
  useSheetViewport(asSheet, () => onClose?.());
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
  }, [messages, loading, asSheet]);
  useLayoutEffect(() => {  // the composer grows with the text (1–5 lines) instead of being a fixed box
    const el = input.current; if (!el) return;
    el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 132) + 'px';
  }, [query, asSheet]);
  useEffect(() => {
    if (!locationOpen) return;
    const closeMenu = e => { if (!locationBox.current?.contains(e.target)) setLocationOpen(false); };
    const escape = e => { if (e.key === 'Escape') setLocationOpen(false); };
    document.addEventListener('pointerdown', closeMenu); document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', closeMenu); document.removeEventListener('keydown', escape); };
  }, [locationOpen]);

  function append(items) {
    setMessages(prev => [...prev, ...items.map(m => ({ ...m, id: ++sequence.current }))].slice(-20));
  }
  function cancel() { controller.current?.abort(); setLoading(false); setError('Запрос отменён. Текст сохранён.'); onMood?.('idle'); }
  async function send(text, index, override, retry = false, display, photo) {
    if (!text.trim() && !photo) return;
    if(!navigator.onLine){setQuery(text);lastRequest.current={text,index,override,photo};setError('Нет сети. Текст сохранён. Подключись к интернету и повтори запрос.');return;}
    if (photo && photo.size > 8 * 1024 * 1024) { setError('Фото больше 8 МБ — выбери поменьше.'); return; }
    controller.current?.abort(); const active = new AbortController(); controller.current = active;
    setError(''); setLoading(true); setQuery(text); onMood?.('thinking');
    if (!retry) append([{ role: 'user', text: display || text || tr('Где я? Вот фото'), image: photo ? URL.createObjectURL(photo) : null }]);
    lastRequest.current = { text, index, override, photo };
    const timeout = setTimeout(() => { if (controller.current === active) { active.abort(); setLoading(false); setError('Ответ задерживается. Попробуй ещё раз.'); onMood?.('idle'); } }, 25000);
    try {
      input.current?.blur();
      const plan = await requestPlan(text, override, active.signal, photo);
      if (active.signal.aborted) return;
      const real = plan.places.filter(p => !p.generated), g = plan.photoGuess;
      const seen = g?.recognized && g.name ? tr('Похоже, это «{name}».', { name: g.name }) + ' ' : '';
      append([{ role: 'assistant', result: true, count: real.length, summary: seen + (plan.summary || ''), names: real.map(p => p.name), places: real.slice(0, 3), route: plan.route, note: real.length ? null : plan.notes[0],
        used: plan.used, considered: plan.considered, notes: plan.notes }]);
      setQuery(current => current === text ? '' : current); setLoading(false); onMood?.(real.length ? 'happy' : 'idle');
    } catch (e) {
      if (active.signal.aborted) return;
      const m = e?.message || '';
      setLoading(false); setError(m === 'rate' ? 'Слишком много запросов. Подожди минуту и попробуй снова.' : m === 'photo_too_large' ? 'Фото больше 8 МБ — выбери поменьше.'
        : m.startsWith('photo-') ? 'Не получилось разобрать фото. Попробуй другое или напиши ориентир.' : 'Не удалось загрузить подборку. Текст сохранён — попробуй ещё раз.'); onMood?.('idle');
    } finally { clearTimeout(timeout); }
  }
  useEffect(() => { if (starter) send(starter.text, starter.index, starter.context, false, starter.display); }, [starter]);
  async function askIdeas() {
    if (loading || !onIdeas) return;
    controller.current?.abort();
    setError(''); setLoading(true); onMood?.('thinking');
    append([{ role: 'user', text: tr('🗺 Покажи интересные маршруты рядом') }]);
    try {
      const ideas = await onIdeas();
      append([ideas.length ? { role: 'assistant', text: 'Вот готовые маршруты от тебя — выбери настроение, покажу путь на карте:', ideas }
        : { role: 'assistant', text: 'Рядом не получилось собрать маршрут из 2–3 мест. Попробуй другую точку старта.' }]);
      onMood?.(ideas.length ? 'happy' : 'idle');
    } catch (e) { setError(e?.message === 'rate' ? 'Слишком много запросов. Подожди минуту и попробуй снова.' : 'Не удалось собрать маршруты. Попробуй ещё раз.'); onMood?.('idle'); }
    finally { setLoading(false); }
  }
  function reset() { controller.current?.abort(); setError(''); setLoading(false); onMood?.('idle'); setMessages([welcome]); setQuery(''); }

  const last = messages.at(-1);
  if (sheet && !open) {  // phone, closed: a compact entry point that keeps the conversation state
    return <section className="chat-launcher" id="chat-panel" aria-label={tr('Чат с Серу')}>
      <button className="launcher-main" onClick={() => onOpen?.()}>
        <span className="chat-avatar seru-avatar"><Mascot decorative mood={loading ? 'thinking' : last?.result ? 'happy' : 'wave'} /></span>
        <span className="launcher-text"><strong>{tr('Открыть чат с Серу')}</strong><span>{loading ? tr('Собираю прогулку…') : last?.result ? (last.summary || tr('Подборка готова')) : tr('Опиши, где ты и чего хочется — подберу места рядом')}</span></span>
        <span className="launcher-go"><MessageCircle size={22} /></span>
      </button>
      <div className="launcher-moods">{onIdeas && <button onClick={() => { onOpen?.(); askIdeas(); }}><MapIcon size={14} />{tr('Маршруты')}</button>}{scenarios.map((s, i) => <button key={s.label} onClick={() => { onOpen?.(); send(tr(s.query), i); }}><s.icon size={14} />{tr(s.label)}</button>)}</div>
    </section>;
  }

  const panel = <section className={'chat-panel' + (messages.length>1?' has-messages':'') + (asSheet ? ' chat-sheet' : '')} id="chat-panel" aria-labelledby="chat-heading" role={asSheet ? 'dialog' : undefined} aria-modal={asSheet || undefined}>
    <div className="chat-heading">
      {asSheet && <button className="sheet-close" onClick={close} aria-label={tr('Свернуть чат')}><ChevronDown size={22} /></button>}
      <span className="chat-avatar seru-avatar"><Mascot decorative mood={loading ? 'thinking' : last?.result ? 'happy' : 'wave'} /></span>
      <div><h2 id="chat-heading">{tr("Серу на связи")}</h2><p><span />{tr(loading ? 'Подбираю места…' : 'Есть идея для твоей прогулки')}</p></div>
      <button className="chat-reset" aria-label={tr("Начать новый диалог")} title={tr("Новый диалог")} onClick={reset}><RotateCcw size={17} /></button>
    </div>
    <div className="chat-body">
      {notice}
      <div className="chat-log" ref={log} role="log" aria-label={tr("История диалога")} aria-live="polite" aria-relevant="additions">
        {messages.map(m => <div key={m.id} className={'chat-message ' + m.role}><span className="message-author">{m.role === 'assistant' ? tr('Серу · твой спутник') : tr('Ты')}</span>
          {m.image && <img className="message-photo" src={m.image} alt={tr('Твоё фото')} />}
          <p>{m.role === 'user' ? m.text : m.result ? !m.count ? (m.note || tr('Подходящих мест пока нет')) : <>{m.summary}</> : tr(m.text)}</p>
          {m.ideas?.length > 0 && <RouteIdeas ideas={m.ideas} onShow={i => { if (asSheet) close(); onShowIdea?.(i); }} />}
          {m.result && m.places?.length > 0 && <ChatPlaces places={m.places} route={m.route} onRoute={p => { if (asSheet) close(); onRoute?.(p); }} onDetails={onDetails} routed={routed} />}
          {m.result && m.count > 0 && <details className="chat-answer-details"><summary>{tr("Что я учёл")}<ChevronDown size={13}/></summary><ChatReasoning used={m.used} considered={m.considered} notes={m.notes} /></details>}
          {m.result && m.count > 0 && <button className="message-results" onClick={() => { if (asSheet) close(); onResult?.(); }}>{tr('Все места и карта')} · {m.count}<ArrowUpRight size={14} /></button>}
        </div>)}
        {loading && <div className="chat-typing" role="status"><span className="thinking-seru"><Mascot decorative mood="thinking" /></span><span className="typing-dots" aria-hidden="true"><i /><i /><i /></span>{tr(stage)}</div>}
      </div>
      {(loading || error) && <div className="request-status" role="status">{loading ? <button onClick={cancel}>{tr('Отменить поиск')}</button> : <><p>{tr(error)}</p><button onClick={() => { const r = lastRequest.current; if (r) send(r.text, r.index, r.override, true, undefined, r.photo); }}>{tr('Повторить запрос')}</button></>}</div>}
      <div className="quick-scenarios" hidden={messages.length > 1}><div>{onIdeas && <button className="ideas-chip" onClick={askIdeas}><MapIcon size={14} />{tr('Маршруты')}</button>}{scenarios.slice(0, 3).map((s, i) => <button disabled={loading} key={s.label} onClick={() => send(tr(s.query), i)}><s.icon size={14} />{tr(s.label)}</button>)}</div></div>
      <form className="chat-composer" onSubmit={e => { e.preventDefault(); if (!loading) send(query); }}>
        <div className="composer-input"><Sparkles size={19} /><textarea ref={input} id="chat-input" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); e.currentTarget.form.requestSubmit(); }
        }} placeholder={tr(messages.length > 1 ? "Что изменить или найти?" : "Например: кофе и прогулка на час")} aria-label={tr("Как хочешь провести время?")} rows={1} enterKeyHint="send" /></div>
        <div className="composer-bottom">
          <div className="location-picker" ref={locationBox}><button type="button" className="location-toggle" aria-expanded={locationOpen} onClick={() => setLocationOpen(!locationOpen)}><MapPin size={13} /><span>{location === MY_LOCATION ? '📍 ' : location === HOME ? '🏠 ' : ''}{tr(location)}</span><ChevronDown size={12} /></button>
            {locationOpen && <div className="location-options"><HomePicker onPick={() => { setLocation(HOME); setLocationOpen(false); }} />{landmarks.map(l => <button type="button" key={l} onClick={() => { setLocation(l); setLocationOpen(false); }}>{tr(l)}{l === location && <Check size={14} />}</button>)}</div>}</div>
          {(Speech || photoEnabled) && <details className="chat-tools"><summary aria-label={tr("Голос и фото")} title={tr("Голос и фото")}><Plus size={18}/></summary><div className="chat-tools-popover"><VoiceButton disabled={loading} onText={setQuery} onFinal={text => send(text)} />
          {photoEnabled && <label className="photo-button" role="button" tabIndex={loading ? -1 : 0} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.currentTarget.querySelector('input')?.click();}}} title={tr('Где я? Отправь фото места')} aria-label={tr('Где я? Отправь фото места')}>
            <Camera size={18} /><input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" hidden disabled={loading}
              onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) send(query.trim(), undefined, undefined, false, undefined, f); }} /></label>}
          </div></details>}
          <button className="send-button" type="submit" disabled={loading || !query.trim()} aria-label={tr("Подобрать места")}><span>{loading ? tr('Подбираю…') : tr('Найти места')}</span><ArrowUpRight size={17} /></button>
        </div>
      </form>

    </div>
  </section>;
  return asSheet ? <>{createPortal(panel, document.body)}<div className="chat-launcher placeholder" id="chat-panel-anchor" /></> : panel;
}
