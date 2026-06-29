const ACTIVE_SESSION_COMPANY = "bw_session_active_company";
const CACHE_PREFIX = "bw_session_page:";
const memoryTasks = new Map();

function cacheKey(page, companyName) {
  return `${CACHE_PREFIX}${String(companyName || "").trim().toLocaleLowerCase()}:${page}`;
}

export function activateBwSessionCompany(companyName) {
  const cleaned = String(companyName || "").trim();
  const previous = window.sessionStorage.getItem(ACTIVE_SESSION_COMPANY) || "";
  if (previous && previous.toLocaleLowerCase() !== cleaned.toLocaleLowerCase()) {
    [window.sessionStorage, window.localStorage].forEach(storage => {
      Object.keys(storage)
        .filter(key => key.startsWith(CACHE_PREFIX))
        .forEach(key => storage.removeItem(key));
    });
  }
  if (cleaned) {
    window.sessionStorage.setItem(ACTIVE_SESSION_COMPANY, cleaned);
  }
  return previous.toLocaleLowerCase() !== cleaned.toLocaleLowerCase();
}

export function getBwSessionState(page, companyName) {
  if (!companyName) return null;
  try {
    const key = cacheKey(page, companyName);
    return JSON.parse(
      window.sessionStorage.getItem(key)
      || window.localStorage.getItem(key)
      || "null",
    );
  } catch {
    return null;
  }
}

export function setBwSessionState(page, companyName, state) {
  if (!companyName) return;
  const key = cacheKey(page, companyName);
  const payload = JSON.stringify(state);
  window.sessionStorage.setItem(key, payload);
  window.localStorage.setItem(key, payload);
}

function notifyTask(task) {
  const snapshot = getBwTaskSnapshot(task.key);
  task.listeners.forEach(listener => listener(snapshot));
}

export function getBwTaskSnapshot(taskKey) {
  const task = memoryTasks.get(taskKey);
  if (!task) return null;
  return {
    key: task.key,
    status: task.status,
    progress: task.progress,
    result: task.result,
    error: task.error,
    startedAt: task.startedAt,
    completedAt: task.completedAt,
    meta: task.meta,
  };
}

export function subscribeBwTask(taskKey, listener) {
  if (!taskKey || typeof listener !== "function") return () => {};
  let task = memoryTasks.get(taskKey);
  if (!task) {
    task = {
      key: taskKey,
      status: "idle",
      progress: null,
      result: null,
      error: "",
      startedAt: "",
      completedAt: "",
      meta: {},
      listeners: new Set(),
    };
    memoryTasks.set(taskKey, task);
  }
  task.listeners.add(listener);
  listener(getBwTaskSnapshot(taskKey));
  return () => {
    const activeTask = memoryTasks.get(taskKey);
    activeTask?.listeners.delete(listener);
  };
}

export function startBwTask(taskKey, runner, meta = {}) {
  if (!taskKey || typeof runner !== "function") return null;
  const existing = memoryTasks.get(taskKey);
  if (existing?.status === "running") {
    return getBwTaskSnapshot(taskKey);
  }

  const task = {
    key: taskKey,
    status: "running",
    progress: meta.progress || null,
    result: null,
    error: "",
    startedAt: new Date().toISOString(),
    completedAt: "",
    meta,
    listeners: existing?.listeners || new Set(),
  };
  memoryTasks.set(taskKey, task);
  notifyTask(task);

  const setProgress = progress => {
    const activeTask = memoryTasks.get(taskKey);
    if (!activeTask || activeTask.status !== "running") return;
    activeTask.progress = progress;
    notifyTask(activeTask);
  };

  task.promise = Promise.resolve()
    .then(() => runner({ setProgress }))
    .then(result => {
      const activeTask = memoryTasks.get(taskKey);
      if (!activeTask) return result;
      activeTask.status = "complete";
      activeTask.result = result;
      activeTask.error = "";
      activeTask.completedAt = new Date().toISOString();
      notifyTask(activeTask);
      return result;
    })
    .catch(error => {
      const activeTask = memoryTasks.get(taskKey);
      if (!activeTask) throw error;
      activeTask.status = "error";
      activeTask.error = error?.message || "Task failed";
      activeTask.completedAt = new Date().toISOString();
      notifyTask(activeTask);
      throw error;
    });

  task.promise.catch(() => {});
  return getBwTaskSnapshot(taskKey);
}
