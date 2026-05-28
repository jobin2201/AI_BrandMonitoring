import axios from "axios";

export async function fetchArticles(brand) {
  const res = await axios.get(`http://localhost:8000/api/articles?brand=${encodeURIComponent(brand)}`);
  // Backend returns { newsapi_results, debug_source, error }
  if (res.data && Array.isArray(res.data.newsapi_results)) {
    return {
      articles: res.data.newsapi_results,
      debug_source: res.data.debug_source || null,
      error: res.data.error || null
    };
  }
  // Defensive: fallback to empty
  return { articles: [], debug_source: null, error: res.data && res.data.error ? res.data.error : null };
}
