import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';
import {buildRequest, toPlan} from '../src/api.js';
import {initialContext} from '../src/planner.js';
import * as planner from '../src/planner.js';

let vite, ServiceCard, ChatAnswer;
const previousDocument = globalThis.document;
before(async () => {
  globalThis.document = {documentElement: {lang: 'ru'}};
  vite = await createServer({configFile: false, optimizeDeps: {noDiscovery: true},
    server: {middlewareMode: true, hmr: false, ws: false}, appType: 'custom'});
  ({ChatAnswer} = await vite.ssrLoadModule('/src/components/Chat.jsx'));
});
after(async () => {
  await vite?.close();
  if (previousDocument === undefined) delete globalThis.document;
  else globalThis.document = previousDocument;
});

const source = {source_url: 'https://redbus.kz/ru/marshruty/', checked_at: '2026-10-18T23:13:29Z', excerpt: 'Перед главным входом в Байтерек'};
const tour = (extra = {}) => ({id: 'service:redbus-astana', name: 'RedBus Astana', kind: 'bus_tour',
  facts: [], ticket_offers: [], routes: [], booking_rules: [], evidence: [source], notes: [],
  schedule_status: 'date_unverified', departures_today: [], ...extra});
const response = services => ({recommendations: [], ideas: [], service_results: services,
  summary: 'Посадка перед главным входом в Байтерек.', notes: []});

test('services survive an empty POI response and their identity becomes follow-up context', () => {
  const plan = toPlan(response([tour()]), initialContext, 'Где сесть на РедБас?');
  assert.equal(plan.services?.[0]?.id, 'service:redbus-astana');
  assert.equal(plan.places.length, 0);
  assert.equal(buildRequest('сколько стоит с ребёнком?', plan.context, 'ru').service_id, 'service:redbus-astana');
});

test('an unrelated or ambiguous result clears the previous service identity', () => {
  const ctx = {...initialContext, serviceId: 'service:redbus-astana'};
  const unrelated = toPlan(response([]), ctx, 'где выпить кофе?');
  assert.equal(buildRequest('а подешевле?', unrelated.context, 'ru').service_id, undefined);
  const ambiguous = toPlan(response([tour(), tour({id: 'service:boat'})]), ctx, 'какие есть экскурсии?');
  assert.equal(ambiguous.context.serviceId, null);
});

test('the empty-results guard treats a service as a real result without inventing a POI', () => {
  assert.equal(typeof planner.hasPlanResults, 'function');
  assert.equal(planner.hasPlanResults(toPlan(response([tour()]), initialContext, 'РедБас')), true);
  assert.equal(planner.hasPlanResults({places: [{generated: true}], services: []}), false);
  assert.equal(planner.hasPlanResults(null), false);
});

test('service-only chat uses the source answer and offers service cards', () => {
  const html = renderToStaticMarkup(React.createElement(ChatAnswer,
    {count: 0, serviceCount: 1, summary: 'Взрослый билет 6000 тенге.'}));
  assert.match(html, /Взрослый билет 6000 тенге/);
  assert.match(html, /карточк/);
  assert.doesNotMatch(html, /Подходящих мест пока нет/);
});

async function renderService(service) {
  if (!ServiceCard) {
    const module = await vite.ssrLoadModule('/src/components/ServiceCard.jsx');
    ServiceCard = module.default;
  }
  return renderToStaticMarkup(React.createElement(ServiceCard, {service}));
}

test('boarding cards show only explicit boarding roles and keep the provider map and source', async () => {
  const html = await renderService(tour({routes: [{id: 'route:left', stops: [
    {id: 'stop:main', name: 'Перед главным входом в Байтерек', role: 'boarding', map_url: 'https://2gis.kz/astana/firm/70000001089193403', evidence: [source]},
    {id: 'view:opera', name: 'Театр Астана Опера', role: 'pass_by', evidence: [source]},
  ]}]}));
  assert.match(html, /Перед главным входом в Байтерек/);
  assert.match(html, /href="https:\/\/2gis.kz\/astana\/firm\/70000001089193403"/);
  assert.match(html, /href="https:\/\/redbus.kz\/ru\/marshruty\/"/);
  const boarding = html.match(/<section class="service-boarding"[\s\S]*?<\/section>/)?.[0];
  assert.ok(boarding);
  assert.doesNotMatch(boarding, /Театр Астана Опера/);
  assert.match(html, /Отправления на сегодня не подтверждены/);
});

