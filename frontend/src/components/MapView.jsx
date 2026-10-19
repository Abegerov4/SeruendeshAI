import { t as tr } from "../i18n";
import React, { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { Plus, Minus, LocateFixed, Layers, Route } from 'lucide-react';

const ASTANA = [51.128, 71.43];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

// Real map (OpenStreetMap data, CARTO tiles): numbered stops, "you are here" (rounded) and the
// walking route geometry returned by the API (network legs follow streets; straight legs are dashed).
export default function CityMap({ places, origin, route, showRoute, setRoute, selected, setSelected, hovered, resultVersion, focusRoute }) {
  const box = useRef(null), map = useRef(null), layers = useRef(null), bounds = useRef(null), focusLayer = useRef(null);
  const fitOpts = () => (box.current?.clientWidth || 0) < 560
    ? { paddingTopLeft: [24, 56], paddingBottomRight: [60, 120], maxZoom: 16 }
    : { paddingTopLeft: [40, 70], paddingBottomRight: [70, 150], maxZoom: 16 };
  useEffect(() => {
    const m = L.map(box.current, { zoomControl: false, attributionControl: true, scrollWheelZoom: true, zoomAnimation: false, markerZoomAnimation: false }).setView(ASTANA, 14);
    // No CSS filter on the tile pane: iOS Safari may not paint filtered layers inside a rounded, clipped box
    // (the map stayed blank on iPhones). The warm look comes from slightly transparent tiles over a cream background.
    const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(m);
    let failed = 0, switched = false;  // some privacy browsers strip the Referer and OSM refuses: switch to the OSM France mirror
    osm.on('tileerror', () => {
      if (switched || ++failed < 4) return;
      switched = true; m.removeLayer(osm);
      L.tileLayer('https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png', {
        maxZoom: 19, subdomains: 'abc', attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, OSM France'
      }).addTo(m);
    });
    osm.on('tileload', () => { failed = 0; });
    layers.current = L.layerGroup().addTo(m);
    map.current = m;
    if (location.search.includes('debug')) window.__seruMap = m;
    let hidden = true, timer;
    const ro = new ResizeObserver(([e]) => {  // hidden tab -> visible: re-fit once the layout has settled
      const { width: w, height: h } = e.contentRect;
      m.invalidateSize();
      const visible = w > 200 && h > 200;
      if (visible && hidden && bounds.current) {
        clearTimeout(timer);
        timer = setTimeout(() => { m.invalidateSize(); m.fitBounds(bounds.current, fitOpts()); }, 180);
      }
      hidden = !visible;
    });
    ro.observe(box.current);
    return () => { clearTimeout(timer); ro.disconnect(); m.remove(); };
  }, []);

  useEffect(() => {
    const m = map.current, g = layers.current;
    if (!m || !g) return;
    g.clearLayers();
    const pts = [];
    if (origin?.lat != null) {
      pts.push([origin.lat, origin.lon]);
      L.marker([origin.lat, origin.lon], { icon: L.divIcon({ className: 'leaflet-you', html: `<span class="you-dot"></span><label>${esc(tr('Вы здесь'))}</label>`, iconSize: [18, 18], iconAnchor: [9, 9] }), keyboard: false }).addTo(g);
      L.circle([origin.lat, origin.lon], { radius: 100, color: '#397257', weight: 1, fillOpacity: .08 }).addTo(g);
    }
    if (showRoute && route?.legs) for (const leg of route.legs) {
      if (!leg.polyline?.length) continue;
      const style = leg.geometry === 'network' ? { color: '#397257', weight: 5, opacity: .9 } : { color: '#397257', weight: 4, opacity: .8, dashArray: '8 10' };
      L.polyline(leg.polyline, { color: '#fff', weight: style.weight + 5, opacity: .9 }).addTo(g);
      L.polyline(leg.polyline, { ...style, className: 'animated-route-leaflet' }).addTo(g);
      leg.polyline.forEach(p => pts.push(p));
    }
    places.forEach((p, i) => {
      if (p.lat == null) return;
      pts.push([p.lat, p.lon]);
      const cls = 'leaflet-stop' + (selected === p.id ? ' selected' : '') + (hovered === p.id ? ' highlighted' : '') + (p.generated ? ' idea' : '');
      const html = `<span>${p.generated ? '✦' : i + 1}</span>${selected === p.id ? `<label>${esc(p.name)}</label>` : ''}`;
      L.marker([p.lat, p.lon], { icon: L.divIcon({ className: cls, html, iconSize: [34, 34], iconAnchor: [17, 17] }), title: p.name, riseOnHover: true })
        .on('click', () => setSelected(p.id)).addTo(g);
    });
    if (pts.length) {
      bounds.current = L.latLngBounds(pts);
      if (location.search.includes('debug')) window.__seruBounds = bounds.current;
      if (box.current.clientWidth > 200 && box.current.clientHeight > 200) m.fitBounds(bounds.current, fitOpts());
    }
  }, [places, origin, route, showRoute, resultVersion]);

  useEffect(() => {  // the route from the user to one chosen place (chat card -> "Маршрут")
    const m = map.current;
    if (!m) return;
    focusLayer.current?.remove();
    focusLayer.current = null;
    if (!focusRoute?.polyline?.length) return;
    const g = L.layerGroup().addTo(m);
    const dashed = focusRoute.geometry !== 'network';
    L.polyline(focusRoute.polyline, { color: '#fff', weight: 10, opacity: .95 }).addTo(g);
    L.polyline(focusRoute.polyline, { color: '#1d5c45', weight: 6, opacity: .95, dashArray: dashed ? '9 10' : null, className: 'focus-route' }).addTo(g);
    const start = focusRoute.polyline[0];
    L.marker(start, { icon: L.divIcon({ className: 'leaflet-you', html: `<span class="you-dot"></span><label>${esc(tr('Вы здесь'))}</label>`, iconSize: [18, 18], iconAnchor: [9, 9] }), keyboard: false }).addTo(g);
    focusLayer.current = g;
    bounds.current = L.latLngBounds(focusRoute.polyline);  // a hidden map tab re-fits to the route when shown
    const fitNow = () => { m.invalidateSize(); m.fitBounds(L.latLngBounds(focusRoute.polyline), { ...fitOpts(), maxZoom: 17 }); };
    if (box.current.clientWidth > 200 && box.current.clientHeight > 200) fitNow(); else setTimeout(fitNow, 350);  // tab just became visible
  }, [focusRoute]);

  useEffect(() => {  // re-render markers on selection/hover without re-fitting the view
    const g = layers.current;
    if (!g) return;
    g.eachLayer(l => {
      const el = l.getElement?.();
      if (!el || !el.classList.contains('leaflet-stop')) return;
      const p = places.find(x => x.name === l.options.title);
      if (!p) return;
      el.classList.toggle('selected', selected === p.id);
      el.classList.toggle('highlighted', hovered === p.id);
    });
    const p = places.find(x => x.id === selected);
    const m = map.current;
    if (p?.lat != null && m && m.getSize().x > 200 && !m.getBounds().pad(-0.1).contains([p.lat, p.lon])) m.panTo([p.lat, p.lon], { animate: true });
  }, [selected, hovered]);

  const fit = () => {
    const pts = places.filter(p => p.lat != null).map(p => [p.lat, p.lon]);
    if (origin?.lat != null) pts.push([origin.lat, origin.lon]);
    if (pts.length) map.current.fitBounds(L.latLngBounds(pts), fitOpts());
  };
  return <div className="map-canvas leaflet-canvas">
    <div ref={box} className="leaflet-box" role="region" aria-label={tr('Карта прогулки')} />
    <div className="map-top"><span className="map-label"><span />{tr('Астана, Казахстан')}</span></div>
    <div className="map-controls"><button aria-label={tr('Приблизить карту')} onClick={() => map.current.zoomIn()}><Plus size={19} /></button><button aria-label={tr('Отдалить карту')} onClick={() => map.current.zoomOut()}><Minus size={19} /></button><i /><button aria-label={tr('Вернуться к маршруту')} onClick={fit}><LocateFixed size={19} /></button></div>
    {route && <div className="map-bottom"><span><Layers size={14} />{tr('Маршрут прогулки')}</span><button onClick={() => setRoute(!showRoute)}><Route size={15} />{showRoute ? tr('Скрыть маршрут') : tr('Показать маршрут')}</button></div>}
  </div>;
}
