import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { ShieldCheck, Users, AlertTriangle, Target, Grid3x3, Download } from 'lucide-react';
import { t as tr, useLocale } from '../i18n';
import { ASTANA_BOUNDS } from '../components/MapView';

// City Insights: what people look for in Astana, where and when, and where the city does not answer yet.
// Only k-anonymous counters come from the API (≈1 km cell × 3-hour slot × intent); nothing personal.
const tone = share => share >= 0.5 ? '#c4532d' : share >= 0.25 ? '#d9a23a' : '#3f8a4a';

function DemandMap({ cells }) {
  const box = useRef(null), map = useRef(null), layer = useRef(null);
  useEffect(() => {
    const m = L.map(box.current, { zoomControl: true, scrollWheelZoom: false, attributionControl: true, maxBounds: ASTANA_BOUNDS,
      maxBoundsViscosity: 1, minZoom: 10 }).setView([51.128, 71.43], 12);  // Astana only
    const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18, bounds: ASTANA_BOUNDS, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(m);
    fetch('/api/meta').then(r => r.json()).then(meta => {  // the calmer data style when the server has a map key
      if (!meta.map?.data_url) return;
      const styled = L.tileLayer(meta.map.data_url, { maxZoom: 18, bounds: ASTANA_BOUNDS, attribution: meta.map.attribution });
      styled.once('tileload', () => m.removeLayer(osm));
      styled.addTo(m);
    }).catch(() => {});
    layer.current = L.layerGroup().addTo(m); map.current = m;
    return () => m.remove();
  }, []);
  useEffect(() => {
    const g = layer.current; if (!g) return;
    g.clearLayers();
    const max = Math.max(1, ...cells.map(c => c.requests));
    cells.forEach(c => {
      // the cell itself (≈1 km), coloured by the share of requests the city could not answer well
      L.rectangle([[c.lat - 0.005, c.lon - 0.005], [c.lat + 0.005, c.lon + 0.005]], {
        color: tone(c.unmet_share), weight: 1, fillColor: tone(c.unmet_share), fillOpacity: 0.18 + 0.5 * c.requests / max })
        .bindPopup(`<b>${c.requests} ${tr('запросов')}</b><br>${tr('без хорошего ответа')}: ${Math.round(c.unmet_share * 100)}%`
          + (c.top.length ? `<br>${tr('Чаще ищут')}: ${c.top.join(', ')}` : ''))
        .addTo(g);
    });
    if (cells.length) map.current.fitBounds(L.latLngBounds(cells.map(c => [c.lat, c.lon])).pad(0.4), { maxZoom: 13 });
  }, [cells]);
  return <div className="insights-map" ref={box} role="img" aria-label={tr('Карта спроса по районам')} />;
}

function Bars({ rows, value, label, extra }) {
  const max = Math.max(1, ...rows.map(value));
  return <ul className="insights-bars">{rows.map(r => <li key={label(r)}>
    <span className="bar-label">{label(r)}</span>
    <span className="bar-track"><i style={{ width: (100 * value(r) / max) + '%' }} />{extra && <b style={{ width: (100 * extra(r) / max) + '%' }} />}</span>
    <span className="bar-value">{value(r)}</span>
  </li>)}</ul>;
}

