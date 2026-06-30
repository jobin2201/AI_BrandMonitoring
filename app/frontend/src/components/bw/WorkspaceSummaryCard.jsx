import React from "react";

export default function WorkspaceSummaryCard({ workspace }) {
  return (
    <section className="bw-dashboard-panel">
      <div className="bw-panel-heading">
        <div>
          <h2>Workspace Summary</h2>
          <p>Current company configuration</p>
        </div>
      </div>
      <dl className="bw-workspace-summary">
        <div><dt>Company</dt><dd>{workspace.companyName || "Not configured"}</dd></div>
        <div><dt>Industry</dt><dd>{workspace.industry || "Not configured"}</dd></div>
        <div><dt>Brands</dt><dd>{workspace.brands?.length || 0}</dd></div>
        <div><dt>Products</dt><dd>{workspace.products?.length || 0}</dd></div>
        <div><dt>Executives</dt><dd>{(workspace.ceos?.length || 0) + (workspace.executives?.length || 0)}</dd></div>
        <div><dt>Campaigns</dt><dd>{workspace.campaigns?.length || 0}</dd></div>
        <div><dt>Hashtags</dt><dd>{workspace.hashtags?.length || 0}</dd></div>
        <div><dt>Keywords</dt><dd>{workspace.keywords?.length || 0}</dd></div>
      </dl>
    </section>
  );
}
