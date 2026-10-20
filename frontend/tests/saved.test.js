import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

test('saved cards survive an account API roundtrip and can be removed', async () => {
  const server = await createServer({server: {middlewareMode: true}, appType: 'custom',
    optimizeDeps: {noDiscovery: true, include: []}});
  const originalFetch = globalThis.fetch;
  const originalDocument = globalThis.document;
  globalThis.document = {documentElement: {lang: 'ru'}};
  const rows = new Map();
  globalThis.fetch = async (url, options = {}) => {
    assert.equal(options.credentials, 'include');
    const id = decodeURIComponent(url.split('/api/me/saved/')[1] || '');
    if (options.method === 'PUT') {
      rows.set(id, {poi_id: id, data: JSON.parse(options.body).data});
      return Response.json(rows.get(id));
    }
    if (options.method === 'DELETE') {
      rows.delete(id);
      return new Response(null, {status: 204});
    }
    return Response.json([...rows.values()]);
  };
  try {
    const {putSaved, fetchSaved, deleteSaved} = await server.ssrLoadModule('/src/auth.js');
    const {toPlace} = await server.ssrLoadModule('/src/api.js');
    const {default: PlaceCard} = await server.ssrLoadModule('/src/components/PlaceCard.jsx');
    const place = toPlace({poi_id: 'osm:node/123', name: 'Saved park', category_detail: 'park',
      category_label: 'Park', icon: 'trees', source: 'poi_data', travel_min: 7, visit_suggested_min: 20});
    await putSaved(place);
    const [restored] = await fetchSaved();
    assert.equal(restored.id, place.id);
    const html = renderToStaticMarkup(React.createElement(PlaceCard, {place: restored, saved: true, onSave() {}}));
    assert.match(html, /Saved park/);
    assert.match(html, /aria-pressed="true"/);
    // Old/minimal snapshots must also render without a stored icon or category.
    rows.set('legacy', {poi_id: 'legacy', data: {name: 'Old favourite'}});
    const legacy = (await fetchSaved()).find(p => p.id === 'legacy');
    assert.match(renderToStaticMarkup(React.createElement(PlaceCard, {place: legacy})), /Old favourite/);
    await deleteSaved(place.id);
    await deleteSaved('legacy');
    assert.deepEqual(await fetchSaved(), []);
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.document = originalDocument;
    await server.close();
  }
});
