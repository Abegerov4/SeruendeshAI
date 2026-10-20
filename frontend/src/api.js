// Client for the SeruendeshAI backend (POST /api/recommend, team contract §3.3 + extensions).
import {Trees, Coffee, Baby, Landmark, Utensils, ShoppingBag, Moon, Music, Palette, BookOpen, Sparkles, Ticket, Activity, Eye, Waves, Fish, Laptop, Gift, Store, Flower2} from 'lucide-react';

export const API_BASE = (import.meta.env?.VITE_API_URL || '').replace(/\/$/, '');

// UI landmark names (RU keys, translated by i18n) -> backend landmark keys (GET /api/meta)
export const LANDMARK_KEYS = {
  'Район Байтерека': 'baiterek', 'Mega Silk Way': 'mega_silk_way', 'ЭКСПО': 'expo', 'Хан Шатыр': 'khan_shatyr',
  'Нурлы Жол': 'nurly_zhol', 'Аэропорт': 'airport'
};
export const MY_LOCATION = 'Моё местоположение';
export const HOME = 'Дом';

// The user's home lives only on this device (rounded to ~100 m); it is sent only when the walk starts from home.
export function loadHome() { try { return JSON.parse(localStorage.getItem('seru.home') || 'null'); } catch { return null; } }
export function saveHome(h) { try { h ? localStorage.setItem('seru.home', JSON.stringify(h)) : localStorage.removeItem('seru.home'); } catch { /* private mode */ } }
const HOME_WORDS = /(?:\bот|\bиз|\bу|\bоколо|\bвозле|рядом с|недалеко от)\s+(?:моего\s+|своего\s+|нашего\s+)?дом(?:а|ом)(?![а-я])|у меня дома|(?:near|from|around|close to)\s+(?:my\s+|our\s+)?home|үйден|үйдің жанында/i;
// an anonymous mark on a place: only the place id and the kind of mark are sent
export async function sendFeedback(poiId, kind, lang) {
  const res = await fetch(`${API_BASE}/api/feedback`, {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({poi_id: poiId, kind, lang})});
  if (!res.ok) throw Error('feedback-' + res.status);
  return res.json();
}

export async function geocode(q) {
  const res = await fetch(`${API_BASE}/api/geocode?q=${encodeURIComponent(q)}`);
  if (!res.ok) throw Error('geocode-' + res.status);
  return (await res.json()).results || [];
}
// Themed walks from the current place (icons, green, museums, coffee, evening, kids): real routes, not lists.
export async function routeIdeas(ctx, lang) {
  const { query, refine, profile, time_budget_min, mode, ...where } = buildRequest('', ctx, lang);
  const res = await fetch(`${API_BASE}/api/routes/ideas`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(where) });
  if (res.status === 429) throw Error('rate');
  if (!res.ok) throw Error('ideas-' + res.status);
  return (await res.json()).ideas || [];
}

const ICONS = {trees: Trees, coffee: Coffee, baby: Baby, landmark: Landmark, monument: Landmark, utensils: Utensils, burger: Utensils,
  shopping: ShoppingBag, beer: Moon, music: Music, mic: Music, cloud: Moon, palette: Palette, gallery: Palette, museum: Landmark,
  book: BookOpen, sparkles: Sparkles, ticket: Ticket, activity: Activity, eye: Eye, waves: Waves, fish: Fish, laptop: Laptop,
  gift: Gift, store: Store, flower: Flower2, worship: Landmark, theatre: Ticket, cinema: Ticket, cake: Coffee, ferris: Sparkles, spa: Waves};

// Cards show a real Wikimedia Commons photo when the place has one, otherwise a designed category cover
// (never a photo of some other place).
const COVER_GROUP = {park: 'green', garden: 'green', playground: 'kids', theme_park: 'kids', kids_indoor: 'kids', viewpoint: 'sights',
  landmark: 'sights', monument: 'sights', artwork: 'sights', worship: 'sights', museum: 'culture', gallery: 'culture', theatre: 'culture',
  cinema: 'culture', arts_centre: 'culture', event_venue: 'culture', library: 'culture', cafe: 'coffee', sweets: 'coffee', coworking: 'coffee',
  restaurant: 'food', fast_food: 'food', market: 'food', bar: 'night', nightclub: 'night', karaoke: 'night', hookah: 'night',
  mall: 'shop', souvenir: 'shop', active: 'active', spa: 'active', water_park: 'active', zoo_aquarium: 'kids'};
export const coverGroup = key => COVER_GROUP[key] || 'sights';

// Persist the icon name, then restore the React component when reading saved places.
// Older snapshots have only a category; their cover group supplies a safe fallback.
export function placeIcon(iconKey, categoryKey) {
  const fallback = {green: Trees, kids: Baby, sights: Landmark, culture: Landmark,
    coffee: Coffee, food: Utensils, night: Moon, shop: ShoppingBag, active: Activity};
  return ICONS[iconKey] || fallback[coverGroup(categoryKey)] || Sparkles;
}

