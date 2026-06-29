import React from "react";
import {
  getBwWorkspace,
  listBwWorkspaces,
} from "../../api/bw/bwWorkspaceApi";
import { getBwMonitoringMentions } from "../../api/bw/bwMonitoringApi";
import { getActiveCompanyName } from "../../utils/bw/companyStorage";
import "./bwWorkspace.css";

const SOURCE_LABELS = {
  google_news: "Google News",
  newsapi: "News API",
  reddit: "Reddit",
  youtube: "YouTube",
};

const STOP_WORDS = new Set([
  "about", "after", "again", "against", "also", "and", "are", "been", "before",
  "being", "between", "but", "can", "company", "could", "for", "from", "has",
  "have", "into", "its", "more", "new", "not", "over", "says", "that", "the",
  "their", "this", "through", "under", "was", "were", "will", "with", "your",
]);

export default function IntelligenceCenterPage({ sourceFilters, dateFilters }) {
  const [workspace, setWorkspace] = React.useState(null);
  const [mentions, setMentions] = React.useState([]);
  const [competitorProfiles, setCompetitorProfiles] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    const load = async () => {
      const companyName = getActiveCompanyName();
      if (!companyName) {
        setError("Load a company in Brand Monitoring first.");
        setLoading(false);
        return;
      }
      try {
        const [savedWorkspace, stored, companyList] = await Promise.all([
          getBwWorkspace(companyName),
          getBwMonitoringMentions(companyName),
          listBwWorkspaces(),
        ]);
        const others = (companyList.companies || [])
          .filter(company => company.company_name.toLocaleLowerCase() !== companyName.toLocaleLowerCase());
        const profiles = await Promise.all(
          others.map(company => getBwWorkspace(company.company_name).catch(() => null)),
        );
        setWorkspace(savedWorkspace);
        setMentions(stored.mentions || []);
        setCompetitorProfiles(profiles.filter(Boolean));
      } catch (loadError) {
        setError(loadError.message);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const filteredMentions = mentions.filter(mention => (
    sourceFilters[mention.source] !== false
    && isWithinDateRange(mention, dateFilters)
  ));
  const splitTimestamp = calculateSplitTimestamp(filteredMentions);
  const productRows = buildEntityRows(
    workspace?.products || [],
    filteredMentions,
    product => product.name,
    splitTimestamp,
  );
  const executiveRows = buildEntityRows(
    [...(workspace?.ceos || []), ...(workspace?.executives || [])],
    filteredMentions,
    executive => executive.name,
    splitTimestamp,
  );
  const sourceRows = buildSourceRows(filteredMentions);
  const competitorRows = buildCompetitorRows(competitorProfiles, filteredMentions);
  const keywordRows = countValues(filteredMentions.map(mention => mention.keyword), 10);
  const hashtagRows = countValues(
    filteredMentions.map(mention => mention.keyword).filter(keyword => String(keyword || "").startsWith("#")),
    10,
  );
  const phraseRows = buildPhraseRows(filteredMentions);

  return (
    <div className="bw-page">
      <div className="bw-page-header">
        <div className="bw-eyebrow">BW / Intelligence</div>
        <h1 className="bw-heading">Intelligence Center</h1>
        <p className="bw-lead">
          Relationships, sentiment patterns, co-occurrence, and topics from stored monitoring data.
        </p>
      </div>

      {loading && <div className="bw-empty">Building intelligence relationships...</div>}
      {error && <div className="bw-save-notice bw-save-notice-error">{error}</div>}

      {!loading && !error && workspace && (
        <>
          <div className="bw-intelligence-summary">
            <SummaryMetric label="Company" value={workspace.companyName} />
            <SummaryMetric label="Filtered Mentions" value={filteredMentions.length} />
            <SummaryMetric label="Products Tracked" value={productRows.length} />
            <SummaryMetric label="Executives Tracked" value={executiveRows.length} />
          </div>

          <div className="bw-intelligence-grid">
            <IntelligenceTable
              title="Product Intelligence"
              description="Volume, sentiment, and movement for configured products."
              columns={["Product", "Mentions", "Positive", "Negative", "Trend"]}
              rows={productRows.map(row => [
                row.name,
                row.mentions,
                `${row.positivePercent}%`,
                `${row.negativePercent}%`,
                <TrendBadge trend={row.trend} />,
              ])}
              empty="No configured products appear in the filtered mentions."
            />

            <IntelligenceTable
              title="Executive Intelligence"
              description="Coverage and sentiment for configured CEOs and executives."
              columns={["Executive", "Mentions", "Positive", "Negative", "Trend"]}
              rows={executiveRows.map(row => [
                row.name,
                row.mentions,
                `${row.positivePercent}%`,
                `${row.negativePercent}%`,
                <TrendBadge trend={row.trend} />,
              ])}
              empty="No configured executives appear in the filtered mentions."
            />

            <IntelligenceTable
              title="Source Intelligence"
              description="Mention volume and sentiment by collection source."
              columns={["Source", "Mentions", "Positive", "Negative", "Neutral"]}
              rows={sourceRows.map(row => [
                row.name,
                row.mentions,
                `${row.positivePercent}%`,
                `${row.negativePercent}%`,
                `${row.neutralPercent}%`,
              ])}
              empty="No source data matches the selected filters."
            />

            <IntelligenceTable
              title="Competitor Co-occurrence"
              description="Other saved company workspaces mentioned in the active company’s evidence."
              columns={["Company", "Co-occurrences", "Recent headline"]}
              rows={competitorRows.map(row => [
                row.name,
                row.mentions,
                row.headline || "No headline",
              ])}
              empty="No other saved company workspace is mentioned in the filtered evidence."
            />
          </div>

          <section className="bw-section bw-topic-intelligence">
            <div className="bw-panel-heading">
              <div>
                <h2>Topic Intelligence</h2>
                <p>Top monitored terms, hashtags, and repeated headline phrases.</p>
              </div>
            </div>
            <div className="bw-topic-columns">
              <RankedList title="Top Keywords" items={keywordRows} />
              <RankedList title="Top Hashtags" items={hashtagRows} />
              <RankedList title="Top Phrases" items={phraseRows} />
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function SummaryMetric({ label, value }) {
  return (
    <div className="bw-stat">
      <div className="bw-stat-label">{label}</div>
      <div className="bw-stat-value">{value}</div>
    </div>
  );
}

function IntelligenceTable({ title, description, columns, rows, empty }) {
  return (
    <section className="bw-section bw-intelligence-panel">
      <div className="bw-panel-heading">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
      </div>
      {rows.length ? (
        <div className="bw-table-wrap">
          <table className="bw-intelligence-table">
            <thead>
              <tr>{columns.map(column => <th key={column}>{column}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`${title}-${rowIndex}`}>
                  {row.map((value, columnIndex) => (
                    <td key={`${title}-${rowIndex}-${columnIndex}`}>{value}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <div className="bw-section-copy bw-intelligence-empty">{empty}</div>}
    </section>
  );
}

function TrendBadge({ trend }) {
  return <span className={`bw-intelligence-trend bw-trend-${trend}`}>{trend}</span>;
}

function RankedList({ title, items }) {
  return (
    <div>
      <h3>{title}</h3>
      <div className="bw-ranked-list">
        {items.map(([label, count], index) => (
          <div key={`${title}-${label}`}>
            <span>{index + 1}</span>
            <strong>{label}</strong>
            <em>{count}</em>
          </div>
        ))}
        {!items.length && <p>No matching data.</p>}
      </div>
    </div>
  );
}

function buildEntityRows(entities, mentions, nameSelector, splitTimestamp) {
  return entities
    .map(entity => {
      const name = String(nameSelector(entity) || "").trim();
      const matches = mentions.filter(mention => mentionMatches(mention, name));
      return name && matches.length
        ? { name, ...sentimentMetrics(matches), trend: calculateTrend(matches, splitTimestamp) }
        : null;
    })
    .filter(Boolean)
    .sort((left, right) => right.mentions - left.mentions);
}

function buildSourceRows(mentions) {
  const grouped = groupBy(mentions, mention => mention.source || "unknown");
  return Object.entries(grouped)
    .map(([source, items]) => ({
      name: SOURCE_LABELS[source] || source,
      ...sentimentMetrics(items),
    }))
    .sort((left, right) => right.mentions - left.mentions);
}

function buildCompetitorRows(profiles, mentions) {
  return profiles
    .map(profile => {
      const terms = [profile.companyName, ...(profile.brands || [])]
        .map(term => String(term || "").trim())
        .filter(term => term.length >= 3);
      const matches = mentions.filter(mention => {
        const text = mentionText(mention);
        return terms.some(term => containsTerm(text, term));
      });
      return matches.length
        ? {
          name: profile.companyName,
          mentions: matches.length,
          headline: matches[0].title || matches[0].content || "",
        }
        : null;
    })
    .filter(Boolean)
    .sort((left, right) => right.mentions - left.mentions);
}

function sentimentMetrics(items) {
  const counts = items.reduce((result, item) => {
    const sentiment = String(item.sentiment || "neutral").toLocaleLowerCase();
    result[sentiment] = (result[sentiment] || 0) + 1;
    return result;
  }, {});
  const total = items.length || 1;
  return {
    mentions: items.length,
    positivePercent: Math.round(((counts.positive || 0) / total) * 100),
    negativePercent: Math.round(((counts.negative || 0) / total) * 100),
    neutralPercent: Math.round((((counts.neutral || 0) + (counts.mixed || 0)) / total) * 100),
  };
}

function calculateSplitTimestamp(mentions) {
  const timestamps = mentions
    .map(mentionTimestamp)
    .filter(Number.isFinite)
    .sort((left, right) => left - right);
  if (timestamps.length < 2) return null;
  return timestamps[Math.floor(timestamps.length / 2)];
}

function calculateTrend(items, splitTimestamp) {
  if (!splitTimestamp || items.length < 2) return "stable";
  const recent = items.filter(item => mentionTimestamp(item) >= splitTimestamp).length;
  const older = items.length - recent;
  if (recent > older * 1.2) return "rising";
  if (older > recent * 1.2) return "declining";
  return "stable";
}

function buildPhraseRows(mentions) {
  const phrases = [];
  mentions.forEach(mention => {
    const words = String(mention.title || mention.content || "")
      .toLocaleLowerCase()
      .replace(/[^a-z0-9\s]/g, " ")
      .split(/\s+/)
      .filter(word => word.length > 2 && !STOP_WORDS.has(word));
    for (let index = 0; index < words.length - 1; index += 1) {
      phrases.push(`${words[index]} ${words[index + 1]}`);
    }
  });
  return countValues(phrases, 10);
}

function countValues(values, limit) {
  const counts = values.reduce((result, value) => {
    const label = String(value || "").trim();
    if (label) result[label] = (result[label] || 0) + 1;
    return result;
  }, {});
  return Object.entries(counts)
    .sort((left, right) => right[1] - left[1])
    .slice(0, limit);
}

function groupBy(items, selector) {
  return items.reduce((result, item) => {
    const key = selector(item);
    if (!result[key]) result[key] = [];
    result[key].push(item);
    return result;
  }, {});
}

function mentionMatches(mention, term) {
  if (!term) return false;
  if (String(mention.keyword || "").toLocaleLowerCase() === term.toLocaleLowerCase()) return true;
  return containsTerm(mentionText(mention), term);
}

function mentionText(mention) {
  return `${mention.title || ""} ${mention.content || ""}`.toLocaleLowerCase();
}

function containsTerm(text, term) {
  const normalizedTerm = term.toLocaleLowerCase();
  return text.includes(normalizedTerm);
}

function mentionTimestamp(mention) {
  return new Date(mention.published_at || mention.collected_at || "").getTime();
}

function isWithinDateRange(mention, dateFilters) {
  const timestamp = mentionTimestamp(mention);
  if (!Number.isFinite(timestamp)) return !dateFilters.startDate;
  if (dateFilters.startDate) {
    const start = new Date(`${dateFilters.startDate}T00:00:00`).getTime();
    if (timestamp < start) return false;
  }
  if (dateFilters.endDate) {
    const end = new Date(`${dateFilters.endDate}T23:59:59.999`).getTime();
    if (timestamp > end) return false;
  }
  return true;
}
