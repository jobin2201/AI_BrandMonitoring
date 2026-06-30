import React from "react";
import { getActiveCompanyName } from "../../utils/bw/companyStorage";
import { getBwWorkspace } from "../../api/bw/bwWorkspaceApi";
import { getBwMonitoringMentions } from "../../api/bw/bwMonitoringApi";
import ArticleCard from "../cards/ArticleCard";
import {
  NewsApiIcon,
  RedditIcon,
  YouTubeIcon,
} from "../icons/SourceIcons";
import { GoogleNewsIcon } from "../icons/GoogleNewsIcon";
import {
  getBwSessionState,
  setBwSessionState,
} from "../../utils/bw/sessionCache";

export const BW_SOURCE_OPTIONS = [
  { value: "all", label: "All Mentions" },
  { value: "google_news", label: "Google News" },
  { value: "newsapi", label: "News API" },
  { value: "reddit", label: "Reddit" },
  { value: "youtube", label: "YouTube" },
];

const SOURCE_LABELS = Object.fromEntries(
  BW_SOURCE_OPTIONS.map(option => [option.value, option.label]),
);

const SOURCE_ICONS = {
  google_news: GoogleNewsIcon,
  newsapi: NewsApiIcon,
  reddit: RedditIcon,
  youtube: YouTubeIcon,
};

const SENTIMENT_LABELS = ["positive", "negative", "mixed", "neutral"];

function normalized(value) {
  return String(value || "").trim().toLocaleLowerCase();
}

function matchesConfiguredValue(keyword, values, selector = value => value) {
  const key = normalized(keyword);
  return (values || []).find(value => normalized(selector(value)) === key) || null;
}

