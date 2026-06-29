const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function readJson(res, fallbackMessage) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || fallbackMessage);
  }
  return data;
}

export async function generateReputationSignals(brandId) {
  const res = await fetch(`${BASE}/api/reputation/signals/${encodeURIComponent(brandId)}`, {
    method: "POST",
  });
  return readJson(res, "Failed to generate reputation signals");
}
