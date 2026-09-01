import test from "node:test";
import assert from "node:assert/strict";
import { fixClass, badge, fmtAge, fmtSigma, fmtT, fmtNum, segmentTrail, SPEED_OPTIONS, eventKey }
  from "../web/js/protocol.js";

test("fixClass per source semantics", () => {
  assert.equal(fixClass("rtkrcv", 1), "fixed");
  assert.equal(fixClass("rtkrcv", 2), "float");
  assert.equal(fixClass("rtkrcv", 5), "bad");
  assert.equal(fixClass("rtkrcv", null), "none");
  assert.equal(fixClass("can", 4), "fixed");
  assert.equal(fixClass("can", 5), "float");
  assert.equal(fixClass("can", 3), "bad");
  assert.equal(fixClass("gpchc", undefined), "none");
});

test("badge prefers sol, falls back to can, honors verdict", () => {
  const sol = { q: 1 }, can = { q: 5 };
  assert.deepEqual(badge({ sol, can, verdict: { level: "ok" } }),
                   { cls: "fixed", text: "RTK 固定" });
  assert.deepEqual(badge({ sol: null, can, verdict: { level: "ok" } }),
                   { cls: "float", text: "浮点解" });
  const b = badge({ sol: null, can: null,
                    verdict: { level: "warning", code: "no_data", message: "无数据——检查采集链路" } });
  assert.equal(b.cls, "none");
  assert.equal(b.text, "无数据——检查采集链路");
  const s = badge({ sol, can, verdict: { level: "serious", message: "差分中断 5s" } });
  assert.equal(s.cls, "fixed");
  assert.equal(s.text, "差分中断 5s");
});

test("formatters render null as em-dash", () => {
  assert.equal(fmtAge(null), "—");
  assert.equal(fmtAge(0.8), "0.8 s");
  assert.equal(fmtSigma(0.011, 0.012), "1.6 cm");
  assert.equal(fmtSigma(null, 0.012), "—");
  assert.equal(fmtNum(undefined, 1, " m/s"), "—");
  assert.match(fmtT(0), /^\d{2}:\d{2}:\d{2}$/);
});

test("segmentTrail splits on class change with continuity", () => {
  const pts = [
    { lat: 1, lon: 1, src: "can", q: 4 },
    { lat: 2, lon: 2, src: "can", q: 4 },
    { lat: 3, lon: 3, src: "can", q: 5 },
    { lat: 4, lon: 4, src: "can", q: 5 },
  ];
  const segs = segmentTrail(pts);
  assert.equal(segs.length, 2);
  assert.equal(segs[0].cls, "fixed");
  assert.equal(segs[1].cls, "float");
  assert.deepEqual(segs[0].latlngs.at(-1), [2, 2]);
  assert.deepEqual(segs[1].latlngs[0], [2, 2]);   // continuity point
  assert.equal(segs[1].latlngs.length, 3);
});

test("speed options", () => assert.deepEqual(SPEED_OPTIONS, [1, 10, 60]));

test("eventKey identifies same open/close occurrence, distinguishes others", () => {
  const a = { t: 100, action: "open", code: "no_data" };
  const b = { t: 100, action: "open", code: "no_data" };
  const c = { t: 100, action: "close", code: "no_data" };
  const d = { t: 100, action: "open", code: "sat_low" };
  assert.equal(eventKey(a), eventKey(b));
  assert.notEqual(eventKey(a), eventKey(c));
  assert.notEqual(eventKey(a), eventKey(d));
});