function classifyMention(mention, workspace) {
  const product = matchesConfiguredValue(mention.keyword, workspace.products, value => value.name);
  const executive = matchesConfiguredValue(
    mention.keyword,
    [...(workspace.ceos || []), ...(workspace.executives || [])],
    value => value.name,
  );
  const campaign = matchesConfiguredValue(mention.keyword, workspace.campaigns);
  const hashtag = matchesConfiguredValue(mention.keyword, workspace.hashtags);
  const brand = matchesConfiguredValue(mention.keyword, workspace.brands);
  return {
    ...mention,
    dimension: product
      ? "product"
      : executive
        ? "executive"
        : campaign
          ? "campaign"
          : brand
            ? "brand"
            : "company",
    productName: product?.name || "",
    executiveName: executive?.name || "",
    campaignName: campaign || "",
    hashtagName: hashtag || "",
    brandName: brand || "",
    sentimentValue: normalized(mention.sentiment) || "neutral",
    sentimentScore: optionalNumber(mention.sentiment_score),
    sentimentConfidence: optionalNumber(mention.sentiment_confidence),
    emotionConfidence: optionalNumber(mention.emotion_confidence),
    keywordType: mention.keyword_type || "",
    mentionConfidence: optionalNumber(mention.mention_confidence),
    confidenceLabel: mention.confidence_label || "",
    matchedBecause: mention.matched_because || "",
    runId: mention.run_id || "",
  };
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

export default function MentionsExplorer({
  initialSource = "all",
  showSourceTabs = true,
  title = "Mentions101",
  description = "Search, filter, and investigate stored workspace mentions.",
  sourceFilters = {
    google_news: true,
    newsapi: true,
    reddit: true,
    youtube: true,
  },
  dateFilters = { startDate: "", endDate: "" },
  showInlineDateFilter = false,
}) {
  const [workspace, setWorkspace] = React.useState(null);
  const [mentions, setMentions] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [localDateFilters, setLocalDateFilters] = React.useState(dateFilters);
  const [dateFilterNotice, setDateFilterNotice] = React.useState("");
  const [filters, setFilters] = React.useState({
    query: "",
    company: "",
    brand: "",
    product: "",
    source: initialSource,
    sentiment: "",
    executive: "",
    campaign: "",
    hashtag: "",
  });

  React.useEffect(() => {
    const load = async () => {
      const companyName = getActiveCompanyName();
      if (!companyName) {
        setError("Complete Company Setup and run Brand Monitoring first.");
        setLoading(false);
        return;
      }
      try {
        const [savedWorkspace, stored] = await Promise.all([
          getBwWorkspace(companyName),
          getBwMonitoringMentions(companyName),
        ]);
        setWorkspace(savedWorkspace);
        setMentions((stored.mentions || []).map(item => classifyMention(item, savedWorkspace)));
        const session = getBwSessionState(`mentions:${title}`, savedWorkspace.companyName);
        const handoff = title === "Sources101"
          ? getBwSessionState("sources101-handoff", savedWorkspace.companyName)
          : null;
        if (handoff?.date) {
          setLocalDateFilters({
            startDate: handoff.date,
            endDate: handoff.date,
          });
          setDateFilterNotice(`Showing exact mentions for ${handoff.label || handoff.date} selected from Dashboard.`);
        } else {
          setLocalDateFilters(dateFilters);
          setDateFilterNotice("");
        }
        setFilters(session?.filters || (current => ({
          ...current,
          company: savedWorkspace.companyName,
        })));
      } catch (loadError) {
        setError(loadError.message);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  React.useEffect(() => {
    if (!showInlineDateFilter) {
      setLocalDateFilters(dateFilters);
    }
  }, [dateFilters, showInlineDateFilter]);

  const updateFilter = (field, value) => {
    setFilters(current => {
      const next = { ...current, [field]: value };
      if (workspace?.companyName) {
        setBwSessionState(`mentions:${title}`, workspace.companyName, { filters: next });
      }
      return next;
    });
  };

  const eligibleMentions = mentions.filter(mention => (
    sourceFilters[mention.source] !== false
    && isWithinDateRange(mention, showInlineDateFilter ? localDateFilters : dateFilters)
  ));

  const filteredMentions = eligibleMentions.filter(mention => {
    const searchable = normalized([
      mention.title,
      mention.content,
      mention.keyword,
      mention.author,
      mention.company_name,
    ].join(" "));
    if (filters.query && !searchable.includes(normalized(filters.query))) return false;
    if (filters.company && normalized(mention.company_name) !== normalized(filters.company)) return false;
    if (filters.source !== "all" && mention.source !== filters.source) return false;
    if (filters.brand && mention.brandName !== filters.brand) return false;
    if (filters.product && mention.productName !== filters.product) return false;
    if (filters.executive && mention.executiveName !== filters.executive) return false;
    if (filters.campaign && mention.campaignName !== filters.campaign) return false;
    if (filters.hashtag && mention.hashtagName !== filters.hashtag) return false;
    if (filters.sentiment && mention.sentimentValue !== filters.sentiment) return false;
    return true;
  });

  const sourceCounts = eligibleMentions.reduce((counts, mention) => {
    counts[mention.source] = (counts[mention.source] || 0) + 1;
    return counts;
  }, {});
  const sentiments = unique(eligibleMentions.map(mention => mention.sentimentValue));
  const sentimentCounts = eligibleMentions.reduce((counts, mention) => {
    counts[mention.sentimentValue] = (counts[mention.sentimentValue] || 0) + 1;
    return counts;
  }, {});

  return (
    <div className="bw-page">
      <div className="bw-page-header">
        <div className="bw-eyebrow">BW / Investigation</div>
        <h1 className="bw-heading">{title}</h1>
        <p className="bw-lead">{description}</p>
      </div>

      {loading && <div className="bw-empty">Loading stored mentions...</div>}
      {error && <div className="bw-save-notice bw-save-notice-error">{error}</div>}

      {!loading && !error && workspace && (
        <>
          {showSourceTabs && (
            <div className="bw-mention-tabs" role="tablist" aria-label="Mention sources">
              {BW_SOURCE_OPTIONS.map(option => (
                <button
                  className={`bw-mention-tab ${filters.source === option.value ? "active" : ""}`}
                  type="button"
                  role="tab"
                  aria-selected={filters.source === option.value}
                  key={option.value}
                  onClick={() => updateFilter("source", option.value)}
                >
                  <span>{option.label}</span>
                  <strong>{option.value === "all" ? eligibleMentions.length : sourceCounts[option.value] || 0}</strong>
                </button>
              ))}
            </div>
          )}

          <div className="bw-sentiment-summary" aria-label="Sentiment summary">
            {SENTIMENT_LABELS.map(sentiment => (
              <button
                className={`bw-sentiment-summary-button bw-sentiment-${sentiment} ${filters.sentiment === sentiment ? "active" : ""}`}
                type="button"
                key={sentiment}
                onClick={() => updateFilter(
                  "sentiment",
                  filters.sentiment === sentiment ? "" : sentiment,
                )}
              >
                <span>{sentiment}</span>
                <strong>{sentimentCounts[sentiment] || 0}</strong>
              </button>
            ))}
            <button
              className={`bw-sentiment-summary-button bw-sentiment-total ${!filters.sentiment ? "active" : ""}`}
              type="button"
              onClick={() => updateFilter("sentiment", "")}
            >
              <span>Total</span>
              <strong>{eligibleMentions.length}</strong>
            </button>
          </div>

          {showInlineDateFilter && (
            <section className="bw-inline-date-filter">
              <div>
                <h2>Source Date Filter</h2>
                <p>
                  {dateFilterNotice || "Filter stored source results by published or collected date."}
                </p>
              </div>
              <div className="bw-inline-date-controls">
                <label className="bw-label">
                  Start date
                  <input
                    className="bw-input"
                    type="date"
                    value={localDateFilters.startDate || ""}
                    max={localDateFilters.endDate || undefined}
                    onChange={event => {
                      setDateFilterNotice("");
                      setLocalDateFilters(current => ({
                        ...current,
                        startDate: event.target.value,
                      }));
                    }}
                  />
                </label>
                <label className="bw-label">
                  End date
                  <input
                    className="bw-input"
                    type="date"
                    value={localDateFilters.endDate || ""}
                    min={localDateFilters.startDate || undefined}
                    onChange={event => {
                      setDateFilterNotice("");
                      setLocalDateFilters(current => ({
                        ...current,
                        endDate: event.target.value,
                      }));
                    }}
                  />
                </label>
                <button
                  className="bw-secondary-button"
                  type="button"
                  onClick={() => {
                    setDateFilterNotice("");
                    setLocalDateFilters({ startDate: "", endDate: "" });
                  }}
                >
                  Clear date
                </button>
              </div>
            </section>
          )}

          <section className="bw-mention-filters">
            <label className="bw-label bw-search-field">
              Search mentions
              <input
                className="bw-input"
                value={filters.query}
                onChange={event => updateFilter("query", event.target.value)}
                placeholder="Search titles, content, keywords, or authors"
              />
            </label>
            <div className="bw-filter-grid">
              <FilterSelect label="Company" value={filters.company} options={[workspace.companyName]} onChange={value => updateFilter("company", value)} />
              <FilterSelect label="Brand" value={filters.brand} options={workspace.brands || []} onChange={value => updateFilter("brand", value)} />
              <FilterSelect label="Product" value={filters.product} options={(workspace.products || []).map(product => product.name)} onChange={value => updateFilter("product", value)} />
              <FilterSelect label="Source" value={filters.source === "all" ? "" : filters.source} options={BW_SOURCE_OPTIONS.slice(1).map(option => option.value)} labels={SOURCE_LABELS} onChange={value => updateFilter("source", value || "all")} />
              <FilterSelect label="Sentiment" value={filters.sentiment} options={sentiments} onChange={value => updateFilter("sentiment", value)} />
              <FilterSelect label="Hashtag" value={filters.hashtag} options={workspace.hashtags || []} onChange={value => updateFilter("hashtag", value)} />
              <FilterSelect label="Executive" value={filters.executive} options={[...(workspace.ceos || []), ...(workspace.executives || [])].map(executive => executive.name)} onChange={value => updateFilter("executive", value)} />
              <FilterSelect label="Campaign" value={filters.campaign} options={workspace.campaigns || []} onChange={value => updateFilter("campaign", value)} />
            </div>
          </section>

          <div className="bw-results-heading">
            <div>
              <h2>{filteredMentions.length} mentions</h2>
              <p>Stored results for {workspace.companyName}</p>
              {filteredMentions[0]?.runId && <p>Latest run: {filteredMentions[0].runId}</p>}
            </div>
            <button
              className="bw-secondary-button"
              type="button"
              onClick={() => setFilters({
                query: "",
                company: workspace.companyName,
                brand: "",
                product: "",
                source: initialSource,
                sentiment: "",
                executive: "",
                campaign: "",
                hashtag: "",
              })}
            >
              Clear filters
            </button>
          </div>

          <div className="bw-mention-results">
            {filteredMentions.map(mention => {
              const SourceIcon = SOURCE_ICONS[mention.source];
              return (
                <div className="bw-mention-card-wrap" key={mention.mention_id}>
                  <div className="bw-mention-card-context">
                    <span className={`bw-source-badge bw-source-${mention.source}`}>
                      {SOURCE_LABELS[mention.source] || mention.source}
                    </span>
                    <span>Matched keyword: {mention.keyword || "Not available"}</span>
                    {mention.keywordType && <span>Type: {mention.keywordType}</span>}
                    {mention.mentionConfidence !== null && (
                      <span>Confidence: {Math.round(mention.mentionConfidence)}% {mention.confidenceLabel}</span>
                    )}
                    <span>{formatDate(mention.published_at || mention.collected_at)}</span>
                  </div>
                  {mention.matchedBecause && (
                    <div className="bw-mention-explainability">
                      Matched because: {mention.matchedBecause}
                    </div>
                  )}
                  <ArticleCard
                    title={mention.title || mention.content || "Untitled mention"}
                    source_name={mention.author || SOURCE_LABELS[mention.source] || mention.source}
                    sentiment_label={mention.sentimentValue}
                    sentiment_score={mention.sentimentScore}
                    sentiment_confidence={mention.sentimentConfidence}
                    primary_category={mention.primary_category || null}
                    emotion={mention.emotion || "indifference"}
                    emotion_confidence={mention.emotionConfidence}
                    url={mention.url}
                    published_at={mention.published_at || mention.collected_at}
                    renderSentimentIcon={SourceIcon ? <SourceIcon /> : null}
                  />
                </div>
              );
            })}
            {!filteredMentions.length && (
              <div className="bw-empty">No mentions match the selected filters.</div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function FilterSelect({ label, value, options, labels = {}, onChange }) {
  return (
    <label className="bw-label">
      {label}
      <select className="bw-input" value={value} onChange={event => onChange(event.target.value)}>
        <option value="">All</option>
        {unique(options).map(option => (
          <option value={option} key={option}>{labels[option] || option}</option>
        ))}
      </select>
    </label>
  );
}

function formatDate(value) {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

function optionalNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function isWithinDateRange(mention, dateFilters) {
  const rawDate = mention.published_at || mention.collected_at;
  if (!rawDate) return !dateFilters.startDate;
  const timestamp = new Date(rawDate).getTime();
  if (Number.isNaN(timestamp)) return false;
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
