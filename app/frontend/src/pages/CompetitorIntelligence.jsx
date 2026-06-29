import React from "react";
import {
  compareCompetitor,
  discoverCompetitors,
  generateCompetitorIntelligence,
} from "../api/competitorsApi";

const sectionStyle = {
  background: "#fff",
  borderRadius: 8,
  border: "1px solid #e5e7eb",
  padding: 20,
  boxShadow: "0 2px 8px #eaeaea",
};

const emptyProfile = {
  competitor_name: "",
  product_names: "",
  service_names: "",
  ceo_names: "",
  executive_names: "",
  campaign_names: "",
  hashtags: "",
  competitor_keywords: "",
};

function splitList(value) {
  return (value || "")
    .split(",")
    .map(item => item.trim())
    .filter(Boolean);
}

function ListBlock({ title, items }) {
  const list = Array.isArray(items) ? items : [];
  return (
    <div style={sectionStyle}>
      <h3 style={{ margin: "0 0 12px 0", fontSize: 18 }}>{title}</h3>
      {list.length ? (
        <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
          {list.map((item, index) => (
            <li key={`${title}-${index}`}>{item}</li>
          ))}
        </ul>
      ) : (
        <p style={{ margin: 0, color: "#6b7280" }}>No items yet.</p>
      )}
    </div>
  );
}

function MetricCard({ title, children }) {
  return (
    <div style={sectionStyle}>
      <h3 style={{ margin: "0 0 12px 0", fontSize: 18 }}>{title}</h3>
      {children}
    </div>
  );
}

function PercentRow({ label, value }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 8 }}>
      <span style={{ color: "#4b5563" }}>{label}</span>
      <strong>{Number(value || 0).toFixed(1)}%</strong>
    </div>
  );
}

function MetricDescription({ intelligence, metric }) {
  const info = intelligence?.metric_descriptions?.[metric];
  if (!info) return null;
  return (
    <div
      style={{
        color: "#4b5563",
        fontSize: 13,
        lineHeight: 1.5,
        marginBottom: 12,
        padding: "10px 12px",
        border: "1px solid #e5e7eb",
        borderRadius: 6,
        background: "#f9fafb",
      }}
    >
      <strong>{info.short}</strong>
      <div>{info.definition}</div>
    </div>
  );
}

function EvidenceList({ title, items }) {
  const list = Array.isArray(items) ? items : [];
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontWeight: 800, marginBottom: 6 }}>{title}</div>
      {list.length ? (
        <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.6 }}>
          {list.slice(0, 5).map((item, index) => (
            <li key={`${title}-${index}`}>
              {typeof item === "string" ? item : (item.title || item.feature || item.event || item.snippet || "Evidence item")}
            </li>
          ))}
        </ul>
      ) : (
        <div style={{ color: "#6b7280", fontSize: 13 }}>No evidence found yet.</div>
      )}
    </div>
  );
}

