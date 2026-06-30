import React from "react";

const CHART_WIDTH = 720;
const CHART_HEIGHT = 240;
const RANGE_OPTIONS = [
  { value: "all", label: "All" },
  { value: "year", label: "Last year" },
  { value: "6m", label: "Last 6 months" },
  { value: "3m", label: "Last 3 months" },
  { value: "1m", label: "Last month" },
  { value: "1w", label: "Last week" },
];

const RANGE_DAYS = {
  year: 365,
  "6m": 183,
  "3m": 92,
  "1m": 31,
  "1w": 7,
};

function filterTrendByRange(trend, range) {
  if (range === "all" || !trend.length) return trend;
  const days = RANGE_DAYS[range];
  if (!days) return trend;
  const latest = new Date(`${trend[trend.length - 1].date}T00:00:00`).getTime();
  const cutoff = latest - (days - 1) * 24 * 60 * 60 * 1000;
  return trend.filter(point => {
    const time = new Date(`${point.date}T00:00:00`).getTime();
    return time >= cutoff;
  });
}

function pointObjectsFor(trend) {
  if (!trend.length) return [];
  const min = -1;
  const max = 1;
  return trend.map((point, index) => {
    const x = trend.length === 1 ? CHART_WIDTH / 2 : (index / (trend.length - 1)) * CHART_WIDTH;
    const y = CHART_HEIGHT - ((point.averageScore - min) / (max - min)) * CHART_HEIGHT;
    const previous = trend[index - 1];
    const delta = previous ? point.averageScore - previous.averageScore : 0;
    return { ...point, index, x, y, delta };
  });
}

function pointsFor(pointObjects) {
  return pointObjects.map(point => `${point.x},${point.y}`).join(" ");
}

function areaPointsFor(pointObjects) {
  if (!pointObjects.length) return "";
  const baseline = CHART_HEIGHT / 2;
  return [
    `0,${baseline}`,
    ...pointObjects.map(point => `${point.x},${point.y}`),
    `${CHART_WIDTH},${baseline}`,
  ].join(" ");
}

function legacyPointsFor(valuesToPlot) {
  const width = 720;
  const height = 220;
  const min = Math.min(...valuesToPlot) - 0.08;
  const max = Math.max(...valuesToPlot) + 0.08;
  if (max === min) {
    return valuesToPlot.map((_, index) => {
      const x = valuesToPlot.length === 1 ? width / 2 : (index / (valuesToPlot.length - 1)) * width;
      return `${x},${height / 2}`;
    }).join(" ");
  }
  return valuesToPlot.map((value, index) => {
    const x = valuesToPlot.length === 1 ? width / 2 : (index / (valuesToPlot.length - 1)) * width;
    const y = height - ((value - min) / (max - min)) * height;
    return `${x},${y}`;
  }).join(" ");
}

