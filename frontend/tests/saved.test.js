import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

let vite, auth, PlaceCard, TrustList, Saved;
const previousDocument = globalThis.document;
before(async () => {
  globalThis.document = {documentElement: {lang: 'ru'}};
  vite = await createServer({configFile: false, optimizeDeps: {noDiscovery: true}, server: {middlewareMode: true, hmr: false, ws: false}, appType: 'custom'});
  auth = await vite.ssrLoadModule('/src/auth.js');
  ({default: PlaceCard, TrustList} = await vite.ssrLoadModule('/src/components/PlaceCard.jsx'));
  ({default: Saved} = await vite.ssrLoadModule('/src/pages/Saved.jsx'));
});
after(async () => {
  await vite?.close();
  if (previousDocument === undefined) delete globalThis.document;
  else globalThis.document = previousDocument;
});

const savedSnapshot = {
  poi_id: 'osm:w123',
  data: {
    name: 'Парк у реки', category: 'Парк', categoryKey: 'park',
    lat: 51.128, lon: 71.43, image: '/images/stories/walk.webp',
    why: 'Рядом и спокойно', action: 'Пройти по дорожке', distance: '500 м',
    travel: 7, visit: 20, visitRange: [15, 30], mode: 'walk',
    features: [], badges: ['outdoor'], dataSources: ['osm'],
    status: 'Часы неизвестны', openConfidence: 'none', accessibility: 'unknown',
    source: 'Данные POI', generated: false,
  },
  created_at: '2026-10-19T00:00:00Z',
};

test('a server-restored saved place renders the real card with its category icon', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify([savedSnapshot])));
  const [place] = await auth.fetchSaved();
  let html;
  assert.doesNotThrow(() => { html = renderToStaticMarkup(React.createElement(PlaceCard, {place, saved: true})); });
  assert.match(html, /Парк у реки/);
  assert.match(html, /lucide-trees/);
  assert.match(html, /Иллюстрация категории, не фото этого места/);
});

test('older saved snapshots render with a fallback icon and safe empty amenities', async t => {
  const older = {...savedSnapshot, data: {...savedSnapshot.data, categoryKey: 'unknown', badges: null, features: null, dataSources: null}};
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify([older])));
  const [place] = await auth.fetchSaved();
  let html;
  assert.doesNotThrow(() => {
    html = renderToStaticMarkup(React.createElement(React.Fragment, null,
      React.createElement(PlaceCard, {place, saved: true}), React.createElement(TrustList, {p: place})));
  });
  assert.match(html, /lucide-sparkles/);
  assert.match(html, /Не подтверждены данными/);
});

test('real auth transitions update the rendered saved page without transferring the previous account cards', async t => {
  let current = null;
  const writes = [];
  t.mock.method(globalThis, 'fetch', async (path, options = {}) => {
    if (path === '/api/auth/login') {
      const {email} = JSON.parse(options.body);
      current = {id: email.startsWith('a@') ? 'a' : 'b', name: 'Local Test', email, lang: 'ru', created_at: savedSnapshot.created_at};
      return new Response(JSON.stringify(current));
    }
    if (path === '/api/auth/logout') { current = null; return new Response(null, {status: 204}); }
    if (path === '/api/me/saved') return new Response(JSON.stringify([
      {...savedSnapshot, poi_id: 'only-' + current.id, data: {...savedSnapshot.data, name: 'only-' + current.id}},
    ]));
    if (options.method === 'PUT') { writes.push(path); return new Response('{}'); }
    throw Error('Unexpected local API request: ' + path);
  });
  function SavedScreen() { return React.createElement(Saved, {saved: auth.useSaved(), toggleSaved: auth.toggleSaved}); }
  const html = () => renderToStaticMarkup(React.createElement(SavedScreen));
  await auth.login('a@example.com', 'local-test-password');
  await new Promise(setImmediate);
  assert.match(html(), /only-a/);
  await auth.logout();
  assert.doesNotMatch(html(), /only-a/);
  await auth.login('b@example.com', 'local-test-password');
  await new Promise(setImmediate);
  assert.match(html(), /only-b/);
  assert.doesNotMatch(html(), /only-a/);
  assert.deepEqual(writes, []);
  await auth.logout();
});
