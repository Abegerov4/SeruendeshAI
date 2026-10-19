import { useLocale, t as tr, getLanguage } from "../i18n";
import React, { useEffect, useState } from 'react';
import { ArrowUpRight, ArrowLeft, Mail, LockKeyhole, Eye, EyeOff, User, Check, ShieldCheck, MapPin, Heart, Route, Info } from 'lucide-react';
import { Link, navigate } from '../navigation';
import { login, register as registerUser, requestReset, confirmReset, AUTH_ERRORS } from '../auth';
import { AuthHeader } from '../components/Layout';
import Mascot from '../components/Mascot';
export default function Auth({
  mode
}) {
  const language = useLocale();
  const register = mode === 'register',
    reset = mode === 'reset',
    confirm = mode === 'confirm';
  const token = new URLSearchParams(location.search).get('token') || '';
  const [busy, setBusy] = useState(false), [ok, setOk] = useState(false);
  const [show, setShow] = useState(false),
    [feedback, setFeedback] = useState(''),
    [password, setPassword] = useState(''),
    [errors, setErrors] = useState({});
  useEffect(() => {
    document.title = (register ? tr('Регистрация') : reset ? tr('Восстановить пароль') : confirm ? tr('Новый пароль') : tr('Войти')) + ' — SeruendeshAI';
  }, [mode, language]);
  async function submit(e) {
    e.preventDefault();
    setFeedback(''); setOk(false);
    const form = e.currentTarget, data = new FormData(form);
    const email = String(data.get('email') || '').trim(), name = String(data.get('name') || '').trim(), pass = String(data.get('password') || '');
    const next = {};
    if (register && name.length < 2) next.name = tr('Как к тебе обращаться? Введи хотя бы 2 символа.');
    if (!confirm && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) next.email = tr('Введи email в формате name@example.com.');
    if (!reset && pass.length < (register || confirm ? 8 : 1)) next.password = register || confirm ? tr('Для пароля нужно минимум 8 символов.') : tr('Введи пароль.');
    setErrors(next);
    if (Object.keys(next).length) { form.querySelector(`[name="${Object.keys(next)[0]}"]`)?.focus(); return; }
    setBusy(true);
    try {
      if (register) { await registerUser(name, email, pass, getLanguage()); navigate('/'); }
      else if (reset) { await requestReset(email); setOk(true); setFeedback(tr('Если такой аккаунт есть, мы отправили письмо со ссылкой. Она действует 1 час.')); }
      else if (confirm) { await confirmReset(token, pass); navigate('/'); }
      else { await login(email, pass); navigate('/'); }
    } catch (err) {
      setFeedback(tr(AUTH_ERRORS[err.message] || (err.status === 422 ? 'Проверь поля формы.' : 'Не получилось. Проверь соединение и попробуй ещё раз.')));
    } finally { setBusy(false); }
  }
  return <div className="auth-page"><AuthHeader /><main className="auth-layout"><aside className="auth-visual"><img className="auth-city-photo" src="/images/astana-hero.webp" alt={tr("AI-визуализация вечерней Астаны")} /><div className="auth-visual-top"><span className="tiny-dot" />{tr(" ТВОЙ ГОРОД. ТВОЯ ИСТОРИЯ.")}</div><div className="auth-seru"><span>{tr("Пойдём знакомиться с городом?")}</span><Mascot decorative /></div><div className="auth-visual-copy"><span className="auth-location"><MapPin size={13} />{tr("Астана, Казахстан")}</span><h1>{tr("Знакомый город.")}<br /><em>{tr("Новые чувства.")}</em></h1><p>{tr("Сохраняй маленькие открытия.")}<br />{tr("Возвращайся к любимым маршрутам.")}<br />{tr("Находи повод выйти из дома.")}</p><div className="auth-benefits"><span><Heart size={15} />{tr("Любимые места")}</span><span><Route size={15} />{tr("Твои маршруты")}</span></div></div><span className="auth-image-note">{tr("Нуржол на закате · AI-визуализация")}</span></aside><section className="auth-form-panel"><div className="auth-form-inner"><span className="section-eyebrow">{register ? tr('ПЕРВЫЙ ШАГ К ОТКРЫТИЯМ') : reset || confirm ? tr('СНОВА НА СВЯЗИ') : tr('РАДЫ ВИДЕТЬ ТЕБЯ')}</span><h2>{register ? tr('Город ждёт тебя.') : reset ? tr('Забыл пароль?') : confirm ? tr('Новый пароль') : tr('С возвращением.')}</h2><p className="auth-description">{register ? tr('Создай свой уголок в большом городе.') : reset ? tr('Укажи email, связанный с твоим аккаунтом.') : confirm ? tr('Придумай новый пароль — и снова в путь.') : tr('Твои любимые места — на расстоянии одного шага.')}</p><form noValidate onSubmit={submit} className="auth-form">{register && <Field label={tr("Как тебя зовут")} name="name" placeholder={tr("Твоё имя")} icon={User} autoComplete="given-name" error={errors.name} />}{!confirm && <Field label="Email" name="email" placeholder="you@example.com" type="email" icon={Mail} autoComplete="email" error={errors.email} />}{!reset && <div className="form-field"><div className="field-label-row"><label htmlFor="password">{tr("Пароль")}</label>{!register && <Link to="/forgot-password">{tr("Забыли пароль?")}</Link>}</div><div className={'field-input ' + (errors.password ? 'invalid' : '')}><LockKeyhole size={17} /><input id="password" name="password" value={password} onChange={e => setPassword(e.target.value)} type={show ? 'text' : 'password'} autoComplete={register || confirm ? 'new-password' : 'current-password'} placeholder={register || confirm ? tr('Минимум 8 символов') : tr('Твой пароль')} aria-invalid={!!errors.password} aria-describedby={errors.password ? 'password-error' : register ? 'password-hint' : undefined} /><button className="password-toggle" type="button" onClick={() => setShow(!show)} aria-label={show ? tr('Скрыть пароль') : tr('Показать пароль')}>{show ? <EyeOff size={17} /> : <Eye size={17} />}</button></div>{errors.password ? <span className="field-error" id="password-error">{tr(errors.password)}</span> : (register || confirm) && <span className={'password-hint ' + (password.length >= 8 ? 'valid' : '')} id="password-hint"><Check size={12} />{tr("Не менее 8 символов")}</span>}</div>}<button className="auth-submit" type="submit" disabled={busy}>{busy ? tr('Секунду…') : register ? tr('Создать аккаунт') : reset ? tr('Получить ссылку') : confirm ? tr('Сохранить пароль') : tr('Войти')}<ArrowUpRight size={18} /></button>{feedback && <div className={'form-feedback' + (ok ? ' ok' : '')} role="status">{ok ? <Check size={18} /> : <Info size={18} />}<span>{feedback}</span></div>}</form><div className="auth-switch">{reset || confirm ? <Link to="/login"><ArrowLeft size={14} />{tr("Вернуться ко входу")}</Link> : <>{register ? tr('Уже есть аккаунт?') : tr('Пока нет аккаунта?')} <Link to={register ? '/login' : '/register'}>{register ? tr('Войти') : tr('Зарегистрироваться')}<ArrowUpRight size={13} /></Link></>}</div><div className="auth-divider"><span />{tr("или")}<span /></div><Link to="/" className="guest-button">{tr("Исследовать без аккаунта")}<ArrowUpRight size={16} /></Link><p className="auth-privacy"><ShieldCheck size={15} />{tr("Храним только имя, email и избранное. Пароль — в виде хэша. Геолокацию к аккаунту не привязываем.")}</p></div><div className="auth-form-footer"><span>SeruendeshAI</span><span>{tr("Твой спутник, а не трекер.")}</span></div></section></main></div>;
}
function Field({
  label,
  name,
  icon: Icon,
  error,
  ...props
}) {
  return <div className="form-field"><label htmlFor={name}>{tr(label)}</label><div className={'field-input ' + (error ? 'invalid' : '')}><Icon size={17} /><input name={name} id={name} aria-invalid={!!error} aria-describedby={error ? name + '-error' : undefined} {...props} /></div>{error && <span className="field-error" id={name + '-error'}>{tr(error)}</span>}</div>;
}
