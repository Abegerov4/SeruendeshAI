import test from 'node:test';
import assert from 'node:assert/strict';
import {arrowPoints, bearing, legEnds, LEG_COLORS} from '../src/routeLegs.js';

test('bearing is clockwise from north on a north-up map', () => {
  assert.equal(Math.round(bearing([51.1, 71.4], [51.2, 71.4])), 0);    // north
  assert.equal(Math.round(bearing([51.1, 71.4], [51.1, 71.5])), 90);   // east
  assert.equal(Math.round(bearing([51.2, 71.4], [51.1, 71.4])), 180);  // south
});

test('arrows sit along the leg, at least one on a short leg, pointing the way it goes', () => {
  const north = [[51.10, 71.40], [51.11, 71.40]];  // ~1.1 km
  const a = arrowPoints(north, 300);
  assert.ok(a.length >= 3);
  assert.ok(a.every(p => Math.round(p.deg) === 0 && p.at[0] > 51.10 && p.at[0] < 51.11));
  const back = arrowPoints([...north].reverse(), 300);
  assert.ok(back.every(p => Math.round(p.deg) === 180));  // the way back points the other way
  assert.equal(arrowPoints([[51.1, 71.4], [51.1001, 71.4]], 300).length, 1);
  assert.deepEqual(arrowPoints([[51.1, 71.4]]), []);
});

test('legs are labelled with the start and the numbered stops', () => {
  const places = [{id: 'a', name: 'Хатико'}, {id: 'b', name: 'Байтерек'}];
  assert.deepEqual(legEnds({from_id: 'start', to_id: 'a'}, places, 'Вы здесь'), ['Вы здесь', '1. Хатико']);
  assert.deepEqual(legEnds({from_id: 'b', to_id: 'start'}, places, 'Старт'), ['2. Байтерек', 'Старт']);
  assert.ok(new Set(LEG_COLORS).size >= 4);
});
