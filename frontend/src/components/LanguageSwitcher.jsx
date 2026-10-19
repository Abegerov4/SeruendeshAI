import React, { useEffect, useRef, useState } from 'react';
import { Globe2, ChevronDown, Check } from 'lucide-react';
import { useLocale, setLanguage } from '../i18n';

const LANGS = [
  { code: 'ru', short: 'RU', name: 'Русский' },
  { code: 'kk', short: 'ҚАЗ', name: 'Қазақша' },
  { code: 'en', short: 'EN', name: 'English' },
];

// Custom listbox (the native <select> looked foreign in the Seru design)
export default function LanguageSwitcher() {
  const language = useLocale();
  const [open, setOpen] = useState(false), [active, setActive] = useState(0);
  const box = useRef(null), list = useRef(null);
  const current = LANGS.find(l => l.code === language) || LANGS[0];
  useEffect(() => {
    if (!open) return;
    setActive(LANGS.findIndex(l => l.code === language));
    requestAnimationFrame(() => list.current?.focus());
    const close = e => { if (!box.current?.contains(e.target)) setOpen(false); };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [open]);
  function choose(code) { setLanguage(code); setOpen(false); box.current?.querySelector('button')?.focus(); }
  function onKey(e) {
    if (e.key === 'Escape') { setOpen(false); box.current?.querySelector('button')?.focus(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setActive(a => (a + 1) % LANGS.length); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(a => (a + LANGS.length - 1) % LANGS.length); }
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(LANGS[active].code); }
  }
  return <div className={'lang-switch' + (open ? ' open' : '')} ref={box}>
    <button type="button" className="lang-trigger" aria-haspopup="listbox" aria-expanded={open} aria-label="Язык / Тіл / Language" onClick={() => setOpen(!open)}>
      <Globe2 size={15} aria-hidden="true" /><span>{current.short}</span><ChevronDown size={13} className="lang-chevron" aria-hidden="true" />
    </button>
    {open && <ul className="lang-menu" role="listbox" tabIndex={-1} ref={list} aria-activedescendant={'lang-' + LANGS[active].code} onKeyDown={onKey}>
      {LANGS.map((l, i) => <li key={l.code} id={'lang-' + l.code} role="option" aria-selected={l.code === language}
        className={(i === active ? 'active ' : '') + (l.code === language ? 'selected' : '')}
        onPointerEnter={() => setActive(i)} onClick={() => choose(l.code)}>
        <span className="lang-code">{l.short}</span><span className="lang-name">{l.name}</span>{l.code === language && <Check size={15} />}
      </li>)}
    </ul>}
  </div>;
}
