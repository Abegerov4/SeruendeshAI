// Accounts: session lives in an httpOnly cookie set by the API; here we only keep the public profile.
import {useSyncExternalStore} from 'react';
import {API_BASE, placeIcon} from './api';

let state = {user: null, ready: false};
const listeners = new Set();
const emit = next => { state = {...state, ...next}; listeners.forEach(fn => fn()); };
export function useAuth() { return useSyncExternalStore(fn => (listeners.add(fn), () => listeners.delete(fn)), () => state, () => state); }

async function call(path, {method = 'GET', body} = {}) {
  const res = await fetch(`${API_BASE}${path}`, {method, credentials: 'include',
    headers: body ? {'Content-Type': 'application/json'} : undefined, body: body ? JSON.stringify(body) : undefined});
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { const e = Error(typeof data.detail === 'string' ? data.detail : 'error'); e.status = res.status; throw e; }
  return data;
}

export async function loadMe() {
  try { const d = await call('/api/auth/me'); emit({user: d && 'user' in d ? d.user : d, ready: true}); }  // guests: 200 {user: null}
  catch { emit({user: null, ready: true}); }
}
export async function register(name, email, password, lang) { const user = await call('/api/auth/register', {method: 'POST', body: {name, email, password, lang}}); emit({user}); return user; }
export async function login(email, password) { const user = await call('/api/auth/login', {method: 'POST', body: {email, password}}); emit({user}); return user; }
export async function logout() { try { await call('/api/auth/logout', {method: 'POST'}); } finally { emit({user: null}); } }
export async function deleteAccount() { await call('/api/me', {method: 'DELETE'}); emit({user: null}); }
export async function requestReset(email) { return call('/api/auth/password-reset/request', {method: 'POST', body: {email}}); }
export async function confirmReset(token, password) { const user = await call('/api/auth/password-reset/confirm', {method: 'POST', body: {token, password}}); emit({user}); return user; }

// saved places (server-side when logged in)
const SNAPSHOT = ['iconKey', 'name', 'category', 'categoryKey', 'lat', 'lon', 'address', 'why', 'action', 'url', 'image', 'status', 'distance',
  'travel', 'visit', 'visitRange', 'mode', 'features', 'badges', 'source', 'generated', 'dataSources', 'descriptionSource', 'openConfidence', 'accessibility'];
export async function fetchSaved() { return (await call('/api/me/saved')).map(r => ({id: r.poi_id, ...r.data, icon: placeIcon(r.data?.iconKey, r.data?.categoryKey)})); }
export async function putSaved(place) {
  const data = Object.fromEntries(SNAPSHOT.filter(k => place[k] !== undefined).map(k => [k, place[k]]));
  return call(`/api/me/saved/${encodeURIComponent(place.id)}`, {method: 'PUT', body: {data}});
}
export async function deleteSaved(id) { return call(`/api/me/saved/${encodeURIComponent(id)}`, {method: 'DELETE'}); }

export const AUTH_ERRORS = {
  email_taken: 'Этот email уже зарегистрирован. Попробуй войти.',
  invalid_credentials: 'Неверный email или пароль.',
  too_many_attempts: 'Слишком много попыток. Подожди несколько минут.',
  email_unavailable: 'Восстановление по почте скоро заработает. Пока напиши нам — поможем вручную.',
  invalid_or_expired_token: 'Ссылка устарела или уже использована. Запроси новую.',
};
