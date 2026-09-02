import test from "node:test";
import assert from "node:assert/strict";
import { createStore } from "../web/js/store.js";

// minimal Vue shim: reactive() just returns the object (no proxying needed
// for these logic tests)
const Vue = { reactive: (o) => o };

test("live mode drops in-flight replay messages", () => {
  const s = createStore(Vue);
  s.replaying = false;
  // a replay position still in flight after 回到实时 must not land on the trail
  s.applyMessage({ type: "position", src: "can", lat: 44.5, lon: 90.3, q: 4, replay: true });
  assert.equal(s.trails.can.length, 0);
  // a genuine live message (no replay flag) is applied
  s.applyMessage({ type: "position", src: "can", lat: 44.5, lon: 90.3, q: 4 });
  assert.equal(s.trails.can.length, 1);
});

test("replay mode accepts replay-flagged messages", () => {
  const s = createStore(Vue);
  s.replaying = true;
  s.applyMessage({ type: "position", src: "rtkrcv", lat: 49.1, lon: 12.8, q: 1, replay: true });
  assert.equal(s.trails.rtkrcv.length, 1);
});

test("replay_end still processed while replaying (clears mode)", () => {
  const s = createStore(Vue);
  s.replaying = true;
  s.applyMessage({ type: "replay_end", t: 100, replay: true });
  assert.equal(s.replaying, false);   // not dropped by the live-guard
});
