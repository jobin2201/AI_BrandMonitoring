import axios from "axios";

export async function fetchRedditPosts(brand) {
  // POST to the backend Reddit scraper endpoint
  const res = await axios.post(
    `http://localhost:8000/api/reddit/scrape-store-reddit?brand=${encodeURIComponent(brand)}`
  );
  // The backend returns the posts directly as an array
  if (Array.isArray(res.data)) return res.data;
  return [];
}
