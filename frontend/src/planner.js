// Walk context shared by the chat, the context editor and the demo panel.
// `touched` marks controls the user changed explicitly: only those override what the text says.
export const initialContext = {
  location: 'Район Байтерека', coords: null, time: 60, transport: 'walk', kid: false, accessible: false,
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
