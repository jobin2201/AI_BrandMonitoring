import axios from "axios";

export async function fetchYouTubeVideos(brand) {
  const res = await axios.post(
    `http://localhost:8000/api/youtube/scrape-store-youtube?brand=${encodeURIComponent(brand)}`
  );
  if (Array.isArray(res.data)) return res.data;
  return [];
}
