import React from "react";

const META = {
  positive: { name: "Positive", color: "#2f8f72" },
  negative: { name: "Negative", color: "#d05b68" },
  mixed: { name: "Mixed", color: "#d39b39" },
  neutral: { name: "Neutral", color: "#8a91a1" },
};

export default function SentimentDistributionChart({ counts, total }) {
  const items = Object.entries(META).map(([key, meta]) => ({
    ...meta,
    count: counts[key] || 0,
    value: total ? Math.round(((counts[key] || 0) / total) * 100) : 0,
  }));
  const chartItems = items.filter(item => item.value > 0);
  const safeItems = chartItems.length
    ? chartItems
    : [{ name: "No sentiment", color: "#d9dde5", count: 0, value: 100 }];
  const accumulated = safeItems.reduce((position, item) => {
    const start = position.total;
    const end = start + item.value;
    position.stops.push(`${item.color} ${start}% ${end}%`);
    position.total = end;
    return position;
  }, { total: 0, stops: [] });

  return (
    <section className="bw-dashboard-panel">
      <div className="bw-panel-heading">
        <div>
          <h2>Sentiment Breakdown</h2>
          <p>Positive, negative, mixed, and neutral mentions</p>
        </div>
      </div>
      <div className="bw-source-chart-layout">
        <div
          className="bw-source-donut"
          aria-label="Sentiment distribution chart"
          style={{ background: `conic-gradient(${accumulated.stops.join(", ")})` }}
        >
          <div className="bw-source-donut-center">
            <strong>{total.toLocaleString()}</strong>
            <span>classified</span>
          </div>
        </div>
        <div className="bw-source-legend">
          {items.map(item => (
            <div className="bw-source-legend-row" key={item.name}>
              <span className="bw-source-dot" style={{ background: item.color }} />
              <span>{item.name}</span>
              <strong>{item.value}% ({item.count})</strong>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
