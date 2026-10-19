// Walk context shared by the chat, the preferences and the refinement chips.
// `touched` marks controls the user changed explicitly: only those override what the text says.
export const initialContext = {
  // geolocation first; a landmark is the fallback
  location: 'Моё местоположение', coords: null, time: 60, transport: 'walk', kid: false, accessible: false,
  closer: false, noCoffee: false, indoor: false, touched: {time: false, transport: false},
};

export function describeContextChange(prev, next) {
  if (!prev) return [];
  const out = [];
  if (prev.location !== next.location) out.push(next.location);
  if (prev.time !== next.time) out.push(`${next.time} мин`);
  if (prev.transport !== next.transport) out.push(next.transport === 'walk' ? 'Пешком' : 'На авто');
  for (const [key, label] of [['kid', 'С ребёнком'], ['accessible', 'Без ступенек'], ['closer', 'Ближе'], ['noCoffee', 'Без кофе'], ['indoor', 'В помещении']])
    if (!!prev[key] !== !!next[key]) out.push((next[key] ? '+ ' : '− ') + label);
  return out;
}

// What a typed message says itself: «кофе на час» sets the time, «на машине» the transport. A typed message
// wins over the settings for what it states; «Найти с этими условиями» sends the settings as they are.
// \b is ASCII-only in JS: Cyrillic word edges are checked with \p{L} lookarounds («час», not «сейчас» or «часы»)
const TIME_WORDS = /\d+\s*(?:мин|ч(?!\p{L})|час|сағ|min|h(?!\p{L})|hour)|полчаса|полтора|(?<!\p{L})час(?:а|ов|ик)?(?!\p{L})|минут|сағат|(?<!\p{L})(?:hours?|minutes?)(?!\p{L})/iu;
const MODE_WORDS = /машин|(?<!\p{L})авто|такси|пешк|пешеход|автобус|транспорт|көлік|жаяу|by car|on foot|(?<!\p{L})(?:drive|taxi)(?!\p{L})/iu;
export function textStates(text) {
  return {time: TIME_WORDS.test(text || ''), transport: MODE_WORDS.test(text || '')};
}

export function forTypedMessage(ctx, text) {
  const says = textStates(text), touched = ctx.touched || {};
  return {...ctx, touched: {...touched, time: !!touched.time && !says.time, transport: !!touched.transport && !says.transport}};
}
