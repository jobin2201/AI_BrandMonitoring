const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function readJson(response, fallbackMessage) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.detail || fallbackMessage);
    error.status = response.status;
    throw error;
  }
  return data;
}

export async function listBwWorkspaces() {
  const response = await fetch(`${BASE}/api/bw/workspaces`);
  return readJson(response, "Failed to load company workspaces");
}

export async function getBwWorkspace(companyName) {
  const response = await fetch(
    `${BASE}/api/bw/workspaces/${encodeURIComponent(companyName)}`,
  );
  return readJson(response, "Failed to load company workspace");
}

export async function saveBwWorkspace(workspace) {
  const response = await fetch(`${BASE}/api/bw/workspaces`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(workspace),
  });
  return readJson(response, "Failed to save company workspace");
}
