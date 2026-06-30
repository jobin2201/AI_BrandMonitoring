
import { LinkedInIcon, TwitterIcon, InstagramIcon, CNNIcon, BBCIcon } from "./components/icons/SourceIcons";
import { GoogleNewsIcon } from "./components/icons/GoogleNewsIcon";
import React, { useEffect, useState } from "react";
import DashboardLayout from "./layouts/DashboardLayout";
import Home from "./pages/Dashboard/Home.jsx";
import ArticleCard from "./components/cards/ArticleCard";
import SummaryPage from "./pages/SummaryPage";
import AIAnalysisPage from "./pages/AIAnalysisPage";
import SocialMediaPage from "./pages/SocialMediaPage";
import MentionsPage from "./pages/MentionsPage";
import CompetitorIntelligence from "./pages/CompetitorIntelligence";
import ReputationSignals from "./pages/ReputationSignals";
import BWDashboardPage from "./pages/bw/DashboardPage";
import CompanySetupPage from "./pages/bw/BrandWorkspace/CompanySetupPage";
import WorkspaceOverviewPage from "./pages/bw/BrandWorkspace/WorkspaceOverviewPage";
import BrandMonitoringPage from "./pages/bw/Monitoring/BrandMonitoringPage";
import ReputationMonitoringPage from "./pages/bw/Monitoring/ReputationMonitoringPage";
import Mentions101Page from "./pages/bw/Mentions101Page";
import Sources101Page from "./pages/bw/Sources101Page";
import AIAnalysis101Page from "./pages/bw/AIAnalysis101Page";
import IntelligenceCenterPage from "./pages/bw/IntelligenceCenterPage";
import BWComingSoonPage from "./components/bw/BWComingSoonPage";


const PAGES = {
  mentions: "Mentions",
  sources: "Sources",
  summary: "Summary",
  ai: "AI Analysis",
  social: "Social Media",
  competitors: "Competitor Intelligence",
  reputation: "Reputation Signals",
};

const BW_ROUTES = {
  "bw-dashboard": "/bw/dashboard",
  "bw-workspace-setup": "/bw/workspace/setup",
  "bw-workspace-overview": "/bw/workspace/overview",
  "bw-monitoring-brand": "/bw/monitoring/brand",
  "bw-monitoring-reputation": "/bw/monitoring/reputation",
  "bw-monitoring-competitor": "/bw/monitoring/competitor",
  "bw-monitoring-influencer": "/bw/monitoring/influencer",
  "bw-monitoring-executive": "/bw/monitoring/executive",
  "bw-monitoring-campaign": "/bw/monitoring/campaign",
  "bw-mentions": "/bw/mentions",
  "bw-sources": "/bw/sources",
  "bw-ai-analysis": "/bw/ai-analysis",
  "bw-intelligence-center": "/bw/intelligence-center",
};

const BW_NAVIGATION = [
  { key: "bw-dashboard", label: "Dashboard" },
  {
    key: "bw-monitoring",
    label: "Monitoring",
    children: [
      { key: "bw-monitoring-brand", label: "Brand Monitoring" },
      { key: "bw-monitoring-reputation", label: "Reputation Monitoring" },
      { key: "bw-monitoring-competitor", label: "Competitor Monitoring" },
      { key: "bw-monitoring-influencer", label: "Influencer Monitoring" },
      { key: "bw-monitoring-executive", label: "Executive Monitoring" },
      { key: "bw-monitoring-campaign", label: "Campaign Monitoring" },
    ],
  },
  { key: "bw-mentions", label: "Mentions101" },
  { key: "bw-sources", label: "Sources101" },
  { key: "bw-ai-analysis", label: "AI Analysis101" },
  { key: "bw-intelligence-center", label: "Intelligence Center" },
  {
    key: "bw-workspace",
    label: "Brand Workspace",
    children: [
      { key: "bw-workspace-setup", label: "Company Setup" },
      { key: "bw-workspace-overview", label: "Workspace Overview" },
    ],
  },
];

function pageFromPath(pathname) {
  return Object.entries(BW_ROUTES).find(([, path]) => path === pathname)?.[0] || null;
}

