import React from 'react';
import {MessageCircle, Map, Compass, Route, CalendarDays} from 'lucide-react';
import {Link} from '../navigation';
import {t as tr} from '../i18n';

export default function MobileNavigation({path, view, onSelect, count}) {
  const walking = path === '/';
  const events = path === '/events' || path.startsWith('/events/');
  return <nav className="mobile-app-nav" aria-label={tr('Основная навигация')}>
    {[['chat',MessageCircle,'Чат'],['map',Map,'Карта'],['places',Compass,'Места'],['plan',Route,'План']].map(([id,Icon,label]) =>
      <button key={id} type="button" aria-current={walking && view === id ? 'page' : undefined} onClick={() => onSelect(id)}>
        <Icon size={21}/><span>{tr(label)}</span>{id === 'places' && count > 0 ? <i>{count}</i> : null}
      </button>)}
    <Link className="mobile-events-link" to="/events" aria-current={events ? 'page' : undefined}><CalendarDays size={21}/><span>{tr('События')}</span></Link>
  </nav>;
}
