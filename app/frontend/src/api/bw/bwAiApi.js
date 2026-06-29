const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function generateBwAiAnalysis(companyName) {
  const response = await fetch(
    `${BASE}/api/bw/workspaces/${encodeURIComponent(companyName)}/ai-analysis`,
    { method: "POST" },
  );
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "Failed to generate AI intelligence");
  }
  return data;
}