function Sidebar({ current, setCurrent }) {
  const [oldUiOpen, setOldUiOpen] = useState(!current.startsWith("bw-"));
  const [bwOpen, setBwOpen] = useState(current.startsWith("bw-"));
  const [openGroups, setOpenGroups] = useState({
    "bw-monitoring": current.startsWith("bw-monitoring-"),
    "bw-workspace": current.startsWith("bw-workspace-"),
  });

  useEffect(() => {
    if (current.startsWith("bw-")) setBwOpen(true);
    if (current.startsWith("bw-monitoring-")) {
      setOpenGroups(groups => ({ ...groups, "bw-monitoring": true }));
    }
    if (current.startsWith("bw-workspace-")) {
      setOpenGroups(groups => ({ ...groups, "bw-workspace": true }));
    }
  }, [current]);

  const navigate = key => {
    const path = BW_ROUTES[key] || "/";
    window.history.pushState({ page: key }, "", path);
    setCurrent(key);
  };

  return (
    <nav style={{ display: "flex", flexDirection: "column", height: "100%", overflowY: "auto" }}>
      <div style={{ fontWeight: 700, fontSize: 22, margin: "0 0 32px 32px", letterSpacing: 1 }}>AIBrand</div>
      <div style={{ borderTop: "1px solid rgba(255,255,255,0.16)", paddingTop: 10 }}>
        <button
          type="button"
          aria-expanded={oldUiOpen}
          onClick={() => setOldUiOpen(open => !open)}
          style={{
            width: "100%",
            border: 0,
            borderLeft: !current.startsWith("bw-") ? "4px solid #eebbc3" : "4px solid transparent",
            background: !current.startsWith("bw-") ? "#121629" : "transparent",
            color: "#fff",
            padding: "12px 24px 12px 28px",
            font: "inherit",
            fontWeight: 750,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            textAlign: "left",
          }}
        >
          <span>Old UI</span>
          <span aria-hidden="true" style={{ fontSize: 14 }}>{oldUiOpen ? "v" : ">"}</span>
        </button>

        {oldUiOpen && (
          <div style={{ padding: "5px 0 2px" }}>
            {Object.entries(PAGES).map(([key, label]) => (
              <a
                key={key}
                href="#"
                onClick={e => { e.preventDefault(); navigate(key); }}
                style={{
                  display: "block",
                  color: "#fff",
                  textDecoration: "none",
                  padding: "9px 18px 9px 40px",
                  background: current === key ? "#121629" : "transparent",
                  borderLeft: current === key ? "4px solid #eebbc3" : "4px solid transparent",
                  fontSize: 15,
                  lineHeight: 1.25,
                }}
              >
                {label}
              </a>
            ))}
          </div>
        )}
      </div>
      <div style={{ marginTop: 10, borderTop: "1px solid rgba(255,255,255,0.16)", paddingTop: 10 }}>
        <button
          type="button"
          aria-expanded={bwOpen}
          onClick={() => setBwOpen(open => !open)}
          style={{
            width: "100%",
            border: 0,
            borderLeft: current.startsWith("bw-") ? "4px solid #eebbc3" : "4px solid transparent",
            background: current.startsWith("bw-") ? "#121629" : "transparent",
            color: "#fff",
            padding: "12px 24px 12px 28px",
            font: "inherit",
            fontWeight: 750,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            textAlign: "left",
          }}
        >
          <span>BW</span>
          <span aria-hidden="true" style={{ fontSize: 14 }}>{bwOpen ? "v" : ">"}</span>
        </button>

        {bwOpen && (
          <div style={{ padding: "5px 0 2px" }}>
            {BW_NAVIGATION.map(item => (
              item.children ? (
                <div key={item.key}>
                  <button
                    type="button"
                    aria-expanded={Boolean(openGroups[item.key])}
                    onClick={() => setOpenGroups(groups => ({
                      ...groups,
                      [item.key]: !groups[item.key],
                    }))}
                    style={{
                      width: "100%",
                      border: 0,
                      background: "transparent",
                      color: "#dbe2ff",
                      padding: "9px 22px 9px 40px",
                      font: "inherit",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      textAlign: "left",
                    }}
                  >
                    <span>{item.label}</span>
                    <span aria-hidden="true">{openGroups[item.key] ? "-" : "+"}</span>
                  </button>
                  {openGroups[item.key] && item.children.map(child => (
                    <a
                      key={child.key}
                      href={BW_ROUTES[child.key]}
                      onClick={event => {
                        event.preventDefault();
                        navigate(child.key);
                      }}
                      style={{
                        display: "block",
                        color: "#fff",
                        textDecoration: "none",
                        padding: "9px 18px 9px 56px",
                        background: current === child.key ? "#121629" : "transparent",
                        borderLeft: current === child.key ? "4px solid #eebbc3" : "4px solid transparent",
                        fontSize: 14,
                      }}
                    >
                      {child.label}
                    </a>
                  ))}
                </div>
              ) : (
                <a
                  key={item.key}
                  href={BW_ROUTES[item.key]}
                  onClick={event => {
                    event.preventDefault();
                    navigate(item.key);
                  }}
                  style={{
                    display: "block",
                    color: "#fff",
                    textDecoration: "none",
                    padding: "9px 18px 9px 40px",
                    background: current === item.key ? "#121629" : "transparent",
                    borderLeft: current === item.key ? "4px solid #eebbc3" : "4px solid transparent",
                    fontSize: 15,
                  }}
                >
                  {item.label}
                </a>
              )
            ))}
          </div>
        )}
      </div>
    </nav>
  );
}

