import React from "react";

const values = [48, 52, 50, 58, 61, 57, 63, 66, 64, 70, 74, 72];

function pointsFor(valuesToPlot) {
  const width = 720;
  const height = 220;
  const min = Math.min(...valuesToPlot) - 5;
  const max = Math.max(...valuesToPlot) + 5;
  return valuesToPlot.map((value, index) => {
    const x = (index / (valuesToPlot.length - 1)) * width;
    const y = height - ((value - min) / (max - min)) * height;
    return `${x},${y}`;
  }).join(" ");
}

export default function SentimentChart() {
  const points = pointsFor(values);

  return (
    <section className="bw-dashboard-panel bw-dashboard-panel-wide">
      <div className="bw-panel-heading">
        <div>
          <h2>Sentiment Trend</h2>
          <p>Positive mentions over the last 30 days</p>
        </div>
        <div className="bw-trend-badge">+9.4%</div>
      </div>
      <div className="bw-line-chart" aria-label="Positive sentiment trend rising over 30 days">
        <svg viewBox="0 0 720 250" role="img">
          {[30, 85, 140, 195].map(y => (
            <line key={y} x1="0" y1={y} x2="720" y2={y} className="bw-chart-gridline" />
          ))}
          <polyline points={points} className="bw-chart-line-shadow" />
          <polyline points={points} className="bw-chart-line" />
        </svg>
      </div>
      <div className="bw-chart-axis">
        <span>30 days ago</span>
        <span>Today</span>
      </div>
    </section>
  );
}
