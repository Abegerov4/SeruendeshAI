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

// Photos are category illustrations (never presented as the real place)
const IMAGES = {walk: '/images/stories/walk.webp', coffee: '/images/stories/coffee.webp', city: '/images/astana-hero.webp', boulevard: '/images/nurzhol.jpg'};
const IMAGE_BY_CATEGORY = {cafe: 'coffee', sweets: 'coffee', restaurant: 'coffee', fast_food: 'coffee', coworking: 'coffee', library: 'coffee',
  park: 'walk', garden: 'walk', playground: 'walk', theme_park: 'walk', viewpoint: 'boulevard', landmark: 'boulevard',
  monument: 'boulevard', artwork: 'boulevard'};
const ICON_BY_CATEGORY = {arts_centre: 'palette', library: 'book', artwork: 'sparkles', viewpoint: 'eye', park: 'trees', garden: 'flower',
  playground: 'baby', kids_indoor: 'baby', zoo_aquarium: 'fish', water_park: 'waves', theme_park: 'ferris', mall: 'shopping',
  market: 'store', souvenir: 'gift', cafe: 'coffee', restaurant: 'utensils', fast_food: 'burger', sweets: 'cake',
  bar: 'beer', nightclub: 'music', karaoke: 'mic', hookah: 'cloud', active: 'activity', coworking: 'laptop', event_venue: 'ticket'};

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
  const imageKey = IMAGE_BY_CATEGORY[r.category_detail] || 'city';
  const descriptionAttribution = Array.isArray(r.description_attribution) ? r.description_attribution : [];
  const description = r.description_source === 'wikipedia' && !descriptionAttribution.length ? null : r.description;
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
    description, descriptionAttribution, descriptionSource: r.description_source, dataSources: r.data_sources || [],
    accessibility: r.accessibility, address: r.address,
    structuredFacts: Array.isArray(r.structured_facts) ? r.structured_facts : [],
    menuItems: Array.isArray(r.menu_items) ? r.menu_items : [],
    prices: Array.isArray(r.prices) ? r.prices : [],
    image: IMAGES[imageKey], imageGenerated: true, imageNote: 'Иллюстрация категории, не фото этого места',
  };
}

// Saved snapshots contain JSON only: restore the component and defaults required by the cards.
export function restoreSaved(record) {
  const p = record.data || {};
  return {...p, id: record.poi_id, icon: ICONS[ICON_BY_CATEGORY[p.categoryKey] || p.categoryKey] || Sparkles,
    features: Array.isArray(p.features) ? p.features : [], badges: Array.isArray(p.badges) ? p.badges : [],
    dataSources: Array.isArray(p.dataSources) ? p.dataSources : [],
    structuredFacts: Array.isArray(p.structuredFacts) ? p.structuredFacts : [],
    menuItems: Array.isArray(p.menuItems) ? p.menuItems : [], prices: Array.isArray(p.prices) ? p.prices : [],
    descriptionAttribution: Array.isArray(p.descriptionAttribution) ? p.descriptionAttribution : [],
    description: p.descriptionSource === 'wikipedia' && !p.descriptionAttribution?.length ? null : p.description,
    image: p.image || IMAGES[IMAGE_BY_CATEGORY[p.categoryKey] || 'city'], imageGenerated: true,
    imageNote: 'Иллюстрация категории, не фото этого места'};
}

export function buildRequest(text, ctx, lang) {
  const body = {query: text, lang, refine: [], profile: {with_kids: !!ctx.kid, tourist: false, accessibility: !!ctx.accessible, group_size: 1}};
  if (ctx.location === MY_LOCATION && ctx.coords) body.location = {lat: roundCoord(ctx.coords.lat), lon: roundCoord(ctx.coords.lon)};
  else body.landmark = LANDMARK_KEYS[ctx.location] || ctx.location || 'baiterek';
  // explicit UI choices win over the text; untouched defaults are left to the parser
  if (ctx.touched?.time) body.time_budget_min = ctx.time;
  if (ctx.touched?.transport) body.mode = ctx.transport;
  if (ctx.closer) body.refine.push('closer');
  if (ctx.noCoffee) body.refine.push('no_coffee');
  if (ctx.indoor) body.refine.push('indoor');
  if (typeof ctx.serviceId === 'string' && ctx.serviceId) body.service_id = ctx.serviceId;
  if (Array.isArray(ctx.foodRequirements) && ctx.foodRequirements.length) body.food_context = ctx.foodRequirements;
  return body;
}

export function toPlan(resp, ctx, text) {
  const origin = resp.used_context?.location;
  const services = Array.isArray(resp.service_results) ? resp.service_results : [];
  // Reuse a text origin as a landmark fallback, so a new origin in the next query still wins.
  const context = origin?.source === 'text_landmark' && origin.label?.trim() && origin.label.length <= 80
    ? {...ctx, location: origin.label, coords: null} : {...ctx};
  // Only one returned service is an unambiguous subject for the next question.
  // The server decides whether service_id applies to a follow-up or a new topic.
  context.serviceId = services.length === 1 ? services[0].id : null;
  context.foodRequirements = resp.used_context?.parsed_from_query?.food_requirements || [];
  return {
    places: [...(resp.recommendations || []), ...(resp.ideas || [])].map(toPlace), route: resp.route, used: resp.used_context, notes: resp.notes || [],
    considered: resp.considered || [], summary: resp.summary, disclaimer: resp.disclaimer, llm: resp.llm, lang: resp.lang,
    services, context, query: text,
  };
}

export async function recommend(text, ctx, lang, {signal} = {}) {
  const res = await fetch(`${API_BASE}/api/recommend`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(buildRequest(text, ctx, lang)), signal,
  });
  if (res.status === 429) throw Error('rate');
  if (!res.ok) throw Error('http-' + res.status);
  return toPlan(await res.json(), ctx, text);
}

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

export function externalMapLinks(p) {
  if (p.lat == null) return [];
  return [
    {label: 'OpenStreetMap', href: `https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lon}#map=18/${p.lat}/${p.lon}`},
    {label: '2GIS', href: `https://2gis.kz/astana/geo/${p.lon}%2C${p.lat}`},
  ];
}
