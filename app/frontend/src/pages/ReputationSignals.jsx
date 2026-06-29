import React from "react";
import { generateReputationSignals } from "../api/reputationApi";

const sectionStyle = {
  background: "#fff",
  borderRadius: 8,
  border: "1px solid #e5e7eb",
  padding: 20,
  boxShadow: "0 2px 8px #eaeaea",
};

export function EvidenceCard({ item, classification }) {
  const data = typeof item === "string" ? { title: item } : (item || {});
  const title = data.title || data.signal || data.event || data.snippet || "Evidence item";
  const sourceType = data.source || data.platform || "";
  const sourceName = data.source_name || data.publisher || data.channel || "";
  const evidenceOrigin = String(data.evidence_origin || "").toLowerCase();
  const originLabel = evidenceOrigin.includes("stored") && evidenceOrigin.includes("live")
    ? "Stored + Live"
    : evidenceOrigin.includes("stored")
      ? "Stored"
      : evidenceOrigin.includes("live")
        ? "Live"
        : "";
  const sdgText = Array.isArray(data.sdgs)
    ? data.sdgs.map(sdg => {
        if (typeof sdg === "string") return sdg;
        const code = sdg?.code || sdg?.id || "";
        const name = sdg?.name || sdg?.title || "";
        return [code, name].filter(Boolean).join(" - ");
      }).filter(Boolean).join(", ")
    : "";

  return (
    <div style={{ ...sectionStyle, boxShadow: "none", padding: 14 }}>
      <div style={{ fontWeight: 800, marginBottom: 6 }}>{title}</div>
      <div style={{ color: "#4b5563", fontSize: 13, lineHeight: 1.6 }}>
        {classification && <div>Classification: <strong>{classification}</strong></div>}
        {data.signal && <div>Signal: <strong>{String(data.signal).replace(/_/g, " ")}</strong></div>}
        {data.confidence !== undefined && data.confidence !== null && (
          <div>Confidence: <strong>{Math.round(Number(data.confidence || 0) * 100)}%</strong></div>
        )}
        {(sourceType || sourceName) && (
          <div>
            Source: <strong>{sourceType || "unknown"}</strong>
            {sourceName && sourceName !== sourceType ? ` - ${sourceName}` : ""}
          </div>
        )}
        {originLabel && (
          <div>
            Evidence Origin: <strong>{originLabel}</strong>
          </div>
        )}
        {Array.isArray(data.evidence_sources) && data.evidence_sources.length > 1 && (
          <div>
            Grouped sources: <strong>{data.evidence_sources.slice(0, 4).join(", ")}</strong>
            {data.evidence_sources.length > 4 ? ` +${data.evidence_sources.length - 4} more` : ""}
          </div>
        )}
        {data.source_weight !== undefined && data.source_weight !== null && (
          <div>Source score: <strong>{Math.round(Number(data.source_weight || 0) * 100)}%</strong></div>
        )}
        {data.published_at && <div>Date: {data.published_at}</div>}
        {data.brsr_principle && <div>BRSR: <strong>{data.brsr_principle}</strong></div>}
        {sdgText && (
          <div>SDGs: <strong>{sdgText}</strong></div>
        )}
        {data.reason && <div>Detected because: {data.reason}</div>}
        {data.snippet && <div style={{ marginTop: 6 }}>{data.snippet}</div>}
        {data.url && (
          <a href={data.url} target="_blank" rel="noreferrer" style={{ display: "inline-block", marginTop: 8 }}>
            Open source
          </a>
        )}
      </div>
    </div>
  );
}

