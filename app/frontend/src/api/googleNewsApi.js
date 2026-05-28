const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function fetchGoogleNewsArticles(brand) {
  try {
    const res = await fetch(
      `${BASE}/api/google-news/search?brand=${encodeURIComponent(brand)}`
    );
    if (!res.ok) {
      console.error(`[Google News] HTTP ${res.status}: ${res.statusText}`);
      return [];
    }
    const data = await res.json();
    if (Array.isArray(data)) return data;
    console.error("[Google News] Unexpected response shape:", data);
    return [];
  } catch (err) {
    console.error("[Google News] Fetch failed:", err);
    return [];
  }
}