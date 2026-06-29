import React from "react";

const fallbackSources = [
  { name: "Google News", value: 42, color: "#5965a8" },
  { name: "News API", value: 18, color: "#2f8f72" },
  { name: "Reddit", value: 24, color: "#d05b68" },
  { name: "YouTube", value: 16, color: "#d39b39" },
];

export default function SourceDistributionChart({ sources = fallbackSources, total = 12800 }) {
  const safeSources = sources.length ? sources : fallbackSources;
  const accumulated = safeSources.reduce((position, source) => {
    const start = position.total;
    const end = start + source.value;
    position.stops.push(`${source.color} ${start}% ${end}%`);
    position.total = end;
    return position;
  }, { total: 0, stops: [] });

  return (
    <section className="bw-dashboard-panel">
      <div className="bw-panel-heading">
        <div>
          <h2>Source Breakdown</h2>
          <p>Share of collected mentions</p>
        </div>
      </div>
      <div className="bw-source-chart-layout">
        <div
          className="bw-source-donut"
          aria-label="Source distribution chart"
          style={{ background: `conic-gradient(${accumulated.stops.join(", ")})` }}
        >
          <div className="bw-source-donut-center">
            <strong>{total.toLocaleString()}</strong>
            <span>mentions</span>
          </div>
        </div>
        <div className="bw-source-legend">
          {safeSources.map(source => (
            <div className="bw-source-legend-row" key={source.name}>
              <span className="bw-source-dot" style={{ background: source.color }} />
              <span>{source.name}</span>
              <strong>{source.value}%</strong>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
