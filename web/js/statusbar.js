// web/js/statusbar.js
import { badge, fmtAge, fmtSigma, fmtNum, fmtT } from "./protocol.js";

export function mountStatusbar(Vue, store) {
  Vue.createApp({
    computed: {
      st() { return store.status || {}; },
      b() { return this.st.verdict ? badge(this.st) : { cls: "none", text: "无数据" }; },
      sol() { return this.st.sol || {}; },
      can() { return this.st.can || {}; },
      speed() { return fmtNum(this.can.speed, 1, " m/s"); },
      sats() { return this.sol.sats ?? this.can.sats ?? "—"; },
      age() { return fmtAge(this.sol.age ?? this.can.age ?? null); },
      sigma() { return fmtSigma(this.sol.sdn, this.sol.sde); },
      clock() { return fmtT(this.st.t); },
      replaying() { return store.replaying; },
    },
    template: `
      <div class="statusbar">
        <span :class="'badge ' + b.cls">{{ b.text }}</span>
        <span v-if="replaying" class="tag replay">回放</span>
        <span class="kv">卫星 <b>{{ sats }}</b></span>
        <span class="kv">龄期 <b>{{ age }}</b></span>
        <span class="kv">σ <b>{{ sigma }}</b></span>
        <span class="kv">速度 <b>{{ speed }}</b></span>
        <span class="kv time">{{ clock }}</span>
      </div>`,
  }).mount("#statusbar");
}
