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
  assert.equal(body.landmark, 'baiterek');
  const touched = buildRequest('x', {...initialContext, time: 30, touched: {time: true, transport: false}}, 'kk');
  assert.equal(touched.time_budget_min, 30);
  assert.equal(touched.lang, 'kk');
});

test('API recommendation maps to a card with honest labels', () => {
  const p = toPlace(rec('osm:1'));
  assert.equal(p.source, 'Данные POI');
  assert.equal(p.distance, '650 м');
  assert.match(p.imageNote, /не фото/);
  assert.equal(toPlace(rec('idea-2', {source: 'generated'})).source, 'Идея ИИ');
  assert.equal(formatDistance(1530), '1,5 км');
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
