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
