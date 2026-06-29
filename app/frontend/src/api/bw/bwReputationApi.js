const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function readJson(response, fallbackMessage) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || fallbackMessage);
  }
  return data;
}

export async function generateBwReputationSignals(companyName, brandId, forceRefresh = false) {
  const response = await fetch(
    `${BASE}/api/bw/workspaces/${encodeURIComponent(companyName)}/reputation`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ brandId, forceRefresh }),
    },
  );
  return readJson(response, "Failed to generate BW reputation signals");
}
