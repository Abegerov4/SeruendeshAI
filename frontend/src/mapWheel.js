// Wheel like Google Maps / 2GIS: a trackpad pinch (ctrlKey) zooms around the cursor, a two-finger swipe pans,
// a mouse wheel notch (wheelDelta in steps of 120, or line/page mode in Firefox) zooms by half a level.
export function wheelKind(e) {
  if (e.ctrlKey) return 'pinch';
  if (e.deltaMode !== 0) return 'mouse';
  if (e.deltaX === 0 && e.wheelDeltaY && e.wheelDeltaY % 120 === 0) return 'mouse';
  return 'pan';
}

// One zoom step per frame toward the target: the share of the remaining distance covered each frame.
export const EASE = 0.22;
export function easeZoom(z, target) {
  const next = z + (target - z) * EASE;
  return Math.abs(target - next) < 0.004 ? target : next;
}

// Continuous zoom the way Leaflet's own flyTo runs it (_moveStart -> _move per frame with flyTo -> _moveEnd):
// the current tiles scale smoothly through fractional zooms and the new ones load once the motion settles
// (tile layers use updateWhenZooming: false), so the map no longer swaps in tile by tile mid-zoom.
// Pinch, wheel notches and the +/- buttons all add to one target, so quick inputs glide instead of jumping.
export function smoothZoom(m, el) {
  let target = null, at = null, moving = false, frame = 0, settle = 0, dx = 0, dy = 0;
  const end = () => {
    moving = false; target = null;
    m._move(m.getCenter(), m.getZoom())._moveEnd(true);
  };
  const cancel = () => {
    cancelAnimationFrame(frame); clearTimeout(settle);
    frame = settle = 0; dx = dy = 0;
    if (moving) end();
    target = at = null;
  };
  const step = () => {
    frame = 0;
    if (!moving) {  // a plain pan
      if (dx || dy) m.panBy([dx, dy], { animate: false });
      dx = dy = 0;
      return;
    }
    const z = m.getZoom(), nz = easeZoom(z, target);
    const half = m.getSize().divideBy(2);
    const center = m.project(m.containerPointToLatLng(at), nz).subtract(at.subtract(half)).add([dx, dy]);
    dx = dy = 0;
    m._move(m.unproject(center, nz), nz, { flyTo: true });
    if (nz !== target) frame = requestAnimationFrame(step);
    else { clearTimeout(settle); settle = setTimeout(end, 120); }  // tiles reload only after the gesture stops
  };
  const kick = () => { if (!frame) frame = requestAnimationFrame(step); };
  const zoomBy = (delta, point) => {
    clearTimeout(settle);
    if (!moving) { m._stop(); m._moveStart(true, false); moving = true; }
    at = point || m.getSize().divideBy(2);
    target = Math.max(m.getMinZoom(), Math.min(m.getMaxZoom(), (target ?? m.getZoom()) + delta));
    kick();
  };
  const onWheel = e => {
    e.preventDefault();
    const kind = wheelKind(e), point = m.mouseEventToContainerPoint(e);
    if (kind === 'pinch') zoomBy(Math.max(-1, Math.min(1, -e.deltaY * 0.012)), point);
    else if (kind === 'mouse') zoomBy(e.deltaY < 0 ? 0.5 : -0.5, point);
    else { dx += e.deltaX; dy += e.deltaY; kick(); }
  };
  el.addEventListener('wheel', onWheel, { passive: false });
  return {
    zoomBy, cancel,
    stop: () => { cancelAnimationFrame(frame); clearTimeout(settle); el.removeEventListener('wheel', onWheel); },
  };
}