// Account snapshots contain JSON only (React icon components cannot be stored): rebuild the presentation fields
// for current and older saved cards — the icon, the cover group, and the AI-idea sparkle.
export function restoreSavedPlace(row) {
  const place = row.data || {};
  return {...place, id: row.poi_id, cover: place.cover || coverGroup(place.categoryKey),
    icon: place.generated ? Sparkles : placeIcon(place.iconKey || place.categoryKey, place.categoryKey)};
}

export const BADGE_LABELS = {indoor: 'В помещении', outdoor: 'На свежем воздухе', kids: 'Можно с детьми', popular: 'Знаковое место',
  hidden_gem: 'Скрытая жемчужина', event: 'Сегодня событие', night: 'Вечерний вариант', free: 'Бесплатно', ai_idea: 'Идея ИИ'};

export function roundCoord(x) { return Math.round(x * 1000) / 1000; }

export function formatDistance(m) {
  if (m == null) return '';
  const en = typeof document !== 'undefined' && document.documentElement.lang === 'en';  // i18n keeps <html lang> in sync
  return m < 1000 ? `${Math.max(10, Math.round(m / 10) * 10)} ${en ? 'm' : 'м'}` : `${(m / 1000).toFixed(1).replace('.', en ? '.' : ',')} ${en ? 'km' : 'км'}`;
}

export const visitText = p => p.visitRange && p.visitRange[0] !== p.visitRange[1] ? `${p.visitRange[0]}–${p.visitRange[1]}` : String(p.visit ?? p.visitRange?.[0] ?? '');

// Commons credits sometimes arrive doubled ("Unknown authorUnknown author")
const cleanAuthor = a => { const s = (a || '').trim(); const half = s.slice(0, s.length / 2); const one = s.length % 2 === 0 && half && s === half + half ? half : s; return /^unknown author$/i.test(one) ? 'автор не указан' : one; };

const CONFIDENCE_TEXT = {high: 'Часы взяты из данных OSM', low: 'Часы выведены приблизительно — уточни перед выходом', none: 'Часы работы неизвестны'};

export function toPlace(r) {
  const generated = r.source === 'generated';
  return {
    id: r.poi_id, name: r.name, category: r.category_label, categoryKey: r.category_detail,
    iconKey: r.icon, icon: placeIcon(r.icon, r.category_detail),
    distance: formatDistance(r.walk_distance_m ?? r.distance_m), distanceM: r.walk_distance_m ?? r.distance_m,
    travel: r.travel_min, visit: r.visit_suggested_min, returnMin: r.return_min || 0, visitRange: r.visit_min, mode: r.travel_mode,
    why: r.why, action: r.what_to_do, rating: r.rating,
    source: generated ? 'Идея ИИ' : 'Данные POI', generated, url: r.source_url,
    lat: r.lat, lon: r.lon, status: r.opening?.label || '', openStatus: r.open_status, openConfidence: r.open_confidence,
    openingKind: r.opening?.status, website: r.website || null,
    confidence: CONFIDENCE_TEXT[r.open_confidence] || '', openingRaw: r.opening?.raw,
    features: r.features || [], badges: r.badges || [], leaveBy: r.leave_by, event: r.event,
    description: r.description, descriptionSource: r.description_source, dataSources: r.data_sources || [],
    accessibility: r.accessibility, address: r.address, descriptionUrl: r.description_url || null,
    phone: r.phone || null, instagram: r.instagram || null, cuisine: r.cuisine || [],
    photo: r.photo ? { ...r.photo, author: cleanAuthor(r.photo.author) } : null, image: r.photo?.url || null, cover: coverGroup(r.category_detail),
    imageNote: r.photo ? (r.photo.source === 'website' ? `Фото с сайта ${r.photo.author}` : `Фото: ${r.photo.author}, ${r.photo.license}`) : 'Обложка категории, не фото этого места',
  };
}

export function buildRequest(text, ctx, lang) {
  const body = {query: text, lang, refine: [], profile: {with_kids: !!ctx.kid, tourist: false, accessibility: !!ctx.accessible, group_size: 1}};
  if (ctx.address && ctx.location === ctx.address.label) {  // a typed address the geocoder found: rounded, with its label
    body.location = {lat: roundCoord(ctx.address.lat), lon: roundCoord(ctx.address.lon)}; body.location_label = ctx.address.label.slice(0, 120);
  } else if (ctx.location === MY_LOCATION && ctx.coords) body.location = {lat: roundCoord(ctx.coords.lat), lon: roundCoord(ctx.coords.lon)};
  else if (LANDMARK_KEYS[ctx.location]) body.landmark = LANDMARK_KEYS[ctx.location];  // no GPS and no chosen start: the API asks where the user is
  const home = loadHome();
  if (home && (ctx.location === HOME || HOME_WORDS.test(text || ''))) {
    body.home = {lat: roundCoord(home.lat), lon: roundCoord(home.lon), label: (home.label || '').slice(0, 120)};
    if (ctx.location === HOME) body.use_home = true;
  }
  // explicit UI choices win over the text; untouched defaults are left to the parser
  if (ctx.touched?.time) body.time_budget_min = ctx.time;
  if (ctx.touched?.transport) body.mode = ctx.transport;
  if (ctx.closer) body.refine.push('closer');
  if (ctx.noCoffee) body.refine.push('no_coffee');
  if (ctx.indoor) body.refine.push('indoor');
  if (ctx.now) body.now = ctx.now;  // a fixed moment from a shared/demo link (?now=)
  return body;
}

