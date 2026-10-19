// Which line goes where: every leg of a route gets its own colour and direction arrows, so an out-and-back
// walk along the same street (start -> 1 -> 2 -> start) no longer reads as one tangle of identical lines.
export const LEG_COLORS = ['#1f6f50', '#2b6cb0', '#c0621b', '#7e4fb0', '#b23a5a', '#3f7f8c'];

const R = 6371000, RAD = Math.PI / 180;

export function metres(a, b) {
  const dLat = (b[0] - a[0]) * RAD, dLon = (b[1] - a[1]) * RAD;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * RAD) * Math.cos(b[0] * RAD) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

// screen direction on a north-up map, degrees clockwise from "up"
export function bearing(a, b) {
  return (Math.atan2((b[1] - a[1]) * Math.cos(a[0] * RAD), b[0] - a[0]) / RAD + 360) % 360;
}

// arrow positions along a polyline: one every `every` metres (offset by half a step), at least one mid-leg
export function arrowPoints(line, every = 300) {
  if (!line || line.length < 2) return [];
  const steps = [];
  let total = 0;
  for (let i = 1; i < line.length; i++) { const d = metres(line[i - 1], line[i]); steps.push(d); total += d; }
  if (!total) return [];
  const marks = [];
  for (let at = Math.min(every / 2, total / 2); at < total; at += every) marks.push(at);
  if (!marks.length) marks.push(total / 2);
  const out = [];
  let walked = 0, k = 0;
  for (let i = 0; i < steps.length && k < marks.length; i++) {
    while (k < marks.length && marks[k] <= walked + steps[i]) {
      const f = steps[i] ? (marks[k] - walked) / steps[i] : 0, a = line[i], b = line[i + 1];
      out.push({ at: [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f], deg: bearing(a, b) });
      k++;
    }
    walked += steps[i];
  }
  return out;
}

// "Старт → 1. Хатико": the start and the numbered stops, as on the map markers
export function legEnds(leg, places, startLabel) {
  const name = id => {
    if (id === 'start') return startLabel;
    const i = places.findIndex(p => p.id === id);
    return i < 0 ? '' : `${i + 1}. ${places[i].name}`;
  };
  return [name(leg.from_id), name(leg.to_id)];
}
