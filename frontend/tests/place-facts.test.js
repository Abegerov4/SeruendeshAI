import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';
import {toPlace, restoreSaved} from '../src/api.js';

let vite, PlaceCard;
const previousDocument = globalThis.document;
before(async () => {
  globalThis.document = {documentElement: {lang: 'ru'}};
  vite = await createServer({configFile: false, optimizeDeps: {noDiscovery: true},
    server: {middlewareMode: true, hmr: false, ws: false}, appType: 'custom'});
  ({default: PlaceCard} = await vite.ssrLoadModule('/src/components/PlaceCard.jsx'));
});
after(async () => {
  await vite?.close();
  if (previousDocument === undefined) delete globalThis.document;
  else globalThis.document = previousDocument;
});

const source = {url: 'https://wolt.com/en/kaz/nur-sultan/restaurant/example-expo', checked_at: '2026-10-19',
  excerpt: 'Published menu item', channel: 'delivery'};
const accepted = {status: 'accepted', conflict_status: 'none', branch_scope: 'exact', source};
const rec = extra => ({poi_id: 'osm:example', name: 'Coffee Expo', category_detail: 'cafe', category_label: 'Кофейня',
  source: 'poi_data', open_confidence: 'none', features: [], ...extra});
const item = (name, extra = {}) => ({id: name, name, price: {amount: 1800, currency: 'KZT', unit: 'item', channel: 'delivery', kind: 'item'},
  ...accepted, ...extra});

test('POI mapping and saved snapshots preserve rich facts with safe empty defaults', () => {
  const payload = {structured_facts: [{field: 'wifi', value: true, ...accepted}], menu_items: [item('Суп')],
    prices: [{amount: 3000, currency: 'KZT', unit: 'person', channel: 'dine_in', kind: 'average_check', ...accepted}]};
  const place = toPlace(rec(payload));
  assert.deepEqual(place.structuredFacts, payload.structured_facts);
  assert.deepEqual(place.menuItems, payload.menu_items);
  assert.deepEqual(place.prices, payload.prices);
  const restored = restoreSaved({poi_id: place.id, data: place});
  assert.deepEqual(restored.menuItems, payload.menu_items);
  assert.deepEqual(toPlace(rec()).menuItems, []);
  assert.deepEqual(restoreSaved({poi_id: 'old', data: {}}).structuredFacts, []);
});

test('real place cards show three menu entries and distinguish delivery from the average check', () => {
  const place = toPlace(rec({menu_items: [item('Сорпа'), item('Котлета с пюре'), item('Латте'), item('Четвёртое блюдо')],
    prices: [{amount: 3000, currency: 'KZT', unit: 'person', channel: 'dine_in', kind: 'average_check',
      ...accepted, source: {...source, url: 'https://2gis.kz/astana/firm/70000001029139626/tab/info', channel: 'dine_in'}}],
    structured_facts: [{field: 'wifi', value: true, ...accepted, source: {...source, channel: 'dine_in'}}]}));
  const html = renderToStaticMarkup(React.createElement(PlaceCard, {place}));
  assert.match(html, /Сорпа/);
  assert.match(html, /Котлета с пюре/);
  assert.match(html, /Латте/);
  assert.doesNotMatch(html, /Четвёртое блюдо/);
  assert.match(html, /Средний чек/);
  assert.match(html, /В заведении/);
  assert.match(html, /Доставка/);
  assert.match(html, /с человека/);
  assert.match(html, /за позицию/);
  assert.match(html, /href="https:\/\/wolt.com/);
  assert.match(html, /href="https:\/\/2gis.kz/);
  assert.match(html, /Wi-Fi/);
  assert.doesNotMatch(html, /"branch_scope"|"conflict_status"/);
});

test('unaccepted, conflicting and source-less food facts cannot appear as published card facts', () => {
  const place = toPlace(rec({menu_items: [item('Спорное блюдо', {conflict_status: 'conflicting'}),
    item('Непроверенное блюдо', {status: 'pending'}), item('Блюдо без источника', {source: {}})],
    prices: [{amount: 100, currency: 'KZT', unit: 'person', kind: 'average_check', ...accepted, source: {...source, url: 'javascript:alert(1)'}}]}));
  const html = renderToStaticMarkup(React.createElement(PlaceCard, {place}));
  assert.doesNotMatch(html, /Спорное блюдо|Непроверенное блюдо|Блюдо без источника|Средний чек|href="javascript:/);
});

test('dine-in card distinguishes menu price, complete payable cost and its fee source', () => {
  const cost = {...accepted, scope: 'one_offering', complete: true, service_percent: 10,
    mandatory_fixed_amount: 0, minimum_payable_amount: 0,
    source: {...source, url: 'https://merchant.example/service', channel: 'dine_in'}};
  const meal = item('Котлета с пюре', {price: {amount: 1800, currency: 'KZT', unit: 'portion', channel: 'dine_in'},
    total_price: {amount: 1980, currency: 'KZT', unit: 'portion', channel: 'dine_in'}, cost_status: 'complete', cost,
    serving_hours: 'Mo-Fr 12:00-15:00'});
  const place = toPlace(rec({menu_items: [meal], structured_facts: [
    {...accepted, field: 'kitchen_hours', value: 'Mo-Su 10:00-21:00'}]}));
  const html = renderToStaticMarkup(React.createElement(PlaceCard, {place}));
  assert.match(html, /Цена по меню/);
  assert.match(html, /Итого с обязательными доплатами/);
  assert.match(html, /1[^0-9]*980/);
  assert.match(html, /Обслуживание/);
  assert.match(html, /10%/);
  assert.match(html, /https:\/\/merchant.example\/service/);
  assert.match(html, /Часы кухни/);
  assert.match(html, /Часы подачи блюда/);
});

test('unknown or conflicting fees never display a supplied total as confirmed', () => {
  const meal = item('Обед', {price: {amount: 1800, currency: 'KZT', unit: 'portion', channel: 'dine_in'},
    role: 'meal',
    total_price: {amount: 1800, currency: 'KZT', unit: 'portion', channel: 'dine_in'}, cost_status: 'unknown',
    cost: {...accepted, scope: 'one_offering', complete: false, service_percent: 10}});
  const html = renderToStaticMarkup(React.createElement(PlaceCard, {place: toPlace(rec({menu_items: [meal]}))}));
  assert.match(html, /Итоговая стоимость с доплатами не подтверждена/);
  assert.match(html, /Часы работы кухни не подтверждены/);
  assert.doesNotMatch(html, /Итого с обязательными доплатами/);
});
