const STORAGE_KEY = "bw_company_workspace_v1";
const ACTIVE_COMPANY_KEY = "bw_active_company_name_v1";

export const DEFAULT_BW_WORKSPACE = {
  companyName: "",
  industry: "",
  brands: [""],
  products: [{ name: "", description: "" }],
  ceo: { name: "", role: "" },
  ceos: [{ name: "", role: "" }],
  executives: [{ name: "", role: "" }],
  campaigns: [""],
  hashtags: [""],
  keywords: [""],
  sources: {
    googleNews: true,
    newsApi: true,
    reddit: true,
    youtube: true,
  },
  updatedAt: "",
};

function cleanStrings(values) {
  return (values || []).map(value => String(value || "").trim()).filter(Boolean);
}

function normalizeExecutives(values) {
  return (values || [])
    .map(value => {
      if (typeof value === "string") {
        const [name, ...roleParts] = value.split(":");
        return {
          name: String(name || "").trim(),
          role: roleParts.join(":").trim(),
        };
      }
      return {
        name: String(value?.name || "").trim(),
        role: String(value?.role || "").trim(),
      };
    })
    .filter(executive => executive.name || executive.role);
}

export function normalizeWorkspace(workspace) {
  const normalizedCeos = normalizeExecutives(
    workspace?.ceos?.length ? workspace.ceos : [workspace?.ceo],
  );
  return {
    ...DEFAULT_BW_WORKSPACE,
    ...workspace,
    companyName: String(workspace?.companyName || "").trim(),
    industry: String(workspace?.industry || "").trim(),
    brands: cleanStrings(workspace?.brands),
    products: (workspace?.products || [])
      .map(product => ({
        name: String(product?.name || "").trim(),
        description: String(product?.description || "").trim(),
      }))
      .filter(product => product.name || product.description),
    ceo: {
      name: normalizedCeos[0]?.name || "",
      role: normalizedCeos[0]?.role || "",
    },
    ceos: normalizedCeos,
    executives: normalizeExecutives(workspace?.executives),
    campaigns: cleanStrings(workspace?.campaigns),
    hashtags: cleanStrings(workspace?.hashtags),
    keywords: cleanStrings(workspace?.keywords),
    sources: {
      ...DEFAULT_BW_WORKSPACE.sources,
      ...(workspace?.sources || {}),
    },
    updatedAt: workspace?.updatedAt || new Date().toISOString(),
  };
}

export function loadCompanyWorkspace() {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (!stored) return { ...DEFAULT_BW_WORKSPACE };
    const parsed = JSON.parse(stored);
    return {
      ...DEFAULT_BW_WORKSPACE,
      ...parsed,
      ceo: {
        name: String(parsed?.ceo?.name || "").trim(),
        role: String(parsed?.ceo?.role || "").trim(),
      },
      ceos: normalizeExecutives(
        parsed?.ceos?.length ? parsed.ceos : [parsed?.ceo],
      ),
      executives: normalizeExecutives(parsed.executives),
      sources: {
        ...DEFAULT_BW_WORKSPACE.sources,
        ...(parsed.sources || {}),
      },
    };
  } catch {
    return { ...DEFAULT_BW_WORKSPACE };
  }
}

export function saveCompanyWorkspace(workspace) {
  const normalized = normalizeWorkspace(workspace);
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
  if (normalized.companyName) {
    window.localStorage.setItem(ACTIVE_COMPANY_KEY, normalized.companyName);
  }
  window.dispatchEvent(new CustomEvent("bw-workspace-updated", { detail: normalized }));
  return normalized;
}

export function getActiveCompanyName() {
  return window.localStorage.getItem(ACTIVE_COMPANY_KEY) || "";
}

export function setActiveCompanyName(companyName) {
  const cleaned = String(companyName || "").trim();
  if (cleaned) {
    window.localStorage.setItem(ACTIVE_COMPANY_KEY, cleaned);
  } else {
    window.localStorage.removeItem(ACTIVE_COMPANY_KEY);
  }
}

export const BW_SOURCE_LABELS = {
  googleNews: "Google News",
  newsApi: "News API",
  reddit: "Reddit",
  youtube: "YouTube",
};
