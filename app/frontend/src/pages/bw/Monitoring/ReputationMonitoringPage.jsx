import React from "react";
import { createMonitor } from "../../../api/monitorsApi";
import { generateBwReputationSignals } from "../../../api/bw/bwReputationApi";
import {
  getBwWorkspace,
  listBwWorkspaces,
} from "../../../api/bw/bwWorkspaceApi";
import {
  getActiveCompanyName,
  loadCompanyWorkspace,
  setActiveCompanyName,
} from "../../../utils/bw/companyStorage";
import {
  activateBwSessionCompany,
  getBwTaskSnapshot,
  getBwSessionState,
  setBwSessionState,
  startBwTask,
  subscribeBwTask,
} from "../../../utils/bw/sessionCache";
import {
  EvidencePanel,
  formatGeneratedAt,
} from "../../ReputationSignals";
import "../bwWorkspace.css";

const SECTION_CONFIG = [
  {
    key: "crisis_indicators",
    label: "Crisis Indicators",
    classification: "potential crisis indicator",
    description: "High-confidence fraud, regulatory, security, workforce, executive, and customer-risk evidence.",
  },
  {
    key: "fraud_signals",
    label: "Fraud Allegations",
    classification: "fraud allegation signal",
  },
  {
    key: "layoff_signals",
    label: "Layoffs",
    classification: "employee well-being signal",
  },
  {
    key: "executive_controversies",
    label: "Executive Controversies",
    classification: "executive controversy signal",
  },
  {
    key: "security_incidents",
    label: "Security Incidents",
    classification: "security incident signal",
  },
  {
    key: "customer_complaints",
    label: "Customer Complaints",
    classification: "customer complaint signal",
  },
  {
    key: "regulatory_signals",
    label: "Regulatory Actions",
    classification: "regulatory signal",
  },
  {
    key: "product_signals",
    label: "Product Failures / Successes",
    classification: "product reputation signal",
  },
  {
    key: "esg_signals",
    label: "ESG Issues",
    classification: "ESG signal",
  },
  {
    key: "investment_signals",
    label: "Investments & Withdrawals",
    classification: "investment or withdrawal signal",
  },
];

const CATEGORY_EVIDENCE = {
  fraud_signals: {
    min: 2,
    verifiedMin: 3,
    terms: [
      "fraud", "corruption", "bribery", "money laundering", "embezzlement",
      "whistleblower", "forgery", "scam", "accounting irregularity", "misconduct",
    ],
  },
  layoff_signals: {
    min: 2,
    verifiedMin: 3,
    terms: [
      "layoff", "layoffs", "job cut", "job cuts", "workforce reduction",
      "headcount", "retrenchment", "downsizing", "salary freeze", "severance",
      "restructuring", "unpaid wages",
    ],
  },
  executive_controversies: {
    min: 3,
    verifiedMin: 4,
    terms: [
      "ceo", "founder", "chairman", "board", "executive", "director",
      "resignation", "resigns", "investigation", "misconduct", "controversy",
      "lawsuit", "arrest", "statement", "probe",
    ],
  },
  security_incidents: {
    min: 2,
    verifiedMin: 3,
    terms: [
      "data breach", "breach", "cyber attack", "cyberattack", "hack",
      "hacked", "ransomware", "leak", "leaked", "privacy", "vulnerability",
      "malware", "phishing", "outage",
    ],
  },
  customer_complaints: {
    min: 2,
    verifiedMin: 3,
    terms: [
      "complaint", "customer", "refund", "support", "service issue", "poor service",
      "unable to access", "not working", "glitch", "delay", "defect", "broken",
      "overheating", "battery drain", "portal down", "outage",
    ],
  },
  regulatory_signals: {
    min: 2,
    verifiedMin: 3,
    terms: [
      "regulator", "regulatory", "court", "lawsuit", "fine", "penalty",
      "notice", "show cause", "investigation", "tax", "compliance",
      "government", "authority", "sebi", "sec", "ftc", "consumer court",
    ],
  },
  product_signals: {
    min: 2,
    verifiedMin: 3,
    terms: [
      "product", "launch", "launched", "review", "rating", "feature", "specs",
      "glitch", "failure", "defect", "recall", "outage", "not working",
      "service disruption", "technical issue", "comparison", "benchmark",
    ],
  },
  esg_signals: {
    min: 2,
    verifiedMin: 3,
    terms: [
      "sustainability", "sustainable", "net zero", "emissions", "climate",
      "renewable", "csr", "diversity", "inclusion", "governance", "ethics",
      "human rights", "community", "environment", "esg",
    ],
  },
  investment_signals: {
    min: 2,
    verifiedMin: 3,
    terms: [
      "investment", "invest", "funding", "expansion", "acquisition", "stake",
      "dividend", "share buyback", "valuation", "ipo", "facility", "plant",
      "partnership", "joint venture", "capex", "deal",
    ],
  },
};

