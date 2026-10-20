import React, {useEffect, useId, useState} from 'react';
import {ArrowRight, CalendarDays, Search, SlidersHorizontal, X} from 'lucide-react';
import {t as tr, useLocale} from '../i18n';
import {Link} from '../navigation';
import EventCalendar, {EventDialog} from '../components/EventCalendar';
import {addDays, astanaToday, fetchEvents, formatDateSelection, formatDay} from '../events';
import EventCard from '../components/EventCard';
import EventDetail from '../components/EventDetail';
import {StateMessage} from '../components/EventPrimitives';
import '../events.css';

const emptyFilters = {q:'', category:'', source:'', price:'all', date_from:'', date_to:'', month:''};
function FilterDialog({value, categories, onApply, onClose}) {
  const [draft, setDraft] = useState(value), id = useId();
  return <EventDialog title={tr('Фильтры')} onClose={onClose}>
    <form onSubmit={event => {event.preventDefault();onApply(draft);}}>
      <label className="events-panel-field" htmlFor={`${id}-category`}>{tr('Категория')}<select id={`${id}-category`} value={draft.category} onChange={event => setDraft({...draft,category:event.target.value})}><option value="">{tr('Все категории')}</option>{categories.map(category => <option value={category.value} key={category.value}>{tr(category.label)}</option>)}</select></label>
      <label className="events-panel-field" htmlFor={`${id}-price`}>{tr('Стоимость')}<select id={`${id}-price`} value={draft.price} onChange={event => setDraft({...draft,price:event.target.value})}><option value="all">{tr('Любая стоимость')}</option><option value="free">{tr('Бесплатно')}</option><option value="paid">{tr('Платные события')}</option></select></label>
      <label className="events-panel-field" htmlFor={`${id}-source`}>{tr('Источник')}<select id={`${id}-source`} value={draft.source} onChange={event => setDraft({...draft,source:event.target.value})}><option value="">{tr('Все источники')}</option><option value="ticketon">Freedom Ticketon</option><option value="sxodim">Sxodim</option></select></label>
      <div className="events-panel-actions"><button type="button" className="events-text-button" onClick={() => setDraft({category:'',price:'all',source:''})}>{tr('Сбросить')}</button><div><button type="button" className="events-text-button" onClick={onClose}>{tr('Отмена')}</button><button type="submit" className="events-primary">{tr('Применить')}</button></div></div>
    </form>
  </EventDialog>;
}
function EventsFeed({view, filters, setFilters, today, setToday, language}) {
  const [dialog, setDialog] = useState(null), [offset, setOffset] = useState(0), [retry, setRetry] = useState(0);
  const [resource, setResource] = useState({key:'',listKey:'',items:[],data:null,nextOffset:0,hasMore:false,pending:true,error:false});
  const listKey = JSON.stringify({view,...filters}), key = `${listKey}:${offset}:${retry}`;
  useEffect(() => {setOffset(0);}, [listKey]);
  useEffect(() => {
    const controller = new AbortController(); let active = true;
    setResource(previous => ({...previous,key,listKey,items:previous.listKey === listKey ? previous.items : [],pending:true,error:false}));
    const timer = setTimeout(() => {
      fetchEvents({view,...filters}, {offset,signal:controller.signal}).then(data => {
        if (!active) return;
        if(data.today) setToday(data.today);
        const received = data.items || [], nextOffset = Number(data.offset ?? offset) + received.length;
        const hasMore = nextOffset > offset && received.length >= Number(data.limit || 20) && nextOffset < Number(data.total || 0);
        setResource(previous => {
          const previousItems = offset > 0 && previous.listKey === listKey ? previous.items : [];
          const seen = new Set(previousItems.map(item => item.id));
          return {key,listKey,items:[...previousItems,...received.filter(item => !seen.has(item.id))],data,nextOffset,hasMore,pending:false,error:false};
        });
      }).catch(error => {if(active && error.name !== 'AbortError') setResource(previous => ({...previous,key,pending:false,error:true}));});
    }, filters.q ? 240 : 0);
    return () => {active = false;clearTimeout(timer);controller.abort();};
  }, [key]);
  const matching = resource.listKey === listKey, items = matching ? resource.items : [];
  const pending = resource.key !== key || resource.pending, error = matching && resource.error;
  const metadata = resource.data || {}, categories = metadata.categories || [], months = metadata.months || [];
  const patch = changes => {setOffset(0);setFilters({...filters,...changes});};
  const selection = {from:filters.date_from,to:filters.date_to};
  const filterCount = Number(!!filters.category) + Number(!!filters.source) + Number(filters.price !== 'all');
  const quick = date => patch(filters.date_from === date && filters.date_to === date ? {date_from:'',date_to:''} : {date_from:date,date_to:date});
  const selectedToday = filters.date_from === today && filters.date_to === today;
  const tomorrow = addDays(today,1), selectedTomorrow = filters.date_from === tomorrow && filters.date_to === tomorrow;
  const customSelected = !!filters.date_from && !selectedToday && !selectedTomorrow;
  const reset = () => patch({...emptyFilters});
  return <section aria-labelledby="events-feed-title"><h1 id="events-feed-title" className="events-sr-only">{tr(view === 'archive' ? 'Архив событий' : 'События Астаны')}</h1>
    <div className={view === 'archive' ? 'events-archive-filters' : 'events-search-area'}>
      <label className="events-search"><Search size={20}/><input type="search" aria-label={tr(view === 'archive' ? 'Поиск в архиве' : 'Поиск событий')} placeholder={tr(view === 'archive' ? 'Поиск в архиве' : 'Поиск событий')} value={filters.q} onChange={event => patch({q:event.target.value})}/></label>
      {view === 'archive' ? <><label className="events-archive-select"><span className="events-sr-only">{tr('Месяц')}</span><select aria-label={tr('Месяц')} value={filters.month} onChange={event => patch({month:event.target.value})}><option value="">{tr('Все месяцы')}</option>{months.map(month => <option key={month} value={month}>{formatDay(`${month}-01`,language,{year:'numeric',month:'long',day:undefined})}</option>)}</select></label><label className="events-archive-select"><span className="events-sr-only">{tr('Категория')}</span><select aria-label={tr('Категория')} value={filters.category} onChange={event => patch({category:event.target.value})}><option value="">{tr('Все категории')}</option>{categories.map(category => <option value={category.value} key={category.value}>{tr(category.label)}</option>)}</select></label></> : null}
    </div>
    {view !== 'archive' ? <div className="events-quick-controls" role="group" aria-label={tr('Даты и фильтры')}>
      <button className={`events-quick-button ${selectedToday ? 'is-selected' : ''}`} aria-pressed={selectedToday} onClick={() => quick(today)}>{tr('Сегодня')}</button>
      <button className={`events-quick-button ${selectedTomorrow ? 'is-selected' : ''}`} aria-pressed={selectedTomorrow} onClick={() => quick(tomorrow)}>{tr('Завтра')}</button>
      <div className="events-custom-dates"><button className={`events-quick-button ${customSelected ? 'is-selected has-clear' : ''}`} aria-haspopup="dialog" aria-expanded={dialog === 'calendar'} onClick={() => setDialog('calendar')}><CalendarDays size={16}/><span>{customSelected ? formatDateSelection(selection,language) : tr('Выбрать даты')}</span></button>{customSelected ? <button className="events-clear-dates" aria-label={tr('Сбросить выбранные даты')} onClick={() => patch({date_from:'',date_to:''})}><X size={14}/></button> : null}</div>
      <button className={`events-quick-button events-filters-trigger ${filterCount ? 'is-selected' : ''}`} aria-haspopup="dialog" aria-expanded={dialog === 'filters'} onClick={() => setDialog('filters')}><SlidersHorizontal size={16}/>{tr('Фильтры')}{filterCount ? <span className="events-filter-count">{filterCount}</span> : null}</button>
    </div> : null}
    <div className="events-results" aria-live="polite">{!pending || items.length ? tr('Событий: {count}', {count:metadata.total ?? items.length}) : tr('Ищем события…')}</div>
    <div className="events-list" aria-busy={pending}>{items.map(event => <EventCard key={event.id} event={event} today={today} language={language} selection={selection} archive={view === 'archive'}/>)}</div>
    {!items.length ? <StateMessage kind={pending ? 'loading' : error ? 'error' : 'empty'} onRetry={() => setRetry(retry+1)} onReset={reset}/> : error ? <div className="events-load-error" role="alert"><p>{tr('Не удалось загрузить следующие события.')}</p><button className="events-primary" onClick={() => setRetry(retry+1)}>{tr('Повторить')}</button></div> : resource.hasMore ? <div className="events-pagination"><button className="events-primary" disabled={pending} onClick={() => setOffset(resource.nextOffset)}>{tr(pending ? 'Загружаем…' : 'Показать ещё')}</button></div> : null}
    {dialog === 'calendar' ? <EventCalendar value={selection} today={today} onClose={() => setDialog(null)} onApply={dates => {patch({date_from:dates.from,date_to:dates.to});setDialog(null);}}/> : null}
    {dialog === 'filters' ? <FilterDialog value={filters} categories={categories} onClose={() => setDialog(null)} onApply={draft => {patch({category:draft.category,price:draft.price,source:draft.source});setDialog(null);}}/> : null}
  </section>;
}
export default function Events({path}) {
  const language = useLocale(), [today,setToday] = useState(astanaToday);
  const [views,setViews] = useState({upcoming:{...emptyFilters},archive:{...emptyFilters}});
  const [detailKind,setDetailKind] = useState({id:'',archived:false});
  const archive = path === '/events/archive', detail = path !== '/events' && !archive;
  let id = '';
  if(detail) {try{id=decodeURIComponent(path.slice('/events/'.length));}catch{id=path.slice('/events/'.length);}}
  const view = archive ? 'archive' : 'upcoming';
  const archiveTab = archive || (detail && detailKind.id === id && detailKind.archived);
  return <main className="events-page" id="events-main"><nav className="events-tabs" aria-label={tr('Раздел событий')}><Link className={!archiveTab ? 'is-active' : ''} aria-current={!archiveTab ? 'page' : undefined} to="/events">{tr('События')}</Link><Link className={archiveTab ? 'is-active' : ''} aria-current={archiveTab ? 'page' : undefined} to="/events/archive">{tr('Архив')}</Link></nav>
    {detail ? <EventDetail key={id} id={id} language={language} today={today} onLoaded={event => setDetailKind({id,archived:event.is_archived})}/> : <EventsFeed key={view} view={view} filters={views[view]} setFilters={next => setViews(previous => ({...previous,[view]:next}))} today={today} setToday={setToday} language={language}/>}
    <footer className="events-footer"><Link to={archive ? '/events' : '/events/archive'}>{tr(archive ? 'Все события' : 'Архив событий')}<ArrowRight size={18}/></Link><span>{tr('Анонсы Ticketon и Sxodim')}</span></footer>
  </main>;
}
