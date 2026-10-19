import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

let vite, TrustList, toPlace;
const previousDocument = globalThis.document;
before(async () => {
  globalThis.document = {documentElement: {lang: 'ru'}};
  vite = await createServer({configFile: false, optimizeDeps: {noDiscovery: true}, server: {middlewareMode: true, hmr: false, ws: false}, appType: 'custom'});
  ({TrustList} = await vite.ssrLoadModule('/src/components/PlaceCard.jsx'));
  ({toPlace} = await vite.ssrLoadModule('/src/api.js'));
});
after(async () => {
  await vite?.close();
  if (previousDocument === undefined) delete globalThis.document;
  else globalThis.document = previousDocument;
});

const article = 'https://en.wikipedia.org/wiki/Baiterek';
const license = 'https://creativecommons.org/licenses/by-sa/4.0/';
const entry = {source: 'wikipedia', title: 'Baiterek', url: article, license: 'CC-BY-SA-4.0', license_url: license,
  attribution: 'Wikipedia contributors', notice: 'Shortened excerpt; see the article for the original text.'};
const rec = (extra = {}) => ({poi_id: 'osm:w10', name: 'Baiterek', category_detail: 'monument', category_label: 'Памятник',
  icon: 'monument', source: 'poi_data', source_url: 'https://www.openstreetmap.org/way/10',
  description: 'An excerpt from the article.', description_source: 'wikipedia', data_sources: ['osm', 'wikipedia'],
  open_confidence: 'none', features: [], accessibility: 'unknown', ...extra});

test('real trust panel links the actual article and license beside the excerpt attribution', () => {
  const place = toPlace(rec({description_attribution: [entry]}));
  assert.deepEqual(place.descriptionAttribution, [entry]);
  const html = renderToStaticMarkup(React.createElement(TrustList, {p: place}));
  assert.match(html, /href="https:\/\/en\.wikipedia\.org\/wiki\/Baiterek"/);
  assert.match(html, /href="https:\/\/creativecommons\.org\/licenses\/by-sa\/4\.0\/"/);
  assert.match(html, /CC-BY-SA-4\.0/);
  assert.match(html, /Wikipedia contributors/);
  assert.match(html, /Shortened excerpt/);
  assert.doesNotMatch(html, /href="https:\/\/www\.openstreetmap\.org/);
});

test('missing metadata defaults to an empty attribution list and publishes no source link', () => {
  const place = toPlace(rec({description: null}));
  assert.deepEqual(place.descriptionAttribution, []);
  const html = renderToStaticMarkup(React.createElement(TrustList, {p: place}));
  assert.doesNotMatch(html, /creativecommons|href=/);
});

test('an older response without attribution does not publish a Wikipedia excerpt', () => {
  assert.equal(toPlace(rec()).description, null);
});

for (const accessibility of ['yes', 'limited', 'no']) {
  test(`wheelchair ${accessibility} is labelled without inventing steps or an OSM field source`, () => {
    const place = toPlace(rec({description: null, accessibility}));
    const html = renderToStaticMarkup(React.createElement(TrustList, {p: place}));
    assert.match(html, /по данным источника/);
    assert.doesNotMatch(html, /ступен|steps|\(OSM\)/i);
  });
}
