import { t as tr } from "../i18n";
import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowUpRight, ArrowUp, MapPin, ChevronDown, Check, ShieldCheck, RotateCcw, Sparkles, Camera, MessageCircle, Navigation, Footprints, Car, Info } from 'lucide-react';
import PlaceVisual from './PlaceVisual';
import { hoursTone, shortHours } from './PlaceCard';
import { landmarks, scenarios } from '../data';
import { MY_LOCATION } from '../api';
import Mascot from './Mascot';

const welcome = {
  id: 0,
  role: 'assistant',
  text: 'Сәлем! Я Серу 👋 Собираю маленькие радости большого города. Чего сегодня хочется: кофе у окна, прогулки без спешки или чего-то совсем нового?'
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
function ChatPlaces({ places, onRoute, onDetails, routed }) {
  return <div className="chat-places">{places.map((p, i) => {
    const Mode = p.mode === 'car' ? Car : Footprints;
    return <article key={p.id} className={'chat-place' + (routed === p.id ? ' routed' : '')}>
      <button className="chat-place-main" onClick={() => onRoute?.(p)} aria-label={tr('Маршрут до места') + ': ' + p.name}>
        <span className="chat-place-thumb"><PlaceVisual place={p} /><i>{i + 1}</i></span>
        <span className="chat-place-text"><b>{p.name}</b><small>{p.category}</small>
          <small className="chat-place-meta"><Mode size={12} />{p.distance} · {p.travel} {tr('мин')}<span className={'chat-hours ' + hoursTone(p)}>{shortHours(p)}</span></small></span>
      </button>
      {p.why && <p className="chat-place-why">{p.why}</p>}
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
    used.weather && '🌡 ' + Math.round(used.weather.temperature_c) + '°C' + (used.weather.max_outdoor_min < 60 ? ' · ' + tr('холодно') : ''),
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

export default function Chat({ requestPlan, onMood, location, setLocation, onResult, starter, sheet = false, open = true, onOpen, onClose, photoEnabled = false, onRoute, onDetails, routed, notice }) {
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
      const plan = await requestPlan(text, override, active.signal, photo);
      if (active.signal.aborted) return;
      const real = plan.places.filter(p => !p.generated), g = plan.photoGuess;
      const seen = g?.recognized && g.name ? tr('Похоже, это «{name}».', { name: g.name }) + ' ' : '';
      append([{ role: 'assistant', result: true, count: real.length, summary: seen + (plan.summary || ''), names: real.map(p => p.name), places: real.slice(0, 3), note: real.length ? null : plan.notes[0],
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
  function reset() { controller.current?.abort(); setError(''); setLoading(false); onMood?.('idle'); setMessages([welcome]); setQuery(''); }

  const last = messages.at(-1);
  if (sheet && !open) {  // phone, closed: a compact entry point that keeps the conversation state
    return <section className="chat-launcher" id="chat-panel" aria-label={tr('Чат с Серу')}>
      <button className="launcher-main" onClick={() => onOpen?.()}>
        <span className="chat-avatar seru-avatar"><Mascot decorative mood={loading ? 'thinking' : last?.result ? 'happy' : 'wave'} /></span>
        <span className="launcher-text"><strong>{tr('Открыть чат с Серу')}</strong><span>{loading ? tr('Собираю прогулку…') : last?.result ? (last.summary || tr('Подборка готова')) : tr('Опиши, где ты и чего хочется — подберу места рядом')}</span></span>
        <span className="launcher-go"><MessageCircle size={22} /></span>
      </button>
      <div className="launcher-moods">{scenarios.map((s, i) => <button key={s.label} onClick={() => { onOpen?.(); send(tr(s.query), i); }}><s.icon size={14} />{tr(s.label)}</button>)}</div>
    </section>;
  }

  const panel = <section className={'chat-panel' + (asSheet ? ' chat-sheet' : '')} id="chat-panel" aria-labelledby="chat-heading" role={asSheet ? 'dialog' : undefined} aria-modal={asSheet || undefined}>
    <div className="chat-heading">
      {asSheet && <button className="sheet-close" onClick={close} aria-label={tr('Свернуть чат')}><ChevronDown size={22} /></button>}
      <span className="chat-avatar seru-avatar"><Mascot decorative mood={loading ? 'thinking' : last?.result ? 'happy' : 'wave'} /></span>
      <div><h2 id="chat-heading">{tr("Серу на связи")}</h2><p><span />{tr(loading ? 'Подбираю места…' : 'Есть идея для твоей прогулки')}</p></div>
      <button className="chat-reset" aria-label={tr("Начать новый диалог")} title={tr("Новый диалог")} onClick={reset}><RotateCcw size={17} /></button>
    </div>
    <div className="chat-body">
      {notice}
      <div className="chat-log" ref={log} role="log" aria-label={tr("История диалога")} aria-live="polite" aria-relevant="additions">
        <span className="chat-date">{tr("МАЛЕНЬКОЕ ПРИКЛЮЧЕНИЕ НАЧИНАЕТСЯ ЗДЕСЬ")}</span>
        {messages.map(m => <div key={m.id} className={'chat-message ' + m.role}><span className="message-author">{m.role === 'assistant' ? tr('Серу · твой спутник') : tr('Ты')}</span>
          {m.image && <img className="message-photo" src={m.image} alt={tr('Твоё фото')} />}
          <p>{m.role === 'user' ? m.text : m.result ? !m.count ? (m.note || tr('Подходящих мест пока нет')) : <>{m.summary} {tr('Нажми на место — построю маршрут от тебя.')}</> : tr(m.text)}</p>
          {m.result && m.places?.length > 0 && <ChatPlaces places={m.places} onRoute={p => { if (asSheet) close(); onRoute?.(p); }} onDetails={onDetails} routed={routed} />}
          {m.result && m.count > 0 && <ChatReasoning used={m.used} considered={m.considered} notes={m.notes} />}
          {m.result && m.count > 0 && <button className="message-results" onClick={() => { if (asSheet) close(); onResult?.(); }}>{tr('Все места и карта')} · {m.count}<ArrowUpRight size={14} /></button>}
        </div>)}
        {loading && <div className="chat-typing" role="status"><span className="thinking-seru"><Mascot decorative mood="thinking" /></span><span className="typing-dots" aria-hidden="true"><i /><i /><i /></span>{tr(stage)}</div>}
      </div>
      {(loading || error) && <div className="request-status" role="status">{loading ? <button onClick={cancel}>{tr('Отменить поиск')}</button> : <><p>{tr(error)}</p><button onClick={() => { const r = lastRequest.current; if (r) send(r.text, r.index, r.override, true, undefined, r.photo); }}>{tr('Повторить запрос')}</button></>}</div>}
      <div className="quick-scenarios"><span>{tr("ИЛИ НАЧНИ С НАСТРОЕНИЯ")}</span><div>{scenarios.map((s, i) => <button key={s.label} onClick={() => send(tr(s.query), i)}><s.icon size={14} />{tr(s.label)}</button>)}</div></div>
      <form className="chat-composer" onSubmit={e => { e.preventDefault(); if (!loading) send(query); }}>
        <div className="composer-input"><Sparkles size={19} /><textarea ref={input} id="chat-input" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); e.currentTarget.form.requestSubmit(); }
        }} placeholder={tr("Чего хочется? Например: кофе и прогулка на час")} aria-label={tr("Как хочешь провести время?")} rows={asSheet ? 1 : 2} enterKeyHint="send" /></div>
        <div className="composer-bottom">
          <div className="location-picker" ref={locationBox}><button type="button" className="location-toggle" aria-expanded={locationOpen} onClick={() => setLocationOpen(!locationOpen)}><MapPin size={13} /><span>{location === MY_LOCATION ? '📍 ' : ''}{tr(location)}</span><ChevronDown size={12} /></button>
            {locationOpen && <div className="location-options">{landmarks.map(l => <button type="button" key={l} onClick={() => { setLocation(l); setLocationOpen(false); }}>{tr(l)}{l === location && <Check size={14} />}</button>)}</div>}</div>
          {photoEnabled && <label className="photo-button" title={tr('Где я? Отправь фото места')} aria-label={tr('Где я? Отправь фото места')}>
            <Camera size={18} /><input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" hidden disabled={loading}
              onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) send(query.trim(), undefined, undefined, false, undefined, f); }} /></label>}
          <button className="send-button" type="submit" disabled={loading || !query.trim()} aria-label={tr("Подобрать места")}><span>{loading ? tr('Подбираю…') : tr('Найти места')}</span><ArrowUpRight size={17} /></button>
        </div>
      </form>
      <div className="chat-note"><ShieldCheck size={12} /><span>{tr("Локация примерная, ничего не храним.")}</span></div>
    </div>
  </section>;
  return asSheet ? <>{createPortal(panel, document.body)}<div className="chat-launcher placeholder" id="chat-panel-anchor" /></> : panel;
}
