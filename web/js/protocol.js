// web/js/protocol.js — pure logic, no DOM; tested with node --test.
export const SPEED_OPTIONS = [1, 10, 60];

export function fixClass(src, q) {
  if (q === null || q === undefined) return "none";
  if (src === "rtkrcv") return q === 1 ? "fixed" : q === 2 ? "float" : "bad";
  return q === 4 ? "fixed" : q === 5 ? "float" : "bad";   // 610 nibble (can/gpchc)
}

const _BADGE_TEXT = { fixed: "RTK 固定", float: "浮点解", bad: "非固定", none: "无数据" };

export function badge(status) {
  const sol = status.sol, can = status.can, v = status.verdict || {};
  let cls;
  if (sol && sol.q !== null && sol.q !== undefined) cls = fixClass("rtkrcv", sol.q);
  else if (can && can.q !== null && can.q !== undefined) cls = fixClass("can", can.q);
  else cls = "none";
  let text = _BADGE_TEXT[cls];
  if (["warning", "serious", "critical"].includes(v.level) && v.message) text = v.message;
  return { cls, text };
}

export function fmtNum(v, digits, suffix) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(digits) + (suffix || "");
}

export const fmtAge = (v) => fmtNum(v, 1, " s");

export function fmtSigma(sdn, sde) {
  if (sdn === null || sdn === undefined || sde === null || sde === undefined) return "—";
  return (Math.hypot(sdn, sde) * 100).toFixed(1) + " cm";
}

export function fmtT(t) {
  if (t === null || t === undefined) return "—";
  return new Date(t * 1000).toTimeString().slice(0, 8);
}

export function segmentTrail(points) {
  const segs = [];
  let cur = null;
  for (const p of points) {
    const cls = fixClass(p.src, p.q);
    if (!cur || cur.cls !== cls) {
      const start = cur ? [cur.latlngs.at(-1)] : [];
      cur = { cls, latlngs: [...start] };
      segs.push(cur);
    }
    cur.latlngs.push([p.lat, p.lon]);
  }
  return segs.filter((s) => s.latlngs.length >= 2);
}
