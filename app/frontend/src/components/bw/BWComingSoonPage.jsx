import React from "react";

export default function BWComingSoonPage({ section, title }) {
  return (
    <div className="bw-page">
      <div className="bw-page-header">
        <div className="bw-eyebrow">BW / {section}</div>
        <h1 className="bw-heading">{title}</h1>
        <p className="bw-lead">This workspace route is ready for its next implementation phase.</p>
      </div>
      <div className="bw-empty">No processing logic has been added to this page yet.</div>
    </div>
  );
}
