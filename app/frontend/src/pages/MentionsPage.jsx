import React from "react";
import ArticleCard from "../components/cards/ArticleCard";
import { NewsApiIcon, RedditIcon, YouTubeIcon } from "../components/icons/SourceIcons";
import { GoogleNewsIcon } from "../components/icons/GoogleNewsIcon";

function getAllResults(newsState, redditState, youtubeState, googleNewsState, lastBrand) {
  let results = [];
  if (lastBrand) {
    if (newsState[lastBrand] && Array.isArray(newsState[lastBrand].data)) {
      results = results.concat(newsState[lastBrand].data.map(a => ({ ...a, _source: "NewsAPI" })));
    }
    if (redditState[lastBrand] && Array.isArray(redditState[lastBrand].data)) {
      results = results.concat(redditState[lastBrand].data.map(a => ({ ...a, _source: "Reddit" })));
    }
    if (youtubeState[lastBrand] && Array.isArray(youtubeState[lastBrand].data)) {
      results = results.concat(youtubeState[lastBrand].data.map(a => ({ ...a, _source: "YouTube" })));
    }
    // In getAllResults(), add after the YouTube block:
    if (googleNewsState && googleNewsState[lastBrand] && Array.isArray(googleNewsState[lastBrand].data)) {
      results = results.concat(googleNewsState[lastBrand].data.map(a => ({ ...a, _source: "Google News" })));
    }
  }
  // Sort by published_at descending (newest first) — better than random shuffle
  results.sort((a, b) => {
    if (!a.published_at) return 1;
    if (!b.published_at) return -1;
    return new Date(b.published_at) - new Date(a.published_at);
  });
  return results;
}

const SENTIMENT_COLORS = {
  positive: { bg: "#d4f7d4", text: "#1a7a3c" },
  negative: { bg: "#ffd6d6", text: "#c0392b" },
  mixed:    { bg: "#fff3cd", text: "#8a5a00" },
  neutral:  { bg: "#f0f0f0", text: "#666" },
};

const MentionsPage = ({ newsState, redditState, youtubeState, googleNewsState, lastBrand }) => {
  const [activeFilter, setActiveFilter] = React.useState(null);
  const results = getAllResults(newsState, redditState, youtubeState, googleNewsState, lastBrand);
  const filteredResults = activeFilter
    ? results.filter(r => (r.sentiment_label || "neutral").toLowerCase() === activeFilter)
    : results;

  const handleFilterClick = type => {
    setActiveFilter(prev => prev === type ? null : type);
  };

  return (
    <div className="mentions-page">
      <h2>Mentions</h2>

      {/* Summary bar — only shows when there are results */}
      {results.length > 0 && (
        <div style={{
          display: "flex", gap: 16, marginBottom: 24, flexWrap: "wrap"
        }}>
          {["positive", "negative", "mixed", "neutral"].map(label => {
            const count = results.filter(r => (r.sentiment_label || "neutral").toLowerCase() === label).length;
            const { bg, text } = SENTIMENT_COLORS[label] || SENTIMENT_COLORS.neutral;
            const isActive = activeFilter === label;
            return (
              <button key={label} type="button" onClick={() => handleFilterClick(label)} style={{
                background: bg, color: text,
                borderRadius: 8, padding: "8px 20px",
                fontWeight: 700, fontSize: 15,
                border: isActive ? `2px solid ${text}` : "2px solid transparent",
                cursor: "pointer",
                boxShadow: isActive ? "0 0 0 3px rgba(35, 41, 70, 0.08)" : "none"
              }}>
                {label.charAt(0).toUpperCase() + label.slice(1)}: {count}
              </button>
            );
          })}
          <button type="button" onClick={() => setActiveFilter(null)} style={{
            background: "#f5f5f5", color: "#333",
            borderRadius: 8, padding: "8px 20px",
            fontWeight: 600, fontSize: 15,
            border: activeFilter === null ? "2px solid #333" : "2px solid transparent",
            cursor: "pointer"
          }}>
            Total: {results.length}
          </button>
        </div>
      )}

      {results.length === 0 ? (
        <div style={{ color: "#888", marginTop: 32 }}>
          No mentions found. Search for a brand in Sources first.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 8 }}>
          {filteredResults.length === 0 && (
            <div style={{ color: "#888", marginTop: 16 }}>
              No {activeFilter} mentions found.
            </div>
          )}
          {filteredResults.map((item, idx) => {
            let SourceIcon = null;
            if (item._source === "NewsAPI") SourceIcon = NewsApiIcon;
            else if (item._source === "Reddit") SourceIcon = RedditIcon;
            else if (item._source === "YouTube") SourceIcon = YouTubeIcon;
            else if (item._source === "Google News") SourceIcon = GoogleNewsIcon;
            return (
              <div style={{ position: "relative" }} key={idx}>
                {/* ArticleCard gets ALL fields including new ones */}
                <ArticleCard
                  {...item}
                  url={item.url}
                  published_at={item.published_at}
                  sentiment_score={item.sentiment_score}
                  primary_category={item.primary_category}
                  emotion={item.emotion}
                  renderSentimentIcon={
                    SourceIcon
                      ? <SourceIcon style={{ verticalAlign: "middle", marginRight: 6 }} />
                      : null
                  }
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default MentionsPage;