function EvidenceCard({ item, classification }) {
  const data = typeof item === "string" ? { title: item } : (item || {});
  const title = data.title || data.feature || data.event || data.evidence || data.snippet || "Evidence item";
  const sourceType = data.source || data.platform || "";
  const sourceName = data.source_name || data.publisher || data.channel || "";
  const matched = [
    data.trigger,
    data.reason,
    data.pricing_context,
    data.event,
    ...(Array.isArray(data.prices) ? data.prices : []),
  ].filter(Boolean);

  return (
    <div style={{ ...sectionStyle, boxShadow: "none", padding: 14 }}>
      <div style={{ fontWeight: 800, marginBottom: 6 }}>{title}</div>
      <div style={{ color: "#4b5563", fontSize: 13, lineHeight: 1.6 }}>
        {classification && <div>Classification: <strong>{classification}</strong></div>}
        {data.relevance && <div>Relevance: <strong>{data.relevance}</strong></div>}
        {data.sentiment && <div>Sentiment: <strong>{data.sentiment}</strong></div>}
        {data.confidence !== undefined && data.confidence !== null && (
          <div>Confidence: <strong>{Math.round(Number(data.confidence || 0) * 100)}%</strong></div>
        )}
        {(sourceType || sourceName) && (
          <div>
            Source: <strong>{sourceType || "unknown"}</strong>
            {sourceName && sourceName !== sourceType ? ` · ${sourceName}` : ""}
          </div>
        )}
        {data.published_at && <div>Date: {data.published_at}</div>}
        {data.signal && <div>Signal: <strong>{data.signal.replace(/_/g, " ")}</strong></div>}
        {data.brsr_principle && <div>BRSR: <strong>{data.brsr_principle}</strong></div>}
        {Array.isArray(data.sdgs) && data.sdgs.length > 0 && (
          <div>SDGs: <strong>{data.sdgs.join(", ")}</strong></div>
        )}
        {matched.length > 0 && <div>Detected because: {matched.join(", ")}</div>}
        {data.snippet && <div style={{ marginTop: 6 }}>{data.snippet}</div>}
        {data.evidence && <div style={{ marginTop: 6 }}>{data.evidence}</div>}
        {data.url && (
          <a href={data.url} target="_blank" rel="noreferrer" style={{ display: "inline-block", marginTop: 8 }}>
            Open source
          </a>
        )}
      </div>
    </div>
  );
}

function EvidencePanel({ title, items, classification, emptyText = "No evidence found yet." }) {
  const list = Array.isArray(items) ? items : [];
  return (
    <div style={sectionStyle}>
      <h3 style={{ margin: "0 0 12px 0" }}>{title}</h3>
      {list.length ? (
        <div style={{ display: "grid", gap: 12 }}>
          {list.map((item, index) => (
            <EvidenceCard key={`${title}-${index}`} item={item} classification={classification} />
          ))}
        </div>
      ) : (
        <p style={{ margin: 0, color: "#6b7280" }}>{emptyText}</p>
      )}
    </div>
  );
}

const INTELLIGENCE_TABS = [
  ["overview", "SWOT Overview"],
  ["sentiment", "Sentiment"],
  ["sov", "Share of Voice"],
  ["pricing", "Pricing"],
  ["features", "Features"],
  ["hiring", "Hiring"],
  ["funding", "Funding"],
  ["ma", "M&A"],
  ["layoffs", "Layoffs"],
  ["evidence", "Evidence Explorer"],
];

function TextField({ label, value, onChange, placeholder }) {
  return (
    <label style={{ display: "block" }}>
      <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>{label}</div>
      <input
        value={value}
        onChange={event => onChange(event.target.value)}
        placeholder={placeholder}
        style={{
          width: "100%",
          boxSizing: "border-box",
          border: "1px solid #d1d5db",
          borderRadius: 6,
          padding: "9px 10px",
          fontSize: 14,
        }}
      />
    </label>
  );
}

const emptyState = {
  suggestions: [],
  profile: emptyProfile,
  comparison: null,
  intelligence: null,
  loading: false,
  comparing: false,
  intelligenceLoading: false,
  error: "",
  loaded: false,
};

