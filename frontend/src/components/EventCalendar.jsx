import React, {useEffect, useId, useRef, useState} from 'react';
import {CalendarDays, ChevronLeft, ChevronRight, X} from 'lucide-react';
import {t as tr, useLocale} from '../i18n';
import {calendarMove, eventLocale, formatDateSelection, formatDay, monthDays, selectCalendarDate, shiftMonth} from '../events';

// Native modal dialogs supply focus containment and make the page behind the picker inert.
export function EventDialog({title, onClose, children, className = '', initialFocus}) {
  const ref = useRef(null), titleId = useId();
  useEffect(() => {
    const dialog = ref.current, previous = document.activeElement;
    dialog.showModal();
    (dialog.querySelector(initialFocus || '[autofocus]') || dialog.querySelector('button, select, input'))?.focus();
    return () => { dialog.close(); if (previous?.isConnected) previous.focus(); };
  }, []);
  return <dialog ref={ref} className={`events-dialog ${className}`} aria-labelledby={titleId}
    onCancel={event => {event.preventDefault(); onClose();}}
    onClick={event => {if(event.target !== event.currentTarget) return; const rect=event.currentTarget.getBoundingClientRect(); if(event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose();}}>
    <div className="events-panel-heading"><h2 id={titleId}>{title}</h2><button type="button" className="events-icon-button" aria-label={tr('Закрыть')} onClick={onClose}><X size={18}/></button></div>
    {children}
  </dialog>;
}

export default function EventCalendar({value, today, onApply, onClose}) {
  const language = useLocale();
  const [selection, setSelection] = useState(value);
  const [mode, setMode] = useState(value.to && value.from !== value.to ? 'range' : 'day');
  const initialDay = value.from || today;
  const [month, setMonth] = useState(initialDay.slice(0,7));
  const [focusDay, setFocusDay] = useState(initialDay);
  const gridRef = useRef(null), moveFocus = useRef(false);
  const days = monthDays(month);
  useEffect(() => {
    if (moveFocus.current) { gridRef.current?.querySelector(`[data-day="${focusDay}"]`)?.focus(); moveFocus.current = false; }
  }, [focusDay, month]);
  const focusDate = date => {
    const next = date < today ? today : date;
    moveFocus.current = true; setFocusDay(next); setMonth(next.slice(0,7));
  };
  const chooseDate = date => {setSelection(previous => selectCalendarDate(previous, date, mode)); setFocusDay(date);};
  const moveMonth = amount => focusDate(shiftMonth(focusDay.slice(0,7) === month ? focusDay : `${month}-01`, amount));
  const weekdays = Array.from({length:7}, (_, i) => new Intl.DateTimeFormat(eventLocale(language), {weekday:'short', timeZone:'UTC'}).format(new Date(Date.UTC(2026,0,5+i))));
  return <EventDialog title={tr('Дата или диапазон')} onClose={onClose} className="events-calendar-dialog" initialFocus={`[data-day="${initialDay}"]`}>
    <div className="events-calendar-modes" role="group" aria-label={tr('Режим выбора даты')}>
      <button type="button" aria-pressed={mode === 'day'} onClick={() => {setMode('day'); setSelection(previous => ({from:previous.from,to:previous.from}));}}>{tr('Один день')}</button>
      <button type="button" aria-pressed={mode === 'range'} onClick={() => {setMode('range'); setSelection({from:'',to:''});}}>{tr('Диапазон')}</button>
    </div>
    <div className="events-calendar-heading">
      <button type="button" className="events-icon-button" aria-label={tr('Предыдущий месяц')} disabled={month <= today.slice(0,7)} onClick={() => moveMonth(-1)}><ChevronLeft size={20}/></button>
      <h3 aria-live="polite">{formatDay(`${month}-01`, language, {month:'long',year:'numeric',day:undefined})}</h3>
      <button type="button" className="events-icon-button" aria-label={tr('Следующий месяц')} onClick={() => moveMonth(1)}><ChevronRight size={20}/></button>
    </div>
    <table ref={gridRef} className="events-calendar-grid" role="grid" aria-multiselectable={mode === 'range'} aria-label={formatDay(`${month}-01`, language, {month:'long',year:'numeric',day:undefined})}>
      <thead><tr>{weekdays.map((day,index) => <th key={index} scope="col">{day}</th>)}</tr></thead>
      <tbody>{Array.from({length:6}, (_, week) => <tr key={week}>{days.slice(week*7,week*7+7).map(day => {
        const start = day === selection.from, end = day === selection.to;
        const inside = !!selection.from && !!selection.to && day >= selection.from && day <= selection.to;
        return <td key={day} role="gridcell" aria-selected={start || end || inside} className={`${inside ? 'is-in-range' : ''} ${start ? 'is-range-start' : ''} ${end ? 'is-range-end' : ''}`}>
          <button type="button" data-day={day} tabIndex={day === focusDay ? 0 : -1} disabled={day < today}
            className={`${day.slice(0,7) !== month ? 'is-outside' : ''} ${start || end ? 'is-selected' : ''} ${day === today ? 'is-today' : ''}`}
            aria-label={formatDay(day, language, {weekday:'long',year:'numeric'})} aria-current={day === today ? 'date' : undefined}
            onFocus={() => setFocusDay(day)} onClick={() => chooseDate(day)} onKeyDown={event => {const next=calendarMove(day,event.key); if(next) {event.preventDefault();focusDate(next);}}}>
            {Number(day.slice(-2))}
          </button>
        </td>;
      })}</tr>)}</tbody>
    </table>
    {selection.from ? <div className="events-date-preview" aria-live="polite"><CalendarDays size={18}/><span>{formatDateSelection(selection, language)}</span></div> : null}
    <div className="events-panel-actions"><button type="button" className="events-text-button" onClick={() => setSelection({from:'',to:''})}>{tr('Сбросить даты')}</button><div><button type="button" className="events-text-button" onClick={onClose}>{tr('Отмена')}</button><button type="button" className="events-primary" onClick={() => onApply({from:selection.from,to:selection.to || selection.from})}>{tr('Применить')}</button></div></div>
  </EventDialog>;
}
