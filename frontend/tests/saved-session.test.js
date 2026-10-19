import test from 'node:test';
import assert from 'node:assert/strict';

const place = id => ({id, name: id});
const ids = session => session.getSnapshot().map(p => p.id);
const deferred = () => Promise.withResolvers();

async function sessionWith(fetchSaved) {
  const {createSavedSession} = await import('../src/saved-session.js');
  const writes = [];
  return {session: createSavedSession({fetchSaved,
    putSaved: async p => { writes.push(['put', p.id]); },
    deleteSaved: async id => { writes.push(['delete', id]); }}), writes};
}

test('guest favourites join the first account without duplicating server favourites', async () => {
  const {session, writes} = await sessionWith(async () => [place('server-a'), place('shared')]);
  session.toggle(place('guest'));
  session.toggle(place('shared'));
  await session.setUser('a');
  assert.deepEqual(ids(session), ['server-a', 'shared', 'guest']);
  assert.deepEqual(writes, [['put', 'guest']]);
});

test('logout clears account favourites before a different account logs in', async () => {
  let server = [place('only-a')];
  const {session, writes} = await sessionWith(async () => server);
  await session.setUser('a');
  const logout = session.setUser(null);
  assert.deepEqual(ids(session), []);
  await logout;
  session.toggle(place('new-guest'));
  server = [place('only-b')];
  await session.setUser('b');
  assert.deepEqual(ids(session), ['only-b', 'new-guest']);
  assert.deepEqual(writes, [['put', 'new-guest']]);
});

test('switching accounts hides the previous list while the new list is loading', async () => {
  const pending = deferred();
  let calls = 0;
  const {session} = await sessionWith(() => ++calls === 1 ? Promise.resolve([place('only-a')]) : pending.promise);
  await session.setUser('a');
  const loading = session.setUser('b');
  assert.deepEqual(ids(session), []);
  pending.resolve([place('only-b')]);
  await loading;
  assert.deepEqual(ids(session), ['only-b']);
});

test('a delayed saved response from the previous account cannot mix lists or upload cards', async () => {
  const first = deferred(), second = deferred();
  let calls = 0;
  const {session, writes} = await sessionWith(() => ++calls === 1 ? first.promise : second.promise);
  session.toggle(place('guest-for-a'));
  const loadingA = session.setUser('a');
  await session.setUser(null);
  const loadingB = session.setUser('b');
  second.resolve([place('only-b')]);
  await loadingB;
  first.resolve([place('only-a')]);
  await loadingA;
  assert.deepEqual(ids(session), ['only-b']);
  assert.deepEqual(writes, []);
});

test('a saved request completed after logout cannot replace new guest favourites', async () => {
  const pending = deferred();
  const {session, writes} = await sessionWith(() => pending.promise);
  const loading = session.setUser('a');
  await session.setUser(null);
  session.toggle(place('guest-after-logout'));
  pending.resolve([place('only-a')]);
  await loading;
  assert.deepEqual(ids(session), ['guest-after-logout']);
  assert.deepEqual(writes, []);
});

test('local additions and removals survive an older response for the same account', async () => {
  const pending = deferred();
  const {session, writes} = await sessionWith(() => pending.promise);
  session.toggle(place('remove-me'));
  const loading = session.setUser('a');
  session.toggle(place('remove-me'));
  session.toggle(place('new-place'));
  pending.resolve([place('remove-me'), place('server-a')]);
  await loading;
  assert.deepEqual(ids(session), ['server-a', 'new-place']);
  assert.deepEqual(writes, [['delete', 'remove-me'], ['put', 'new-place']]);
});

test('failed loading keeps the current account edits and remains isolated after logout', async () => {
  const pending = deferred();
  const {session} = await sessionWith(() => pending.promise);
  const loading = session.setUser('a');
  session.toggle(place('local-a'));
  pending.reject(Error('unavailable'));
  await loading;
  assert.deepEqual(ids(session), ['local-a']);
  await session.setUser(null);
  assert.deepEqual(ids(session), []);
});
