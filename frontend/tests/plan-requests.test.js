import test from 'node:test';
import assert from 'node:assert/strict';
import {buildRequest, toPlan} from '../src/api.js';
import {initialContext} from '../src/planner.js';
import * as planner from '../src/planner.js';

const response = (label = 'EXPO / Нур Алем', source = 'text_landmark') => ({
  recommendations: [], ideas: [], notes: [], summary: 'Нет подтверждения блюда и цены. Можно поискать места без этих условий?',
  used_context: {location_source: source === 'gps_rounded' ? source : 'landmark', location_label: label,
    location: {source, label, lat: 51.093, lon: 71.421, precision_m: source === 'gps_rounded' ? 100 : 50}},
});

test('food wishes survive follow-ups and are cleared by a new topic response', () => {
  const requirements = [{kind: 'menu', text: 'пюре'}, {kind: 'price', text: 'до 2000 тенге'}];
  const resp = response();
  resp.used_context.parsed_from_query = {food_requirements: requirements};
  const plan = toPlan(resp, initialContext, 'Пюре до 2000 тенге');
  assert.deepEqual(buildRequest('Поближе пожалуйста', plan.context, 'ru').food_context, requirements);
  const changed = toPlan(response(), plan.context, 'Хочу погулять');
  assert.equal(buildRequest('Поближе', changed.context, 'ru').food_context, undefined);
});

test('a follow-up reuses the text landmark returned by the API without turning it into GPS', () => {
  const plan = toPlan(response(), initialContext, 'я рядом с экспо, хочу пюре с котлетой');
  const followUp = buildRequest('покажи другой вариант', plan.context, 'ru');
  assert.equal(followUp.landmark, 'EXPO / Нур Алем');
  assert.equal(followUp.location, undefined);
  assert.equal(plan.context.location, 'EXPO / Нур Алем');
  assert.equal(initialContext.location, 'Район Байтерека');
});

test('an explicit picker change replaces the remembered text origin', () => {
  const plan = toPlan(response(), initialContext, 'я рядом с экспо');
  const changed = {...plan.context, location: 'Хан Шатыр', coords: null};
  assert.equal(buildRequest('куда сходить?', changed, 'ru').landmark, 'khan_shatyr');
});

test('GPS stays GPS and a location-free response does not erase the current origin', () => {
  const gps = {...initialContext, location: 'Моё местоположение', coords: {lat: 51.1284, lon: 71.4304}};
  const plan = toPlan(response('Округлённая локация', 'gps_rounded'), gps, 'кофе рядом');
  assert.deepEqual(buildRequest('другое место', plan.context, 'ru').location, {lat: 51.128, lon: 71.43});
  const missing = toPlan({...response(), used_context: {location: null}}, plan.context, 'другое место');
  assert.equal(missing.context.location, 'Моё местоположение');
});

test('an empty result presents the API summary before incidental notes', () => {
  assert.equal(typeof planner.emptyPlanExplanation, 'function', 'empty result explanation must be available');
  const plan = toPlan({...response(), notes: ['Часы работы неизвестны.']}, initialContext, 'пюре с котлетой');
  assert.equal(planner.emptyPlanExplanation(plan), 'Нет подтверждения блюда и цены. Можно поискать места без этих условий?');
  assert.equal(planner.emptyPlanExplanation({notes: ['Нет подтверждения цены.']}), 'Нет подтверждения цены.');
});

async function requestHarness() {
  const {createPlanRequests} = await import('../src/plan-requests.js');
  const contexts = [], plans = [], loading = [];
  const requests = createPlanRequests();
  const run = (pending, extra = {}) => requests.run({text: 'я рядом с экспо', context: initialContext, lang: 'ru',
    resolveContext: async c => c,
    recommend: async (text, ctx) => toPlan(await pending.promise, ctx, text),
    onContext: c => contexts.push(c), onPlan: p => plans.push(p), onLoading: v => loading.push(v), ...extra});
  return {requests, contexts, plans, loading, run};
}

test('a late initial request cannot replace the newer result or remembered origin', async () => {
  const h = await requestHarness(), first = Promise.withResolvers(), second = Promise.withResolvers();
  const oldRequest = h.run(first);
  const oldRejected = assert.rejects(oldRequest, {name: 'AbortError'});
  await Promise.resolve(); // The first transport is already waiting for its response.
  const newRequest = h.run(second);
  second.resolve(response('Хан Шатыр'));
  await newRequest;
  first.resolve(response());
  await oldRejected;
  assert.deepEqual(h.contexts.map(c => c.location), ['Хан Шатыр']);
  assert.equal(h.plans.length, 1);
  assert.deepEqual(h.loading, [true, true, false]);
});

test('an explicitly changed location invalidates an older pending response', async () => {
  const h = await requestHarness(), pending = Promise.withResolvers();
  const active = h.run(pending);
  const rejected = assert.rejects(active, {name: 'AbortError'});
  await Promise.resolve();
  h.requests.invalidate();
  pending.resolve(response());
  await rejected;
  assert.deepEqual(h.contexts, []);
  assert.deepEqual(h.plans, []);
});

test('an aborted response cannot commit even when the transport resolves', async () => {
  const h = await requestHarness(), pending = Promise.withResolvers(), controller = new AbortController();
  const active = h.run(pending, {signal: controller.signal});
  const rejected = assert.rejects(active, {name: 'AbortError'});
  await Promise.resolve();
  controller.abort();
  pending.resolve(response());
  await rejected;
  assert.deepEqual(h.contexts, []);
  assert.deepEqual(h.plans, []);
  assert.deepEqual(h.loading, [true, false]);
});

test('a stale GPS lookup cannot start a recommendation or change context', async () => {
  const h = await requestHarness(), coords = Promise.withResolvers();
  let searched = false;
  const active = h.run(Promise.withResolvers(), {resolveContext: () => coords.promise,
    recommend: async () => { searched = true; return toPlan(response(), initialContext, 'кофе'); }});
  const rejected = assert.rejects(active, {name: 'AbortError'});
  h.requests.invalidate();
  coords.resolve({...initialContext, location: 'Моё местоположение', coords: {lat: 51.1, lon: 71.4}});
  await rejected;
  assert.equal(searched, false);
  assert.deepEqual(h.contexts, []);
});

test('a stale transport failure is cancellation instead of a new search error', async () => {
  const h = await requestHarness(), pending = Promise.withResolvers();
  const active = h.run(pending);
  const rejected = assert.rejects(active, {name: 'AbortError'});
  await Promise.resolve();
  h.requests.invalidate();
  pending.reject(Error('old server failure'));
  await rejected;
  assert.deepEqual(h.contexts, []);
  assert.deepEqual(h.plans, []);
});

test('changing the origin aborts the pending transport immediately', async () => {
  const h = await requestHarness(), pending = Promise.withResolvers();
  let transportSignal;
  const active = h.run(pending, {recommend: async (text, ctx, lang, {signal}) => {
    transportSignal = signal;
    return toPlan(await pending.promise, ctx, text);
  }});
  const rejected = assert.rejects(active, {name: 'AbortError'});
  await Promise.resolve();
  h.requests.invalidate();
  assert.equal(transportSignal?.aborted, true);
  pending.resolve(response());
  await rejected;
});
