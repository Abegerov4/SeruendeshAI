import test from 'node:test';
import assert from 'node:assert/strict';
import {wheelKind, easeZoom} from '../src/mapWheel.js';

const wheel = (extra = {}) => ({ctrlKey: false, deltaMode: 0, deltaX: 0, deltaY: 0, wheelDeltaY: 0, ...extra});

test('a trackpad pinch zooms, a two-finger swipe pans', () => {
  assert.equal(wheelKind(wheel({ctrlKey: true, deltaY: -3.2})), 'pinch');
  assert.equal(wheelKind(wheel({deltaY: 7.5, wheelDeltaY: -22})), 'pan');
  assert.equal(wheelKind(wheel({deltaX: 12, deltaY: 120, wheelDeltaY: -120})), 'pan');
});

test('a mouse wheel notch zooms', () => {
  assert.equal(wheelKind(wheel({deltaY: 100, wheelDeltaY: -120})), 'mouse');
  assert.equal(wheelKind(wheel({deltaY: 3, deltaMode: 1})), 'mouse');  // Firefox lines
});

test('zoom glides to the target in small steps and lands on it exactly', () => {
  let z = 14, steps = [];
  while (z !== 15 && steps.length < 100) { z = easeZoom(z, 15); steps.push(z); }
  assert.equal(z, 15);
  assert.ok(steps.length > 10 && steps.length < 40, `${steps.length} frames`);
  assert.ok(steps.every((v, i) => i === 0 || v > steps[i - 1]));
  assert.ok(steps[0] - 14 < 0.25);  // no jump on the first frame
});

test('cancel discards queued zoom before returning to the route', async () => {
  const {smoothZoom} = await import('../src/mapWheel.js');
  const frames = new Map();
  const oldRequest = globalThis.requestAnimationFrame, oldCancel = globalThis.cancelAnimationFrame;
  let sequence = 0, ended = 0;
  globalThis.requestAnimationFrame = fn => { frames.set(++sequence, fn); return sequence; };
  globalThis.cancelAnimationFrame = id => frames.delete(id);
  const map = {
    _stop() {}, _moveStart() {}, getSize: () => ({divideBy: () => ({x: 100, y: 100})}),
    getMinZoom: () => 11, getMaxZoom: () => 19, getZoom: () => 14, getCenter: () => [51, 71],
    _move() { return this; }, _moveEnd() { ended++; },
  };
  try {
    const zoom = smoothZoom(map, {addEventListener() {}, removeEventListener() {}});
    zoom.zoomBy(1);
    assert.equal(frames.size, 1);
    zoom.cancel();
    assert.equal(frames.size, 0);
    assert.equal(ended, 1);
    zoom.cancel();
    assert.equal(ended, 1);
    zoom.zoomBy(-1);
    assert.equal(frames.size, 1, 'zoom still works after cancellation');
    zoom.cancel(); zoom.stop();
  } finally {
    globalThis.requestAnimationFrame = oldRequest;
    globalThis.cancelAnimationFrame = oldCancel;
  }
});
