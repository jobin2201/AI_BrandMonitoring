import React from "react";
import {
  BW_SOURCE_LABELS,
  getActiveCompanyName,
  loadCompanyWorkspace,
  saveCompanyWorkspace,
} from "../../../utils/bw/companyStorage";
import { getBwWorkspace } from "../../../api/bw/bwWorkspaceApi";
import "../bwWorkspace.css";

export default function WorkspaceOverviewPage() {
  const [workspace, setWorkspace] = React.useState(() => loadCompanyWorkspace());
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    const loadActiveWorkspace = async () => {
      const companyName = getActiveCompanyName() || workspace.companyName;
      if (!companyName) {
        setLoading(false);
        return;
      }
      try {
        const saved = await getBwWorkspace(companyName);
        setWorkspace(saveCompanyWorkspace(saved));
      } catch (loadError) {
        setError(loadError.message);
      } finally {
        setLoading(false);
      }
    };
    loadActiveWorkspace();
  }, []);

  React.useEffect(() => {
    const refresh = event => {
      setWorkspace(event.detail || loadCompanyWorkspace());
    };
    window.addEventListener("storage", refresh);
    window.addEventListener("bw-workspace-updated", refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener("bw-workspace-updated", refresh);
    };
  }, []);

  const configuredSources = Object.entries(workspace.sources || {})
    .filter(([, enabled]) => enabled)
    .map(([key]) => BW_SOURCE_LABELS[key])
    .filter(Boolean);

  const openBrandMonitoring = () => {
    window.history.pushState(
      { page: "bw-monitoring-brand" },
      "",
      "/bw/monitoring/brand",
    );
    window.dispatchEvent(new PopStateEvent("popstate"));
  };

  const metrics = [
    { label: "Company", value: workspace.companyName || "Not configured" },
    { label: "Industry", value: workspace.industry || "Not configured" },
    { label: "Brands", value: workspace.brands?.length || 0 },
    { label: "Products", value: workspace.products?.length || 0 },
    {
      label: "Executives",
      value: (workspace.executives?.length || 0)
        + (workspace.ceos?.filter(ceo => ceo.name).length || (workspace.ceo?.name ? 1 : 0)),
    },
    { label: "Campaigns", value: workspace.campaigns?.length || 0 },
    { label: "Keywords", value: workspace.keywords?.length || 0 },
  ];

  return (
    <div className="bw-page">
      <div className="bw-page-header">
        <div className="bw-eyebrow">BW / Brand Workspace</div>
        <h1 className="bw-heading">Workspace Overview</h1>
        <p className="bw-lead">
          Pure configuration overview for the active company workspace.
        </p>
      </div>

      {loading ? (
        <div className="bw-empty">Loading the active company workspace...</div>
      ) : error ? (
        <div className="bw-empty">{error}</div>
      ) : !workspace.companyName ? (
        <div className="bw-empty">
          No company has been configured yet. Complete Company Setup to populate this page.
        </div>
      ) : (
        <>
          <div className="bw-overview-grid">
            {metrics.map((metric, index) => (
              <div
                className="bw-stat"
                key={metric.label}
                style={{ animationDelay: `${index * 35}ms` }}
              >
                <div className="bw-stat-label">{metric.label}</div>
                <div className="bw-stat-value">{metric.value}</div>
              </div>
            ))}
          </div>

          <section className="bw-overview-band">
            <h2 className="bw-section-title">Configured Sources</h2>
            <p className="bw-section-copy">Sources enabled for this workspace configuration.</p>
            <div className="bw-chip-list">
              {configuredSources.length
                ? configuredSources.map(source => (
                  <span className="bw-chip" key={source}>{source}</span>
                ))
                : <span style={{ color: "#6b7280" }}>No sources configured.</span>}
            </div>
          </section>

          <section className="bw-overview-band">
            <h2 className="bw-section-title">Configuration Detail</h2>
            <p className="bw-section-copy">
              CEOs:{" "}
              {(workspace.ceos || []).map(ceo => ceo.name).filter(Boolean).join(", ")
                || workspace.ceo?.name
                || "Not configured"}{" "}
              | Hashtags:{" "}
              {workspace.hashtags?.length || 0} | Last saved:{" "}
              {workspace.updatedAt
                ? new Date(workspace.updatedAt).toLocaleString()
                : "Not available"}
            </p>
            <button
              className="bw-start-monitoring-button"
              type="button"
              onClick={openBrandMonitoring}
            >
              Start Monitoring
            </button>
            <div className="bw-monitoring-note">
              Opens the BW monitoring engine using this saved workspace.
            </div>
          </section>
        </>
      )}
    </div>
  );
}
