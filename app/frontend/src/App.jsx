
import { LinkedInIcon, TwitterIcon, InstagramIcon, CNNIcon, BBCIcon } from "./components/icons/SourceIcons";
import { GoogleNewsIcon } from "./components/icons/GoogleNewsIcon";
import React, { useState } from "react";
import DashboardLayout from "./layouts/DashboardLayout";
import Home from "./pages/Dashboard/Home.jsx";
import ArticleCard from "./components/cards/ArticleCard";
import SummaryPage from "./pages/SummaryPage";
import AIAnalysisPage from "./pages/AIAnalysisPage";
import SocialMediaPage from "./pages/SocialMediaPage";
import MentionsPage from "./pages/MentionsPage";


const PAGES = {
  mentions: "Mentions",
  sources: "Sources",
  summary: "Summary",
  ai: "AI Analysis",
  social: "Social Media",
};

function Sidebar({ current, setCurrent }) {
  return (
    <nav style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ fontWeight: 700, fontSize: 22, margin: "0 0 32px 32px", letterSpacing: 1 }}>AIBrand</div>
      {Object.entries(PAGES).map(([key, label]) => (
        <a
          key={key}
          className={"nav-link" + (current === key ? " active" : "")}
          href="#"
          style={{ marginBottom: 8 }}
          onClick={e => { e.preventDefault(); setCurrent(key); }}
        >
          {label}
        </a>
      ))}
    </nav>
  );
}

function RightPanel({ current, filters, setFilters }) {
  // Example filter UI
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
  const handleSearch = (e, brandOverride) => {
    if (e) e.preventDefault();
    const rawSearch = (brandOverride !== undefined ? brandOverride : search).trim();
    const { brand, aliases } = parseBrandInput(rawSearch);
    if (!brand) return;

    setLastBrand(brand);
    setMonitorState(prev => ({
      ...prev,
      [brand]: { ...(prev[brand] || {}), loading: true, error: "", message: "Checking stored mentions..." }
    }));

    createMonitor(brand, aliases)
      .then(monitor => {
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
      .then(({ monitor, mentions }) => {
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

  const handleRefresh = () => {
    const rawSearch = (search || lastBrand || "").trim();
    const { brand, aliases } = parseBrandInput(rawSearch);
    if (!brand) return;

    setLastBrand(brand);
    createMonitor(brand, aliases)
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
        <button type="submit" style={{ marginLeft: 8, padding: "8px 16px" }} disabled={selected === null}>🔍</button>
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
  const [current, setCurrent] = useState("sources");
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
  else content = <Home />;

  return (
    <DashboardLayout
      sidebar={<Sidebar current={current} setCurrent={setCurrent} />}
      rightPanel={<RightPanel current={current} filters={filters} setFilters={setFilters} />}
    >
      {content}
    </DashboardLayout>
  );
}