export default function ReputationMonitoringPage() {
  const [companies, setCompanies] = React.useState([]);
  const [companyInput, setCompanyInput] = React.useState("");
  const [workspace, setWorkspace] = React.useState(null);
  const [brandId, setBrandId] = React.useState("");
  const [selectedSection, setSelectedSection] = React.useState("all");
  const [reputation, setReputation] = React.useState(null);
  const [generatedAt, setGeneratedAt] = React.useState("");
  const [loadingCompany, setLoadingCompany] = React.useState(false);
  const [generating, setGenerating] = React.useState(false);
  const [progress, setProgress] = React.useState(0);
  const [progressLabel, setProgressLabel] = React.useState("");
  const [error, setError] = React.useState("");
  const taskKey = workspace?.companyName
    ? `reputation-monitoring:${workspace.companyName.toLocaleLowerCase()}`
    : "";

  React.useEffect(() => {
    listBwWorkspaces()
      .then(result => setCompanies(result.companies || []))
      .catch(() => setCompanies([]));
    const activeCompany = getActiveCompanyName();
    if (activeCompany) {
      setCompanyInput(activeCompany);
      restoreCompany(activeCompany);
    }
  }, []);

  const restoreCachedCompany = (companyName, fallbackMessage = "") => {
    const cached = loadCompanyWorkspace();
    const requested = String(companyName || "").trim().toLocaleLowerCase();
    const cachedName = String(cached?.companyName || "").trim();
    if (!cachedName || cachedName.toLocaleLowerCase() !== requested) {
      return false;
    }
    const session = getBwSessionState("reputation-monitoring", cachedName);
    const task = getBwTaskSnapshot(`reputation-monitoring:${cachedName.toLocaleLowerCase()}`);
    const taskProgress = task?.progress || {};
    setWorkspace(cached);
    setCompanyInput(cachedName);
    setBrandId(task?.meta?.brandId || session?.brandId || "");
    setSelectedSection(session?.selectedSection || "all");
    setGenerating(task?.status === "running");
    setReputation(task?.result?.data || session?.reputation || null);
    setGeneratedAt(task?.result?.generatedAt || session?.generatedAt || "");
    setProgress(taskProgress.percent || (task?.result || session?.reputation ? 100 : 0));
    setProgressLabel(
      taskProgress.label
      || (task?.result || session?.reputation ? "Analysis complete" : fallbackMessage),
    );
    setError("");
    return true;
  };

  const restoreCompany = async companyName => {
    if (!companyName) return;
    setLoadingCompany(true);
    setError("");
    restoreCachedCompany(companyName);
    try {
      const saved = await getBwWorkspace(companyName);
      const aliases = (saved.brands || [])
        .filter(alias => alias.toLocaleLowerCase() !== saved.companyName.toLocaleLowerCase())
        .join(",");
      const monitor = await createMonitor(saved.companyName, aliases, true);
      const session = getBwSessionState("reputation-monitoring", saved.companyName);
      setWorkspace(saved);
      setCompanyInput(saved.companyName);
      setBrandId(monitor.brand_id);
      setSelectedSection(session?.selectedSection || "all");
      const task = getBwTaskSnapshot(`reputation-monitoring:${saved.companyName.toLocaleLowerCase()}`);
      const taskProgress = task?.progress || {};
      setGenerating(task?.status === "running");
      setReputation(task?.result?.data || session?.reputation || null);
      setGeneratedAt(task?.result?.generatedAt || session?.generatedAt || "");
      setProgress(taskProgress.percent || (task?.result || session?.reputation ? 100 : 0));
      setProgressLabel(taskProgress.label || (task?.result || session?.reputation ? "Analysis complete" : ""));
      setError(task?.status === "error" ? task.error : "");
    } catch (loadError) {
      if (!restoreCachedCompany(companyName, "Showing cached BW reputation data while backend is offline")) {
        setError(loadError.message || "Could not load this company");
      }
    } finally {
      setLoadingCompany(false);
    }
  };

  const loadCompany = async event => {
    event?.preventDefault();
    const companyName = companyInput.trim();
    if (!companyName || loadingCompany) return;
    setLoadingCompany(true);
    setError("");
    restoreCachedCompany(companyName);
    try {
      const saved = await getBwWorkspace(companyName);
      const companyChanged = activateBwSessionCompany(saved.companyName);
      setActiveCompanyName(saved.companyName);
      const aliases = (saved.brands || [])
        .filter(alias => alias.toLocaleLowerCase() !== saved.companyName.toLocaleLowerCase())
        .join(",");
      const monitor = await createMonitor(saved.companyName, aliases, true);
      setWorkspace(saved);
      setCompanyInput(saved.companyName);
      setBrandId(monitor.brand_id);
      const session = companyChanged
        ? null
        : getBwSessionState("reputation-monitoring", saved.companyName);
      setSelectedSection(session?.selectedSection || "all");
      const task = getBwTaskSnapshot(`reputation-monitoring:${saved.companyName.toLocaleLowerCase()}`);
      const taskProgress = task?.progress || {};
      setGenerating(task?.status === "running");
      setReputation(task?.result?.data || session?.reputation || null);
      setGeneratedAt(task?.result?.generatedAt || session?.generatedAt || "");
      setProgress(taskProgress.percent || (task?.result || session?.reputation ? 100 : 0));
      setProgressLabel(taskProgress.label || (task?.result || session?.reputation ? "Analysis complete" : ""));
      setError(task?.status === "error" ? task.error : "");
      setBwSessionState("reputation-monitoring", saved.companyName, {
        reputation: task?.result?.data || session?.reputation || null,
        generatedAt: task?.result?.generatedAt || session?.generatedAt || "",
        selectedSection: session?.selectedSection || "all",
        brandId: monitor.brand_id,
      });
    } catch (loadError) {
      if (!restoreCachedCompany(companyName, "Showing cached BW reputation data while backend is offline")) {
        setWorkspace(null);
        setBrandId("");
        setReputation(null);
        setError(loadError.message || "Could not load this company");
      }
    } finally {
      setLoadingCompany(false);
    }
  };

  React.useEffect(() => {
    if (!taskKey || !workspace?.companyName) return undefined;
    return subscribeBwTask(taskKey, task => {
      if (!task) return;
      const taskProgress = task.progress || {};
      setGenerating(task.status === "running");
      if (taskProgress.percent || task.status === "complete") {
        setProgress(taskProgress.percent || 100);
      }
      if (taskProgress.label || task.status === "complete") {
        setProgressLabel(taskProgress.label || "Analysis complete");
      }
      if (task.status === "error") {
        setError(task.error || "Could not generate reputation signals");
        setProgressLabel("Analysis failed");
      }
      if (task.status === "complete" && task.result) {
        setError("");
        setReputation(task.result.data);
        setGeneratedAt(task.result.generatedAt);
        setBwSessionState("reputation-monitoring", workspace.companyName, {
          reputation: task.result.data,
          generatedAt: task.result.generatedAt,
          selectedSection: task.meta?.selectedSection || selectedSection,
        });
      }
    });
  }, [taskKey, workspace?.companyName, selectedSection]);

  const runReputation = async () => {
    if (!brandId || generating || !taskKey) return;
    setError("");
    setProgress(6);
    setProgressLabel("Starting reputation analysis");
    startBwTask(
      taskKey,
      async ({ setProgress: setTaskProgress }) => {
        let current = 6;
        const timer = window.setInterval(() => {
          current = Math.min(92, current + Math.max(1, Math.round((92 - current) / 12)));
          let label = "Resolving company and preparing queries";
          if (current >= 70) label = "Classifying and mapping signals";
          else if (current >= 35) label = "Retrieving and validating evidence";
          setTaskProgress({ percent: current, label });
        }, 900);
        try {
          setTaskProgress({ percent: 6, label: "Starting reputation analysis" });
          const data = await generateBwReputationSignals(workspace.companyName, brandId, Boolean(reputation));
          return {
            data,
            generatedAt: new Date().toISOString(),
          };
        } finally {
          window.clearInterval(timer);
        }
      },
      {
        brandId,
        selectedSection,
        progress: { percent: 6, label: "Starting reputation analysis" },
      },
    );
    setBwSessionState("reputation-monitoring", workspace.companyName, {
      reputation,
      generatedAt,
      selectedSection,
      brandId,
    });
  };

  const visibleSections = selectedSection === "all"
    ? SECTION_CONFIG
    : SECTION_CONFIG.filter(section => section.key === selectedSection);
  const curatedReputation = React.useMemo(
    () => curateReputationForBw(reputation),
    [reputation],
  );

  return (
    <div className="bw-page">
      <div className="bw-page-header">
        <div className="bw-eyebrow">BW / Monitoring</div>
        <h1 className="bw-heading">Reputation Monitoring</h1>
        <p className="bw-lead">
          Generate and inspect the existing Reputation Signals analysis for a saved company.
        </p>
      </div>

      <form className="bw-company-monitor-search" onSubmit={loadCompany}>
        <label className="bw-label">
          Company name
          <input
            className="bw-input"
            value={companyInput}
            list="bw-reputation-company-options"
            onChange={event => setCompanyInput(event.target.value)}
            placeholder="Enter a saved company"
          />
          <datalist id="bw-reputation-company-options">
            {companies.map(company => (
              <option value={company.company_name} key={company.company_id} />
            ))}
          </datalist>
        </label>
        <button
          className="bw-save-button"
          type="submit"
          disabled={loadingCompany || !companyInput.trim()}
        >
          {loadingCompany ? "Loading..." : "Load Company"}
        </button>
      </form>

      {error && <div className="bw-save-notice bw-save-notice-error">{error}</div>}

      {workspace && (
        <>
          <section className="bw-section bw-reputation-controls">
            <div>
              <div className="bw-stat-label">Active Company</div>
              <div className="bw-reputation-company">{workspace.companyName}</div>
              <p className="bw-section-copy">
                Temporary analysis only. Reputation results are kept in memory for this session.
              </p>
              {generatedAt && (
                <p className="bw-section-copy">{formatGeneratedAt(generatedAt)}</p>
              )}
            </div>
            <label className="bw-label">
              Signal category
              <select
                className="bw-input"
                value={selectedSection}
                onChange={event => {
                  const value = event.target.value;
                  setSelectedSection(value);
                  setBwSessionState("reputation-monitoring", workspace.companyName, {
                    reputation,
                    generatedAt,
                    selectedSection: value,
                  });
                }}
              >
                <option value="all">All Signals</option>
                {SECTION_CONFIG.map(section => (
                  <option value={section.key} key={section.key}>{section.label}</option>
                ))}
              </select>
            </label>
            <button
              className="bw-save-button"
              type="button"
              onClick={runReputation}
              disabled={generating}
            >
              {generating
                ? "Generating Reputation Signals..."
                : reputation
                  ? "Regenerate Reputation Signals"
                  : "Generate Reputation Signals"}
            </button>
          </section>

          {(generating || progress > 0) && (
            <section className="bw-section bw-reputation-progress">
              <div className="bw-monitoring-progress-meta">
                <span>{progressLabel || "Preparing analysis"}</span>
                <span>{progress}%</span>
              </div>
              <div className="bw-monitoring-progress-track">
                <div
                  className="bw-monitoring-progress-fill"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </section>
          )}

          {!reputation && (
            <div className="bw-empty">
              {generating
                ? "Generating live reputation signals..."
                : "No reputation signals generated yet."}
            </div>
          )}

          {reputation && (
            <div className="bw-reputation-sections">
              <ReputationHealthCard reputation={curatedReputation} />
              {(reputation.classification_log || reputation.error_log || reputation.error) && (
                <section className="bw-section">
                  <h2 className="bw-section-title">Debug Logs</h2>
                  {reputation.classification_log && (
                    <p className="bw-section-copy">
                      Classification log: <strong>{reputation.classification_log}</strong>
                    </p>
                  )}
                  {reputation.error_log && (
                    <p className="bw-section-copy">Error log: <strong>{reputation.error_log}</strong></p>
                  )}
                  {reputation.error && <p className="bw-monitoring-warning">{reputation.error}</p>}
                  {reputation.bw_postprocessing?.category_debug && (
                    <div className="bw-reputation-debug-grid">
                      {SECTION_CONFIG
                        .filter(section => section.key !== "crisis_indicators")
                        .map(section => {
                          const debug = reputation.bw_postprocessing.category_debug[section.key] || {};
                          return (
                            <div className="bw-reputation-debug-card" key={section.key}>
                              <strong>{section.label}</strong>
                              <span>Raw: {(debug.raw_verified || 0) + (debug.raw_related || 0)}</span>
                              <span>Verified: {debug.verified || 0}</span>
                              <span>Related: {debug.related || 0}</span>
                              <span>Rejected: {debug.rejected || 0}</span>
                            </div>
                          );
                        })}
                    </div>
                  )}
                </section>
              )}

              {visibleSections.map(section => {
                const data = section.key === "crisis_indicators"
                  ? buildCrisisIndicators(curatedReputation)
                  : curatedReputation[section.key] || {};
                const safeData = sanitizeReputationSection(data);
                return (
                  <EvidencePanel
                    key={section.key}
                    title={section.label}
                    description={
                      section.description
                      || reputation.descriptions?.[section.key]?.short
                    }
                    items={safeData.items}
                    relatedMentions={safeData.related_mentions}
                    classification={section.classification}
                  />
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function curateReputationForBw(reputation) {
  if (!reputation) return {};
  if (reputation.bw_postprocessing) {
    return reputation;
  }
  const curated = { ...reputation };
  SECTION_CONFIG
    .filter(section => section.key !== "crisis_indicators")
    .forEach(section => {
      curated[section.key] = {
        ...(reputation[section.key] || {}),
        items: [],
        related_mentions: [],
      };
    });

  const evidenceById = new Map();
  SECTION_CONFIG
    .filter(section => section.key !== "crisis_indicators")
    .forEach(section => {
      const sourceSection = reputation[section.key] || {};
      [
        ...(sourceSection.items || []).map(item => ({ item, wasVerified: true })),
        ...(sourceSection.related_mentions || []).map(item => ({ item, wasVerified: false })),
      ].forEach(({ item, wasVerified }) => {
        const id = evidenceIdentity(item);
        if (!id) return;
        const existing = evidenceById.get(id);
        const confidence = Number(item?.confidence || 0);
        if (!existing || confidence > Number(existing.item?.confidence || 0)) {
          evidenceById.set(id, { item, wasVerified });
        }
      });
    });

  evidenceById.forEach(({ item, wasVerified }) => {
    const assignment = chooseBestCategory(item);
    if (!assignment) return;
    const section = curated[assignment.key];
    const prepared = {
      ...item,
      reason: appendCategoryReason(
        sanitizeText(item.reason),
        assignment.reason,
      ),
      bw_category_score: assignment.score,
    };
    const confidence = Number(item?.confidence || 0);
    const verified = wasVerified && confidence >= 0.65 && assignment.score >= assignment.verifiedMin;
    if (verified) {
      section.items.push(prepared);
    } else {
      section.related_mentions.push(prepared);
    }
  });

  SECTION_CONFIG
    .filter(section => section.key !== "crisis_indicators")
    .forEach(section => {
      const bucket = curated[section.key];
      bucket.items = dedupeEvidence(bucket.items)
        .sort((left, right) => Number(right?.confidence || 0) - Number(left?.confidence || 0));
      bucket.related_mentions = dedupeEvidence(bucket.related_mentions)
        .sort((left, right) => Number(right?.bw_category_score || 0) - Number(left?.bw_category_score || 0));
    });

  return curated;
}

function chooseBestCategory(item) {
  const candidates = Object.entries(CATEGORY_EVIDENCE)
    .map(([key, rule]) => {
      const score = scoreCategoryEvidence(item, key, rule);
      return {
        key,
        score,
        min: rule.min,
        verifiedMin: rule.verifiedMin,
        reason: matchedTermsReason(item, rule),
      };
    })
    .filter(candidate => candidate.score >= candidate.min)
    .sort((left, right) => right.score - left.score);
  return candidates[0] || null;
}

function scoreCategoryEvidence(item, key, rule) {
  const text = evidenceText(item);
  const matchedTerms = rule.terms.filter(term => text.includes(term));
  const signal = normalizedText(item?.signal || "");
  const classification = normalizedText(item?.classification || item?.category || "");
  const sectionWords = key.replace(/_/g, " ").replace("signals", "").replace("incidents", "");
  let score = matchedTerms.length;
  if (signal && rule.terms.some(term => signal.includes(term))) score += 2;
  if (classification && rule.terms.some(term => classification.includes(term))) score += 1;
  if (classification.includes(sectionWords.trim())) score += 1;
  return score;
}

function matchedTermsReason(item, rule) {
  const text = evidenceText(item);
  const matched = rule.terms.filter(term => text.includes(term)).slice(0, 4);
  return matched.length
    ? `Category evidence: ${matched.join(", ")}`
    : "Category evidence matched the signal metadata";
}

function evidenceText(item) {
  return normalizedText([
    item?.title,
    item?.signal,
    item?.event,
    item?.snippet,
    item?.description,
    item?.summary,
    item?.reason,
    item?.classification,
    item?.category,
    item?.source_name,
  ].filter(Boolean).join(" "));
}

function normalizedText(value) {
  return String(value || "")
    .toLocaleLowerCase()
    .replace(/[_-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function evidenceIdentity(item) {
  const url = String(item?.url || "").trim().toLocaleLowerCase().replace(/\/$/, "");
  if (url) return `url:${url}`;
  const title = normalizedText(item?.title || item?.signal || item?.snippet || "");
  const source = normalizedText(item?.source || item?.source_name || item?.publisher || "");
  return title ? `title:${source}:${title}` : "";
}

function dedupeEvidence(items) {
  const seen = new Set();
  return (items || []).filter(item => {
    const id = evidenceIdentity(item);
    if (!id || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

function appendCategoryReason(reason, categoryReason) {
  const cleanReason = sanitizeText(reason);
  if (!cleanReason) return categoryReason;
  if (cleanReason.includes(categoryReason)) return cleanReason;
  return `${cleanReason}; ${categoryReason}`;
}

function ReputationHealthCard({ reputation }) {
  const sections = SECTION_CONFIG
    .filter(section => section.key !== "crisis_indicators")
    .map(section => reputation[section.key]?.items || []);
  const verifiedSignals = sections.reduce((total, items) => total + items.length, 0);
  const relatedMentions = SECTION_CONFIG
    .filter(section => section.key !== "crisis_indicators")
    .reduce((total, section) => (
      total + (reputation[section.key]?.related_mentions || []).length
    ), 0);
  const crisisItems = buildCrisisIndicators(reputation).items;
  const highestRisk = crisisItems[0]?.signal || crisisItems[0]?.title || "Low";
  const health = verifiedSignals >= 8 || crisisItems.length >= 3
    ? "Watch"
    : verifiedSignals > 0
      ? "Stable"
      : "Healthy";

  return (
    <section className="bw-section bw-reputation-health">
      <div>
        <div className="bw-stat-label">Overall Reputation</div>
        <h2 className="bw-section-title">{health}</h2>
      </div>
      <div className="bw-monitoring-results">
        <span>Verified Signals: <strong>{verifiedSignals}</strong></span>
        <span>Related Mentions: <strong>{relatedMentions}</strong></span>
        <span>Highest Risk: <strong>{highestRisk}</strong></span>
      </div>
    </section>
  );
}

function sanitizeText(value, fallback = "Mention discusses the company but confidence was below verification threshold.") {
  const text = String(value || "").trim();
  if (!text) return text;
  if (
    text.includes("Extra data:")
    || /line\s+\d+\s+column\s+\d+/i.test(text)
    || text.includes("JSONDecodeError")
  ) {
    return fallback;
  }
  return text;
}

function sanitizeReputationSection(section) {
  return {
    ...section,
    items: (section.items || []).map(item => ({
      ...item,
      reason: sanitizeText(item.reason),
      detected_because: sanitizeText(item.detected_because),
      detectedBecause: sanitizeText(item.detectedBecause),
      verification_reason: sanitizeText(item.verification_reason),
      classification_reason: sanitizeText(item.classification_reason),
    })),
    related_mentions: (section.related_mentions || []).map(item => ({
      ...item,
      reason: sanitizeText(item.reason, "Related mention did not meet verified signal confidence."),
      detected_because: sanitizeText(item.detected_because, "Related mention did not meet verified signal confidence."),
    })),
  };
}

function buildCrisisIndicators(reputation) {
  const crisisKeys = [
    "fraud_signals",
    "layoff_signals",
    "executive_controversies",
    "security_incidents",
    "customer_complaints",
    "regulatory_signals",
  ];
  const seen = new Set();
  const items = crisisKeys.flatMap(key => reputation[key]?.items || [])
    .filter(item => Number(item?.confidence ?? 0) >= 0.7)
    .filter(item => {
      const identity = String(item?.url || item?.title || item?.signal || "").toLocaleLowerCase();
      if (!identity || seen.has(identity)) return false;
      seen.add(identity);
      return true;
    })
    .sort((left, right) => Number(right?.confidence || 0) - Number(left?.confidence || 0));
  return { items, related_mentions: [] };
}