export function toPlan(resp, ctx, text) {
  return {
    places: [...(resp.recommendations || []), ...(resp.ideas || [])].map(r => ({...toPlace(r), budget: resp.used_context?.time_budget_min || ctx.time})), route: resp.route, used: resp.used_context, notes: resp.notes || [],
    considered: resp.considered || [], summary: resp.summary, disclaimer: resp.disclaimer, llm: resp.llm, lang: resp.lang,
    offTopic: !!resp.off_topic, photoGuess: resp.photo_guess || null, navigateTo: resp.navigate_to || null,
    context: {...ctx}, query: text,
  };
}

// "Where am I?" from a photo: the server strips EXIF (GPS is never read), downscales and forgets the image.
export async function recommendPhoto(file, text, ctx, lang, {signal} = {}) {
  const form = new FormData();
  form.append('image', file);
  if (text) form.append('query', text);
  form.append('lang', lang);
  if (ctx.location !== MY_LOCATION) form.append('landmark', LANDMARK_KEYS[ctx.location] || 'baiterek');
  const res = await fetch(`${API_BASE}/api/recommend/photo`, {method: 'POST', body: form, signal});
  if (res.status === 429) throw Error('rate');
  if (res.status === 413) throw Error('photo_too_large');
  if (!res.ok) throw Error('photo-' + res.status);
  return toPlan(await res.json(), ctx, text || '');
}

export async function recommend(text, ctx, lang, {signal} = {}) {
  const res = await fetch(`${API_BASE}/api/recommend`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(buildRequest(text, ctx, lang)), signal,
  });
  if (res.status === 429) throw Error('rate');
  if (!res.ok) throw Error('http-' + res.status);
  return toPlan(await res.json(), ctx, text);
}

// Route from the user to one place: rounded GPS when allowed, otherwise the chosen landmark.
export async function routeTo(place, ctx, from) {
  const body = {poi_id: place.id, mode: ctx.transport === 'car' ? 'car' : 'walk'};
  if (from) body.location = {lat: roundCoord(from.lat), lon: roundCoord(from.lon)};
  else if (LANDMARK_KEYS[ctx.location]) body.landmark = LANDMARK_KEYS[ctx.location];  // no GPS and no chosen start: the API asks where the user is
  const res = await fetch(`${API_BASE}/api/route`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  if (res.status === 422 && (await res.clone().json().catch(() => ({}))).error === 'route_unavailable') throw Error('no-path');
  if (!res.ok) throw Error('route-' + res.status);
  return res.json();
}

// Astana bounding box: GPS outside it is not used as a start (the API would refuse it as well)
export const inAstana = c => !!c && c.lat > 50.95 && c.lat < 51.32 && c.lon > 71.15 && c.lon < 71.8;

// Totals for the timeline: a route is a sequence (legs + visits); otherwise places are alternatives.
export function planTotals(plan) {
  if (!plan?.places?.length) return {total: 0, sequence: false};
  if (plan.route) return {total: plan.route.total_min, sequence: true};
  const real = plan.places.filter(p => !p.generated);
  return {total: Math.max(0, ...real.map(p => p.travel + p.visit)), sequence: false};
}

export function diffPlans(prev, next) {
  if (!prev) return null;
  const before = new Set(prev.places.map(p => p.id)), after = new Set(next.places.map(p => p.id));
  return {
    added: next.places.filter(p => !before.has(p.id) && !p.generated).map(p => p.name),
    removed: prev.places.filter(p => !after.has(p.id) && !p.generated).map(p => p.name),
    before: planTotals(prev).total, after: planTotals(next).total,
  };
}

export function instagramUrl(handle) {
  if (!handle) return null;
  if (/^https?:/.test(handle)) return handle;
  return 'https://instagram.com/' + handle.replace(/^@/, '').replace(/^(www\.)?instagram\.com\//, '');
}

export function telUrl(phone) {
  const first = (phone || '').split(/[;,]/)[0].replace(/[^+\d]/g, '');
  return first.length >= 6 ? 'tel:' + first : null;
}

// 2GIS opens a route on phones; OSM is the open fallback
export function routeUrl(p, from) {
  if (p.lat == null) return null;
  const to = `${p.lon}%2C${p.lat}`;
  return from ? `https://2gis.kz/astana/directions/points/${from.lon}%2C${from.lat}%7C${to}` : `https://2gis.kz/astana/geo/${to}`;
}

export function externalMapLinks(p) {
  if (p.lat == null) return [];
  return [
    {label: 'OpenStreetMap', href: `https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lon}#map=18/${p.lat}/${p.lon}`},
    {label: '2GIS', href: `https://2gis.kz/astana/geo/${p.lon}%2C${p.lat}`},
  ];
}
