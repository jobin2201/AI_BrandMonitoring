function clean(value) {
  return String(value || "").trim();
}

function pushUnique(entries, seen, value, type, label = type) {
  const keyword = clean(value);
  const normalized = keyword.toLocaleLowerCase();
  if (!keyword || seen.has(normalized)) return;
  seen.add(normalized);
  entries.push({ value: keyword, type, label });
}

export function buildWorkspaceKeywordEntries(workspace) {
  const seen = new Set();
  const entries = [];

  pushUnique(entries, seen, workspace?.companyName, "company", "Company");
  (workspace?.brands || []).forEach(value => pushUnique(entries, seen, value, "brand", "Brand"));
  (workspace?.products || []).forEach(product => (
    pushUnique(entries, seen, product?.name, "product", "Product")
  ));
  (workspace?.ceos || []).forEach(ceo => pushUnique(entries, seen, ceo?.name, "executive", "Executive"));
  (workspace?.executives || []).forEach(executive => (
    pushUnique(entries, seen, executive?.name, "executive", "Executive")
  ));
  (workspace?.campaigns || []).forEach(value => pushUnique(entries, seen, value, "campaign", "Campaign"));
  (workspace?.hashtags || []).forEach(value => pushUnique(entries, seen, value, "hashtag", "Hashtag"));
  (workspace?.keywords || []).forEach(value => pushUnique(entries, seen, value, "keyword", "Keyword"));

  return entries;
}

export function buildWorkspaceKeywords(workspace) {
  return buildWorkspaceKeywordEntries(workspace).map(entry => entry.value);
}

export function buildMonitoringKeywords(workspace) {
  const companyName = clean(workspace?.companyName);
  return companyName ? [companyName] : [];
}
