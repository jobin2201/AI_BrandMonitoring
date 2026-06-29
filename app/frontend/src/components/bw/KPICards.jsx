import React from "react";

export default function KPICards({ items }) {
  return (
    <div className="bw-kpi-grid">
      {items.map((item, index) => (
        <article
          className={`bw-kpi-card bw-kpi-${item.tone || "neutral"}`}
          key={item.label}
          style={{ animationDelay: `${index * 35}ms` }}
        >
          <div className="bw-kpi-label">{item.label}</div>
          <div className="bw-kpi-value">{item.value}</div>
          <div className="bw-kpi-note">{item.note}</div>
        </article>
      ))}
    </div>
  );
}
