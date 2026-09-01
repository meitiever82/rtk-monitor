// web/js/store.js
// NOTE: intra-web/js imports use relative paths so `node --test` can resolve
// them without a bundler or import map; web/app.js (never node-tested) uses
// absolute /js/... paths instead, matching how the FastAPI StaticFiles mount
// serves web/ at "/".
import { fixClass } from "./protocol.js";

const TRAIL_MAX = 3600, SERIES_MAX = 1800, EVENTS_MAX = 200;

export function createStore(Vue) {
  const s = Vue.reactive({
    connected: false, replaying: false, status: null, lastError: null,
    trails: { can: [], rtkrcv: [], gpchc: [] },
    events: [],
    series: { t: [], sats: [], age: [], sigma: [], ratio: [] },
  });

  function pushTrail(src, lat, lon, q) {
    if (lat === null || lat === undefined) return;
    const arr = s.trails[src];
    arr.push({ lat, lon, src, q });
    if (arr.length > TRAIL_MAX) arr.splice(0, arr.length - TRAIL_MAX);
  }

  s.applyMessage = (m) => {
    if (m.type === "status") {
      s.status = m;
      if (m.sol) pushTrail("rtkrcv", m.sol.lat, m.sol.lon, m.sol.q);
      if (m.gpchc) pushTrail("gpchc", m.gpchc.lat, m.gpchc.lon, m.gpchc.q);
      const sol = m.sol || {}, can = m.can || {};
      for (const [k, v] of Object.entries({
        t: m.t, sats: sol.sats ?? can.sats ?? null,
        age: sol.age ?? can.age ?? null,
        sigma: (sol.sdn != null && sol.sde != null) ? Math.hypot(sol.sdn, sol.sde) : null,
        ratio: sol.ratio ?? null,
      })) {
        s.series[k].push(v);
        if (s.series[k].length > SERIES_MAX) s.series[k].shift();
      }
    } else if (m.type === "position") {
      pushTrail(m.src, m.lat, m.lon, m.q);
    } else if (m.type === "event") {
      s.events.unshift({ action: m.action, ...m.event });
      if (s.events.length > EVENTS_MAX) s.events.pop();
    } else if (m.type === "replay_end") {
      s.replaying = false;
    } else if (m.type === "error") {
      s.lastError = m.detail; s.replaying = false;
    }
  };

  s.clearForReplay = () => {
    s.trails = { can: [], rtkrcv: [], gpchc: [] };
    s.series = { t: [], sats: [], age: [], sigma: [], ratio: [] };
    s.replaying = true;
  };
  return s;
}
