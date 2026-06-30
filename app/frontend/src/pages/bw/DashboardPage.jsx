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
import {
  getBwSessionState,
  setBwSessionState,
} from "../../utils/bw/sessionCache";
import "./bwWorkspace.css";

const SOURCE_META = {
  google_news: { name: "Google News", color: "#5965a8" },
  newsapi: { name: "News API", color: "#2f8f72" },
  reddit: { name: "Reddit", color: "#d05b68" },
  youtube: { name: "YouTube", color: "#d39b39" },
};

const ENTITY_GROUPS = [
  ["company", "Brands"],
  ["products", "Products"],
  ["executives", "Executives"],
  ["campaigns", "Campaigns"],
  ["hashtags", "Hashtags"],
];

function normalized(value) {
  return String(value || "").trim().toLocaleLowerCase();
}

function optionalNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function parseMatchedEntities(mention) {
  if (mention._matchedEntities) return mention._matchedEntities;
  const fallback = {
    company: [],
    products: [],
    executives: [],
    campaigns: [],
    hashtags: [],
  };
  const raw = mention.matched_entities_json;
  if (!raw) return fallback;
  try {
    return { ...fallback, ...JSON.parse(raw) };
  } catch {
    return fallback;
  }
}

function mentionDateKey(mention) {
  const raw = mention.published_at || mention.collected_at;
  const date = raw ? new Date(raw) : null;
  if (!date || Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 10);
}

