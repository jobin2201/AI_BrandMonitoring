import { fetchGoogleNewsArticles } from "../googleNewsApi";
import { fetchArticles } from "../newsApi";
import { fetchRedditPosts } from "../redditApi";
import { fetchYouTubeVideos } from "../youtubeApi";

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

function normalizeGoogleNews(item, keyword, keywordType, searchQuery) {
  return {
    keyword,
    keywordType,
    searchQuery,
    source: "google_news",
    title: item.title || "",
    content: item.description || "",
    url: item.url || "",
    author: item.source_name || "Google News",
    sentiment: item.sentiment_label || "",
    sentimentScore: item.sentiment_score ?? null,
    sentimentConfidence: item.sentiment_confidence ?? null,
    emotion: item.emotion || "",
    emotionConfidence: item.emotion_confidence ?? null,
    primaryCategory: item.primary_category || "",
    publishedAt: item.published_at || "",
  };
}

function normalizeNewsApi(item, keyword, keywordType, searchQuery) {
  return {
    keyword,
    keywordType,
    searchQuery,
    source: "newsapi",
    title: item.title || "",
    content: item.description || item.content || "",
    url: item.url || "",
    author: item.source_name || "NewsAPI",
    sentiment: item.sentiment_label || "",
    sentimentScore: item.sentiment_score ?? null,
    sentimentConfidence: item.sentiment_confidence ?? null,
    emotion: item.emotion || "",
    emotionConfidence: item.emotion_confidence ?? null,
    primaryCategory: item.primary_category || "",
    publishedAt: item.published_at || "",
  };
}

function normalizeReddit(item, keyword, keywordType, searchQuery) {
  return {
    keyword,
    keywordType,
    searchQuery,
    source: "reddit",
    title: item.title || item.content || "",
    content: item.content || "",
    url: item.url || "",
    author: item.username || "",
    sentiment: item.sentiment_label || "",
    sentimentScore: item.sentiment_score ?? null,
    sentimentConfidence: item.sentiment_confidence ?? null,
    emotion: item.emotion || "",
    emotionConfidence: item.emotion_confidence ?? null,
    primaryCategory: item.primary_category || "",
    publishedAt: item.date || item.scraped_at || "",
  };
}

function normalizeYouTube(item, keyword, keywordType, searchQuery) {
  return {
    keyword,
    keywordType,
    searchQuery,
    source: "youtube",
    title: item.title || "",
    content: "",
    url: item.video_url || item.url || "",
    author: item.youtuber || item.channelTitle || "",
    sentiment: item.sentiment_label || "",
    sentimentScore: item.sentiment_score ?? null,
    sentimentConfidence: item.sentiment_confidence ?? null,
    emotion: item.emotion || "",
    emotionConfidence: item.emotion_confidence ?? null,
    primaryCategory: item.primary_category || "",
    publishedAt: item.published || item.published_at || "",
  };
}

const SOURCE_RUNNERS = {
  googleNews: async entry => (
    (await fetchGoogleNewsArticles(entry.searchQuery)).map(item => (
      normalizeGoogleNews(item, entry.value, entry.type, entry.searchQuery)
    ))
  ),
  newsApi: async entry => {
    const result = await fetchArticles(entry.searchQuery);
    return (result.articles || []).map(item => (
      normalizeNewsApi(item, entry.value, entry.type, entry.searchQuery)
    ));
  },
  reddit: async entry => (
    (await fetchRedditPosts(entry.searchQuery)).map(item => (
      normalizeReddit(item, entry.value, entry.type, entry.searchQuery)
    ))
  ),
  youtube: async entry => (
    (await fetchYouTubeVideos(entry.searchQuery)).map(item => (
      normalizeYouTube(item, entry.value, entry.type, entry.searchQuery)
    ))
  ),
};

function normalizeKeywordEntry(keyword, companyName) {
  const entry = typeof keyword === "string" ? { value: keyword, type: "keyword" } : keyword;
  const value = String(entry?.value || "").trim();
  const type = String(entry?.type || "keyword").trim() || "keyword";
  const company = String(companyName || "").trim();
  const needsCompanyContext = ["campaign", "executive", "product", "hashtag"].includes(type);
  const searchQuery = needsCompanyContext && company
    ? `${value} ${company}`
    : value;
  return {
    value,
    type,
    searchQuery,
  };
}

function dedupeMentions(mentions) {
  const seen = new Set();
  return mentions.filter(mention => {
    const key = [
      mention.source,
      String(mention.url || "").trim().toLocaleLowerCase()
        || String(mention.title || mention.content || "").trim().toLocaleLowerCase(),
    ].join("|");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

async function saveMonitoringMentions(companyName, mentions) {
  const response = await fetch(
    `${BASE}/api/bw/workspaces/${encodeURIComponent(companyName)}/mentions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mentions }),
    },
  );
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "Failed to save monitoring mentions");
  }
  return data;
}

export async function runBwMonitoring({
  companyName,
  keywords,
  sources,
  onProgress,
}) {
  const enabledSources = Object.keys(SOURCE_RUNNERS)
    .filter(source => sources?.[source]);
  const keywordEntries = keywords
    .map(keyword => normalizeKeywordEntry(keyword, companyName))
    .filter(entry => entry.value);
  const totalTasks = keywordEntries.length * enabledSources.length;
  let completedTasks = 0;
  const collected = [];
  const sourceCounts = {};
  const errors = [];

  for (const keyword of keywordEntries) {
    const tasks = enabledSources.map(async source => {
      try {
        const mentions = await SOURCE_RUNNERS[source](keyword);
        collected.push(...mentions);
        sourceCounts[source] = (sourceCounts[source] || 0) + mentions.length;
      } catch (error) {
        errors.push({ keyword, source, message: error.message });
      } finally {
        completedTasks += 1;
        onProgress?.({
          completedTasks,
          totalTasks,
          keyword: keyword.value,
          keywordType: keyword.type,
          collected: collected.length,
        });
      }
    });
    await Promise.allSettled(tasks);
  }

  const mentions = dedupeMentions(collected);
  const storage = await saveMonitoringMentions(companyName, mentions);
  return {
    keywords: keywordEntries.map(entry => entry.value),
    sourceCounts,
    errors,
    collected: collected.length,
    deduped: mentions.length,
    storage,
  };
}

export async function getBwMonitoringMentions(companyName) {
  const response = await fetch(
    `${BASE}/api/bw/workspaces/${encodeURIComponent(companyName)}/mentions`,
  );
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "Failed to load monitoring mentions");
  }
  return data;
}
