// web/js/timeline.js
export function sigmaSeriesCm(arr) {
  return arr.map((v) => (v === null || v === undefined ? null : Math.round(v * 1000) / 10));
}

const AXIS = { stroke: "#8b95a3", grid: { stroke: "#232b35" }, ticks: { stroke: "#232b35" } };

// Zoom preservation (I5, partial/pragmatic): uPlot has no first-class "did the
// user zoom" flag, so we track it ourselves, per chart, as a plain property
// on the uPlot instance (chart._userZoom). A drag-selection with nonzero
// width (uPlot's "setSelect" hook) means the user is zooming in; a
// double-click on the chart root is uPlot's built-in reset-to-full-data
// gesture, so it clears the flag there too. While _userZoom is set,
// setData(data, false) is used so uPlot keeps the current x-scale instead of
// re-fitting it to the new data on every incoming point.
// LIMITATION: zoom state is per chart, not synced across the four charts
// (only cursor position is, via the shared `sync: { key: "rtk" }` group) —
// zooming one chart does not zoom the other three. Revisit if that turns out
// to matter in practice.
function mkChart(el, label, color) {
  const chart = new uPlot({
    width: el.clientWidth || 600, height: 110,
    cursor: { sync: { key: "rtk" } },
    legend: { show: false },
    scales: { x: { time: true } },
    axes: [ { ...AXIS }, { ...AXIS, label } ],
    series: [ {}, { label, stroke: color, width: 2, spanGaps: false } ],
    hooks: {
      setSelect: [(u) => { if (u.select && u.select.width > 0) u._userZoom = true; }],
    },
  }, [[], []], el);
  chart._userZoom = false;
  el.addEventListener("dblclick", () => { chart._userZoom = false; });
  return chart;
}

export class Timelines {
  constructor(store) {
    this.store = store;
    this.charts = {
      sats: mkChart(document.getElementById("chart-sats"), "卫星数", "#4a90d9"),
      age: mkChart(document.getElementById("chart-age"), "龄期 s", "#3fb96c"),
      sigma: mkChart(document.getElementById("chart-sigma"), "σ cm", "#e0b23c"),
      ratio: mkChart(document.getElementById("chart-ratio"), "ratio", "#b07ad9"),
    };
  }
  render() {
    const s = this.store.series;
    const set = (chart, data) => chart.setData(data, !chart._userZoom);
    set(this.charts.sats, [s.t, s.sats]);
    set(this.charts.age, [s.t, s.age]);
    set(this.charts.sigma, [s.t, sigmaSeriesCm(s.sigma)]);
    set(this.charts.ratio, [s.t, s.ratio]);
  }
}
