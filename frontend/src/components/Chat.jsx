import { t as tr } from "../i18n";
import React, { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, MapPin, ChevronDown, Check, ShieldCheck, RotateCcw, Sparkles } from 'lucide-react';
import { landmarks, scenarios } from '../data';
import { MY_LOCATION } from '../api';
import Mascot from './Mascot';
const welcome = {
  id: 0,
  role: 'assistant',
  text: 'Сәлем! Я Серу 👋 Собираю маленькие радости большого города. Чего сегодня хочется: кофе у окна, прогулки без спешки или чего-то совсем нового?'
};
export default function Chat({
  onScenario,
  requestPlan,
  onMood,
  location,
  setLocation,
  onResult,
  starter
}) {
  const [messages, setMessages] = useState([welcome]),
    [query, setQuery] = useState(''),
    [loading, setLoading] = useState(false),
    [locationOpen, setLocationOpen] = useState(false);
  const [error,setError]=useState('');
  const controller=useRef(null),lastRequest=useRef(null);
  const timer = useRef(null),
    log = useRef(null),
    sequence = useRef(0),
    locationBox = useRef(null);
  useEffect(() => () => {clearTimeout(timer.current);controller.current?.abort();}, []);
  useEffect(() => {
    log.current?.scrollTo({
      top: log.current.scrollHeight,
      behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'
    });
  }, [messages, loading]);
  useEffect(() => {
    if (!locationOpen) return;
    const close = e => {
      if (!locationBox.current?.contains(e.target)) setLocationOpen(false);
    };
    const escape = e => {
      if (e.key === 'Escape') setLocationOpen(false);
    };
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', escape);
    };
  }, [locationOpen]);
  function append(items) {
    setMessages(prev => [...prev, ...items.map(m => ({
      ...m,
      id: ++sequence.current
    }))].slice(-20));
  }
  function cancel(){controller.current?.abort();setLoading(false);setError('Запрос отменён. Текст сохранён.');onMood?.('idle');}
  async function send(text,index,override,retry=false,display){
    if(!text.trim())return;
    controller.current?.abort();const active=new AbortController();controller.current=active;
    setError('');setLoading(true);setQuery(text);onMood?.('thinking');
    if(!retry)append([{role:'user',text:display||text}]);
    lastRequest.current={text,index,override};
    const timeout=setTimeout(()=>{if(controller.current===active){active.abort();setLoading(false);setError('Ответ задерживается. Попробуй ещё раз.');onMood?.('idle');}},25000);
    try{const plan=await requestPlan(text,override,active.signal);if(active.signal.aborted)return;const real=plan.places.filter(p=>!p.generated);append([{role:'assistant',result:true,count:real.length,summary:plan.summary,names:real.map(p=>p.name),note:real.length?null:plan.notes[0],template:plan.llm?.mode==='template'}]);setQuery(current=>current===text?'':current);setLoading(false);onMood?.(real.length?'happy':'idle');}
    catch(e){if(active.signal.aborted)return;setLoading(false);setError(e?.message==='rate'?'Слишком много запросов. Подожди минуту и попробуй снова.':'Не удалось загрузить подборку. Текст сохранён — попробуй ещё раз.');onMood?.('idle');}
    finally{clearTimeout(timeout);}
  }
  useEffect(() => {
    if (starter) send(starter.text, starter.index, starter.context, false, starter.display);
  }, [starter]);
  return <section className="chat-panel" id="chat-panel" aria-labelledby="chat-heading"><div className="chat-heading"><span className="chat-avatar seru-avatar"><Mascot decorative mood={loading ? 'thinking' : messages.at(-1)?.result ? 'happy' : 'wave'} /></span><div><h2 id="chat-heading">{tr("Серу на связи")}</h2><p><span />{tr("Есть идея для твоей прогулки")}</p></div><button className="chat-reset" aria-label={tr("Начать новый диалог")} title={tr("Новый диалог")} onClick={() => {
        clearTimeout(timer.current);controller.current?.abort();setError('');
        setLoading(false);
        onMood?.('idle');
        setMessages([welcome]);
        setQuery('');
      }}><RotateCcw size={17} /></button></div><div className="chat-body"><div className="chat-log" ref={log} role="log" aria-label={tr("История диалога")} aria-live="polite" aria-relevant="additions"><span className="chat-date">{tr("МАЛЕНЬКОЕ ПРИКЛЮЧЕНИЕ НАЧИНАЕТСЯ ЗДЕСЬ")}</span>{messages.map(m => <div key={m.id} className={'chat-message ' + m.role}><span className="message-author">{m.role === 'assistant' ? tr('Серу · твой спутник') : tr('Ты')}</span><p>{m.role === 'user' ? m.text : m.result ? !m.count ? (m.note || tr('Подходящих мест пока нет')) : <>{m.summary} {tr('Посмотри карточки — там объясню, почему и что делать на месте.')}</> : tr(m.text)}</p>{m.result && <button className="message-results" onClick={onResult}>{tr("Посмотреть места")}<ArrowUpRight size={14} /></button>}</div>)}{loading && <div className="chat-typing" role="status"><span className="thinking-seru"><Mascot decorative mood={loading ? 'thinking' : messages.at(-1)?.result ? 'happy' : 'wave'} /></span><span className="typing-dots" aria-hidden="true"><i /><i /><i /></span>{tr("Собираю прогулку…")}</div>}</div>{(loading||error)&&<div className="request-status" role="status">{loading?<button onClick={cancel}>{tr('Отменить поиск')}</button>:<><p>{tr(error)}</p><button onClick={()=>{const r=lastRequest.current;if(r)send(r.text,r.index,r.override,true);}}>{tr('Повторить запрос')}</button></>}</div>}<div className="quick-scenarios"><span>{tr("ИЛИ НАЧНИ С НАСТРОЕНИЯ")}</span><div>{scenarios.map((s, i) => <button key={tr(s.label)} onClick={() => send(tr(s.query), i)}><s.icon size={14} />{tr(s.label)}</button>)}</div></div><form className="chat-composer" onSubmit={e => {
        e.preventDefault();
        if (!loading) send(query);
      }}><div className="composer-input"><Sparkles size={19} /><textarea id="chat-input" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              e.currentTarget.form.requestSubmit();
            }
          }} placeholder={tr("Я рядом с Байтереком. Куда заглянуть?")} aria-label={tr("Как хочешь провести время?")} rows={2} /></div><div className="composer-bottom"><div className="location-picker" ref={locationBox}><button type="button" className="location-toggle" aria-expanded={locationOpen} onClick={() => setLocationOpen(!locationOpen)}><MapPin size={13} /><span>{location === MY_LOCATION ? '📍 ' : ''}{tr(location)}</span><ChevronDown size={12} /></button>{locationOpen && <div className="location-options">{landmarks.map(l => <button type="button" key={l} onClick={() => {
                setLocation(l);
                setLocationOpen(false);
              }}>{tr(l)}{l === location && <Check size={14} />}</button>)}</div>}</div><button className="send-button" type="submit" disabled={loading || !query.trim()} aria-label={tr("Подобрать места")}>{loading ? tr('Подбираю…') : tr('Найти места')}<ArrowUpRight size={17} /></button></div></form><div className="chat-note"><ShieldCheck size={12} /><span>{tr("Локация примерная, ничего не храним.")}</span></div></div></section>;
}
