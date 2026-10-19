import { t as tr } from "../i18n";
import React, { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { smoothZoom } from '../mapWheel';
import { LEG_COLORS, arrowPoints, legEnds } from '../routeLegs';
import { formatDistance } from '../api';
import { Plus, Minus, LocateFixed, Layers, Route } from 'lucide-react';

const ASTANA = [51.128, 71.43];
// Astana only: the map cannot be panned or zoomed out to other cities (same box as the API's in_astana)
export const ASTANA_BOUNDS = [[50.857, 71.217], [51.352, 71.786]];
// updateWhenZooming off: while zooming the loaded tiles only scale, the next level loads when the motion stops
// (otherwise every whole-level crossing mid-zoom swapped the map in piece by piece); keepBuffer keeps more around.
const TILE_OPTS = { maxZoom: 19, minZoom: 11, bounds: ASTANA_BOUNDS, updateWhenZooming: false, keepBuffer: 4 };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

// Real map (OpenStreetMap data, CARTO tiles): numbered stops, "you are here" (rounded) and the
// walking route geometry returned by the API (network legs follow streets; straight legs are dashed).
export default function CityMap({ places, origin, route, showRoute, setRoute, selected, setSelected, hovered, resultVersion, focusRoute, tiles, routeVisible, onToggleRoute }) {
  const box = useRef(null), map = useRef(null), layers = useRef(null), bounds = useRef(null), focusLayer = useRef(null);
  const fitOpts = () => (box.current?.clientWidth || 0) < 560
    ? { paddingTopLeft: [24, 56], paddingBottomRight: [60, 120], maxZoom: 16 }
    : { paddingTopLeft: [40, 70], paddingBottomRight: [70, 150], maxZoom: 16 };
  const baseLayer = useRef(null), zoomer = useRef(null);
  useEffect(() => {
    // Leaflet's own wheel zoom rounds every tiny trackpad event up to a whole zoom level (zoomSnap 1),
    // so a two-finger swipe threw the map several levels at once. Wheel and +/- go through smoothZoom (mapWheel.js).
    const smooth = !L.Browser.mobile;  // zoom animation stays off on phones (as before), on for desktop
    const m = L.map(box.current, { maxBounds: ASTANA_BOUNDS, maxBoundsViscosity: 0.7, minZoom: 11, zoomControl: false, attributionControl: true, scrollWheelZoom: false, zoomSnap: 0.25, zoomAnimation: smooth, markerZoomAnimation: smooth }).setView(ASTANA, 14);
    zoomer.current = smoothZoom(m, box.current);
    // No CSS filter on the tile pane: iOS Safari may not paint filtered layers inside a rounded, clipped box
    // (the map stayed blank on iPhones). The warm look comes from slightly transparent tiles over a cream background.
    // OpenStreetMap tiles; if they fail (privacy browsers strip the Referer and OSM refuses), the OSM France mirror.
    // Keyless styled basemaps (CARTO) now answer «API key required» as an image, so they are not used.
    const OSM = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
    const providers = [
      ['https://tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: OSM }],
      ['https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png', { subdomains: 'abc', attribution: OSM + ', OSM France' }],
    ];
    const useTiles = i => {
      const [url, opts] = providers[i];
      const layer = L.tileLayer(url, { ...TILE_OPTS, ...opts }).addTo(m);
      baseLayer.current = layer;
      let failed = 0;
      layer.on('tileload', () => { failed = 0; });
      layer.on('tileerror', () => { if (++failed === 4 && i + 1 < providers.length) { m.removeLayer(layer); useTiles(i + 1); } });
    };
    useTiles(0);
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
        timer = setTimeout(() => { m.invalidateSize(); zoomer.current.cancel(); m.fitBounds(bounds.current, fitOpts()); }, 180);
      }
      hidden = !visible;
    });
    ro.observe(box.current);
    return () => { clearTimeout(timer); ro.disconnect(); zoomer.current.stop(); m.remove(); };
  }, []);
  useEffect(() => {  // a styled basemap (MapTiler) when the server has a key; OpenStreetMap stays if it fails
    const m = map.current;
    if (!m || !tiles?.url) return;
    const styled = L.tileLayer(tiles.url, { ...TILE_OPTS, tileSize: 256, attribution: tiles.attribution });
    let failed = 0, ok = false;
    styled.on('tileload', () => { if (!ok) { ok = true; if (baseLayer.current && baseLayer.current !== styled) m.removeLayer(baseLayer.current); baseLayer.current = styled; } });
    styled.on('tileerror', () => { if (!ok && ++failed >= 3) m.removeLayer(styled); });
    styled.addTo(m);
    return () => { if (baseLayer.current !== styled) m.removeLayer(styled); };
  }, [tiles?.url, map.current]);

  useEffect(() => {
    const m = map.current, g = layers.current;
    if (!m || !g) return;
    g.clearLayers();
    const pts = [];
    if (origin?.lat != null) {
      pts.push([origin.lat, origin.lon]);
      L.marker([origin.lat, origin.lon], { icon: L.divIcon({ className: 'leaflet-you', html: `<span class="you-dot"></span><label>${esc(origin.label ? tr('Старт') + ': ' + origin.label : tr('Вы здесь'))}</label>`, iconSize: [18, 18], iconAnchor: [9, 9] }), keyboard: false }).addTo(g);
      L.circle([origin.lat, origin.lon], { radius: 100, color: '#397257', weight: 1, fillOpacity: .08 }).addTo(g);
    }
    if (showRoute && route?.legs) route.legs.forEach((leg, n) => {
      if (!leg.polyline?.length) return;
      // each leg its own colour + direction arrows + a hover label, so out-and-back legs on one street stay readable
      const color = LEG_COLORS[n % LEG_COLORS.length];
      const style = leg.geometry === 'network' ? { color, weight: 5, opacity: .92 } : { color, weight: 4, opacity: .85, dashArray: '8 10' };
      const casing = L.polyline(leg.polyline, { color: '#fff', weight: style.weight + 5, opacity: .9 }).addTo(g);
      const line = L.polyline(leg.polyline, { ...style, className: 'animated-route-leaflet' }).addTo(g);
      const [from, to] = legEnds(leg, places, origin?.label ? tr('Старт') : tr('Вы здесь'));
      line.bindTooltip(`<span class="leg-dot" style="background:${color}"></span>${esc(from)} → ${esc(to)} · ${formatDistance(leg.distance_m)} · ${leg.travel_min} ${tr('мин')}`, { sticky: true, className: 'leg-tooltip' });
      line.on('mouseover', () => { casing.bringToFront(); line.bringToFront().setStyle({ weight: style.weight + 2 }); })
        .on('mouseout', () => line.setStyle({ weight: style.weight }));
      for (const a of arrowPoints(leg.polyline)) {
        L.marker(a.at, { icon: L.divIcon({ className: 'leg-arrow', html: `<span style="transform:rotate(${a.deg.toFixed(0)}deg);color:${color}"></span>`, iconSize: [16, 16], iconAnchor: [8, 8] }), interactive: false, keyboard: false }).addTo(g);
      }
      leg.polyline.forEach(p => pts.push(p));
    });
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
      if (box.current.clientWidth > 200 && box.current.clientHeight > 200) { zoomer.current.cancel(); m.fitBounds(bounds.current, fitOpts()); }
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
    L.marker(start, { icon: L.divIcon({ className: 'leaflet-you', html: `<span class="you-dot"></span><label>${esc(focusRoute.origin_label ? tr('Старт') + ': ' + focusRoute.origin_label : tr('Вы здесь'))}</label>`, iconSize: [18, 18], iconAnchor: [9, 9] }), keyboard: false }).addTo(g);
    focusLayer.current = g;
    bounds.current = L.latLngBounds(focusRoute.polyline);  // a hidden map tab re-fits to the route when shown
    const fitNow = () => { zoomer.current.cancel(); m.invalidateSize(); m.fitBounds(L.latLngBounds(focusRoute.polyline), { ...fitOpts(), maxZoom: 17 }); };
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
    zoomer.current.cancel();
    const pts = places.filter(p => p.lat != null).map(p => [p.lat, p.lon]);
    if (origin?.lat != null) pts.push([origin.lat, origin.lon]);
    if (pts.length) map.current.fitBounds(L.latLngBounds(pts), fitOpts());
  };
  return <div className="map-canvas leaflet-canvas">
    <div ref={box} className="leaflet-box" role="region" aria-label={tr('Карта прогулки')} />
    <div className="map-top"><span className="map-label"><span />{tr('Астана, Казахстан')}</span></div>
    <div className="map-controls"><button aria-label={tr('Приблизить карту')} onClick={() => zoomer.current.zoomBy(1)}><Plus size={19} /></button><button aria-label={tr('Отдалить карту')} onClick={() => zoomer.current.zoomBy(-1)}><Minus size={19} /></button><i /><button aria-label={tr('Вернуться к маршруту')} onClick={fit}><LocateFixed size={19} /></button></div>
    {route && <div className="map-bottom"><span><Layers size={14} />{tr('Маршрут прогулки')}</span><button onClick={() => onToggleRoute ? onToggleRoute() : setRoute(!showRoute)}><Route size={15} />{(routeVisible ?? showRoute) ? tr('Скрыть маршрут') : tr('Показать маршрут')}</button></div>}
  </div>;
}
