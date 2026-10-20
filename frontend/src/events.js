import {API_BASE} from './api.js';

const isoDay = date => date.toISOString().slice(0, 10);
const parseDay = day => new Date(`${day}T12:00:00Z`);
export const eventLocale = language => ({ru: 'ru-RU', kk: 'kk-KZ', en: 'en-GB'}[language] || 'ru-RU');
export function astanaToday(now = new Date()) {
  return new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Almaty', year:'numeric', month:'2-digit', day:'2-digit'}).format(now);
}
export function addDays(day, amount) {
  const date = parseDay(day); date.setUTCDate(date.getUTCDate() + amount); return isoDay(date);
}
export function shiftMonth(day, amount) {
  const date = parseDay(day), wanted = date.getUTCDate();
  date.setUTCDate(1); date.setUTCMonth(date.getUTCMonth() + amount);
  const last = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate();
  date.setUTCDate(Math.min(wanted, last)); return isoDay(date);
}
export function monthDays(month) {
  const first = `${month}-01`, monday = addDays(first, -((parseDay(first).getUTCDay() + 6) % 7));
  return Array.from({length: 42}, (_, index) => addDays(monday, index));
}
export function calendarMove(day, key) {
  const weekday = (parseDay(day).getUTCDay() + 6) % 7;
  if (key === 'Home') return addDays(day, -weekday);
  if (key === 'End') return addDays(day, 6 - weekday);
  if (key === 'PageUp') return shiftMonth(day, -1);
  if (key === 'PageDown') return shiftMonth(day, 1);
  const delta = {ArrowLeft:-1, ArrowRight:1, ArrowUp:-7, ArrowDown:7}[key];
  return delta === undefined ? null : addDays(day, delta);
}
export function selectCalendarDate(selection, day, mode) {
  if (mode === 'day') return {from:day, to:day};
  if (!selection.from || selection.to) return {from:day, to:''};
  return {from: day < selection.from ? day : selection.from, to: day < selection.from ? selection.from : day};
}
export function formatDay(day, language, options = {}) {
  return new Intl.DateTimeFormat(eventLocale(language), {day:'numeric', month:'long', timeZone:'UTC', ...options}).format(parseDay(day));
}
export function formatEventDate(value, language, withTime = true) {
  if (!value) return '';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  return new Intl.DateTimeFormat(eventLocale(language), {timeZone:'Asia/Almaty', day:'numeric', month:'long', ...(withTime && value.includes('T') ? {hour:'2-digit', minute:'2-digit'} : {})}).format(date);
}
export function imageOrientation(width, height) {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return 'unknown';
  const ratio = width / height;
  return ratio < 0.85 ? 'portrait' : ratio > 1.15 ? 'landscape' : 'square';
}
export function ongoingEventEndDay(event, today = astanaToday()) {
  if (event.schedule_kind !== 'continuous' || event.is_archived || !event.start || !event.end) return '';
  const start = new Date(event.start), end = new Date(event.end);
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) return '';
  const startDay = astanaToday(start), endDay = astanaToday(end);
  return startDay < today && endDay >= today ? endDay : '';
}
export function formatDateSelection(selection, language) {
  if (!selection.from) return '';
  if (!selection.to || selection.from === selection.to) return formatDay(selection.from, language);
  return `${formatDay(selection.from, language)} – ${formatDay(selection.to, language)}`;
}
export function buildEventsQuery(filters, offset = 0, limit = 20) {
  const query = new URLSearchParams({view:filters.view || 'upcoming', offset:String(offset), limit:String(limit)});
  for (const key of ['q', 'category', 'source', 'price', 'date_from', 'date_to', 'month']) {
    const value = String(filters[key] || '').trim();
    if (value && value !== 'all') query.set(key, value);
  }
  return query;
}
async function readEventResponse(response) {
  if (!response.ok) { const error = new Error(`events-${response.status}`); error.status = response.status; throw error; }
  return response.json();
}
export async function fetchEvents(filters, {offset = 0, signal} = {}) {
  return readEventResponse(await fetch(`${API_BASE}/api/events?${buildEventsQuery(filters, offset)}`, {signal}));
}
export async function fetchEvent(id, {signal} = {}) {
  return readEventResponse(await fetch(`${API_BASE}/api/events/${encodeURIComponent(id)}`, {signal}));
}
export const eventPath = id => `/events/${encodeURIComponent(id)}`;
export function safeExternalUrl(value) {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : null; } catch { return null; }
}

// A long-running series is presented by its next applicable performance in the feed.
export function relevantSessions(event, selection = {}, today = '') {
  if (event.schedule_kind === 'continuous' || (!event.schedule_kind && event.sessions?.length === 1 && event.sessions[0] === event.start)) return [];
  const from = selection.from || today, to = selection.to || '';
  return (event.sessions || []).filter(value => {
    const day = value.includes('T') ? astanaToday(new Date(value)) : value;
    return (!from || day >= from) && (!to || day <= to);
  }).sort();
}
