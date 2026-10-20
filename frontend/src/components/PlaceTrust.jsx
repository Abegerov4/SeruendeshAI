import React, { useState } from 'react';
import { ThumbsUp, ThumbsDown, Check } from 'lucide-react';
import { t as tr, getLanguage } from '../i18n';
import { sendFeedback } from '../api';

// «12 туда + 30 на месте = 42 из 60 мин»: the same numbers the server checked the place against
export function TimeLedger({ place: p, compact = false }) {
  if (p.generated || p.travel == null || !p.visit || !p.budget) return null;
  const back = p.returnMin || 0, used = p.travel + p.visit + back, free = Math.max(0, p.budget - used);
  const pct = n => Math.max(0, Math.min(100, (n / Math.max(p.budget, used)) * 100)) + '%';
  return <div className={'time-ledger' + (compact ? ' compact' : '')}>
    <div className="ledger-bar" aria-hidden="true"><i className="go" style={{ width: pct(p.travel) }} /><i className="stay" style={{ width: pct(p.visit) }} />{back > 0 && <i className="back" style={{ width: pct(back) }} />}</div>
    <p>{p.travel} {tr('туда')} + {p.visit} {tr('на месте')}{back > 0 ? ` + ${back} ${tr('обратно')}` : ''} = <b>{used} {tr('из')} {p.budget} {tr('мин')}</b>
      {free >= 5 && <span> · {tr('запас')} {free} {tr('мин')}</span>}</p>
    {!back && !compact && p.mode === 'walk' && <small>{tr('Вернуться к старту — ещё ≈ {m} мин', { m: p.travel })}</small>}
  </div>;
}

const REASONS = [['closed', 'Было закрыто'], ['wrong_hours', 'Часы не совпали'], ['not_as_described', 'Не то, что написано'], ['other', 'Другое']];
const seenKey = id => 'seru-mark-' + id;
function seen(id) { try { return localStorage.getItem(seenKey(id)); } catch { return null; } }

// 👍 / 👎 with a reason: an anonymous mark (day × place × kind); «было закрыто» can only lower trust in «open»
export function PlaceFeedback({ place: p }) {
  const [done, setDone] = useState(() => seen(p.id)), [asking, setAsking] = useState(false), [error, setError] = useState(false);
  if (p.generated || !p.id) return null;
  async function send(kind) {
    setAsking(false); setError(false);
    try { await sendFeedback(p.id, kind, getLanguage()); setDone(kind); try { localStorage.setItem(seenKey(p.id), kind); } catch {} }
    catch { setError(true); }
  }
  if (done) return <p className="place-feedback thanks" role="status"><Check size={14} />{tr(done === 'great' ? 'Спасибо! Рады, что место понравилось.' : 'Спасибо! Если это подтвердят другие, часы покажем как неподтверждённые.')}</p>;
  return <div className="place-feedback">
    <span>{tr('Как место?')}</span>
    <button type="button" onClick={() => send('great')} aria-label={tr('Понравилось')} title={tr('Понравилось')}><ThumbsUp size={15} /></button>
    <button type="button" aria-expanded={asking} onClick={() => setAsking(!asking)} aria-label={tr('Что-то не так')} title={tr('Что-то не так')}><ThumbsDown size={15} /></button>
    {asking && <div className="feedback-reasons" role="group" aria-label={tr('Что не так?')}>{REASONS.map(([kind, label]) => <button type="button" key={kind} onClick={() => send(kind)}>{tr(label)}</button>)}</div>}
    {error && <small role="alert">{tr('Не получилось отправить. Попробуй ещё раз.')}</small>}
  </div>;
}
