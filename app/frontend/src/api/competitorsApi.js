const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function readJson(res, fallbackMessage) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || fallbackMessage);
  }
  return data;
}

export async function discoverCompetitors(brandId, refresh = false) {
  const res = await fetch(
    `${BASE}/api/competitors/discover/${encodeURIComponent(brandId)}?refresh=${refresh ? "true" : "false"}`,
    { method: "POST" }
  );
  return readJson(res, "Failed to discover competitors");
}

export async function listCompetitors(brandId) {
  const res = await fetch(`${BASE}/api/competitors/${encodeURIComponent(brandId)}`);
  return readJson(res, "Failed to load competitors");
}

export async function compareCompetitor(brandId, competitorProfile) {
  const profile = typeof competitorProfile === "string"
    ? { competitor: competitorProfile }
    : competitorProfile;
  const res = await fetch(`${BASE}/api/competitors/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ brand_id: brandId, ...profile }),
  });
  return readJson(res, "Failed to compare competitor");
}

export async function generateCompetitorIntelligence(brandId, competitorProfile) {
  const profile = typeof competitorProfile === "string"
    ? { competitor: competitorProfile }
    : competitorProfile;
  const res = await fetch(`${BASE}/api/competitors/intelligence`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ brand_id: brandId, ...profile }),
  });
  return readJson(res, "Failed to generate competitor intelligence");
}

export async function getComparison(comparisonId) {
  const res = await fetch(`${BASE}/api/competitors/comparison/${encodeURIComponent(comparisonId)}`);
  return readJson(res, "Failed to load comparison");
}
