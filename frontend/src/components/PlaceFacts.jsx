import React from 'react';
import {t as tr, getLanguage} from '../i18n';
import '../food-facts.css';

const FIELDS = {format: 'Формат', cuisine: 'Кухня', cuisines: 'Кухня', wifi: 'Wi-Fi', kids_area: 'Детская зона',
  terrace: 'Веранда', laptop_allowed: 'Можно с ноутбуком', seating_capacity_max: 'Мест до',
  phone: 'Телефон', opening_hours: 'Часы по источнику', address: 'Адрес',
  kitchen_hours: 'Часы кухни', kitchen_closes_at: 'Кухня закрывается',
  halal: 'Халал', vegetarian_options: 'Вегетарианские варианты', vegan_options: 'Веганские варианты',
  wheelchair_accessible: 'Доступный вход', sockets: 'Розетки', toilets: 'Туалет',
  changing_table: 'Пеленальный столик', reservations: 'Бронирование', takeaway: 'С собой'};
const CHANNELS = {delivery: 'Доставка', dine_in: 'В заведении', takeaway: 'С собой'};
const UNITS = {person: 'с человека', item: 'за позицию', portion: 'за порцию', dish: 'за блюдо', cup: 'за чашку',
  kg: 'за кг', liter: 'за литр', group: 'за группу', hour: 'за час', ticket: 'за билет'};

function sourceUrl(entry) {
  try { const url = new URL(entry?.source?.url); return ['https:', 'http:'].includes(url.protocol) ? url.href : null; }
  catch { return null; }
}

function accepted(entry) {
  return entry?.status === 'accepted' && entry.conflict_status === 'none' && entry.branch_scope === 'exact'
    && sourceUrl(entry) && entry.source.checked_at && entry.source.excerpt;
}

function displayValue(value) {
  if (typeof value === 'boolean') return tr(value ? 'Да' : 'Нет');
  if (typeof value === 'string' || typeof value === 'number') return value;
  if (Array.isArray(value) && value.every(item => ['string', 'number'].includes(typeof item))) return value.join(', ');
  return null;
}

function Price({price}) {
  if (typeof price?.amount !== 'number' || !Number.isFinite(price.amount) || !price.currency) return null;
  return <span className="food-price">{new Intl.NumberFormat(getLanguage() === 'en' ? 'en-US' : 'ru-RU').format(price.amount)}{' '}
    {price.currency === 'KZT' ? '₸' : price.currency}<small>{UNITS[price.unit] ? tr(UNITS[price.unit]) :
      typeof price.unit === 'string' && price.unit.length <= 80 ? price.unit : tr('Единицу цены уточни')}</small></span>;
}

function Source({entry, channel}) {
  const url = sourceUrl(entry);
  return <div className="food-source"><span>{tr(CHANNELS[channel || entry.source.channel] || 'Условия уточни у источника')}</span>
    <a href={url} target="_blank" rel="noreferrer">{new URL(url).hostname.replace(/^www\./, '')}</a>
    <time dateTime={entry.source.checked_at}>{entry.source.checked_at.slice(0, 10)}</time>
    {entry.source.source_updated_at && <span>{tr('Версия источника')}: {entry.source.source_updated_at.slice(0, 10)}</span>}</div>;
}

function MealCost({item}) {
  const cost = accepted(item.cost) && item.cost.scope === 'one_offering' ? item.cost : null;
  const complete = cost?.complete === true && item.cost_status === 'complete' && item.total_price;
  return <>
    {complete ? <div><small>{tr('Итого с обязательными доплатами')}</small><Price price={item.total_price} /></div>
      : <p className="food-menu-note">{tr('Итоговая стоимость с доплатами не подтверждена')}</p>}
    {cost && <div className="food-cost-terms">
      {typeof cost.service_percent === 'number' && Number.isFinite(cost.service_percent) && <small>{tr('Обслуживание')}: {cost.service_percent}%</small>}
      <Source entry={cost} channel={item.price?.channel} />
    </div>}
  </>;
}

export default function PlaceFacts({place}) {
  const menu = (place.menuItems || []).filter(accepted).slice(0, 3);
  const prices = (place.prices || []).filter(accepted);
  const facts = (place.structuredFacts || []).filter(fact => accepted(fact) && FIELDS[fact.field] && displayValue(fact.value) != null);
  const menuLink = (place.structuredFacts || []).find(fact => accepted(fact) && fact.field === 'menu_url'
    && typeof fact.value === 'string' && sourceUrl({source: {url: fact.value}}));
  if (!menu.length && !prices.length && !facts.length) return null;
  return <section className="place-food-facts" aria-label={tr('Меню, цены и сведения из источников')}>
    {prices.map((price, index) => <div className="food-check" key={index}>
      <div><strong>{tr(price.kind === 'average_check' ? 'Средний чек' : 'Цена по источнику')}</strong><Price price={price} /></div>
      <Source entry={price} channel={price.channel} />
    </div>)}
    {menu.length > 0 && <><h4>{tr('Из меню')}</h4><ul className="food-menu">{menu.map((item, index) => <li key={item.id || index}>
      <div><span>{item.name}</span><span><small>{tr('Цена по меню')}</small> <Price price={item.price} /></span></div>
      <Source entry={item} channel={item.price?.channel} />
      {item.serving_hours && <p className="food-menu-note">{tr('Часы подачи блюда')}: {item.serving_hours}</p>}
      <MealCost item={item} />
    </li>)}</ul><p className="food-menu-note">{tr('Часть опубликованного меню. Цены доставки могут отличаться от цен в заведении.')}</p></>}
    {menu.some(item => item.role === 'meal' && item.price?.channel === 'dine_in')
      && !facts.some(fact => fact.field === 'kitchen_hours')
      && <p className="food-menu-note">{tr('Часы работы кухни не подтверждены')}</p>}
    {menuLink && <p><a href={menuLink.value} target="_blank" rel="noreferrer">{tr('Полное меню у источника')}</a></p>}
    {facts.length > 0 && <details className="food-venue-facts"><summary>{tr('Сведения о месте')}</summary><dl>{facts.map((fact, index) =>
      <div key={fact.field + index}><dt>{tr(FIELDS[fact.field])}</dt><dd>{displayValue(fact.value)}<Source entry={fact} /></dd></div>)}</dl></details>}
  </section>;
}