export default function CompetitorIntelligence({
  lastBrand,
  monitorState,
  competitorState,
  setCompetitorState,
}) {
  const [activeTab, setActiveTab] = React.useState("overview");
  const selectedBrand = lastBrand || "";
  const selectedBrandId = selectedBrand ? monitorState[selectedBrand]?.brand_id : null;
  const pageState = selectedBrandId
    ? { ...emptyState, ...(competitorState[selectedBrandId] || {}) }
    : emptyState;
  const {
    suggestions,
    profile,
    comparison,
    intelligence,
    loading,
    comparing,
    intelligenceLoading,
    error,
  } = pageState;

  const setPageState = React.useCallback((updates) => {
    if (!selectedBrandId) return;
    setCompetitorState(prev => ({
      ...prev,
      [selectedBrandId]: {
        ...emptyState,
        ...(prev[selectedBrandId] || {}),
        ...(typeof updates === "function"
          ? updates({ ...emptyState, ...(prev[selectedBrandId] || {}) })
          : updates),
      },
    }));
  }, [selectedBrandId, setCompetitorState]);

  React.useEffect(() => {
    if (!selectedBrandId) {
      return;
    }

    const cached = competitorState[selectedBrandId];
    if (cached?.loaded || cached?.loading || cached?.suggestions?.length || cached?.comparison) {
      return;
    }

    setPageState({ loading: true, error: "" });
    discoverCompetitors(selectedBrandId)
      .then(data => {
        setPageState({
          suggestions: data.competitors || [],
          loaded: true,
          loading: false,
          error: "",
        });
      })
      .catch(err => {
        const hasCachedData = Boolean(
          competitorState[selectedBrandId]?.suggestions?.length ||
          competitorState[selectedBrandId]?.comparison
        );
        setPageState({
          error: hasCachedData
            ? "Unable to refresh competitor data. Showing last cached result."
            : (err.message || "Could not load competitor suggestions"),
          suggestions: hasCachedData
            ? competitorState[selectedBrandId]?.suggestions || []
            : [],
          loaded: true,
          loading: false,
        });
      });
  }, [selectedBrandId]);

  const updateProfile = (field, value) => {
    setPageState(prev => ({
      profile: { ...prev.profile, [field]: value },
    }));
  };

  const buildPayload = nextProfile => ({
    competitor_name: nextProfile.competitor_name.trim(),
    product_names: splitList(nextProfile.product_names),
    service_names: splitList(nextProfile.service_names),
    ceo_names: splitList(nextProfile.ceo_names),
    executive_names: splitList(nextProfile.executive_names),
    campaign_names: splitList(nextProfile.campaign_names),
    hashtags: splitList(nextProfile.hashtags),
    competitor_keywords: splitList(nextProfile.competitor_keywords),
  });

  const runComparison = nextProfile => {
    if (!selectedBrandId || !nextProfile.competitor_name.trim()) return;

    setPageState({
      comparison: null,
      intelligence: null,
      error: "",
      comparing: true,
      intelligenceLoading: true,
    });

    const payload = buildPayload(nextProfile);
    Promise.allSettled([
      compareCompetitor(selectedBrandId, payload),
      generateCompetitorIntelligence(selectedBrandId, payload),
    ])
      .then(([comparisonResult, intelligenceResult]) => {
        const updates = {
          comparing: false,
          intelligenceLoading: false,
          error: "",
        };

        if (comparisonResult.status === "fulfilled") {
          updates.comparison = comparisonResult.value;
        }

        if (intelligenceResult.status === "fulfilled") {
          updates.intelligence = intelligenceResult.value;
        }

        if (comparisonResult.status === "rejected" || intelligenceResult.status === "rejected") {
          const firstError = comparisonResult.reason || intelligenceResult.reason;
          updates.error = pageState.comparison || pageState.intelligence
            ? "Unable to refresh all competitor data. Showing last cached result where available."
            : (firstError?.message || "Could not generate competitor analysis");
        }

        setPageState({
          ...updates,
        });
      })
  };

  const handleSuggestionClick = competitor => {
    const nextProfile = {
      ...emptyProfile,
      competitor_name: competitor.name || competitor.competitor_name || "",
      competitor_keywords: competitor.reason || "",
    };
    setPageState({ profile: nextProfile });
    runComparison(nextProfile);
  };

  const handleSubmit = event => {
    event.preventDefault();
    runComparison(profile);
  };

  if (!selectedBrand || !selectedBrandId) {
    return (
      <div>
        <h2>Competitor Intelligence</h2>
        <div style={sectionStyle}>
          <p style={{ margin: 0, color: "#4b5563" }}>
            Search a brand in Sources first. The competitor page will use that same brand automatically.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h2>Competitor Intelligence</h2>

      <div style={{ ...sectionStyle, marginBottom: 24 }}>
        <div style={{ color: "#6b7280", fontSize: 13, marginBottom: 4 }}>Active Brand</div>
        <div style={{ fontSize: 26, fontWeight: 800 }}>{selectedBrand}</div>
        <div style={{ color: "#6b7280", fontSize: 13, marginTop: 4 }}>
          Competitor profiles are temporary. Nothing is saved to competitor tables.
        </div>
      </div>

      {error && <p style={{ color: "#b91c1c" }}>{error}</p>}

      <div style={{ ...sectionStyle, marginBottom: 24 }}>
        <h3 style={{ margin: "0 0 12px 0" }}>Temporary Competitor Profile</h3>
        <form onSubmit={handleSubmit}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 14 }}>
            <TextField label="Competitor Name" value={profile.competitor_name} onChange={value => updateProfile("competitor_name", value)} placeholder="Samsung" />
            <TextField label="Products" value={profile.product_names} onChange={value => updateProfile("product_names", value)} placeholder="Galaxy S25, Galaxy Watch" />
            <TextField label="Services" value={profile.service_names} onChange={value => updateProfile("service_names", value)} placeholder="Samsung Care" />
            <TextField label="CEO Names" value={profile.ceo_names} onChange={value => updateProfile("ceo_names", value)} placeholder="TM Roh" />
            <TextField label="Executives" value={profile.executive_names} onChange={value => updateProfile("executive_names", value)} placeholder="Executive names" />
            <TextField label="Campaigns" value={profile.campaign_names} onChange={value => updateProfile("campaign_names", value)} placeholder="Galaxy AI" />
            <TextField label="Hashtags" value={profile.hashtags} onChange={value => updateProfile("hashtags", value)} placeholder="#GalaxyAI, #TeamGalaxy" />
            <TextField label="Keywords" value={profile.competitor_keywords} onChange={value => updateProfile("competitor_keywords", value)} placeholder="samsung phones, galaxy reviews" />
          </div>
          <button
            type="submit"
            disabled={!profile.competitor_name.trim() || comparing}
            style={{
              marginTop: 16,
              padding: "10px 16px",
              borderRadius: 6,
              border: "1px solid #232946",
              background: "#232946",
              color: "#fff",
              fontWeight: 700,
              cursor: profile.competitor_name.trim() && !comparing ? "pointer" : "not-allowed",
            }}
          >
            {comparing ? "Generating SWOT..." : "Generate SWOT"}
          </button>
        </form>
      </div>

      <div style={{ marginBottom: 24 }}>
        <h3 style={{ margin: "0 0 12px 0" }}>Suggested Competitors</h3>
        {loading && <p>Finding suggestions...</p>}
        {suggestions.length ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 14 }}>
            {suggestions.map(competitor => (
              <button
                key={`${competitor.name}-${competitor.type}`}
                type="button"
                onClick={() => handleSuggestionClick(competitor)}
                style={{
                  textAlign: "left",
                  background: "#fff",
                  border: "1px solid #e5e7eb",
                  borderRadius: 8,
                  padding: 16,
                  cursor: "pointer",
                  boxShadow: "0 2px 8px #eaeaea",
                  minHeight: 106,
                }}
              >
                <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 8 }}>{competitor.name}</div>
                <div style={{ color: "#6b7280", fontSize: 13, textTransform: "capitalize" }}>
                  {(competitor.type || "direct").replace(/_/g, " ")}
                </div>
                {competitor.confidence !== null && competitor.confidence !== undefined && (
                  <div style={{ color: "#374151", fontSize: 13, marginTop: 8 }}>
                    Confidence: {Number(competitor.confidence).toFixed(2)}
                  </div>
                )}
                {competitor.expected_domain && (
                  <div style={{ color: "#6b7280", fontSize: 12, marginTop: 6 }}>
                    Domain: {competitor.candidate_domain || "unknown"} · Expected: {competitor.expected_domain}
                  </div>
                )}
                {competitor.confidence_breakdown && Object.keys(competitor.confidence_breakdown).length > 0 && (
                  <div style={{ color: "#6b7280", fontSize: 12, marginTop: 6 }}>
                    Mentions: {competitor.mention_count || 0} · Category: {Number(competitor.category_relevance || 0).toFixed(2)}
                  </div>
                )}
              </button>
            ))}
          </div>
        ) : (
          !loading && <p style={{ color: "#6b7280" }}>No suggestions yet. You can still enter a competitor manually.</p>
        )}
      </div>

      <div style={{ ...sectionStyle, marginBottom: 24, padding: 12 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {INTELLIGENCE_TABS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setActiveTab(key)}
              style={{
                border: activeTab === key ? "1px solid #232946" : "1px solid #d1d5db",
                background: activeTab === key ? "#232946" : "#fff",
                color: activeTab === key ? "#fff" : "#374151",
                borderRadius: 6,
                padding: "8px 10px",
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {activeTab === "overview" && (
        <div>
          <div style={{ ...sectionStyle, marginBottom: 24 }}>
            <h3 style={{ margin: "0 0 12px 0" }}>SWOT Results</h3>
            {!comparison && !comparing && <p style={{ margin: 0, color: "#6b7280" }}>Enter a competitor profile or click a suggestion to generate SWOT.</p>}
            {comparing && <p style={{ margin: 0 }}>Generating SWOT...</p>}
            {comparison && (
              <div>
                <div style={{ fontWeight: 800, fontSize: 22, marginBottom: 10 }}>
                  {comparison.brand || selectedBrand} vs {comparison.competitor}
                </div>
                <p style={{ color: "#374151", lineHeight: 1.6 }}>
                  {comparison.summary || comparison.comparison_summary || "No summary returned."}
                </p>
                {Array.isArray(comparison.recommendations) && comparison.recommendations.length > 0 && (
                  <div style={{ marginTop: 14, padding: 14, borderRadius: 8, background: "#eefbf3", color: "#14532d" }}>
                    <div style={{ fontWeight: 800, marginBottom: 4 }}>Recommendations</div>
                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                      {comparison.recommendations.map((item, index) => (
                        <li key={`recommendation-${index}`}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {comparison.evidence_basis && (
                  <div style={{ marginTop: 14, padding: 14, borderRadius: 8, background: "#f9fafb", border: "1px solid #e5e7eb" }}>
                    <div style={{ fontWeight: 800, marginBottom: 8 }}>Evidence Used</div>
                    <div style={{ color: "#4b5563", fontSize: 13, marginBottom: 8 }}>
                      Mentions analyzed: {comparison.evidence_basis.mention_count || 0}
                    </div>
                    <EvidenceList title="Strength topics" items={comparison.evidence_basis.strength_topics} />
                    <EvidenceList title="Weakness topics" items={comparison.evidence_basis.weakness_topics} />
                  </div>
                )}
              </div>
            )}
          </div>

          {comparison && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16 }}>
              <ListBlock title="Strengths" items={comparison.strengths} />
              <ListBlock title="Weaknesses" items={comparison.weaknesses} />
              <ListBlock title="Opportunities" items={comparison.opportunities} />
              <ListBlock title="Threats" items={comparison.threats} />
            </div>
          )}
        </div>
      )}

      {activeTab === "sentiment" && (
        <div>
          <MetricCard title="Competitor Sentiment">
            <MetricDescription intelligence={intelligence} metric="sentiment" />
            <PercentRow label="Positive" value={intelligence?.sentiment?.percentages?.positive} />
            <PercentRow label="Neutral" value={intelligence?.sentiment?.percentages?.neutral} />
            <PercentRow label="Negative" value={intelligence?.sentiment?.percentages?.negative} />
            <div style={{ color: "#6b7280", fontSize: 13, marginTop: 8 }}>
              Uses the stored sentiment labels from the existing RoBERTa/Groq classification pipeline.
            </div>
          </MetricCard>
          <div style={{ marginTop: 16 }}>
            <EvidencePanel title="Sentiment Evidence" items={intelligence?.evidence?.competitor_examples} classification="sentiment mention" />
          </div>
        </div>
      )}

      {activeTab === "sov" && (
        <div>
          <MetricCard title="Share of Voice">
            <MetricDescription intelligence={intelligence} metric="sov" />
            <PercentRow label={intelligence?.brand || "Brand"} value={intelligence?.share_of_voice?.brand} />
            <PercentRow label={intelligence?.competitor || "Competitor"} value={intelligence?.share_of_voice?.competitor} />
            <div style={{ color: "#6b7280", fontSize: 13, marginTop: 8 }}>
              Brand mentions: {intelligence?.share_of_voice?.brand_mentions || 0} · Competitor mentions: {intelligence?.share_of_voice?.competitor_mentions || 0}
            </div>
          </MetricCard>
          <div style={{ marginTop: 16 }}>
            <EvidencePanel title="Competitor Mention Evidence" items={intelligence?.evidence?.competitor_examples} classification="share of voice mention" />
          </div>
        </div>
      )}

      {activeTab === "pricing" && (
        <MetricCard title="Pricing Intelligence">
          <MetricDescription intelligence={intelligence} metric="pricing" />
          <div style={{ fontWeight: 800, marginBottom: 8 }}>
            Average: {intelligence?.pricing?.average_price ? intelligence.pricing.average_price : "No signal"}
          </div>
          <div style={{ color: "#6b7280", fontSize: 13 }}>
            Price points: {(intelligence?.pricing?.price_points || []).slice(0, 8).join(", ") || "None found"}
          </div>
          <EvidencePanel title="Pricing Evidence" items={intelligence?.evidence?.pricing_examples} classification="pricing" />
        </MetricCard>
      )}

      {activeTab === "features" && (
        <MetricCard title="Feature Announcements">
          <MetricDescription intelligence={intelligence} metric="features" />
          <EvidencePanel title="Feature Evidence" items={intelligence?.feature_announcements} classification="feature announcement" />
        </MetricCard>
      )}

      {activeTab === "hiring" && (
        <MetricCard title="Hiring Intelligence">
          <MetricDescription intelligence={intelligence} metric="hiring" />
          <EvidencePanel title="Hiring Evidence" items={intelligence?.hiring_trends?.evidence} classification="hiring signal" />
        </MetricCard>
      )}

      {activeTab === "funding" && (
        <MetricCard title="Funding Intelligence">
          <MetricDescription intelligence={intelligence} metric="funding" />
          <EvidencePanel title="Funding Evidence" items={intelligence?.funding} classification="funding signal" />
        </MetricCard>
      )}

      {activeTab === "ma" && (
        <MetricCard title="M&A Intelligence">
          <MetricDescription intelligence={intelligence} metric="ma" />
          <EvidencePanel title="M&A Evidence" items={intelligence?.mergers} classification="M&A signal" />
        </MetricCard>
      )}

      {activeTab === "layoffs" && (
        <MetricCard title="Layoff / Termination Intelligence">
          <MetricDescription intelligence={intelligence} metric="terminations" />
          <EvidencePanel title="Termination Evidence" items={intelligence?.terminations} classification="layoff or termination signal" />
        </MetricCard>
      )}

      {activeTab === "evidence" && (
        <div style={{ display: "grid", gap: 16 }}>
          <EvidencePanel title="LLM Classified Evidence" items={intelligence?.evidence?.classified_evidence_examples} classification="classified evidence" />
          <EvidencePanel title="Direct Comparison Evidence" items={intelligence?.evidence?.direct_comparison_examples} classification="direct comparison" />
          <EvidencePanel title="Competitor Mention Evidence" items={intelligence?.evidence?.competitor_examples} classification="competitor mention" />
          <EvidencePanel title="Pricing Evidence" items={intelligence?.evidence?.pricing_examples} classification="pricing" />
          <EvidencePanel title="Feature Evidence" items={intelligence?.evidence?.feature_examples} classification="feature announcement" />
          <EvidencePanel title="Hiring Evidence" items={intelligence?.evidence?.hiring_examples} classification="hiring signal" />
          <EvidencePanel title="Funding Evidence" items={intelligence?.evidence?.funding_examples} classification="funding signal" />
          <EvidencePanel title="M&A Evidence" items={intelligence?.evidence?.merger_examples} classification="M&A signal" />
          <EvidencePanel title="Layoff Evidence" items={intelligence?.evidence?.termination_examples} classification="layoff or termination signal" />
        </div>
      )}
    </div>
  );
}