test('route names and ordered locations distinguish boarding, pass-by and visit', async () => {
  const html = await renderService(tour({routes: [{id: 'route:left', name: 'Левый берег', evidence: [source], stops: [
    {id: 'stop:main', name: 'Перед главным входом в Байтерек', role: 'boarding', evidence: [source]},
    {id: 'view:opera', name: 'Театр Астана Опера', role: 'pass_by', evidence: [source]},
    {id: 'visit:expo', name: 'Павильон EXPO', role: 'visit', evidence: [source]},
  ]}, {id: 'route:right', name: 'Правый берег', evidence: [source], stops: []}]}));
  const routes = html.match(/<details class="service-routes"[\s\S]*?<\/details>/)?.[0];
  assert.ok(routes, 'the route description must be reachable from the service card');
  assert.match(routes, /Левый берег/);
  assert.match(routes, /Правый берег/);
  const locations = [...routes.matchAll(/<li[^>]*data-stop-role="([^"]+)"[^>]*>([\s\S]*?)<\/li>/g)];
  assert.deepEqual(locations.map(match => match[1]), ['boarding', 'pass_by', 'visit']);
  assert.match(locations[0][2], /Перед главным входом в Байтерек[\s\S]*Посадка/);
  assert.match(locations[1][2], /Театр Астана Опера[\s\S]*Проезжаем мимо, посадка не подтверждена/);
  assert.match(locations[2][2], /Павильон EXPO[\s\S]*Посещение/);
  assert.match(routes, /<ol[\s>]/);
});

test('route role labels are localized without changing provider location names', async () => {
  const {setLanguage} = await vite.ssrLoadModule('/src/i18n.js');
  const service = tour({routes: [{id: 'route:left', name: 'Левый берег', stops: [
    {id: 'stop:main', name: 'Байтерек', role: 'boarding', evidence: [source]},
    {id: 'view:opera', name: 'Астана Опера', role: 'pass_by', evidence: [source]},
    {id: 'visit:expo', name: 'EXPO', role: 'visit', evidence: [source]},
  ]}]});
  try {
    setLanguage('en');
    const english = await renderService(service);
    assert.match(english, /Routes/);
    assert.match(english, /Boarding/);
    assert.match(english, /Passes by, boarding unverified/);
    assert.match(english, /Visit/);
    assert.match(english, /Астана Опера/);
    setLanguage('kk');
    const kazakh = await renderService(service);
    assert.match(kazakh, /Бағыттар/);
    assert.match(kazakh, /Міну орны/);
    assert.match(kazakh, /Жанынан өтеді, міну орны расталмаған/);
    assert.match(kazakh, /Аралау/);
  } finally { setLanguage('ru'); }
});

test('additive fares retain their units and notes while uncertain offers stay unconfirmed', async () => {
  const html = await renderService(tour({ticket_offers: [
    {id: 'rental', name: 'Аренда катера', audience: 'Группа', amount: 20000, currency: 'KZT', unit: 'per_group', status: 'confirmed', evidence: [source], notes: 'Плюс 4000 тенге за участника.'},
    {id: 'entry', name: 'Входной билет', audience: 'Участник', amount: 4000, currency: 'KZT', unit: 'per_person', status: 'confirmed', evidence: [source], notes: 'Доплата к аренде катера.'},
    {id: 'child', name: 'Бесплатный детский', audience: 'Ребёнок', amount: 0, currency: 'KZT', unit: 'per_person', status: 'conflicting', evidence: [source]},
  ], facts: [{field: 'child_age_policy', value: 'Возраст ребёнка требуется уточнить.', status: 'conflicting', evidence: [source]}]}));
  assert.match(html, /за группу/);
  assert.match(html, /с человека/);
  assert.match(html, /Плюс 4000 тенге за участника/);
  assert.match(html, /Доплата к аренде катера/);
  assert.match(html, /требуют уточнения/);
  assert.doesNotMatch(html, /Бесплатный детский/);
});

test('unsafe provider URLs never become navigable links', async () => {
  const html = await renderService(tour({evidence: [{...source, source_url: 'javascript:alert(1)'}],
    routes: [{stops: [{id: 'stop:unsafe', name: 'Вход', role: 'boarding', map_url: 'javascript:alert(2)', evidence: [source]}]}]}));
  assert.doesNotMatch(html, /href="javascript:/);
});
