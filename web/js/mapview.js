// web/js/mapview.js — Leaflet map view: offline tiles with grid fallback,
// state-colored trails, vehicle marker with heading, sigma circle.
//
// NOTE: intra-web/js imports use relative paths so `node --test` can resolve
// them without a bundler (see web/js/store.js); web/app.js (never
// node-tested) imports this module via the absolute /js/mapview.js path.
import { segmentTrail } from "./protocol.js";

const COLORS = { fixed: "#3fb96c", float: "#e0b23c", bad: "#e05c4f", none: "#5a6472" };
export const trailColor = (cls) => COLORS[cls];

// Grid fallback tile layer: draws a bordered canvas tile labeled z/x/y so an
// offline deployment without tiles still shows a readable grid instead of a
// blank pane. Guarded by `typeof L` so this module stays importable under
// `node --test` (no global Leaflet there) while trailColor is exercised in
// isolation — see tests_js/mapview.test.mjs.
const GridFallback = typeof L !== "undefined" ? L.GridLayer.extend({
  createTile(coords) {
    const c = document.createElement("canvas");
    c.width = c.height = 256;
    const g = c.getContext("2d");
    g.strokeStyle = "#2a3340";
    g.strokeRect(0, 0, 256, 256);
    g.fillStyle = "#5a6472";
    g.font = "12px sans-serif";
    g.fillText(`${coords.z}/${coords.x}/${coords.y}`, 8, 16);
    return c;
  },
}) : null;

export class MapView {
  constructor(elId, store) {
    this.store = store;
    this.map = L.map(elId, { zoomControl: true }).setView([0, 0], 3);
    this.map.on("dragstart", () => { this._userMoved = true; });

    // Probe /api/tiles_info rather than a fixed tile coordinate: with a
    // mine-only tileset, any single hardcoded tile (e.g. z12/3000/1500) can
    // legitimately be absent while the tile store itself is populated, which
    // would false-negative a fixed-tile probe into the grid fallback.
    fetch("/api/tiles_info").then((r) => r.json()).then((info) => {
      if (info && info.available) L.tileLayer("/tiles/{z}/{x}/{y}.png", { maxZoom: 22 }).addTo(this.map);
      else new GridFallback().addTo(this.map);
    }).catch(() => new GridFallback().addTo(this.map));

    this.groups = {
      can: L.layerGroup().addTo(this.map),
      rtkrcv: L.layerGroup().addTo(this.map),
      gpchc: L.layerGroup().addTo(this.map),
    };
    this.marker = null;
    this.sigma = null;
    this._centered = false;
    this._userMoved = false;
  }

  _style(src, cls) {
    const base = { color: trailColor(cls) };
    if (src === "rtkrcv") return { ...base, weight: 3 };
    if (src === "can") return { ...base, weight: 2, opacity: 0.8 };
    return { ...base, weight: 2, dashArray: "4 6" };
  }

  render() {
    for (const src of ["can", "rtkrcv", "gpchc"]) {
      const g = this.groups[src];
      g.clearLayers();
      for (const seg of segmentTrail(this.store.trails[src]))
        L.polyline(seg.latlngs, this._style(src, seg.cls)).addTo(g);
    }

    const st = this.store.status || {};
    const pos = st.can && st.can.lat != null ? st.can : (st.sol && st.sol.lat != null ? st.sol : null);
    if (!pos) return;

    const ll = [pos.lat, pos.lon];
    const heading = pos.heading ?? 0;
    // .veh-arrow (style.css) already styles an inner <svg> arrow sized to
    // the divIcon; rotate the wrapper by heading to point it.
    const icon = L.divIcon({
      className: "veh",
      html: `<div class="veh-arrow" style="transform:rotate(${heading}deg)">`
          + `<svg viewBox="0 0 24 24"><polygon points="12,2 20,22 12,17 4,22"/></svg></div>`,
      iconSize: [18, 18],
      iconAnchor: [9, 9],
    });
    if (!this.marker) this.marker = L.marker(ll, { icon }).addTo(this.map);
    else { this.marker.setLatLng(ll); this.marker.setIcon(icon); }

    const sol = st.sol;
    if (sol && sol.sdn != null && sol.sde != null) {
      const r = Math.hypot(sol.sdn, sol.sde);
      if (!this.sigma) this.sigma = L.circle(ll, { radius: r, color: "#4a90d9", weight: 1 }).addTo(this.map);
      else { this.sigma.setLatLng(ll); this.sigma.setRadius(r); }
    }

    if (!this._centered) { this.map.setView(ll, 17); this._centered = true; }
    else if (!this._userMoved) this.map.panTo(ll, { animate: false });
  }
}