function RightPanel({
  current,
  filters,
  setFilters,
  bwSourceFilters,
  setBwSourceFilters,
  bwDateFilters,
  setBwDateFilters,
}) {
  if (
    current === "bw-mentions"
    || current === "bw-sources"
    || current === "bw-intelligence-center"
  ) {
    const bwSources = [
      ["google_news", "Google News"],
      ["newsapi", "News API"],
      ["reddit", "Reddit"],
      ["youtube", "YouTube"],
    ];
    return (
      <div>
        <div style={{ fontWeight: 600, marginBottom: 16 }}>BW Source Filters</div>
        {bwSources.map(([key, label]) => (
          <label style={{ display: "block", marginBottom: 10 }} key={key}>
            <input
              type="checkbox"
              checked={bwSourceFilters[key]}
              onChange={event => setBwSourceFilters(currentFilters => ({
                ...currentFilters,
                [key]: event.target.checked,
              }))}
            />{" "}
            {label}
          </label>
        ))}
        <div style={{ fontWeight: 600, margin: "24px 0 10px" }}>Date Range</div>
        <label style={{ display: "grid", gap: 5, marginBottom: 10, fontSize: 13 }}>
          Start date
          <input
            type="date"
            value={bwDateFilters.startDate}
            max={bwDateFilters.endDate}
            onChange={event => setBwDateFilters(currentFilters => ({
              ...currentFilters,
              startDate: event.target.value,
            }))}
            style={{ width: "100%", boxSizing: "border-box" }}
          />
        </label>
        <label style={{ display: "grid", gap: 5, marginBottom: 10, fontSize: 13 }}>
          End date
          <input
            type="date"
            value={bwDateFilters.endDate}
            min={bwDateFilters.startDate}
            max={todayDateValue()}
            onChange={event => setBwDateFilters(currentFilters => ({
              ...currentFilters,
              endDate: event.target.value || todayDateValue(),
            }))}
            style={{ width: "100%", boxSizing: "border-box" }}
          />
        </label>
        <p style={{ marginTop: 20, color: "#6b7280", fontSize: 12, lineHeight: 1.5 }}>
          These filters apply only to Mentions101 and Sources101.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div style={{ fontWeight: 600, marginBottom: 16 }}>Filter Sources</div>
      <label style={{ display: "block", marginBottom: 8 }}>
        <input type="checkbox" checked={filters.news} onChange={e => setFilters(f => ({ ...f, news: e.target.checked }))} /> NewsAPI
      </label>
      <label style={{ display: "block", marginBottom: 8 }}>
        <input type="checkbox" checked={filters.reddit} onChange={e => setFilters(f => ({ ...f, reddit: e.target.checked }))} /> Reddit
      </label>
      <label style={{ display: "block", marginBottom: 8 }}>
        <input type="checkbox" checked={filters.facebook} onChange={e => setFilters(f => ({ ...f, facebook: e.target.checked }))} /> Facebook
      </label>
      <div style={{ fontWeight: 600, margin: "24px 0 8px 0" }}>Date Range</div>
      <input type="date" value={filters.startDate} onChange={e => setFilters(f => ({ ...f, startDate: e.target.value }))} style={{ marginBottom: 8, width: "100%" }} />
      <input type="date" value={filters.endDate} onChange={e => setFilters(f => ({ ...f, endDate: e.target.value }))} style={{ width: "100%" }} />
    </div>
  );
}

const SOURCES = [
  { name: "NewsAPI", desc: "News articles from NewsAPI", links: ["https://newsapi.org/"] },
  { name: "Reddit", desc: "Reddit posts", links: ["https://reddit.com/"] },
  { name: "Facebook", desc: "Facebook posts", links: ["https://facebook.com/"] },
  { name: "YouTube", desc: "YouTube videos", links: ["https://youtube.com/"] },
  { name: "LinkedIn", desc: "LinkedIn posts", links: ["https://linkedin.com/"] },
  { name: "Twitter", desc: "Tweets from Twitter", links: ["https://twitter.com/"] },
  { name: "Instagram", desc: "Instagram posts", links: ["https://instagram.com/"] },
  { name: "CNN", desc: "CNN News", links: ["https://cnn.com/"] },
  { name: "BBC", desc: "BBC News", links: ["https://bbc.com/"] },
  { name: "Google News", desc: "Google News web results", links: ["https://news.google.com/home?hl=en-IN&gl=IN&ceid=IN:en"] },
];



import { createMonitor, getMentions, runMonitorBrand } from "./api/monitorsApi";
import { NewsApiIcon, RedditIcon, FacebookIcon, YouTubeIcon } from "./components/icons/SourceIcons";
import dayjs from "dayjs";

function SourcesPage({
  filters, setFilters,
  selected, setSelected,
  search, setSearch,
  lastBrand, setLastBrand,
  newsState, setNewsState,
  redditState, setRedditState,
  youtubeState, setYouTubeState,
  googleNewsState, setGoogleNewsState,
  monitorState, setMonitorState
}) {
  const [disambiguation, setDisambiguation] = React.useState(null);

  // Helper to get current source state
  const getSourceState = () => {
    if (selected === null || !lastBrand) return { loading: false, error: "", data: [], pipelineLog: [] };
    if (SOURCES[selected].name === "NewsAPI") return newsState[lastBrand] || { loading: false, error: "", data: [], pipelineLog: [] };
    if (SOURCES[selected].name === "Reddit") return redditState[lastBrand] || { loading: false, error: "", data: [], pipelineLog: [] };
    if (SOURCES[selected].name === "YouTube") return youtubeState[lastBrand] || { loading: false, error: "", data: [], pipelineLog: [] };
    if (SOURCES[selected].name === "Google News") return googleNewsState[lastBrand] || { loading: false, error: "", data: [], pipelineLog: [] };
    return { loading: false, error: "", data: [], pipelineLog: [] };
  };


  const setStoredMentionStates = (brand, mentions, counts = {}) => {
    const bySource = {
      newsapi: [],
      reddit: [],
      youtube: [],
      google_news: []
    };

    (mentions || []).forEach(mention => {
      const source = (mention.source || "").toLowerCase();
      if (bySource[source]) {
        bySource[source].push({
          ...mention,
          source,
          source_name: source
        });
      }
    });

    setNewsState(prev => ({
      ...prev,
      [brand]: {
        loading: false,
        error: "",
        data: bySource.newsapi,
        pipelineLog: [`Stored NewsAPI mentions: ${bySource.newsapi.length}`, `Matched this run: ${counts.newsapi || 0}`]
      }
    }));
    setRedditState(prev => ({
      ...prev,
      [brand]: {
        loading: false,
        error: "",
        data: bySource.reddit,
        pipelineLog: [`Stored Reddit mentions: ${bySource.reddit.length}`, `Matched this run: ${counts.reddit || 0}`]
      }
    }));
    setYouTubeState(prev => ({
      ...prev,
      [brand]: {
        loading: false,
        error: "",
        data: bySource.youtube,
        pipelineLog: [`Stored YouTube mentions: ${bySource.youtube.length}`, `Matched this run: ${counts.youtube || 0}`]
      }
    }));
    setGoogleNewsState(prev => ({
      ...prev,
      [brand]: {
        loading: false,
        error: "",
        data: bySource.google_news,
        pipelineLog: [`Stored Google News mentions: ${bySource.google_news.length}`, `Matched this run: ${counts.google_news || 0}`]
      }
    }));
  };

  const countMentionSources = mentions => {
    return (mentions || []).reduce((counts, mention) => {
      const source = (mention.source || "").toLowerCase();
      if (source) {
        counts[source] = (counts[source] || 0) + 1;
      }
      return counts;
    }, {});
  };

  const hasRedditMentions = mentions => (countMentionSources(mentions).reddit || 0) > 0;

  const waitFor = ms => new Promise(resolve => setTimeout(resolve, ms));

  const setAllSourcesLoading = brand => {
    const loadingState = { loading: true, error: "", data: [], pipelineLog: ["Waiting for single-brand monitor..."] };
    setNewsState(prev => ({ ...prev, [brand]: loadingState }));
    setRedditState(prev => ({ ...prev, [brand]: loadingState }));
    setYouTubeState(prev => ({ ...prev, [brand]: loadingState }));
    setGoogleNewsState(prev => ({ ...prev, [brand]: loadingState }));
  };

  const parseBrandInput = value => {
    const [brand, ...aliasParts] = value
      .trim()
      .split(",")
      .map(part => part.trim())
      .filter(Boolean);
    return {
      brand,
      aliases: aliasParts.join(",")
    };
  };

  const loadStoredMentions = (brand, counts = {}) => {
    return getMentions(brand).then(mentions => {
      setStoredMentionStates(brand, mentions, counts);
      return mentions;
    });
  };

  const loadStoredMentionsWithRedditRetry = async (brand, counts = {}, attempts = 3) => {
    let mentions = [];
    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      mentions = await loadStoredMentions(brand, counts);
      if (hasRedditMentions(mentions) || attempt === attempts) {
        return mentions;
      }
      await waitFor(900);
    }
    return mentions;
  };

  const runBrandRefresh = (brand, brandId, statusMessage = "No stored mentions yet. Running first collection...") => {
    setAllSourcesLoading(brand);
    setMonitorState(prev => ({
      ...prev,
      [brand]: {
        ...(prev[brand] || {}),
        brand_id: brandId,
        loading: true,
        error: "",
        message: statusMessage
      }
    }));

    return runMonitorBrand(brandId)
      .then(result => {
        return loadStoredMentionsWithRedditRetry(brand, result.counts || {}).then(mentions => ({ result, mentions }));
      })
      .then(({ result, mentions }) => {
        setMonitorState(prev => ({
          ...prev,
          [brand]: {
            ...(prev[brand] || {}),
            brand_id: brandId,
            loading: false,
            error: "",
            message: `Refresh complete. Showing ${mentions.length} stored mentions.`
          }
        }));
        return { result, mentions };
      });
  };

  // Search handler: first search scrapes, repeated searches load cached DB mentions.
  const handleSearch = (e, brandOverride, confirmed = false, aliasesOverride = null) => {
    if (e) e.preventDefault();
    const rawSearch = (brandOverride !== undefined ? brandOverride : search).trim();
    const { brand, aliases: parsedAliases } = parseBrandInput(rawSearch);
    const aliases = aliasesOverride !== null ? aliasesOverride : parsedAliases;
    if (!brand) return;

    setLastBrand(brand);
    if (!confirmed) {
      setDisambiguation(null);
    }
    setMonitorState(prev => ({
      ...prev,
      [brand]: { ...(prev[brand] || {}), loading: true, error: "", message: "Checking stored mentions..." }
    }));

    createMonitor(brand, aliases, confirmed)
      .then(monitor => {
        if (monitor.status === "needs_disambiguation") {
          setDisambiguation({
            brand,
            options: monitor.options || [],
            message: monitor.message || `We found multiple possible entities for "${brand}".`
          });
          setMonitorState(prev => ({
            ...prev,
            [brand]: {
              ...(prev[brand] || {}),
              loading: false,
              error: "",
              message: "Please choose the entity you want to monitor."
            }
          }));
          return null;
        }

        setDisambiguation(null);
        setMonitorState(prev => ({
          ...prev,
          [brand]: {
            ...(prev[brand] || {}),
            brand_id: monitor.brand_id,
            loading: true,
            error: "",
            message: "Monitor saved. Loading stored mentions..."
          }
        }));
        return loadStoredMentions(brand).then(mentions => ({ monitor, mentions }));
      })
      .then(payload => {
        if (!payload) return null;
        const { monitor, mentions } = payload;
        const sourceCounts = countMentionSources(mentions);

        if (mentions.length > 0 && sourceCounts.reddit > 0 && sourceCounts.youtube >= 5) {
          setMonitorState(prev => ({
            ...prev,
            [brand]: {
              ...(prev[brand] || {}),
              brand_id: monitor.brand_id,
              loading: false,
              error: "",
              message: `Loaded ${mentions.length} stored mentions from DB, including ${sourceCounts.reddit} Reddit posts.`
            }
          }));
          return null;
        }

        if (mentions.length > 0 && sourceCounts.youtube < 5) {
          return runBrandRefresh(brand, monitor.brand_id, "YouTube cache has fewer than 5 videos. Refreshing this brand once...");
        }

        if (mentions.length > 0) {
          return runBrandRefresh(brand, monitor.brand_id, "Reddit is missing from cache. Refreshing this brand once...");
        }

        return runBrandRefresh(brand, monitor.brand_id);
      })
      .catch(error => {
        const errorState = {
          loading: false,
          error: error.message || "Could not start monitoring",
          data: [],
          pipelineLog: ["Single-brand monitor failed"]
        };
        setNewsState(prev => ({ ...prev, [brand]: errorState }));
        setRedditState(prev => ({ ...prev, [brand]: errorState }));
        setYouTubeState(prev => ({ ...prev, [brand]: errorState }));
        setGoogleNewsState(prev => ({ ...prev, [brand]: errorState }));
        setMonitorState(prev => ({
          ...prev,
          [brand]: {
            loading: false,
            error: error.message || "Could not start monitoring",
            message: ""
          }
        }));
      });
  };

  const handleDisambiguationSelect = option => {
    const selectedBrand = (option.search_value || option.label || disambiguation?.brand || "").trim();
    const aliases = Array.isArray(option.aliases) ? option.aliases.join(",") : (option.aliases || "");
    if (!selectedBrand) return;

    setSearch(selectedBrand);
    setLastBrand(selectedBrand);
    setDisambiguation(null);
    handleSearch(null, selectedBrand, true, aliases);
  };

  const handleRefresh = () => {
    const rawSearch = (search || lastBrand || "").trim();
    const { brand, aliases } = parseBrandInput(rawSearch);
    if (!brand) return;

    setLastBrand(brand);
    createMonitor(brand, aliases, true)
      .then(monitor => runBrandRefresh(brand, monitor.brand_id, "Force refreshing this brand..."))
      .catch(error => {
        const errorState = {
          loading: false,
          error: error.message || "Could not refresh monitoring",
          data: [],
          pipelineLog: ["Forced brand refresh failed"]
        };
        setNewsState(prev => ({ ...prev, [brand]: errorState }));
        setRedditState(prev => ({ ...prev, [brand]: errorState }));
        setYouTubeState(prev => ({ ...prev, [brand]: errorState }));
        setGoogleNewsState(prev => ({ ...prev, [brand]: errorState }));
        setMonitorState(prev => ({
          ...prev,
          [brand]: {
            ...(prev[brand] || {}),
            loading: false,
            error: error.message || "Could not refresh monitoring",
            message: ""
          }
        }));
      });
  };

  // When switching sources, just update search field and let per-source state drive UI
  React.useEffect(() => {
    if (selected !== null && lastBrand) {
      setSearch(lastBrand);
    }
  }, [selected]);

  // Destructure state for selected source/brand
  const { loading, error, data: articles, pipelineLog, debug_source } = getSourceState();
  const currentMonitor = lastBrand ? monitorState[lastBrand] : null;

  // Always show search bar for all sources
  const showSearch = selected !== null;

  return (
    <div>
      <h2>Sources</h2>
      {/* Search bar always on top, enabled for all sources */}
      <form onSubmit={handleSearch} style={{ display: "flex", marginBottom: 24, maxWidth: 720 }}>
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Brand or Brand, Alias 1, Alias 2"
          style={{ flex: 1, padding: 8, fontSize: 16 }}
          disabled={selected === null}
        />
        <button type="submit" style={{ marginLeft: 8, padding: "8px 16px" }} disabled={selected === null}>ðŸ”</button>
        <button
          type="button"
          onClick={handleRefresh}
          style={{ marginLeft: 8, padding: "8px 16px" }}
          disabled={selected === null || !(search || lastBrand) || currentMonitor?.loading}
        >
          Refresh
        </button>
      </form>
      {currentMonitor && (currentMonitor.message || currentMonitor.error) && (
        <div
          style={{
            maxWidth: 720,
            margin: "-8px 0 24px 0",
            padding: "12px 14px",
            borderRadius: 8,
            background: currentMonitor.error ? "#fff1f2" : "#eefbf3",
            color: currentMonitor.error ? "#9f1239" : "#166534",
            border: currentMonitor.error ? "1px solid #fecdd3" : "1px solid #bbf7d0",
            fontWeight: 500
          }}
        >
          {currentMonitor.loading ? "Starting monitor: " : ""}
          {currentMonitor.error || currentMonitor.message}
        </div>
      )}
      {disambiguation && (
        <div
          style={{
            maxWidth: 720,
            margin: "-8px 0 24px 0",
            padding: "14px 16px",
            borderRadius: 8,
            background: "#eefbf3",
            color: "#14532d",
            border: "1px solid #bbf7d0",
            boxShadow: "0 1px 4px rgba(22, 101, 52, 0.08)"
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 6 }}>
            {disambiguation.message || `We found multiple possible entities for "${disambiguation.brand}".`}
          </div>
          <div style={{ fontSize: 14, marginBottom: 12 }}>
            Select the meaning you want to monitor. I will update the search box and run that search directly.
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {(disambiguation.options || []).map(option => (
              <button
                key={`${option.id}-${option.search_value}-${option.label}`}
                type="button"
                onClick={() => handleDisambiguationSelect(option)}
                style={{
                  width: "100%",
                  textAlign: "left",
                  padding: "10px 12px",
                  borderRadius: 6,
                  border: "1px solid #86efac",
                  background: "#ffffff",
                  color: "#14532d",
                  cursor: "pointer"
                }}
              >
                <div style={{ fontWeight: 700 }}>{option.label}</div>
                {option.description && (
                  <div style={{ fontSize: 13, marginTop: 3, color: "#166534" }}>{option.description}</div>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 24 }}>
        {SOURCES.map((src, idx) => {
          let Icon = NewsApiIcon;
          if (src.name === "Reddit") Icon = RedditIcon;
          if (src.name === "Facebook") Icon = FacebookIcon;
          if (src.name === "YouTube") Icon = YouTubeIcon;
          if (src.name === "LinkedIn") Icon = LinkedInIcon;
          if (src.name === "Twitter") Icon = TwitterIcon;
          if (src.name === "Instagram") Icon = InstagramIcon;
          if (src.name === "CNN") Icon = CNNIcon;
          if (src.name === "BBC") Icon = BBCIcon;
          if (src.name === "Google News") Icon = GoogleNewsIcon;
          return (
            <div
              key={src.name}
              style={{
                background: "#fff",
                borderRadius: 12,
                boxShadow: selected === idx ? "0 0 0 4px #eebbc3aa, 0 2px 8px #eaeaea" : "0 2px 8px #eaeaea",
                padding: 24,
                minWidth: 180,
                cursor: "pointer",
                flex: "1 0 180px",
                maxWidth: 220,
                border: selected === idx ? "2px solid #eebbc3" : "2px solid transparent",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                transition: "box-shadow 0.25s, border 0.25s, transform 0.18s, background 0.3s",
                position: "relative",
                overflow: "hidden",
                outline: selected === idx ? "2px solid #eebbc3" : "none"
              }}
              onClick={() => setSelected(idx)}
              onMouseEnter={e => e.currentTarget.style.boxShadow = "0 0 16px 4px #eebbc3cc, 0 8px 32px 0 #23294644"}
              onMouseLeave={e => e.currentTarget.style.boxShadow = selected === idx ? "0 0 0 4px #eebbc3aa, 0 2px 8px #eaeaea" : "0 2px 8px #eaeaea"}
            >
              <div style={{ marginBottom: 12 }}><Icon /></div>
              <div style={{ fontWeight: 600, fontSize: 18 }}>{src.name}</div>
              <div style={{ color: "#555", fontSize: 14, margin: "8px 0 0 0", textAlign: "center" }}>{src.desc}</div>
            </div>
          );
        })}
      </div>
      {/* Show output and info below cards if selected */}
      {showSearch && (
        <div style={{ marginTop: 32 }}>
          {/* Links heading with count right-aligned */}
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
            <h3 style={{ margin: 0, flex: 1, textAlign: 'left' }}>{SOURCES[selected].name} Links</h3>
            {/* Compute filtered count for NewsAPI or Reddit */}
            <span style={{ fontWeight: 500, color: '#232946', fontSize: 18, textAlign: 'right', minWidth: 60 }}>
              {(() => {
                let filtered = articles;
                if (Array.isArray(articles)) {
                  filtered = articles.filter(article => {
                    if (SOURCES[selected].name === "NewsAPI" && !filters.news) return false;
                    if (SOURCES[selected].name === "Reddit" && !filters.reddit) return false;
                    if (SOURCES[selected].name === "YouTube") {
                      // No filter for news/reddit, but filter by date if set
                      if (!filters.startDate && !filters.endDate) return true;
                      const pub = article.published_at ? dayjs(article.published_at) : (article.published ? dayjs(article.published) : null);
                      if (!pub) return false;
                      if (filters.startDate && pub.isBefore(dayjs(filters.startDate))) return false;
                      if (filters.endDate && pub.isAfter(dayjs(filters.endDate).endOf('day'))) return false;
                      return true;
                    }
                    if (!filters.startDate && !filters.endDate) return true;
                    const pub = article.published_at ? dayjs(article.published_at) : null;
                    if (!pub) return false;
                    if (filters.startDate && pub.isBefore(dayjs(filters.startDate))) return false;
                    if (filters.endDate && pub.isAfter(dayjs(filters.endDate).endOf('day'))) return false;
                    return true;
                  });
                }
                return filtered.length;
              })()}
            </span>
          </div>
          {SOURCES[selected].links.map(link => (
            <div key={link} style={{ marginBottom: 8 }}>
              <a href={link} target="_blank" rel="noopener noreferrer" style={{ color: "#232946", textDecoration: "underline", fontWeight: 500 }}>{link}</a>
            </div>
          ))}
          {/* Show search results and pipeline info */}
          <div style={{ marginTop: 32 }}>
            {loading && <p>Loading...</p>}
            {error && <p style={{ color: "red" }}>{error}</p>}
            {/* Show debug source for NewsAPI */}
            {SOURCES[selected].name === "NewsAPI" && debug_source && (
              <div style={{ color: '#555', fontStyle: 'italic', marginBottom: 8 }}>
                Source: {debug_source === 'newsapi' ? 'NewsAPI' : debug_source === 'beautifulsoup' ? 'Google News Webscraper' : debug_source}
              </div>
            )}
            {!error && articles.length === 0 && !loading && search && (
              <p style={{ color: '#888', fontStyle: 'italic' }}>No {SOURCES[selected].name} results found for "{search}".</p>
            )}
            {/* Filter by date range if set */}
            {articles && Array.isArray(articles) && articles.length > 0 &&
              articles
                .filter(article => {
                  if (SOURCES[selected].name === "NewsAPI" && !filters.news) return false;
                  if (SOURCES[selected].name === "Reddit" && !filters.reddit) return false;
                  if (SOURCES[selected].name === "YouTube") {
                    // No filter for news/reddit, but filter by date if set
                    if (!filters.startDate && !filters.endDate) return true;
                    const pub = article.published_at ? dayjs(article.published_at) : (article.published ? dayjs(article.published) : null);
                    if (!pub) return false;
                    if (filters.startDate && pub.isBefore(dayjs(filters.startDate))) return false;
                    if (filters.endDate && pub.isAfter(dayjs(filters.endDate).endOf('day'))) return false;
                    return true;
                  }
                  if (!filters.startDate && !filters.endDate) return true;
                  const pub = article.published_at ? dayjs(article.published_at) : null;
                  if (!pub) return false;
                  if (filters.startDate && pub.isBefore(dayjs(filters.startDate))) return false;
                  if (filters.endDate && pub.isAfter(dayjs(filters.endDate).endOf('day'))) return false;
                  return true;
                })
                .map((article, idx) => {
                  if (SOURCES[selected].name === "YouTube") {
                    // ArticleCard already wraps itself in <a> if url is present
                    return (
                      <ArticleCard
                        key={idx}
                        {...article}
                        title={article.title}
                        source_name={article.source_name}
                        url={article.url}
                        published_at={article.published_at}
                      />
                    );
                  }
                  // NewsAPI/Reddit
                  return (
                    <ArticleCard key={idx} {...article} url={article.url} published_at={article.published_at} />
                  );
                })}
            {/* Defensive: show error if articles is not an array */}
            {articles && !Array.isArray(articles) && (
              <div style={{ color: 'red', marginTop: 16 }}>
                Unexpected response from backend. Please check API and try again.
              </div>
            )}
            {/* Pipeline log output */}
            {pipelineLog.length > 0 && (
              <div style={{ background: "#232946", color: "#fff", borderRadius: 8, padding: 20, marginTop: 32, fontFamily: "monospace", fontSize: 15 }}>
                {pipelineLog.map((line, i) => (
                  <div key={i} style={{ marginBottom: 4, whiteSpace: "pre-line" }}>{line}</div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
// End of SourcesPage

export default function App() {
  const [current, setCurrent] = useState(() => pageFromPath(window.location.pathname) || "bw-dashboard");
  const [filters, setFilters] = useState({ news: true, reddit: true, facebook: true, startDate: "", endDate: "" });
  // SourcesPage state lifted to App
  const [selected, setSelected] = useState(0);
  const [search, setSearch] = useState("");
  const [lastBrand, setLastBrand] = useState("");
  const [newsState, setNewsState] = useState({});
  const [redditState, setRedditState] = useState({});
  const [youtubeState, setYouTubeState] = useState({});
  const [googleNewsState, setGoogleNewsState] = useState({});
  const [monitorState, setMonitorState] = useState({});
  const [competitorState, setCompetitorState] = useState({});
  const [reputationState, setReputationState] = useState({});
  const [bwSourceFilters, setBwSourceFilters] = useState({
    google_news: true,
    newsapi: true,
    reddit: true,
    youtube: true,
  });
  const [bwDateFilters, setBwDateFilters] = useState({
    startDate: "",
    endDate: todayDateValue(),
  });

  useEffect(() => {
    const handlePopState = () => {
      setCurrent(pageFromPath(window.location.pathname) || "bw-dashboard");
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  let content;
  if (current === "mentions") content = (
    <MentionsPage
      newsState={newsState}
      redditState={redditState}
      youtubeState={youtubeState}
      googleNewsState={googleNewsState}
      lastBrand={lastBrand}
    />
  );
  else if (current === "sources") {
    content = (
      <SourcesPage
        filters={filters}
        setFilters={setFilters}
        selected={selected}
        setSelected={setSelected}
        search={search}
        setSearch={setSearch}
        lastBrand={lastBrand}
        setLastBrand={setLastBrand}
        newsState={newsState}
        setNewsState={setNewsState}
        redditState={redditState}
        setRedditState={setRedditState}
        youtubeState={youtubeState}
        setYouTubeState={setYouTubeState}
        googleNewsState={googleNewsState}
        setGoogleNewsState={setGoogleNewsState}
        monitorState={monitorState}
        setMonitorState={setMonitorState}
      />
    );
  } else if (current === "summary") content = <SummaryPage />;
  else if (current === "ai") content = <AIAnalysisPage />;
  else if (current === "social") content = <SocialMediaPage />;
  else if (current === "competitors") content = (
    <CompetitorIntelligence
      lastBrand={lastBrand}
      monitorState={monitorState}
      competitorState={competitorState}
      setCompetitorState={setCompetitorState}
    />
  );
  else if (current === "reputation") content = (
    <ReputationSignals
      lastBrand={lastBrand}
      monitorState={monitorState}
      reputationState={reputationState}
      setReputationState={setReputationState}
    />
  );
  else if (current === "bw-dashboard") content = <BWDashboardPage />;
  else if (current === "bw-workspace-setup") content = <CompanySetupPage />;
  else if (current === "bw-workspace-overview") content = <WorkspaceOverviewPage />;
  else if (current === "bw-monitoring-brand") content = <BrandMonitoringPage />;
  else if (current === "bw-mentions") content = (
    <Mentions101Page sourceFilters={bwSourceFilters} dateFilters={bwDateFilters} />
  );
  else if (current === "bw-sources") content = (
    <Sources101Page sourceFilters={bwSourceFilters} dateFilters={bwDateFilters} />
  );
  else if (current === "bw-monitoring-reputation") content = <ReputationMonitoringPage />;
  else if (current === "bw-monitoring-competitor") content = <BWComingSoonPage section="Monitoring" title="Competitor Monitoring" />;
  else if (current === "bw-monitoring-influencer") content = <BWComingSoonPage section="Monitoring" title="Influencer Monitoring" />;
  else if (current === "bw-monitoring-executive") content = <BWComingSoonPage section="Monitoring" title="Executive Monitoring" />;
  else if (current === "bw-monitoring-campaign") content = <BWComingSoonPage section="Monitoring" title="Campaign Monitoring" />;
  else if (current === "bw-ai-analysis") content = <AIAnalysis101Page />;
  else if (current === "bw-intelligence-center") content = (
    <IntelligenceCenterPage
      sourceFilters={bwSourceFilters}
      dateFilters={bwDateFilters}
    />
  );
  else content = <Home />;

  return (
    <DashboardLayout
      sidebar={<Sidebar current={current} setCurrent={setCurrent} />}
      rightPanel={(
        <RightPanel
          current={current}
          filters={filters}
          setFilters={setFilters}
          bwSourceFilters={bwSourceFilters}
          setBwSourceFilters={setBwSourceFilters}
          bwDateFilters={bwDateFilters}
          setBwDateFilters={setBwDateFilters}
        />
      )}
    >
      {content}
    </DashboardLayout>
  );
}

function todayDateValue() {
  const today = new Date();
  const offset = today.getTimezoneOffset() * 60000;
  return new Date(today.getTime() - offset).toISOString().slice(0, 10);
}

