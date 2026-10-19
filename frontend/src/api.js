// Client for the SeruendeshAI backend (POST /api/recommend, team contract §3.3 + extensions).
import {Trees, Coffee, Baby, Landmark, Utensils, ShoppingBag, Moon, Music, Palette, BookOpen, Sparkles, Ticket, Activity, Eye, Waves, Fish, Laptop, Gift, Store, Flower2} from 'lucide-react';

export const API_BASE = (import.meta.env?.VITE_API_URL || '').replace(/\/$/, '');

// UI landmark names (RU keys, translated by i18n) -> backend landmark keys (GET /api/meta)
export const LANDMARK_KEYS = {
  'Район Байтерека': 'baiterek', 'Mega Silk Way': 'mega_silk_way', 'ЭКСПО': 'expo', 'Хан Шатыр': 'khan_shatyr',
  'Нурлы Жол': 'nurly_zhol', 'Аэропорт': 'airport'
};
export const MY_LOCATION = 'Моё местоположение';

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

export const BADGE_LABELS = {indoor: 'В помещении', outdoor: 'На свежем воздухе', kids: 'Можно с детьми', popular: 'Знаковое место',
  hidden_gem: 'Скрытая жемчужина', event: 'Сегодня событие', night: 'Вечерний вариант', free: 'Бесплатно', ai_idea: 'Идея ИИ'};

export function roundCoord(x) { return Math.round(x * 1000) / 1000; }

export function formatDistance(m) {
  if (m == null) return '';
  return m < 1000 ? `${Math.max(10, Math.round(m / 10) * 10)} м` : `${(m / 1000).toFixed(1).replace('.', ',')} км`;
}

const CONFIDENCE_TEXT = {high: 'Часы взяты из данных OSM', low: 'Часы выведены приблизительно — уточни перед выходом', none: 'Часы работы неизвестны'};

export function toPlace(r) {
  const generated = r.source === 'generated';
  return {
    id: r.poi_id, name: r.name, category: r.category_label, categoryKey: r.category_detail,
    icon: ICONS[r.icon] || Sparkles,
    distance: formatDistance(r.walk_distance_m ?? r.distance_m), distanceM: r.walk_distance_m ?? r.distance_m,
    travel: r.travel_min, visit: r.visit_suggested_min, visitRange: r.visit_min, mode: r.travel_mode,
    why: r.why, action: r.what_to_do, rating: r.rating,
    source: generated ? 'Идея ИИ' : 'Данные POI', generated, url: r.source_url,
    lat: r.lat, lon: r.lon, status: r.opening?.label || '', openStatus: r.open_status, openConfidence: r.open_confidence,
    openingKind: r.opening?.status, website: r.website || null,
    confidence: CONFIDENCE_TEXT[r.open_confidence] || '', openingRaw: r.opening?.raw,
    features: r.features || [], badges: r.badges || [], leaveBy: r.leave_by, event: r.event,
    description: r.description, descriptionSource: r.description_source, dataSources: r.data_sources || [],
    accessibility: r.accessibility, address: r.address, descriptionUrl: r.description_url || null,
    phone: r.phone || null, instagram: r.instagram || null, cuisine: r.cuisine || [],
    photo: r.photo || null, image: r.photo?.url || null, cover: coverGroup(r.category_detail),
    imageNote: r.photo ? `Фото: ${r.photo.author}, ${r.photo.license}` : 'Обложка категории, не фото этого места',
  };
}

export function buildRequest(text, ctx, lang) {
  const body = {query: text, lang, refine: [], profile: {with_kids: !!ctx.kid, tourist: false, accessibility: !!ctx.accessible, group_size: 1}};
  if (ctx.location === MY_LOCATION && ctx.coords) body.location = {lat: roundCoord(ctx.coords.lat), lon: roundCoord(ctx.coords.lon)};
  else body.landmark = LANDMARK_KEYS[ctx.location] || 'baiterek';
  // explicit UI choices win over the text; untouched defaults are left to the parser
  if (ctx.touched?.time) body.time_budget_min = ctx.time;
  if (ctx.touched?.transport) body.mode = ctx.transport;
  if (ctx.closer) body.refine.push('closer');
  if (ctx.noCoffee) body.refine.push('no_coffee');
  if (ctx.indoor) body.refine.push('indoor');
  return body;
}

export function toPlan(resp, ctx, text) {
  return {
    places: [...(resp.recommendations || []), ...(resp.ideas || [])].map(toPlace), route: resp.route, used: resp.used_context, notes: resp.notes || [],
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
  else body.landmark = LANDMARK_KEYS[ctx.location] || 'baiterek';
  const res = await fetch(`${API_BASE}/api/route`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
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
