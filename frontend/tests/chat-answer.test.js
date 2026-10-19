import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

let vite, ChatAnswer;
const previousDocument = globalThis.document;
before(async () => {
  globalThis.document = {documentElement: {lang: 'ru'}};
  vite = await createServer({configFile: false, optimizeDeps: {noDiscovery: true}, server: {middlewareMode: true, hmr: false, ws: false}, appType: 'custom'});
  ({ChatAnswer} = await vite.ssrLoadModule('/src/components/Chat.jsx'));
});
after(async () => {
  await vite?.close();
  if (previousDocument === undefined) delete globalThis.document;
  else globalThis.document = previousDocument;
});

test('empty food results render the API limitation and offer without the success prompt', () => {
  assert.equal(typeof ChatAnswer, 'function', 'chat result renderer must preserve the API explanation');
  const html = renderToStaticMarkup(React.createElement(ChatAnswer, {count: 0,
    summary: 'Нет подтверждения пюре с котлетой по низкой цене. Показать места без этих условий?',
    note: 'Часы неизвестны.'}));
  assert.match(html, /Нет подтверждения пюре с котлетой по низкой цене/);
  assert.match(html, /Показать места без этих условий/);
  assert.doesNotMatch(html, /Посмотри карточки|Подобрал|Часы неизвестны/);
});

test('empty results fall back to an API note when summary is absent', () => {
  assert.equal(typeof ChatAnswer, 'function', 'chat result renderer must preserve API notes');
  const html = renderToStaticMarkup(React.createElement(ChatAnswer, {count: 0, note: 'Нет подтверждения меню.'}));
  assert.match(html, /Нет подтверждения меню/);
  assert.doesNotMatch(html, /Посмотри карточки/);
});
