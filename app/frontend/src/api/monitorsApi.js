const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function createMonitor(brand, aliases = "", confirmed = false) {
  const res = await fetch(
    `${BASE}/api/monitors/?brand_name=${encodeURIComponent(brand)}&aliases=${encodeURIComponent(aliases)}&confirmed=${confirmed ? "true" : "false"}`,
    { method: "POST" }
  );
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || "Failed to create monitor");
  }
  return data;
}

export async function listMonitors() {
  const res = await fetch(`${BASE}/api/monitors/`);
  return res.json();
}

export async function getMentions(brand, source = null) {
  const url = source
    ? `${BASE}/api/monitors/mentions?brand_name=${encodeURIComponent(brand)}&source=${source}`
    : `${BASE}/api/monitors/mentions?brand_name=${encodeURIComponent(brand)}`;
  const res = await fetch(url);
  return res.json();
}

export async function runMonitorBrand(brandId) {
  const res = await fetch(`${BASE}/api/monitors/run-brand/${encodeURIComponent(brandId)}`, {
    method: "POST",
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || "Failed to run brand monitor");
  }
  return data;
}

export async function triggerNow() {
  const res = await fetch(`${BASE}/api/monitors/run-now`, { method: "POST" });
  return res.json();
}