export function EvidencePanel({ title, description, items, relatedMentions, classification }) {
  const list = Array.isArray(items) ? items : [];
  const related = Array.isArray(relatedMentions) ? relatedMentions : [];
  return (
    <div style={sectionStyle}>
      <h3 style={{ margin: "0 0 8px 0" }}>{title}</h3>
      {description && (
        <p style={{ margin: "0 0 12px 0", color: "#4b5563", lineHeight: 1.5 }}>
          {description}
        </p>
      )}
      {list.length ? (
        <div style={{ display: "grid", gap: 12 }}>
          {list.map((item, index) => (
            <EvidenceCard key={`${title}-${index}`} item={item} classification={classification} />
          ))}
        </div>
      ) : (
        <>
          <p style={{ margin: 0, color: "#6b7280" }}>No verified signal found yet.</p>
          {related.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontWeight: 700, marginBottom: 8 }}>
                Related mentions (unverified)
              </div>
              <div style={{ display: "grid", gap: 10 }}>
                {related.map((item, index) => (
                  <EvidenceCard
                    key={`${title}-related-${index}`}
                    item={item}
                    classification="unverified related mention"
                  />
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function formatGeneratedAt(value) {
  if (!value) return "";
  const generated = new Date(value);
  if (Number.isNaN(generated.getTime())) return "";

  const diffMs = Date.now() - generated.getTime();
  const diffMinutes = Math.max(0, Math.floor(diffMs / 60000));
  if (diffMinutes < 1) return "Generated just now";
  if (diffMinutes === 1) return "Generated 1 minute ago";
  if (diffMinutes < 60) return `Generated ${diffMinutes} minutes ago`;

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours === 1) return "Generated 1 hour ago";
  if (diffHours < 24) return `Generated ${diffHours} hours ago`;

  return `Generated on ${generated.toLocaleString()}`;
}

export default function ReputationSignals({
  lastBrand,
  monitorState,
  reputationState,
  setReputationState,
}) {
  const selectedBrand = lastBrand || "";
  const selectedBrandId = selectedBrand ? monitorState[selectedBrand]?.brand_id : null;
  const pageState = selectedBrandId ? reputationState[selectedBrandId] || {} : {};
  const reputation = pageState.data;

  const runReputation = React.useCallback(() => {
    if (!selectedBrandId) return;
    const cached = reputationState[selectedBrandId];
    if (cached?.loading) return;

    setReputationState(prev => ({
      ...prev,
      [selectedBrandId]: {
        ...(prev[selectedBrandId] || {}),
        loading: true,
        error: "",
      },
    }));

    generateReputationSignals(selectedBrandId)
      .then(data => {
        setReputationState(prev => ({
          ...prev,
          [selectedBrandId]: {
            data,
            loaded: true,
            loading: false,
            error: "",
            generatedAt: new Date().toISOString(),
          },
        }));
      })
      .catch(error => {
        setReputationState(prev => ({
          ...prev,
          [selectedBrandId]: {
            ...(prev[selectedBrandId] || {}),
            loaded: true,
            loading: false,
            error: error.message || "Could not generate reputation signals",
          },
        }));
      });
  }, [selectedBrandId, reputationState, setReputationState]);

  if (!selectedBrand || !selectedBrandId) {
    return (
      <div>
        <h2>Reputation Signals</h2>
        <div style={sectionStyle}>
          <p style={{ margin: 0, color: "#4b5563" }}>
            Search a brand in Sources first. Reputation Signals will use the same active brand.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h2>Reputation Signals</h2>

      <div style={{ ...sectionStyle, marginBottom: 24 }}>
        <div style={{ color: "#6b7280", fontSize: 13, marginBottom: 4 }}>Active Brand</div>
        <div style={{ fontSize: 26, fontWeight: 800 }}>{selectedBrand}</div>
        <div style={{ color: "#6b7280", fontSize: 13, marginTop: 4 }}>
          Temporary analysis only. Nothing is saved to reputation tables.
        </div>
        {pageState.generatedAt && (
          <div style={{ color: "#4b5563", fontSize: 13, marginTop: 8 }}>
            {formatGeneratedAt(pageState.generatedAt)}. Showing temporary in-memory cache for this brand.
          </div>
        )}
        <button
          type="button"
          onClick={runReputation}
          disabled={pageState.loading}
          style={{
            marginTop: 16,
            border: "1px solid #111827",
            background: pageState.loading ? "#9ca3af" : "#111827",
            color: "#fff",
            borderRadius: 8,
            padding: "10px 14px",
            fontWeight: 700,
            cursor: pageState.loading ? "not-allowed" : "pointer",
          }}
        >
          {pageState.loading
            ? "Generating Reputation Signals..."
            : reputation
              ? "Regenerate Reputation Signals"
              : "Generate Reputation Signals"}
        </button>
      </div>

      {!reputation && (
        <div style={{ ...sectionStyle, marginBottom: 24 }}>
          <p style={{ margin: 0, color: "#4b5563" }}>
            {pageState.loading
              ? "Generating live reputation signals..."
              : pageState.error || "No reputation signals generated yet. Click Generate Reputation Signals to run the analysis."}
          </p>
        </div>
      )}

      {reputation && (
        <div style={{ display: "grid", gap: 16 }}>
          {reputation.classification_log && (
            <div style={sectionStyle}>
              <h3 style={{ margin: "0 0 8px 0" }}>Debug Logs</h3>
              <p style={{ margin: 0, color: "#4b5563", lineHeight: 1.5 }}>
                Classification log: <strong>{reputation.classification_log}</strong>
              </p>
              {reputation.error_log && (
                <p style={{ margin: "8px 0 0 0", color: "#b91c1c", lineHeight: 1.5 }}>
                  Error log: <strong>{reputation.error_log}</strong>
                </p>
              )}
              {reputation.error && (
                <p style={{ margin: "8px 0 0 0", color: "#b91c1c", lineHeight: 1.5 }}>
                  Error: {reputation.error}
                </p>
              )}
            </div>
          )}
          {!reputation.classification_log && (reputation.error_log || reputation.error) && (
            <div style={sectionStyle}>
              <h3 style={{ margin: "0 0 8px 0" }}>Debug Logs</h3>
              {reputation.error_log && (
                <p style={{ margin: 0, color: "#b91c1c", lineHeight: 1.5 }}>
                  Error log: <strong>{reputation.error_log}</strong>
                </p>
              )}
              {reputation.error && (
                <p style={{ margin: "8px 0 0 0", color: "#b91c1c", lineHeight: 1.5 }}>
                  Error: {reputation.error}
                </p>
              )}
            </div>
          )}
          <EvidencePanel
            title="Product Failures / Successes"
            description={reputation.descriptions?.product_signals?.short}
            items={reputation.product_signals?.items}
            relatedMentions={reputation.product_signals?.related_mentions}
            classification="product reputation signal"
          />
          <EvidencePanel
            title="ESG Issues"
            description={reputation.descriptions?.esg_signals?.short}
            items={reputation.esg_signals?.items}
            relatedMentions={reputation.esg_signals?.related_mentions}
            classification="ESG signal"
          />
          <EvidencePanel
            title="Investments & Withdrawals"
            description={reputation.descriptions?.investment_signals?.short}
            items={reputation.investment_signals?.items}
            relatedMentions={reputation.investment_signals?.related_mentions}
            classification="investment or withdrawal signal"
          />
          <EvidencePanel
            title="Regulatory Actions"
            description={reputation.descriptions?.regulatory_signals?.short}
            items={reputation.regulatory_signals?.items}
            relatedMentions={reputation.regulatory_signals?.related_mentions}
            classification="regulatory signal"
          />
          <EvidencePanel
            title="Customer Complaints"
            description={reputation.descriptions?.customer_complaints?.short}
            items={reputation.customer_complaints?.items}
            relatedMentions={reputation.customer_complaints?.related_mentions}
            classification="customer complaint signal"
          />
          <EvidencePanel
            title="Security Incidents"
            description={reputation.descriptions?.security_incidents?.short}
            items={reputation.security_incidents?.items}
            relatedMentions={reputation.security_incidents?.related_mentions}
            classification="security incident signal"
          />
          <EvidencePanel
            title="Layoffs & Employee Well-being"
            description={reputation.descriptions?.layoff_signals?.short}
            items={reputation.layoff_signals?.items}
            relatedMentions={reputation.layoff_signals?.related_mentions}
            classification="employee well-being signal"
          />
          <EvidencePanel
            title="Fraud Allegations"
            description={reputation.descriptions?.fraud_signals?.short}
            items={reputation.fraud_signals?.items}
            relatedMentions={reputation.fraud_signals?.related_mentions}
            classification="fraud allegation signal"
          />
          <EvidencePanel
            title="Executive Controversies"
            description={reputation.descriptions?.executive_controversies?.short}
            items={reputation.executive_controversies?.items}
            relatedMentions={reputation.executive_controversies?.related_mentions}
            classification="executive controversy signal"
          />
        </div>
      )}
    </div>
  );
}
