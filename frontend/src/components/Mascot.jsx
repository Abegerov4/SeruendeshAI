import { t as tr } from "../i18n";
import React from 'react';
export default function Mascot({
  className = '',
  decorative = false,
  priority = false,
  mood = 'idle'
}) {
  return <img className={'seru-mascot mascot-' + mood + ' ' + className} src="/mascot/seru-wave.webp" alt={decorative ? '' : tr('Серу — маленькая зелёная птичка, твой городской спутник')} width="1024" height="1280" loading={priority ? 'eager' : 'lazy'} draggable="false" />;
}