function shortDateLabel(dateKey) {
  if (!dateKey) return "";
  const date = new Date(`${dateKey}T00:00:00`);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function fullDateLabel(dateKey) {
  if (!dateKey) return "";
  const date = new Date(`${dateKey}T00:00:00`);
  return date.toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function sentimentValue(mention) {
  return normalized(mention.sentiment) || "neutral";
}

function confidenceBand(mention) {
  const label = normalized(mention.confidence_label);
  if (label) return label;
  const score = optionalNumber(mention.mention_confidence);
  if (score === null) return "unknown";
  if (score >= 80) return "high";
  if (score >= 50) return "medium";
  return "low";
}

function countConfiguredMatches(mentions, configuredValues, entityKey, selector = value => value) {
  return (configuredValues || [])
    .map(value => {
      const name = selector(value);
      const key = normalized(name);
      const matchedMentions = mentions.filter(mention => {
        const entities = parseMatchedEntities(mention);
        const entityMatches = (entities[entityKey] || []).some(entity => normalized(entity) === key);
        const keywordMatches = normalized(mention.keyword) === key;
        const textMatches = normalized(`${mention.title || ""} ${mention.content || ""}`).includes(key);
        return entityMatches || keywordMatches || (key.length > 3 && textMatches);
      });
      const scored = matchedMentions
        .map(mention => optionalNumber(mention.sentiment_score))
        .filter(score => score !== null);
      const positives = matchedMentions.filter(mention => sentimentValue(mention) === "positive").length;
      return {
        name,
        mentions: matchedMentions.length,
        positivePercent: matchedMentions.length
          ? Math.round((positives / matchedMentions.length) * 100)
          : 0,
        averageScore: scored.length
          ? scored.reduce((sum, score) => sum + score, 0) / scored.length
          : 0,
        averageScoreLabel: scored.length
          ? (scored.reduce((sum, score) => sum + score, 0) / scored.length).toFixed(2)
          : "n/a",
      };
    })
    .sort((left, right) => right.mentions - left.mentions);
}

function buildSentimentTrend(mentions) {
  const byDate = mentions.reduce((groups, mention) => {
    const key = mentionDateKey(mention);
    if (!key) return groups;
    groups[key] = groups[key] || {
      date: key,
      positive: 0,
      neutral: 0,
      negative: 0,
      mixed: 0,
      scores: [],
    };
    const sentiment = sentimentValue(mention);
    groups[key][sentiment] = (groups[key][sentiment] || 0) + 1;
    const score = optionalNumber(mention.sentiment_score);
    if (score !== null) groups[key].scores.push(score);
    return groups;
  }, {});
  return Object.values(byDate)
    .sort((left, right) => left.date.localeCompare(right.date))
    .map(point => ({
      ...point,
      label: shortDateLabel(point.date),
      fullLabel: fullDateLabel(point.date),
      shortLabel: shortDateLabel(point.date),
      averageScore: point.scores.length
        ? point.scores.reduce((sum, score) => sum + score, 0) / point.scores.length
        : 0,
    }));
}

function buildTopEntities(mentions) {
  const counts = {};
  mentions.forEach(mention => {
    const entities = parseMatchedEntities(mention);
    ENTITY_GROUPS.forEach(([key, label]) => {
      (entities[key] || []).forEach(entity => {
        const value = String(entity || "").trim();
        if (!value) return;
        const countKey = `${label}:${value}`;
        counts[countKey] = counts[countKey] || { label, value, count: 0 };
        counts[countKey].count += 1;
      });
    });
  });
  return Object.values(counts)
    .sort((left, right) => right.count - left.count)
    .slice(0, 8);
}

function buildEntityDistribution(mentions) {
  const counts = {
    Brands: 0,
    Products: 0,
    Executives: 0,
    Campaigns: 0,
    Hashtags: 0,
  };
  mentions.forEach(mention => {
    const entities = parseMatchedEntities(mention);
    ENTITY_GROUPS.forEach(([key, label]) => {
      counts[label] += (entities[key] || []).length;
    });
  });
  return Object.entries(counts).map(([label, count]) => ({ label, count }));
}

function latestBySentiment(mentions, sentiment) {
  return [...mentions]
    .filter(mention => sentimentValue(mention) === sentiment)
    .sort((left, right) => (
      new Date(right.published_at || right.collected_at || 0)
      - new Date(left.published_at || left.collected_at || 0)
    ))
    .slice(0, 3);
}

export default function DashboardPage() {
  const [workspace, setWorkspace] = React.useState(() => loadCompanyWorkspace());
  const [mentions, setMentions] = React.useState(() => {
    const companyName = getActiveCompanyName();
    return getBwSessionState("dashboard", companyName)?.mentions || [];
  });
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    const restoreCachedDashboard = (companyName, fallbackMessage = "") => {
      const cachedName = companyName || getActiveCompanyName();
      const session = getBwSessionState("dashboard", cachedName);
      const localWorkspace = loadCompanyWorkspace();
      const fallbackWorkspace = session?.workspace || (
        localWorkspace.companyName ? localWorkspace : null
      );
      if (!fallbackWorkspace) return false;
      setWorkspace(fallbackWorkspace);
      setMentions(session.mentions || []);
      setError(fallbackMessage);
      return true;
    };

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
        setBwSessionState("dashboard", savedWorkspace.companyName, {
          workspace: savedWorkspace,
          mentions: stored.mentions || [],
        });
      } catch (loadError) {
        if (!restoreCachedDashboard(companyName, "Showing cached BW dashboard data while backend is offline")) {
          setError(loadError.message);
        }
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

  const enrichedMentions = mentions.map(mention => ({
    ...mention,
    _matchedEntities: parseMatchedEntities(mention),
  }));
  const sourceCounts = enrichedMentions.reduce((counts, mention) => {
    counts[mention.source] = (counts[mention.source] || 0) + 1;
    return counts;
  }, {});
  const sentimentCounts = enrichedMentions.reduce((counts, mention) => {
    const sentiment = sentimentValue(mention);
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
  const averageSentimentScores = enrichedMentions
    .map(mention => optionalNumber(mention.sentiment_score))
    .filter(score => score !== null);
  const averageConfidenceScores = enrichedMentions
    .map(mention => optionalNumber(mention.mention_confidence))
    .filter(score => score !== null);
  const averageSentiment = averageSentimentScores.length
    ? averageSentimentScores.reduce((sum, score) => sum + score, 0) / averageSentimentScores.length
    : 0;
  const averageConfidence = averageConfidenceScores.length
    ? Math.round(averageConfidenceScores.reduce((sum, score) => sum + score, 0) / averageConfidenceScores.length)
    : 0;
  const topEntities = buildTopEntities(enrichedMentions);
  const topEntity = topEntities[0];
  const entityDistribution = buildEntityDistribution(enrichedMentions);
  const confidenceCounts = enrichedMentions.reduce((counts, mention) => {
    const band = confidenceBand(mention);
    counts[band] = (counts[band] || 0) + 1;
    return counts;
  }, {});
  const executiveMentionCount = entityDistribution.find(item => item.label === "Executives")?.count || 0;
  const campaignMentionCount = entityDistribution.find(item => item.label === "Campaigns")?.count || 0;
  const riskScore = negativePercent
    + (sentimentCounts.negative || 0)
    + (confidenceCounts.low || 0);
  const risk = riskScore >= 45 ? "Critical" : riskScore >= 28 ? "High" : riskScore >= 14 ? "Medium" : "Low";
  const kpis = [
    {
      label: "Mentions",
      value: enrichedMentions.length.toLocaleString(),
      note: `${Object.keys(sourceCounts).length} sources active`,
      tone: "neutral",
    },
    {
      label: "Sentiment",
      value: averageSentimentScores.length ? averageSentiment.toFixed(2) : "n/a",
      note: `${positivePercent}% positive / ${negativePercent}% negative`,
      tone: averageSentiment >= 0 ? "positive" : "negative",
    },
    {
      label: "Coverage",
      value: `${workspace.products?.length || 0} products`,
      note: `${executiveMentionCount} executive mentions, ${campaignMentionCount} campaign mentions`,
      tone: "competitor",
    },
    {
      label: "Risk Score",
      value: risk,
      note: `${sentimentCounts.negative || 0} negative, ${confidenceCounts.low || 0} low confidence`,
      tone: "risk",
    },
    {
      label: "Confidence",
      value: averageConfidenceScores.length ? `${averageConfidence}%` : "n/a",
      note: `${confidenceCounts.high || 0} high-confidence mentions`,
      tone: "reach",
    },
    {
      label: "Top Entity",
      value: topEntity?.value || "n/a",
      note: topEntity ? `${topEntity.count} matched ${topEntity.label.toLowerCase()}` : "No matched entities yet",
      tone: "competitor",
    },
  ];

  const products = (workspace.products || [])
    .filter(product => product.name)
    .slice(0, 8);
  const productPerformance = countConfiguredMatches(
    enrichedMentions,
    products,
    "products",
    product => product.name,
  );
  const sentimentTrend = buildSentimentTrend(enrichedMentions);
  const sourceDistribution = Object.entries(SOURCE_META)
    .map(([key, meta]) => ({
      ...meta,
      value: enrichedMentions.length
        ? Math.round(((sourceCounts[key] || 0) / enrichedMentions.length) * 100)
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
  const recentMentions = [...enrichedMentions]
    .sort((left, right) => (
      new Date(right.published_at || right.collected_at || 0)
      - new Date(left.published_at || left.collected_at || 0)
    ))
    .slice(0, 6);
  const recentPositive = latestBySentiment(enrichedMentions, "positive");
  const recentNeutral = latestBySentiment(enrichedMentions, "neutral");
  const recentNegative = latestBySentiment(enrichedMentions, "negative");
  const isCachedNotice = error.startsWith("Showing cached");
  const isBlockingError = Boolean(error) && !isCachedNotice;

  const openSourcesForTrendPoint = point => {
    if (!workspace.companyName || !point?.date) return;
    setBwSessionState("sources101-handoff", workspace.companyName, {
      date: point.date,
      label: point.fullLabel || point.label,
      source: "all",
      createdAt: new Date().toISOString(),
    });
    window.history.pushState({ page: "bw-sources" }, "", "/bw/sources");
    window.dispatchEvent(new PopStateEvent("popstate"));
  };

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
      {error && (
        <div className={`bw-save-notice ${isCachedNotice ? "" : "bw-save-notice-error"}`}>
          {error}
        </div>
      )}

      {!loading && !isBlockingError && !workspace.companyName && (
        <div className="bw-empty">No active company has been loaded yet.</div>
      )}

      {!loading && !isBlockingError && workspace.companyName && (
        <>
          <KPICards items={kpis} />

          <div className="bw-dashboard-grid bw-dashboard-grid-primary">
            <SentimentChart trend={sentimentTrend} onPointClick={openSourcesForTrendPoint} />
            <ProductPerformanceChart products={productPerformance} />
          </div>

          <div className="bw-dashboard-grid bw-dashboard-grid-secondary">
            <SourceDistributionChart sources={sourceDistribution} total={enrichedMentions.length} />
            <SentimentDistributionChart
              counts={sentimentCounts}
              total={classifiedSentiments}
            />
          </div>

          <div className="bw-dashboard-grid bw-dashboard-grid-secondary">
            <section className="bw-dashboard-panel">
              <div className="bw-panel-heading">
                <div>
                  <h2>Top Mentioned Entities</h2>
                  <p>Entities extracted from matched monitoring results</p>
                </div>
              </div>
              <div className="bw-entity-list">
                {topEntities.map(entity => (
                  <div className="bw-entity-row" key={`${entity.label}-${entity.value}`}>
                    <span>{entity.label}</span>
                    <strong>{entity.value}</strong>
                    <em>{entity.count}</em>
                  </div>
                ))}
                {!topEntities.length && (
                  <div className="bw-empty">No matched entities found yet.</div>
                )}
              </div>
            </section>

            <section className="bw-dashboard-panel">
              <div className="bw-panel-heading">
                <div>
                  <h2>Data Quality</h2>
                  <p>Confidence and entity coverage in stored mentions</p>
                </div>
              </div>
              <div className="bw-quality-grid">
                {["high", "medium", "low", "unknown"].map(label => (
                  <div className="bw-quality-card" key={label}>
                    <span>{label}</span>
                    <strong>{confidenceCounts[label] || 0}</strong>
                  </div>
                ))}
              </div>
              <div className="bw-entity-distribution">
                {entityDistribution.map(item => (
                  <div key={item.label}>
                    <span>{item.label}</span>
                    <strong>{item.count}</strong>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <div className="bw-dashboard-grid bw-dashboard-grid-summary">
            <WorkspaceSummaryCard workspace={workspace} />
            <section className="bw-dashboard-panel">
              <div className="bw-panel-heading">
                <div>
                  <h2>Monitoring Snapshot</h2>
                  <p>Compact overview of the active stored dataset</p>
                </div>
              </div>
              <dl className="bw-workspace-summary">
                <div><dt>Stored Mentions</dt><dd>{enrichedMentions.length}</dd></div>
                <div><dt>Sources Active</dt><dd>{Object.keys(sourceCounts).length}</dd></div>
                <div><dt>Avg Sentiment</dt><dd>{averageSentimentScores.length ? averageSentiment.toFixed(2) : "n/a"}</dd></div>
                <div><dt>Avg Confidence</dt><dd>{averageConfidenceScores.length ? `${averageConfidence}%` : "n/a"}</dd></div>
                <div><dt>Top Entity</dt><dd>{topEntity?.value || "n/a"}</dd></div>
              </dl>
            </section>
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
                  <small>
                    {mention.keyword}
                    {mention.confidence_label ? ` · ${mention.confidence_label} confidence` : ""}
                  </small>
                </a>
              ))}
              {!recentMentions.length && (
                <div className="bw-empty">No mentions stored for this company yet.</div>
              )}
            </div>
          </section>

          <section className="bw-dashboard-panel bw-dashboard-recent">
            <div className="bw-panel-heading">
              <div>
                <h2>Latest By Sentiment</h2>
                <p>Recent positive, neutral, and negative mentions</p>
              </div>
            </div>
            <div className="bw-sentiment-columns">
              <SentimentMentionColumn title="Positive" mentions={recentPositive} />
              <SentimentMentionColumn title="Neutral" mentions={recentNeutral} />
              <SentimentMentionColumn title="Negative" mentions={recentNegative} />
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function SentimentMentionColumn({ title, mentions }) {
  return (
    <div className="bw-sentiment-column">
      <h3>{title}</h3>
      {mentions.map(mention => (
        <a
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
      {!mentions.length && <p>No {title.toLocaleLowerCase()} mentions yet.</p>}
    </div>
  );
}
