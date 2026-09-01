// web/js/timeline.js
export function sigmaSeriesCm(arr) {
  return arr.map((v) => (v === null || v === undefined ? null : Math.round(v * 1000) / 10));
}

const AXIS = { stroke: "#8b95a3", grid: { stroke: "#232b35" }, ticks: { stroke: "#232b35" } };

function mkChart(el, label, color) {
  return new uPlot({
    width: el.clientWidth || 600, height: 110,
    cursor: { sync: { key: "rtk" } },
    legend: { show: false },
    scales: { x: { time: true } },
    axes: [ { ...AXIS }, { ...AXIS, label } ],
    series: [ {}, { label, stroke: color, width: 2, spanGaps: false } ],
  }, [[], []], el);
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
    this.charts.sats.setData([s.t, s.sats]);
    this.charts.age.setData([s.t, s.age]);
    this.charts.sigma.setData([s.t, sigmaSeriesCm(s.sigma)]);
    this.charts.ratio.setData([s.t, s.ratio]);
  }
}
