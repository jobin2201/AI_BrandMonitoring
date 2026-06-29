import React from "react";
import { generateBwAiAnalysis } from "../../api/bw/bwAiApi";
import { getBwWorkspace } from "../../api/bw/bwWorkspaceApi";
import { getActiveCompanyName } from "../../utils/bw/companyStorage";
import {
  getBwSessionState,
  setBwSessionState,
} from "../../utils/bw/sessionCache";
import "./bwWorkspace.css";

const SECTIONS = [
  { key: "top_risks", title: "Top Risks", tone: "risk" },
  { key: "top_opportunities", title: "Top Opportunities", tone: "opportunity" },
  { key: "emerging_topics", title: "Emerging Topics", tone: "topic" },
  { key: "recommendations", title: "Recommendations", tone: "recommendation" },
];

export default function AIAnalysis101Page() {
  const [workspace, setWorkspace] = React.useState(null);
  const [result, setResult] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [generating, setGenerating] = React.useState(false);
  const [progress, setProgress] = React.useState(0);
  const [error, setError] = React.useState("");
  const timerRef = React.useRef(null);

  React.useEffect(() => {
    const load = async () => {
      const companyName = getActiveCompanyName();
      if (!companyName) {
        setError("Load a company in Brand Monitoring first.");
        setLoading(false);
        return;
      }
      try {
        const saved = await getBwWorkspace(companyName);
        const session = getBwSessionState("ai-analysis", saved.companyName);
        setWorkspace(saved);
        setResult(session?.result || null);
        setProgress(session?.result ? 100 : 0);
      } catch (loadError) {
        setError(loadError.message);
      } finally {
        setLoading(false);
      }
    };
    load();
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, []);

  const generate = async () => {
    if (!workspace || generating) return;
    setGenerating(true);
    setError("");
    setProgress(8);
    timerRef.current = window.setInterval(() => {
      setProgress(current => Math.min(92, current + Math.max(1, Math.round((92 - current) / 10))));
    }, 700);
    try {
      const data = await generateBwAiAnalysis(workspace.companyName);
      setResult(data);
      setProgress(100);
      setBwSessionState("ai-analysis", workspace.companyName, { result: data });
    } catch (generateError) {
      setError(generateError.message);
    } finally {
      if (timerRef.current) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
      }
      setGenerating(false);
    }
  };

  const analysis = result?.analysis || {};

  return (
    <div className="bw-page">
      <div className="bw-page-header">
        <div className="bw-eyebrow">BW / Intelligence</div>
        <h1 className="bw-heading">AI Analysis101</h1>
        <p className="bw-lead">
          Groq-generated intelligence grounded in the active company’s stored monitoring evidence.
        </p>
      </div>

      {loading && <div className="bw-empty">Loading the active workspace...</div>}
      {error && <div className="bw-save-notice bw-save-notice-error">{error}</div>}

      {!loading && workspace && (
        <>
          <section className="bw-section bw-ai-header">
            <div>
              <div className="bw-stat-label">Active Company</div>
              <div className="bw-reputation-company">{workspace.companyName}</div>
              <p className="bw-section-copy">
                Uses stored BW mentions, sentiment, sources, products, and monitored terms.
              </p>
            </div>
            <button
              className="bw-save-button"
              type="button"
              onClick={generate}
              disabled={generating}
            >
              {generating
                ? "Generating Intelligence..."
                : result
                  ? "Regenerate Intelligence"
                  : "Generate Intelligence"}
            </button>
          </section>

          {(generating || progress > 0) && (
            <section className="bw-section">
              <div className="bw-monitoring-progress-meta">
                <span>{progress === 100 ? "Intelligence ready" : "Analyzing monitoring evidence"}</span>
                <span>{progress}%</span>
              </div>
              <div className="bw-monitoring-progress-track">
                <div className="bw-monitoring-progress-fill" style={{ width: `${progress}%` }} />
              </div>
            </section>
          )}

          {!result && !generating && (
            <div className="bw-empty">
              Generate intelligence after Brand Monitoring has stored mentions for this company.
            </div>
          )}

          {result && (
            <>
              <section className="bw-section bw-ai-summary">
                <div className="bw-stat-label">Executive Summary</div>
                <p>{analysis.executive_summary || "No executive summary returned."}</p>
                <div className="bw-ai-meta">
                  <span>{result.generated_from_mentions} mentions analyzed</span>
                  <span>{result.groq_usage?.total_tokens || 0} Groq tokens</span>
                </div>
              </section>

              <div className="bw-ai-grid">
                {SECTIONS.map(section => (
                  <section className={`bw-section bw-ai-section bw-ai-${section.tone}`} key={section.key}>
                    <h2 className="bw-section-title">{section.title}</h2>
                    <div className="bw-ai-items">
                      {(analysis[section.key] || []).map((item, index) => (
                        <article key={`${section.key}-${index}`}>
                          <strong>{item.title || item.topic || item.action || "Insight"}</strong>
                          <p>{item.evidence || item.reason || ""}</p>
                          <span>{item.impact || item.trend || item.priority || ""}</span>
                        </article>
                      ))}
                      {!(analysis[section.key] || []).length && (
                        <div className="bw-section-copy">No evidence-backed items returned.</div>
                      )}
                    </div>
                  </section>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
