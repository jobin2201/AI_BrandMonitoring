import React from "react";
import {
  getActiveCompanyName,
  saveCompanyWorkspace,
  setActiveCompanyName,
} from "../../../utils/bw/companyStorage";
import { buildWorkspaceKeywordEntries } from "../../../utils/bw/keywordBuilder";
import {
  getBwWorkspace,
  listBwWorkspaces,
} from "../../../api/bw/bwWorkspaceApi";
import {
  getBwMonitoringScope,
  getBwMonitoringMentions,
  runBwMonitoring,
} from "../../../api/bw/bwMonitoringApi";
import {
  activateBwSessionCompany,
  getBwTaskSnapshot,
  getBwSessionState,
  setBwSessionState,
  startBwTask,
  subscribeBwTask,
} from "../../../utils/bw/sessionCache";
import "../bwWorkspace.css";

const SOURCE_LABELS = {
  googleNews: "Google News",
  newsApi: "News API",
  reddit: "Reddit",
  youtube: "YouTube",
};

const COMPANY_SCOPE_LIMITS = {
  brand: 2,
  product: 2,
  executive: 1,
};

function uniqueEntries(entries) {
  const seen = new Set();
  return entries.filter(entry => {
    const key = `${entry.type}:${entry.value}`.toLocaleLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function scopedMonitoringEntries(entries, selectedValues) {
  const selected = new Set(selectedValues);
  const selectedEntries = entries.filter(entry => selected.has(entry.value));
  const companySelected = selectedEntries.some(entry => entry.type === "company");
  if (!companySelected) return selectedEntries;

  const counts = {};
  const companyScope = entries.filter(entry => {
    if (entry.type === "company") return true;
    const limit = COMPANY_SCOPE_LIMITS[entry.type];
    if (!limit) return false;
    counts[entry.type] = counts[entry.type] || 0;
    if (counts[entry.type] >= limit) return false;
    counts[entry.type] += 1;
    return true;
  });

  return uniqueEntries([...companyScope, ...selectedEntries]);
}

export default function BrandMonitoringPage() {
  const [workspace, setWorkspace] = React.useState(null);
  const [companyInput, setCompanyInput] = React.useState("");
  const [companies, setCompanies] = React.useState([]);
  const [loadingCompany, setLoadingCompany] = React.useState(false);
  const [generatedKeywords, setGeneratedKeywords] = React.useState([]);
  const [selectedKeywords, setSelectedKeywords] = React.useState([]);
  const [running, setRunning] = React.useState(false);
  const [progress, setProgress] = React.useState(null);
  const [result, setResult] = React.useState(null);
  const [storedTotal, setStoredTotal] = React.useState(0);
  const [error, setError] = React.useState("");
  const taskKey = workspace?.companyName
    ? `brand-monitoring:${workspace.companyName.toLocaleLowerCase()}`
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

  const restoreCompany = async companyName => {
    try {
      const saved = await getBwWorkspace(companyName);
      const cached = saveCompanyWorkspace(saved);
      const session = getBwSessionState("brand-monitoring", saved.companyName);
      setWorkspace(cached);
      setCompanyInput(saved.companyName);
      setGeneratedKeywords(buildWorkspaceKeywordEntries(saved));
      setSelectedKeywords(session?.selectedKeywords || []);
      const task = getBwTaskSnapshot(`brand-monitoring:${saved.companyName.toLocaleLowerCase()}`);
      setRunning(task?.status === "running");
      setProgress(task?.progress || null);
      setResult(task?.result || session?.result || null);
      setError(task?.status === "error" ? task.error : "");
      const mentions = await getBwMonitoringMentions(saved.companyName);
      setStoredTotal(mentions.total || 0);
    } catch (loadError) {
      setError(loadError.message);
    }
  };

  const loadCompany = async event => {
    event?.preventDefault();
    const companyName = companyInput.trim();
    if (!companyName || loadingCompany) return;
    setLoadingCompany(true);
    setError("");
    setResult(null);
    try {
      const saved = await getBwWorkspace(companyName);
      const cached = saveCompanyWorkspace(saved);
      const companyChanged = activateBwSessionCompany(saved.companyName);
      const session = companyChanged
        ? null
        : getBwSessionState("brand-monitoring", saved.companyName);
      setActiveCompanyName(saved.companyName);
      setWorkspace(cached);
      setCompanyInput(saved.companyName);
      setGeneratedKeywords(buildWorkspaceKeywordEntries(saved));
      setSelectedKeywords(session?.selectedKeywords || []);
      const mentions = await getBwMonitoringMentions(saved.companyName);
      setStoredTotal(mentions.total || 0);
      const task = getBwTaskSnapshot(`brand-monitoring:${saved.companyName.toLocaleLowerCase()}`);
      setRunning(task?.status === "running");
      setProgress(task?.progress || null);
      setResult(task?.result || session?.result || null);
      setError(task?.status === "error" ? task.error : "");
      window.dispatchEvent(new CustomEvent("bw-active-company-changed", {
        detail: { companyName: saved.companyName },
      }));
    } catch (loadError) {
      setWorkspace(null);
      setGeneratedKeywords([]);
      setSelectedKeywords([]);
      setStoredTotal(0);
      setError(loadError.status === 404
        ? `No saved workspace found for "${companyName}". Add it in Company Setup first.`
        : loadError.message);
    } finally {
      setLoadingCompany(false);
    }
  };

  React.useEffect(() => {
    if (!taskKey || !workspace?.companyName) return undefined;
    return subscribeBwTask(taskKey, task => {
      if (!task) return;
      setRunning(task.status === "running");
      setProgress(task.progress || null);
      if (task.status === "error") {
        setError(task.error || "Monitoring failed");
      }
      if (task.status === "complete" && task.result) {
        setError("");
        setResult(task.result);
        setStoredTotal(task.result.storage?.total || storedTotal);
        setBwSessionState("brand-monitoring", workspace.companyName, {
          selectedKeywords: task.meta?.selectedKeywords || selectedKeywords,
          result: task.result,
        });
      }
    });
  }, [taskKey, workspace?.companyName, selectedKeywords, storedTotal]);

  const startMonitoring = async () => {
    if (!workspace || !selectedKeywords.length || running || !taskKey) return;
    setError("");
    setResult(null);
    let monitoringEntries = [];
    try {
      const scope = await getBwMonitoringScope(workspace.companyName, selectedKeywords);
      monitoringEntries = scope.entries || [];
    } catch (scopeError) {
      setError(scopeError.message || "Failed to resolve monitoring scope");
      return;
    }
    const initialProgress = {
      completedTasks: 0,
      totalTasks: monitoringEntries.length * Object.values(workspace.sources || {}).filter(Boolean).length,
      collected: 0,
    };
    setProgress(initialProgress);
    startBwTask(
      taskKey,
      ({ setProgress: setTaskProgress }) => runBwMonitoring({
        companyName: workspace.companyName,
        keywords: monitoringEntries,
        sources: workspace.sources,
        onProgress: setTaskProgress,
      }),
      {
        selectedKeywords,
        progress: initialProgress,
      },
    );
    setBwSessionState("brand-monitoring", workspace.companyName, {
        selectedKeywords,
        result: null,
    });
  };

  const toggleKeyword = (kw) => {
    setSelectedKeywords(prev => {
      const next = prev.includes(kw) ? prev.filter(k => k !== kw) : [...prev, kw];
      if (workspace?.companyName) {
        setBwSessionState("brand-monitoring", workspace.companyName, {
          selectedKeywords: next,
          result,
        });
      }
      return next;
    });
  };

  const enabledSources = Object.entries(workspace?.sources || {})
    .filter(([, enabled]) => enabled)
    .map(([source]) => SOURCE_LABELS[source])
    .filter(Boolean);
  const effectiveMonitoringEntries = React.useMemo(
    () => scopedMonitoringEntries(generatedKeywords, selectedKeywords),
    [generatedKeywords, selectedKeywords],
  );
  const progressPercent = progress?.totalTasks
    ? Math.round((progress.completedTasks / progress.totalTasks) * 100)
    : 0;
  const mentionsReady = Boolean(result) && !running;

  const openMentionsResults = () => {
    window.history.pushState({ page: "bw-mentions" }, "", "/bw/mentions");
    window.dispatchEvent(new PopStateEvent("popstate"));
  };

  return (
    <div className="bw-page">
      <div className="bw-page-header">
        <div className="bw-eyebrow">BW / Monitoring</div>
        <h1 className="bw-heading">Brand Monitoring</h1>
        <p className="bw-lead">
          Run the configured workspace terms through the existing source APIs.
        </p>
      </div>

      <form className="bw-company-monitor-search" onSubmit={loadCompany}>
        <label className="bw-label">
          Company name
          <input
            className="bw-input"
            value={companyInput}
            list="bw-monitoring-company-options"
            onChange={event => setCompanyInput(event.target.value)}
            placeholder="Enter a saved company, for example TCS"
          />
          <datalist id="bw-monitoring-company-options">
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

      {!workspace && !error && (
        <div className="bw-empty">
          Search for a saved company to load its keywords, configured sources, and stored mentions.
        </div>
      )}

      {workspace && (
        <>
          <div className="bw-monitoring-summary">
            <div className="bw-stat">
              <div className="bw-stat-label">Company</div>
              <div className="bw-stat-value">{workspace.companyName}</div>
            </div>
            <div className="bw-stat">
              <div className="bw-stat-label">Selected Keywords</div>
              <div className="bw-stat-value">{selectedKeywords.length}</div>
            </div>
            <div className="bw-stat">
              <div className="bw-stat-label">Effective Terms</div>
              <div className="bw-stat-value">{effectiveMonitoringEntries.length}</div>
            </div>
            <div className="bw-stat">
              <div className="bw-stat-label">Stored Mentions</div>
              <div className="bw-stat-value">{storedTotal}</div>
            </div>
          </div>

          <section className="bw-section">
            <h2 className="bw-section-title">Generated Keywords</h2>
            <p className="bw-section-copy">
              Select specific chips to monitor only those terms. Selecting the company uses a focused company scope, and any extra selected chips are added to it.
            </p>
            <div className="bw-chip-list">
              {generatedKeywords.map(keyword => {
                const active = selectedKeywords.includes(keyword.value);
                return (
                  <button
                    className={`bw-chip bw-keyword-chip ${active ? "bw-chip-active" : ""}`}
                    key={keyword.value}
                    type="button"
                    aria-pressed={active}
                    onClick={() => toggleKeyword(keyword.value)}
                  >
                    <span>{keyword.value}</span>
                    <small>{keyword.label || keyword.type}</small>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="bw-section">
            <h2 className="bw-section-title">Monitoring Sources</h2>
            <p className="bw-section-copy">
              These are the source APIs enabled in Company Setup.
            </p>
            <div className="bw-chip-list">
              {enabledSources.map(source => (
                <span className="bw-chip" key={source}>{source}</span>
              ))}
            </div>

            {running && (
              <div className="bw-monitoring-progress">
                <div className="bw-monitoring-progress-meta">
                  <span>{progressPercent}% complete</span>
                  <span>{progress?.collected || 0} results collected</span>
                </div>
                <div className="bw-monitoring-progress-track">
                  <div
                    className="bw-monitoring-progress-fill"
                    style={{ width: `${progressPercent}%` }}
                  />
                </div>
                <div className="bw-monitoring-current">
                  Current keyword: {progress?.keyword || "Preparing sources"}
                </div>
              </div>
            )}

            <button
              className="bw-save-button bw-monitoring-run-button"
              type="button"
              onClick={startMonitoring}
              disabled={running || !selectedKeywords.length || !enabledSources.length}
            >
              {running ? "Monitoring..." : "Start Monitoring"}
            </button>
            <button
              className="bw-secondary-button bw-monitoring-results-button"
              type="button"
              onClick={openMentionsResults}
              disabled={!mentionsReady}
              title={mentionsReady
                ? "Open Mentions101 to inspect this run's stored results"
                : "Mentions101 will be available after monitoring reaches 100%"
              }
            >
              View Mentions Results
            </button>
          </section>

          {result && (
            <section className="bw-section">
              <h2 className="bw-section-title">Monitoring Complete</h2>
              <div className="bw-monitoring-results">
                <span>Collected: <strong>{result.collected}</strong></span>
                <span>Unique: <strong>{result.deduped}</strong></span>
                <span>Newly stored: <strong>{result.storage.added}</strong></span>
                <span>Low-confidence filtered: <strong>{result.storage.filtered || 0}</strong></span>
                <span>Duplicates skipped: <strong>{result.storage.duplicates}</strong></span>
              </div>
              <p className="bw-section-copy bw-storage-location">
                Saved to {result.storage.storageLocation}
              </p>
              {result.errors.length > 0 && (
                <div className="bw-monitoring-warning">
                  {result.errors.length} source request(s) failed. Other completed source results were still saved.
                </div>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}