export default function SentimentChart({ trend = [], onPointClick }) {
  const [activeIndex, setActiveIndex] = React.useState(null);
  const [range, setRange] = React.useState("all");
  const visibleTrend = React.useMemo(() => filterTrendByRange(trend, range), [trend, range]);
  const pointObjects = pointObjectsFor(visibleTrend);
  const activePoint = activeIndex !== null ? pointObjects[activeIndex] : pointObjects[pointObjects.length - 1];
  const points = pointObjects.length ? pointsFor(pointObjects) : legacyPointsFor([0]);
  const areaPoints = areaPointsFor(pointObjects);
  const first = visibleTrend[0]?.averageScore ?? 0;
  const last = visibleTrend[visibleTrend.length - 1]?.averageScore ?? 0;
  const change = visibleTrend.length > 1 ? last - first : 0;
  const changeLabel = `${change >= 0 ? "+" : ""}${change.toFixed(2)}`;
  const activeMovement = activePoint
    ? activePoint.delta > 0
      ? `Improved by ${activePoint.delta.toFixed(2)} from previous day`
      : activePoint.delta < 0
        ? `Declined by ${Math.abs(activePoint.delta).toFixed(2)} from previous day`
        : "No change from previous day"
    : "No trend point selected";

  const handleMouseMove = event => {
    if (!pointObjects.length) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * CHART_WIDTH;
    const closest = pointObjects.reduce((best, point) => (
      Math.abs(point.x - x) < Math.abs(best.x - x) ? point : best
    ), pointObjects[0]);
    setActiveIndex(closest.index);
  };

  const openPointMentions = point => {
    if (!point || typeof onPointClick !== "function") return;
    onPointClick(point);
  };

  React.useEffect(() => {
    setActiveIndex(null);
  }, [range, trend]);

  return (
    <section className="bw-dashboard-panel bw-dashboard-panel-wide">
      <div className="bw-panel-heading">
        <div>
          <h2>Sentiment Trend</h2>
          <p>Average sentiment score from stored mentions</p>
        </div>
        <div className="bw-chart-controls">
          <label>
            Range
            <select value={range} onChange={event => setRange(event.target.value)}>
              {RANGE_OPTIONS.map(option => (
                <option value={option.value} key={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <div className={`bw-trend-badge ${change < 0 ? "bw-trend-badge-negative" : ""}`}>
            {changeLabel}
          </div>
        </div>
      </div>
      <div className="bw-sentiment-legend">
        <span><i className="bw-legend-score" /> Avg sentiment score</span>
        <span><i className="bw-legend-positive" /> Positive count</span>
        <span><i className="bw-legend-negative" /> Negative count</span>
      </div>
      <div
        className="bw-line-chart bw-line-chart-interactive"
        aria-label="Interactive average sentiment trend over time"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setActiveIndex(null)}
        onClick={() => openPointMentions(activePoint)}
      >
        <svg viewBox={`0 0 ${CHART_WIDTH} 270`} role="img">
          {[0, 60, 120, 180, 240].map(y => (
            <line key={y} x1="0" y1={y} x2={CHART_WIDTH} y2={y} className="bw-chart-gridline" />
          ))}
          <line x1="0" y1={CHART_HEIGHT / 2} x2={CHART_WIDTH} y2={CHART_HEIGHT / 2} className="bw-chart-baseline" />
          {areaPoints && <polygon points={areaPoints} className="bw-chart-area" />}
          <polyline points={points} className="bw-chart-line-shadow" />
          <polyline points={points} className="bw-chart-line" />
          {pointObjects.map(point => (
            <circle
              className={`bw-chart-point ${activePoint?.index === point.index ? "active" : ""}`}
              cx={point.x}
              cy={point.y}
              r={activePoint?.index === point.index ? 7 : 4}
              tabIndex="0"
              key={point.date}
              role="button"
              aria-label={`${point.label}: sentiment ${point.averageScore.toFixed(2)}`}
              onFocus={() => setActiveIndex(point.index)}
              onMouseEnter={() => setActiveIndex(point.index)}
              onClick={event => {
                event.stopPropagation();
                openPointMentions(point);
              }}
            />
          ))}
          {activePoint && (
            <line
              x1={activePoint.x}
              y1="0"
              x2={activePoint.x}
              y2={CHART_HEIGHT}
              className="bw-chart-hover-line"
            />
          )}
        </svg>
        {activePoint && (
          <div
            className="bw-chart-tooltip"
            style={{
              left: `${Math.min(82, Math.max(10, (activePoint.x / CHART_WIDTH) * 100))}%`,
              top: `${Math.min(72, Math.max(10, (activePoint.y / CHART_HEIGHT) * 100))}%`,
            }}
          >
            <strong>{activePoint.fullLabel || activePoint.label}</strong>
            <span>Avg score: {activePoint.averageScore.toFixed(2)}</span>
            <span>Positive: {activePoint.positive || 0}</span>
            <span>Neutral: {activePoint.neutral || 0}</span>
            <span>Negative: {activePoint.negative || 0}</span>
            <em>{activeMovement}</em>
            <button
              type="button"
              onClick={event => {
                event.stopPropagation();
                openPointMentions(activePoint);
              }}
            >
              View exact mentions
            </button>
          </div>
        )}
      </div>
      <div className="bw-chart-axis">
        <span>Negative zone</span>
        <span>{visibleTrend[0]?.fullLabel || "No data"}</span>
        <span>{visibleTrend[visibleTrend.length - 1]?.fullLabel || "Today"}</span>
        <span>Positive zone</span>
      </div>
      <div className="bw-trend-bars" aria-label="Daily sentiment counts">
        {visibleTrend.map((point, index) => (
          <button
            className={`bw-trend-bar-day ${activePoint?.date === point.date ? "active" : ""}`}
            type="button"
            onClick={() => {
              setActiveIndex(index);
              openPointMentions(point);
            }}
            onFocus={() => setActiveIndex(index)}
            key={point.date}
          >
            <span>{point.shortLabel}</span>
            <div>
              <i className="bw-trend-positive" style={{ height: `${Math.max(3, point.positive * 7)}px` }} />
              <i className="bw-trend-neutral" style={{ height: `${Math.max(3, point.neutral * 7)}px` }} />
              <i className="bw-trend-negative" style={{ height: `${Math.max(3, point.negative * 7)}px` }} />
            </div>
          </button>
        ))}
        {!visibleTrend.length && <p className="bw-chart-empty">No dated sentiment mentions for this range.</p>}
      </div>
    </section>
  );
}
