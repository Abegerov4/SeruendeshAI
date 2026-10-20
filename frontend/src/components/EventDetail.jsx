import React, {useEffect, useRef, useState} from 'react';
import {ArrowLeft, CalendarDays, ExternalLink, MapPin} from 'lucide-react';
import {t as tr} from '../i18n';
import {Link} from '../navigation';
import {eventLocale, fetchEvent, formatEventDate, relevantSessions, safeExternalUrl} from '../events';
import {EventImage, EventTiming, SourceBrand, StateMessage, eventPrice} from './EventPrimitives';
import '../event-detail.css';

const sourceLabel = name => name === 'ticketon' ? 'Freedom Ticketon' : name === 'sxodim' ? 'Sxodim' : name;
function formatProvenanceDate(value, language) {
  if (!value) return '';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  return new Intl.DateTimeFormat(eventLocale(language), {
    timeZone:'Asia/Almaty', day:'numeric', month:'long', year:'numeric',
    ...(value.includes('T') ? {hour:'2-digit', minute:'2-digit'} : {}),
  }).format(date);
}

export default function EventDetail({id, language, today, originView, onLoaded}) {
  const [resource, setResource] = useState({id:'', event:null, pending:true, error:null});
  const [retry, setRetry] = useState(0);
  const loadedCallback = useRef(onLoaded);
  useEffect(() => {loadedCallback.current = onLoaded;}, [onLoaded]);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setResource({id, event:null, pending:true, error:null});
    fetchEvent(id, {signal:controller.signal}).then(event => {
      if (!active) return;
      setResource({id, event, pending:false, error:null});
      loadedCallback.current?.(event);
    }).catch(error => {
      if (active && error.name !== 'AbortError') setResource({id, event:null, pending:false, error});
    });
    return () => {active = false; controller.abort();};
  }, [id, retry]);

  const event = resource.id === id ? resource.event : null;
  const sources = (event?.sources || []).flatMap(source => {
    const url = safeExternalUrl(source.url);
    return url ? [{...source, url}] : [];
  });
  const primarySource = sources.find(source => source.name === 'ticketon') || sources.find(source => source.name === 'sxodim') || sources[0];
  const sessions = event ? relevantSessions(event, {}, event.is_archived ? '' : today) : [];
  const publication = formatProvenanceDate(event?.announced_at, language);
  const firstSeen = formatProvenanceDate(event?.first_seen_at, language);
  const returnToArchive = originView ? originView === 'archive' : !!event?.is_archived;
  const returnPath = returnToArchive ? '/events/archive' : '/events';
  const returnLabel = tr(returnToArchive ? 'К архиву событий' : 'К событиям');

  return <section className="events-detail">
    <Link className="events-back" to={returnPath}><ArrowLeft size={16} aria-hidden="true"/>{returnLabel}</Link>
    {resource.id !== id || resource.pending ? <StateMessage kind="loading"/> : resource.error?.status === 404 ? <div className="events-state"><h1>{tr('Событие не найдено')}</h1><p>{tr('Возможно, источник удалил этот анонс. Другие события доступны в ленте.')}</p><Link className="events-primary" to={returnPath}>{returnLabel}</Link></div> : resource.error ? <StateMessage kind="error" onRetry={() => setRetry(value => value + 1)}/> : event ? <>
      <div className="events-detail-layout">
        <div className="events-detail-content">
          <h1>{event.title}</h1>
          {event.is_archived ? <p className="events-archived-label">{tr('Событие завершилось')}</p> : null}
          <div className="events-detail-facts">
            <div className="events-detail-timing"><CalendarDays size={19} aria-hidden="true"/><div><EventTiming event={event} language={language} sessions={sessions} today={today}/></div></div>
            {event.venue || event.address ? <div className="events-detail-place"><MapPin size={19} aria-hidden="true"/><div>{event.venue ? <p>{event.venue}</p> : null}{event.address && event.address !== event.venue ? <p className="events-detail-address">{event.address}</p> : null}</div></div> : null}
          </div>
          <div className="events-detail-booking">
            <p className="events-detail-price">{eventPrice(event, language)}</p>
            {primarySource ? <a className="events-primary events-detail-action" data-source={primarySource.name} href={primarySource.url} target="_blank" rel="noopener noreferrer">{tr('Открыть в {source}', {source:sourceLabel(primarySource.name)})}<ExternalLink size={16} aria-hidden="true"/></a> : null}
          </div>
        </div>
        <EventImage event={event} detail/>
      </div>
      <div className="events-detail-body">
        {event.description ? <div className="events-detail-description">{event.description}</div> : null}
        {event.sessions?.length > 1 ? <section className="events-sessions"><h2>{tr('Сеансы')}</h2><ul>{event.sessions.map((session, index) => <li key={`${session}-${index}`}><time dateTime={session}>{formatEventDate(session, language)}</time></li>)}</ul></section> : null}
        <footer className="events-detail-provenance">
          {sources.length ? <div className="events-original-sources"><h2>{tr('Уточнить у источника')}</h2><div>{sources.map(source => <a href={source.url} key={`${source.name}-${source.url}`} target="_blank" rel="noopener noreferrer" aria-label={tr('Открыть в {source}', {source:sourceLabel(source.name)})}><SourceBrand name={source.name}/><ExternalLink size={14} aria-hidden="true"/></a>)}</div></div> : null}
          {publication || firstSeen ? <div className="events-detail-publication">
            {publication ? <p><span>{tr('Опубликовано источником')}</span> <time dateTime={event.announced_at}>{publication}</time></p> : null}
            {firstSeen ? <p><span>{tr('Добавлено в нашу ленту')}</span> <time dateTime={event.first_seen_at}>{firstSeen}</time></p> : null}
          </div> : null}
        </footer>
      </div>
    </> : null}
  </section>;
}
