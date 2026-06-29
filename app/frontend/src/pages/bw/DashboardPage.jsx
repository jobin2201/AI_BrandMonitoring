import React from "react";
import KPICards from "../../components/bw/KPICards";
import ProductPerformanceChart from "../../components/bw/ProductPerformanceChart";
import SentimentChart from "../../components/bw/SentimentChart";
import SourceDistributionChart from "../../components/bw/SourceDistributionChart";
import SentimentDistributionChart from "../../components/bw/SentimentDistributionChart";
import WorkspaceSummaryCard from "../../components/bw/WorkspaceSummaryCard";
import {
  getActiveCompanyName,
  loadCompanyWorkspace,
} from "../../utils/bw/companyStorage";
import { getBwWorkspace } from "../../api/bw/bwWorkspaceApi";
import { getBwMonitoringMentions } from "../../api/bw/bwMonitoringApi";
import "./bwWorkspace.css";

const SOURCE_META = {
  google_news: { name: "Google News", color: "#5965a8" },
  newsapi: { name: "News API", color: "#2f8f72" },
  reddit: { name: "Reddit", color: "#d05b68" },
  youtube: { name: "YouTube", color: "#d39b39" },
};

export default function DashboardPage() {
  const [workspace, setWorkspace] = React.useState(() => loadCompanyWorkspace());
  const [mentions, setMentions] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    const loadDashboard = async companyOverride => {
      const companyName = companyOverride || getActiveCompanyName();
      if (!companyName) {
        setLoading(false);
        return;
      }
      setLoading(true);
      setError("");
      try {
        const [savedWorkspace, stored] = await Promise.all([
          getBwWorkspace(companyName),
          getBwMonitoringMentions(companyName),
        ]);
        setWorkspace(savedWorkspace);
        setMentions(stored.mentions || []);
      } catch (loadError) {
        setError(loadError.message);
      } finally {
        setLoading(false);
      }
    };

    const refresh = event => {
      const companyName = event.detail?.companyName || getActiveCompanyName();
      loadDashboard(companyName);
    };
    loadDashboard();
    window.addEventListener("bw-active-company-changed", refresh);
    window.addEventListener("bw-workspace-updated", refresh);
    return () => {
      window.removeEventListener("bw-active-company-changed", refresh);
      window.removeEventListener("bw-workspace-updated", refresh);
    };
  }, []);

  const sourceCounts = mentions.reduce((counts, mention) => {
    counts[mention.source] = (counts[mention.source] || 0) + 1;
    return counts;
  }, {});
  const sentimentCounts = mentions.reduce((counts, mention) => {
    const sentiment = String(mention.sentiment || "").toLocaleLowerCase();
    if (sentiment) counts[sentiment] = (counts[sentiment] || 0) + 1;
    return counts;
  }, {});
  const classifiedSentiments = Object.values(sentimentCounts).reduce((sum, count) => sum + count, 0);
  const positivePercent = classifiedSentiments
    ? Math.round(((sentimentCounts.positive || 0) / classifiedSentiments) * 100)
    : 0;
  const negativePercent = classifiedSentiments
    ? Math.round(((sentimentCounts.negative || 0) / classifiedSentiments) * 100)
    : 0;
  const risk = negativePercent >= 35 ? "High" : negativePercent >= 15 ? "Medium" : "Low";
  const kpis = [
    { label: "Mentions", value: mentions.length.toLocaleString(), note: "Stored monitoring results", tone: "neutral" },
    { label: "Positive", value: `${positivePercent}%`, note: `${sentimentCounts.positive || 0} classified positive`, tone: "positive" },
    { label: "Negative", value: `${negativePercent}%`, note: `${sentimentCounts.negative || 0} classified negative`, tone: "negative" },
    { label: "Sources", value: Object.keys(sourceCounts).length, note: "Active result sources", tone: "reach" },
    { label: "Products", value: workspace.products?.length || 0, note: "Configured products", tone: "competitor" },
    { label: "Risk Score", value: risk, note: classifiedSentiments ? "Based on classified sentiment" : "Awaiting sentiment data", tone: "risk" },
  ];

  const products = (workspace.products || [])
    .filter(product => product.name)
    .slice(0, 5)
    .map(product => ({
      name: product.name,
      mentions: mentions.filter(mention => (
        String(mention.keyword || "").toLocaleLowerCase()
          === product.name.toLocaleLowerCase()
      )).length,
    }));
  const sourceDistribution = Object.entries(SOURCE_META)
    .map(([key, meta]) => ({
      ...meta,
      value: mentions.length
        ? Math.round(((sourceCounts[key] || 0) / mentions.length) * 100)
        : 0,
    }))
    .filter(source => source.value > 0);
  if (!sourceDistribution.length) {
    sourceDistribution.push({
      name: "No mentions",
      value: 100,
      color: "#d9dde5",
    });
  }
  const recentMentions = [...mentions]
    .sort((left, right) => (
      new Date(right.published_at || right.collected_at || 0)
      - new Date(left.published_at || left.collected_at || 0)
    ))
    .slice(0, 6);

  return (
    <div className="bw-page bw-dashboard-page">
      <div className="bw-dashboard-header bw-page-header">
        <div>
          <div className="bw-eyebrow">BW / Executive Overview</div>
          <h1 className="bw-heading">Dashboard</h1>
          <p className="bw-lead">
            {workspace.companyName
              ? `${workspace.companyName} monitoring overview from stored BW results.`
              : "Load a company in Brand Monitoring to populate this dashboard."}
          </p>
        </div>
        <div className="bw-dashboard-period">
          <span>Reporting period</span>
          <strong>Last 30 days</strong>
        </div>
      </div>

      {loading && <div className="bw-empty">Loading the active company dashboard...</div>}
      {error && <div className="bw-save-notice bw-save-notice-error">{error}</div>}

      {!loading && !error && !workspace.companyName && (
        <div className="bw-empty">No active company has been loaded yet.</div>
      )}

      {!loading && !error && workspace.companyName && (
        <>
          <KPICards items={kpis} />

          <div className="bw-dashboard-grid bw-dashboard-grid-primary">
            <SentimentChart />
            <ProductPerformanceChart products={products} />
          </div>

          <div className="bw-dashboard-grid bw-dashboard-grid-secondary">
            <SourceDistributionChart sources={sourceDistribution} total={mentions.length} />
            <SentimentDistributionChart
              counts={sentimentCounts}
              total={classifiedSentiments}
            />
          </div>

          <div className="bw-dashboard-grid bw-dashboard-grid-summary">
            <WorkspaceSummaryCard workspace={workspace} />
          </div>

          <section className="bw-dashboard-panel bw-dashboard-recent">
            <div className="bw-panel-heading">
              <div>
                <h2>Recent Mentions</h2>
                <p>Latest stored results for the active company</p>
              </div>
            </div>
            <div className="bw-dashboard-mention-list">
              {recentMentions.map(mention => (
                <a
                  className="bw-dashboard-mention"
                  href={mention.url || undefined}
                  target={mention.url ? "_blank" : undefined}
                  rel={mention.url ? "noreferrer" : undefined}
                  key={mention.mention_id}
                >
                  <span>{SOURCE_META[mention.source]?.name || mention.source}</span>
                  <strong>{mention.title || mention.content || "Untitled mention"}</strong>
                  <small>{mention.keyword}</small>
                </a>
              ))}
              {!recentMentions.length && (
                <div className="bw-empty">No mentions stored for this company yet.</div>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
