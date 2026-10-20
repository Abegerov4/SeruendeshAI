import React from 'react';
import {ArrowRight,CalendarDays,MapPin} from 'lucide-react';
import {t as tr} from '../i18n';
import {Link} from '../navigation';
import {astanaToday,eventPath,relevantSessions} from '../events';
import {EventImage,EventTiming,SourceBrand,eventPrice} from './EventPrimitives';

const localDay=value=>value && Number.isFinite(Date.parse(value)) ? astanaToday(new Date(value)) : '';

export default function EventCard({event,today,language,selection,archive}) {
 const sessions=relevantSessions(event,selection,archive ? '' : today);
 const badge=archive ? '' : localDay(event.announced_at)===today ? 'Новый анонс' : localDay(event.first_seen_at)===today ? 'Новое в ленте' : '';
 return <article className="events-card">
  <Link className="events-cover-link" to={eventPath(event.id)} tabIndex={-1} aria-hidden="true"><EventImage event={event}/></Link>
  <div className="events-card-content">
   <div className="events-card-top">{badge ? <span className="events-new-tag">{tr(badge)}</span> : null}<span className="events-card-sources">{(event.sources || []).map(source=><SourceBrand key={source.name} name={source.name}/>)}</span></div>
   <h2><Link to={eventPath(event.id)}>{event.title}</Link></h2>
   <div className="events-meta">
    <span className="events-event-date"><CalendarDays size={15} aria-hidden="true"/><span><EventTiming event={event} language={language} sessions={sessions} compact={!archive} today={today}/></span></span>
    {event.venue || event.address ? <span className="events-venue"><MapPin size={15} aria-hidden="true"/><span>{event.venue || event.address}</span></span> : null}
   </div>
   <div className="events-card-bottom"><span className="events-price">{eventPrice(event,language)}</span><Link className="events-details-link" to={eventPath(event.id)}>{tr('Подробнее')}<ArrowRight size={16} aria-hidden="true"/><span className="events-sr-only">: {event.title}</span></Link></div>
  </div>
 </article>;
}