export default function Insights() {
  const lang = useLocale();
  const [days, setDays] = useState(30), [data, setData] = useState(null), [error, setError] = useState(false);
  useEffect(() => {
    let live = true; setError(false);
    fetch(`/api/insights?days=${days}&lang=${lang}`).then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(d => { if (live) setData(d); }).catch(() => { if (live) setError(true); });
    return () => { live = false; };
  }, [days, lang]);
  const enough = data && data.requests >= data.k;
  const unmet = data ? [...data.intents].filter(i => i.unmet_share > 0).sort((a, b) => b.unmet_share - a.unmet_share).slice(0, 5) : [];
  return <main className="insights-page">
    <section className="insights-hero">
      <span className="section-eyebrow">{tr('ДЛЯ ГОРОДА · SMART CITY')}</span>
      <h1>{tr('Город глазами жителей')}</h1>
      <p>{tr('Что жители и гости ищут в Астане, где и когда — и где город пока не отвечает. Помогает акимату и Центру Smart City планировать площадки, маршруты и сервисы по реальному спросу.')}</p>
      <div className="insights-period" role="group" aria-label={tr('Период')}>{[7, 30, 90].map(d =>
        <button key={d} aria-pressed={days === d} onClick={() => setDays(d)}>{d} {tr('дней')}</button>)}</div>
    </section>

    <section className="insights-privacy"><ShieldCheck size={20} /><p><b>{tr('Приватность по умолчанию.')}</b> {tr('Храним только счётчики: ячейка ≈1 км, интервал 3 часа, тип запроса. Ни текста запросов, ни точных координат, ни пользователей. Значение показывается, только если за ним стоит не меньше {k} запросов.', { k: data?.k ?? 5 })}</p></section>

    {error && <p className="insights-empty">{tr('Не удалось загрузить данные. Попробуй обновить страницу.')}</p>}
    {data && <>
      <section className="insights-kpis">
        <div><Users size={18} /><b>{data.requests}</b><span>{tr('запросов за период')}</span></div>
        <div><AlertTriangle size={18} /><b>{data.unmet_share == null ? '—' : Math.round(data.unmet_share * 100) + '%'}</b><span>{tr('без хорошего ответа рядом')}</span></div>
        <div><Target size={18} /><b>{data.intents[0]?.label || '—'}</b><span>{tr('ищут чаще всего')}</span></div>
        <div><Grid3x3 size={18} /><b>{data.cells.length}</b><span>{tr('районов на карте')} ({tr('скрыто')}: {data.suppressed_requests})</span></div>
      </section>
      {!enough && <p className="insights-empty">{tr('Данных пока мало: сервис считает запросы с {since}. Районы и темы появятся, когда за ними наберётся не меньше {k} запросов — так никого нельзя вычислить.', { since: data.since, k: data.k })}</p>}
      <section className="insights-grid">
        <div className="insights-card wide"><h2>{tr('Где ищут')}</h2><DemandMap cells={data.cells} />
          <p className="insights-legend"><i style={{ background: '#3f8a4a' }} />{tr('город отвечает')}<i style={{ background: '#d9a23a' }} />{tr('частично')}<i style={{ background: '#c4532d' }} />{tr('не хватает мест рядом')}</p></div>
        <div className="insights-card"><h2>{tr('Что ищут')}</h2>{data.intents.length ? <Bars rows={data.intents.slice(0, 8)} value={r => r.requests} extra={r => Math.round(r.requests * r.unmet_share)} label={r => r.label} />
          : <p className="muted">{tr('Пока ни одна тема не набрала {k} запросов.', { k: data.k })}</p>}
          <p className="insights-legend"><i className="ok" />{tr('все запросы')}<i className="bad" />{tr('без хорошего ответа')}</p></div>
        <div className="insights-card"><h2>{tr('Когда')}</h2>{data.slots.length ? <Bars rows={data.slots} value={r => r.requests} label={r => r.from + '–' + r.to} /> : <p className="muted">—</p>}</div>
        <div className="insights-card"><h2>{tr('Чего не хватает')}</h2>{unmet.length ? <ol className="insights-gaps">{unmet.map(i =>
          <li key={i.key}><b>{i.label}</b><span>{Math.round(i.unmet_share * 100)}% {tr('запросов без хорошего ответа рядом')}</span></li>)}</ol>
          : <p className="muted">{tr('Пробелов с достаточным числом запросов пока нет.')}</p>}
          <p className="insights-note">{tr('«Без хорошего ответа» — рядом ничего не нашлось, пришлось расширить радиус или нужное место было закрыто.')}</p></div>
      </section>
      <p className="insights-api"><Download size={15} /><a href={`/api/insights?days=${days}`} target="_blank" rel="noreferrer">{tr('Открытые агрегаты в JSON')}</a> · {tr('для городских систем и дашбордов НИЦ')}</p>
    </>}
  </main>;
}
