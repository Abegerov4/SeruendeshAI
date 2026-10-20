import React, {useCallback, useState} from 'react';
import {Ticket} from 'lucide-react';
import {t as tr} from '../i18n';
import {eventLocale, formatDay, formatEventDate, imageOrientation, ongoingEventEndDay, safeExternalUrl} from '../events';

export function SourceBrand({name}) {
  return name === 'sxodim' ? <span className="events-source events-source-sxodim"><img src="/brand/source-sxodim.svg" alt="Sxodim" width="52" height="25"/></span> : name === 'ticketon' ? <span className="events-source events-source-ticketon"><span>Freedom</span><span>Ticketon</span></span> : <span className="events-source">{name}</span>;
}

export function EventImage({event, detail = false}) {
  const image = safeExternalUrl(event.image_url);
  return <EventImageMedia key={image || 'fallback'} image={image} event={event} detail={detail}/>;
}

function EventImageMedia({image, event, detail}) {
  const [failed,setFailed] = useState(false), [orientation,setOrientation] = useState('unknown');
  const readImage = useCallback(node => {
    if (node?.complete && node.naturalWidth > 0) setOrientation(imageOrientation(node.naturalWidth,node.naturalHeight));
  },[]);
  const hasImage = !!image && !failed;
  const onError = () => {setFailed(true);setOrientation('unknown');};
  return <div className={`events-cover ${hasImage ? 'events-cover-photo' : ''} ${detail ? 'events-detail-cover' : ''}`} data-media={hasImage ? 'photo' : 'fallback'} data-orientation={hasImage ? orientation : 'unknown'}>
    {hasImage ? <img ref={readImage} src={image} alt="" loading={detail ? 'eager' : 'lazy'} decoding="async" onLoad={event => setOrientation(imageOrientation(event.currentTarget.naturalWidth,event.currentTarget.naturalHeight))} onError={onError}/> : <div className="events-category-cover"><Ticket size={34} strokeWidth={1.3}/><span>{tr(event.category_label || 'Событие')}</span></div>}
  </div>;
}

export function eventPrice(event, language) {
  if (event.price_from === 0) return tr('Вход свободный');
  if (event.price_from == null) return tr('Стоимость у организатора');
  const amount = new Intl.NumberFormat(eventLocale(language), {maximumFractionDigits:0}).format(event.price_from);
  return tr('от {price} {currency}', {price:amount,currency:event.currency === 'KZT' ? '₸' : event.currency || '₸'});
}

export function EventTiming({event, language, sessions, compact = false, today}) {
  const endDay = compact ? ongoingEventEndDay(event,today) : '';
  if (endDay) return <time dateTime={event.end}>{tr('До {date}',{date:formatDay(endDay,language)})}</time>;
  const visibleStart = sessions?.[0] || event.start;
  const start = formatEventDate(visibleStart, language), end = sessions?.length ? '' : formatEventDate(event.end, language);
  return <>{start ? <time dateTime={visibleStart}>{start}</time> : tr('Дата уточняется')}{end && end !== start ? <> – <time dateTime={event.end}>{end}</time></> : null}</>;
}

export function StateMessage({kind, onRetry, onReset}) {
  return <div className="events-state" role={kind === 'error' ? 'alert' : 'status'}>
    {kind === 'loading' ? <><span className="events-loading" aria-hidden="true"/><p>{tr('Загружаем события…')}</p></> : kind === 'error' ? <><h2>{tr('Не удалось загрузить события')}</h2><p>{tr('Проверьте соединение и попробуйте ещё раз.')}</p><button className="events-primary" onClick={onRetry}>{tr('Повторить')}</button></> : <><h2>{tr('Пока ничего не нашлось')}</h2><p>{tr('Измените запрос, даты или фильтры.')}</p><button className="events-primary" onClick={onReset}>{tr('Сбросить фильтры')}</button></>}
  </div>;
}
