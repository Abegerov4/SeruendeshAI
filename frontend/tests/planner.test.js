import test from 'node:test';
import assert from 'node:assert/strict';
import {buildRequest, toPlace, diffPlans, planTotals, roundCoord, formatDistance} from '../src/api.js';
import {initialContext, describeContextChange} from '../src/planner.js';

const rec = (id, extra = {}) => ({poi_id: id, name: 'Place ' + id, category: 'park', category_detail: 'park', category_label: 'Парк',
  icon: 'trees', lat: 51.1, lon: 71.4, distance_m: 500, walk_distance_m: 650, travel_min: 9, visit_min: [20, 40], visit_suggested_min: 25,
  why: 'w', what_to_do: 'd', open_status: 'open', open_confidence: 'low', source: 'poi_data', source_url: null, rating: null,
  opening: {label: 'Открытая территория', raw: null}, badges: ['outdoor'], features: [], travel_mode: 'walk', ...extra});

test('coordinates are rounded to ~100 m before sending', () => {
  const body = buildRequest('кофе', {...initialContext, location: 'Моё местоположение', coords: {lat: 51.1283456, lon: 71.4304567}}, 'ru');
  assert.deepEqual(body.location, {lat: 51.128, lon: 71.43});
  assert.equal(body.landmark, undefined);
  assert.equal(roundCoord(51.1289), 51.129);
});

test('untouched UI defaults do not override the text; refinements are sent', () => {
  const body = buildRequest('2 часа погулять', {...initialContext, closer: true, indoor: true}, 'ru');
  assert.equal(body.time_budget_min, undefined);
  assert.equal(body.mode, undefined);
  assert.deepEqual(body.refine, ['closer', 'indoor']);
  assert.equal(body.landmark, undefined);  // no GPS yet: no silent Baiterek, the API asks where the user is
  assert.equal(body.location, undefined);
  const touched = buildRequest('x', {...initialContext, time: 30, touched: {time: true, transport: false}}, 'kk');
  assert.equal(touched.time_budget_min, 30);
  assert.equal(touched.lang, 'kk');
});

test('API recommendation maps to a card with honest labels', () => {
  const p = toPlace(rec('osm:1'));
  assert.equal(p.source, 'Данные POI');
  assert.equal(p.distance, '650 м');
  assert.match(p.imageNote, /не фото/);
  assert.equal(p.image, null);
  assert.equal(p.cover, 'green');
  const withPhoto = toPlace(rec('osm:3', {photo: {url: 'https://upload.wikimedia.org/x.jpg', author: 'A', license: 'CC BY-SA 4.0'}}));
  assert.equal(withPhoto.image, 'https://upload.wikimedia.org/x.jpg');
  assert.match(withPhoto.imageNote, /CC BY-SA/);
  assert.equal(toPlace(rec('idea-2', {source: 'generated'})).source, 'Идея ИИ');
  assert.equal(toPlace(rec('osm:2', {opening: {status: 'always', label: 'x'}, website: 'https://a.kz'})).openingKind, 'always');
  assert.equal(formatDistance(1530), '1,5 км');
});

test('researched hours keep a link to their source (sxodim asks for an active link)', () => {
  const card = 'https://sxodim.com/astana/place/muzey';
  const p = toPlace(rec('osm:4', {opening: {status: 'open', label: 'Открыто до 18:00', raw: 'Mo-Su 10:00-18:00', source: 'sxodim.com', source_url: card, check_date: '2023-03-07'}}));
  assert.equal(p.hoursUrl, card);
  assert.equal(p.hoursChecked, '2023-03-07');
  assert.equal(toPlace(rec('osm:5', {opening: {label: 'x', source_url: 'javascript:alert(1)'}})).hoursUrl, null);
});

test('plan diff and totals use route when present, alternatives otherwise', () => {
  const a = {places: [toPlace(rec('a')), toPlace(rec('b'))], route: null};
  const b = {places: [toPlace(rec('b')), toPlace(rec('c'))], route: {total_min: 52}};
  assert.deepEqual(planTotals(a), {total: 34, sequence: false});
  assert.deepEqual(planTotals(b), {total: 52, sequence: true});
  const d = diffPlans(a, b);
  assert.deepEqual([d.added, d.removed, d.before, d.after], [['Place c'], ['Place a'], 34, 52]);
  assert.deepEqual(describeContextChange(initialContext, {...initialContext, indoor: true}), ['+ В помещении']);
});

test('default context: walking, 60 minutes, geolocation first', () => {
  assert.equal(initialContext.time, 60);
  assert.equal(initialContext.transport, 'walk');
  assert.equal(initialContext.kid, false);
  assert.equal(initialContext.location, 'Моё местоположение');
});

test('a typed message wins over the settings for what it states itself', async () => {
  const {forTypedMessage, textStates} = await import('../src/planner.js');
  const picked = {...initialContext, time: 120, transport: 'car', touched: {time: true, transport: true}};
  assert.deepEqual(textStates('хочу попить кофе и прогулка на час'), {time: true, transport: false});
  assert.deepEqual(textStates('на машине до музея'), {time: false, transport: true});
  assert.deepEqual(textStates('кофе рядом'), {time: false, transport: false});
  assert.equal(textStates('что сейчас открыто, Кофе и Часы').time, false);  // not «сейчас», not a café's name
  assert.equal(textStates('погулять 2 часа').time, true);
  const body = buildRequest('хочу попить кофе и прогулка на час', forTypedMessage(picked, 'хочу попить кофе и прогулка на час'), 'ru');
  assert.equal(body.time_budget_min, undefined);  // «на час» from the text, not 120 from the buttons
  assert.equal(body.mode, 'car');                 // the text says nothing about transport: the setting stays
  const plain = buildRequest('кофе рядом', forTypedMessage(picked, 'кофе рядом'), 'ru');
  assert.equal(plain.time_budget_min, 120);
});
