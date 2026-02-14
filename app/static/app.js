// DOM Elements
const integrationsEl = document.getElementById("integrations");
const recsEl = document.getElementById("recommendations");
const template = document.getElementById("rec-card-template");
const swarmMap = document.getElementById("swarm-map");
const agentLog = document.getElementById("agent-log");
const generatedAtEl = document.getElementById("generated-at");
const memoryCountEl = document.getElementById("memory-count");
const countInput = document.getElementById("count");
const movieDayContentEl = document.getElementById("movie-day-content");
const heroBackdropEl = document.getElementById("hero-backdrop");
const releaseCalendarEl = document.getElementById("release-calendar");
const homeSourceFiltersEl = document.getElementById("home-source-filters");
const calendarSourceFiltersEl = document.getElementById("calendar-source-filters");
const releaseFromEl = document.getElementById("release-from");
const releaseToEl = document.getElementById("release-to");
const clearAllFiltersBtn = document.getElementById("clear-all-filters");
const downloadHealthEl = document.getElementById("download-health");
const activeDownloadsEl = document.getElementById("active-downloads");
const downloadHistoryEl = document.getElementById("download-history");
const refreshDownloadsBtn = document.getElementById("refresh-downloads");
const clearDownloadHistoryBtn = document.getElementById("clear-download-history");
const autoDeleteOnClearEl = document.getElementById("auto-delete-on-clear");
const downloadAllBtn = document.getElementById("download-all");
const monitoredStatusEl = document.getElementById("monitored-status");
const monitoredListEl = document.getElementById("monitored-list");
const refreshMonitoredBtn = document.getElementById("refresh-monitored");
const movieSearchInput = document.getElementById("movie-search");
const searchResultsEl = document.getElementById("search-results");
const nowDownloadingEl = document.getElementById("now-downloading");
const sortSelect = document.getElementById("sort-select");
const themeSelect = document.getElementById("theme-select");
const minScoreEl = document.getElementById("min-score");
const yearFromEl = document.getElementById("year-from");
const yearToEl = document.getElementById("year-to");
const genreFilterEl = document.getElementById("genre-filter");

const movieModal = document.getElementById("movie-modal");
const modalPosterImg = document.getElementById("modal-poster-img");
const modalTitle = document.getElementById("modal-title");
const modalMeta = document.getElementById("modal-meta");
const modalScore = document.getElementById("modal-score");
const modalOverview = document.getElementById("modal-overview");
const modalSourceLinks = document.getElementById("modal-source-links");
const modalTrailerContainer = document.getElementById("modal-trailer-container");
const modalDownloadBtn = document.getElementById("modal-download");
const modalSkipBtn = document.getElementById("modal-skip");

const DOWNLOAD_HISTORY_CLEAR_KEY = "majic_download_history_cleared_at";
const THEME_KEY = "majic_theme";
let downloadHistoryClearedAt = localStorage.getItem(DOWNLOAD_HISTORY_CLEAR_KEY);
let currentRecommendations = [];
let currentModalMovie = null;

const SOURCE_OPTIONS = [
  { key: "rt", label: "RT" },
  { key: "rogerebert", label: "Ebert" },
  { key: "nzbgeek", label: "NZBGeek" },
  { key: "drunkenslug", label: "DSlug" },
  { key: "releases", label: "Releases" },
  { key: "upcoming", label: "Upcoming" },
  { key: "plex", label: "Plex" },
  { key: "radarr", label: "Radarr" },
  { key: "oscars", label: "Oscars" },
  { key: "criterion", label: "Criterion" },
];

// Initialize with all sources selected
const homeSourceSelections = new Set(SOURCE_OPTIONS.map((opt) => opt.key));
const calendarSourceSelections = new Set();
let calendarItems = [];
let filterDebounceTimer = null;
const MAX_RECOMMENDATION_COUNT = 100;

// Theme handling
function initTheme() {
  const saved = localStorage.getItem(THEME_KEY) || "dark";
  document.documentElement.setAttribute("data-theme", saved);
  if (themeSelect) {
    themeSelect.value = saved;
    themeSelect.addEventListener("change", () => {
      const theme = themeSelect.value;
      document.documentElement.setAttribute("data-theme", theme);
      localStorage.setItem(THEME_KEY, theme);
    });
  }
}

// Status banner
const radarrStatusEl = document.getElementById("radarr-status");
async function updateStatusBanner() {
  if (!radarrStatusEl) return;
  try {
    const res = await fetch("/api/download-health");
    const data = await res.json();
    if (!data.configured) {
      radarrStatusEl.innerHTML = '<span class="status-error">⚠ Radarr not configured</span> — Downloads disabled. <a href="/integrations" style="color: var(--primary);">Configure in Settings</a>';
    } else if (!data.ok) {
      radarrStatusEl.innerHTML = `<span class="status-error">⚠ Radarr error</span> — ${data.message || "Connection failed"}`;
    } else {
      const queueText = data.queue_count === 0 ? "No active downloads" : `${data.queue_count} in queue`;
      const rateText = data.download_rate_human ? ` • ${data.download_rate_human}` : "";
      radarrStatusEl.innerHTML = `<span class="status-ok">✓ Radarr connected</span> — ${queueText}${rateText}`;
    }
  } catch (err) {
    radarrStatusEl.innerHTML = '<span class="status-error">⚠ Cannot check Radarr</span>';
  }
}

function currentUserId() {
  const key = "majic_movie_selector_user_id";
  let userId = localStorage.getItem(key);
  if (!userId) {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      userId = `user-${window.crypto.randomUUID()}`;
    } else {
      userId = `user-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    }
    localStorage.setItem(key, userId);
  }
  return userId;
}

function canonicalSourceKey(raw) {
  const value = String(raw || "").toLowerCase().trim();
  if (!value) return null;
  if (value === "rottentomatoes" || value === "rt" || value.startsWith("rt-")) return "rt";
  if (value === "nzbgeek" || value === "nzbgeek-rss") return "nzbgeek";
  if (value === "drunkenslug") return "drunkenslug";
  if (value === "usenet") return "usenet";
  if (value === "rogerebert" || value === "critic-review") return "rogerebert";
  if (value === "releases") return "releases";
  if (value === "upcoming") return "upcoming";
  if (value === "plex") return "plex";
  if (value === "radarr") return "radarr";
  if (value === "oscars") return "oscars";
  if (value === "criterion") return "criterion";
  return value;
}

function sourceKeysFromMovie(movie) {
  const keys = new Set();
  (movie.source_tags || []).forEach((tag) => {
    const mapped = canonicalSourceKey(tag);
    if (mapped) keys.add(mapped);
  });
  if (movie.available_on_usenet) keys.add("usenet");
  if (movie.available_on_plex) keys.add("plex");
  if (movie.available_on_radarr) keys.add("radarr");
  return keys;
}

function sourceLabel(key) {
  const option = SOURCE_OPTIONS.find((item) => item.key === key);
  return option ? option.label : key;
}

function renderSourceFilters(container, options, selectedSet, onToggle) {
  if (!container) return;
  container.innerHTML = "";

  // Add Select All / None buttons
  const controlsWrap = document.createElement("div");
  controlsWrap.className = "source-filter-controls";

  const selectAllBtn = document.createElement("button");
  selectAllBtn.type = "button";
  selectAllBtn.className = "source-chip-mini";
  selectAllBtn.textContent = "All";
  selectAllBtn.addEventListener("click", () => {
    options.forEach((opt) => selectedSet.add(opt.key));
    renderSourceFilters(container, options, selectedSet, onToggle);
    onToggle();
  });

  const selectNoneBtn = document.createElement("button");
  selectNoneBtn.type = "button";
  selectNoneBtn.className = "source-chip-mini";
  selectNoneBtn.textContent = "None";
  selectNoneBtn.addEventListener("click", () => {
    selectedSet.clear();
    renderSourceFilters(container, options, selectedSet, onToggle);
    onToggle();
  });

  controlsWrap.appendChild(selectAllBtn);
  controlsWrap.appendChild(selectNoneBtn);
  container.appendChild(controlsWrap);

  const chipsWrap = document.createElement("div");
  chipsWrap.className = "source-chips-wrap";

  options.forEach((option) => {
    const button = document.createElement("button");
    button.type = "button";
    const active = selectedSet.has(option.key);
    button.className = `source-chip ${active ? "active" : "inactive"}`;
    button.textContent = option.label;
    button.addEventListener("click", () => {
      if (selectedSet.has(option.key)) {
        selectedSet.delete(option.key);
      } else {
        selectedSet.add(option.key);
      }
      renderSourceFilters(container, options, selectedSet, onToggle);
      onToggle();
    });
    chipsWrap.appendChild(button);
  });

  container.appendChild(chipsWrap);
}

function activeHomeSourceQuery() {
  if (homeSourceSelections.size === 0 || homeSourceSelections.size === SOURCE_OPTIONS.length) {
    return null;
  }
  return [...homeSourceSelections].join(",");
}

function activeReleaseDateFilters() {
  let releaseFrom = String(releaseFromEl?.value || "").trim();
  let releaseTo = String(releaseToEl?.value || "").trim();
  if (releaseFrom && releaseTo && releaseFrom > releaseTo) {
    const tmp = releaseFrom;
    releaseFrom = releaseTo;
    releaseTo = tmp;
  }
  return {
    releaseFrom: releaseFrom || null,
    releaseTo: releaseTo || null,
  };
}

function activeCalendarSourceFilter() {
  return calendarSourceSelections.size === 0 ? null : new Set(calendarSourceSelections);
}

function criticLabel(movie) {
  if (Number.isFinite(movie.rottentomatoes_score)) {
    return `RT ${Math.round(movie.rottentomatoes_score)}%`;
  }
  if (Number.isFinite(movie.rogerebert_score)) {
    const score = Number(movie.rogerebert_score);
    if (score <= 4) return `Ebert ${score.toFixed(1)}/4`;
    if (score <= 5) return `Ebert ${score.toFixed(1)}/5`;
    return `Ebert ${score.toFixed(0)}`;
  }
  return null;
}

async function fetchIntegrations() {
  if (!integrationsEl) return;

  try {
    const res = await fetch("/api/integrations");
    const data = await res.json();
    integrationsEl.innerHTML = "";

    const labelMap = {
      rottentomatoes: "RT",
      rogerebert: "Ebert",
      releases: "Releases",
      nzbgeek: "NZBGeek",
      drunkenslug: "DSlug",
      tmdb: "TMDB",
      plex: "Plex",
      radarr: "Radarr",
    };

    // Put radarr first since it's important for downloads
    const entries = Object.entries(data).filter(([name]) => name !== "usenet");
    const radarrEntry = entries.find(([name]) => name === "radarr");
    const otherEntries = entries.filter(([name]) => name !== "radarr");
    const sortedEntries = radarrEntry ? [radarrEntry, ...otherEntries] : otherEntries;

    sortedEntries.forEach(([name, active]) => {
      const badge = document.createElement("span");
      badge.className = `badge ${active ? "active" : "inactive"}`;
      const statusText = active ? "on" : "off";
      badge.textContent = `${labelMap[name] || name}: ${statusText}`;

      // Add special styling for Radarr since it affects downloads
      if (name === "radarr" && !active) {
        badge.title = "Configure Radarr to enable movie downloads";
      }

      integrationsEl.appendChild(badge);
    });
  } catch (err) {
    console.error("Failed to fetch integrations:", err);
    integrationsEl.innerHTML = '<span class="badge inactive">Error loading integrations</span>';
  }
}

function clearList(element) {
  if (element) element.innerHTML = "";
}

function appendListItem(element, text) {
  if (!element) return;
  const li = document.createElement("li");
  li.textContent = text;
  element.appendChild(li);
}

function appendActiveDownloadItem(item, radarrUrl) {
  if (!activeDownloadsEl) return;
  const li = document.createElement("li");

  const topRow = document.createElement("div");
  topRow.className = "download-top-row";

  if (radarrUrl && item.movie_id != null) {
    const title = document.createElement("a");
    title.href = `${radarrUrl}/movie/${item.movie_id}`;
    title.target = "_blank";
    title.rel = "noopener noreferrer";
    title.className = "download-title-link dl-title-scroll";
    title.innerHTML = `<strong><span>${escapeXml(item.title)}${item.year ? ` (${item.year})` : ""}</span></strong>`;
    topRow.appendChild(title);
  } else {
    const title = document.createElement("strong");
    title.className = "dl-title-scroll";
    const span = document.createElement("span");
    span.textContent = `${item.title}${item.year ? ` (${item.year})` : ""}`;
    title.appendChild(span);
    topRow.appendChild(title);
  }

  if (item.queue_id != null) {
    const cancelBtn = document.createElement("button");
    cancelBtn.className = "cancel-dl-btn";
    cancelBtn.textContent = "Cancel";
    cancelBtn.title = "Cancel this download";
    cancelBtn.addEventListener("click", async () => {
      cancelBtn.disabled = true;
      cancelBtn.textContent = "...";
      await cancelDownload(item.queue_id);
    });
    topRow.appendChild(cancelBtn);
  }
  li.appendChild(topRow);

  const meta = document.createElement("span");
  meta.className = "download-meta";
  meta.textContent = [
    item.status || "unknown",
    item.rate_human || null,
    item.time_left ? `ETA ${item.time_left}` : null,
    item.size_left_human ? `left ${item.size_left_human}` : null,
  ]
    .filter(Boolean)
    .join(" • ");
  li.appendChild(meta);

  if (item.progress != null) {
    const track = document.createElement("div");
    track.className = "progress-track";
    const fill = document.createElement("div");
    fill.className = "progress-fill";
    fill.style.width = `${Math.max(0, Math.min(100, Number(item.progress)))}%`;
    track.appendChild(fill);
    li.appendChild(track);

    const pct = document.createElement("span");
    pct.className = "download-pct";
    pct.textContent = `${Math.round(Number(item.progress))}%`;
    li.appendChild(pct);
  }

  activeDownloadsEl.appendChild(li);
}

async function cancelDownload(queueId) {
  try {
    const response = await fetch("/api/download-cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ queue_id: queueId, remove_from_client: true, blocklist: false }),
    });
    const result = await response.json();
    if (!result.ok && downloadHealthEl) {
      downloadHealthEl.textContent = `Cancel failed: ${result.message}`;
    }
  } catch (err) {
    if (downloadHealthEl) downloadHealthEl.textContent = err.message || "Cancel failed.";
  }
  await loadDownloadActivity();
}

async function cancelAllDownloads() {
  const cancelAllBtn = document.getElementById("cancel-all-downloads");
  if (cancelAllBtn) cancelAllBtn.disabled = true;
  try {
    const response = await fetch("/api/download-cancel-all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const result = await response.json();
    if (downloadHealthEl) {
      downloadHealthEl.textContent = result.ok
        ? result.message
        : `Bulk cancel failed: ${result.message}`;
    }
  } catch (err) {
    if (downloadHealthEl) downloadHealthEl.textContent = err.message || "Bulk cancel failed.";
  }
  await loadDownloadActivity();
  if (cancelAllBtn) cancelAllBtn.disabled = false;
}

function formatDownloadEventName(raw) {
  const value = String(raw || "").trim();
  if (!value) return "event";
  return value.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
}

function hasPassedClearCutoff(timestamp) {
  if (!downloadHistoryClearedAt || !timestamp) return false;
  const cutoff = new Date(downloadHistoryClearedAt);
  const itemTs = new Date(timestamp);
  if (Number.isNaN(cutoff.getTime()) || Number.isNaN(itemTs.getTime())) return false;
  return itemTs <= cutoff;
}

async function clearDownloadHistory() {
  if (!clearDownloadHistoryBtn) return;
  clearDownloadHistoryBtn.disabled = true;
  try {
    const response = await fetch("/api/download-history/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        auto_download: false,
        auto_delete: Boolean(autoDeleteOnClearEl?.checked),
      }),
    });
    if (!response.ok) throw new Error(`clear failed (${response.status})`);
    const payload = await response.json();
    downloadHistoryClearedAt = payload.cleared_at || new Date().toISOString();
    localStorage.setItem(DOWNLOAD_HISTORY_CLEAR_KEY, downloadHistoryClearedAt);
    if (downloadHealthEl) {
      const deleteNote = payload.deleted_count != null ? ` Deleted ${payload.deleted_count} rows.` : "";
      downloadHealthEl.textContent = `History cleared.${deleteNote}`;
    }
    await loadDownloadActivity();
  } catch (err) {
    if (downloadHealthEl) downloadHealthEl.textContent = err.message || "Failed to clear.";
  } finally {
    clearDownloadHistoryBtn.disabled = false;
  }
}

function renderNowDownloading(health) {
  if (!nowDownloadingEl) return;
  const items = (health?.items || []).filter((i) => i.status === "downloading" || i.progress != null);
  if (!items.length || !health?.ok) {
    nowDownloadingEl.classList.add("hidden");
    nowDownloadingEl.innerHTML = "";
    return;
  }

  nowDownloadingEl.classList.remove("hidden");
  nowDownloadingEl.innerHTML = "";

  const header = document.createElement("div");
  header.className = "now-dl-header";
  header.innerHTML = `<span class="now-dl-label">⬇ Now Downloading</span><span class="now-dl-rate">${health.download_rate_human || ""}</span>`;
  nowDownloadingEl.appendChild(header);

  const list = document.createElement("div");
  list.className = "now-dl-list";

  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "now-dl-card";

    const info = document.createElement("div");
    info.className = "now-dl-info";

    const title = document.createElement("div");
    title.className = "now-dl-title";
    const titleSpan = document.createElement("span");
    titleSpan.textContent = `${item.title}${item.year ? ` (${item.year})` : ""}`;
    title.appendChild(titleSpan);
    info.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "now-dl-meta";
    const parts = [];
    if (item.progress != null) parts.push(`${Math.round(item.progress)}%`);
    if (item.rate_human) parts.push(item.rate_human);
    if (item.time_left && item.time_left !== "00:00:00") parts.push(`ETA ${item.time_left}`);
    if (item.size_left_human) parts.push(`${item.size_left_human} left`);
    meta.textContent = parts.join(" • ");
    info.appendChild(meta);

    card.appendChild(info);

    if (item.progress != null) {
      const track = document.createElement("div");
      track.className = "now-dl-progress";
      const fill = document.createElement("div");
      fill.className = "now-dl-fill";
      fill.style.width = `${Math.max(0, Math.min(100, Number(item.progress)))}%`;
      track.appendChild(fill);
      card.appendChild(track);
    }

    list.appendChild(card);
  });

  nowDownloadingEl.appendChild(list);
}

async function loadDownloadActivity(silent = false) {
  if (!downloadHealthEl || !activeDownloadsEl || !downloadHistoryEl) return;

  if (refreshDownloadsBtn) refreshDownloadsBtn.disabled = true;
  if (!silent) {
    downloadHealthEl.textContent = "Loading...";
    clearList(activeDownloadsEl);
    clearList(downloadHistoryEl);
  }

  // Also update the status banner
  updateStatusBanner();

  try {
    const [healthRes, historyRes] = await Promise.all([
      fetch("/api/download-health"),
      fetch("/api/download-history?limit=40"),
    ]);

    const health = await healthRes.json();
    const history = await historyRes.json();

    clearList(activeDownloadsEl);
    clearList(downloadHistoryEl);
    renderNowDownloading(health);

    if (!health.configured) {
      downloadHealthEl.textContent = health.message || "Radarr not configured.";
      appendListItem(activeDownloadsEl, "Configure Radarr in Integrations.");
    } else if (!health.ok) {
      downloadHealthEl.textContent = `Error: ${health.message || "unknown"}`;
    } else if (!health.queue_count) {
      downloadHealthEl.textContent = "No active downloads.";
      appendListItem(activeDownloadsEl, "Nothing downloading.");
    } else {
      downloadHealthEl.textContent = `${health.active_count}/${health.queue_count} active • ${health.download_rate_human || "n/a"}`;
      const radarrUrl = (health.radarr_base_url || "").replace(/\/$/, "");
      (health.items || []).forEach((item) => appendActiveDownloadItem(item, radarrUrl));
    }

    const historyItems = (history.items || []).filter((item) => !hasPassedClearCutoff(item.timestamp));

    if (!history.configured) {
      appendListItem(downloadHistoryEl, "Radarr not configured.");
    } else if (!history.ok) {
      appendListItem(downloadHistoryEl, `Error: ${history.message || "unknown"}`);
    } else if (!historyItems.length) {
      appendListItem(downloadHistoryEl, "No recent history.");
    } else {
      historyItems.slice(0, 10).forEach((item) => {
        const when = item.timestamp ? new Date(item.timestamp).toLocaleString() : "";
        const detail = [formatDownloadEventName(item.event), item.quality, when].filter(Boolean).join(" • ");
        appendListItem(downloadHistoryEl, `${item.title}${item.year ? ` (${item.year})` : ""} • ${detail}`);
      });
    }
  } catch (err) {
    downloadHealthEl.textContent = err.message || "Failed to load.";
  } finally {
    if (refreshDownloadsBtn) refreshDownloadsBtn.disabled = false;
  }
}

async function loadRadarrMonitored() {
  if (!monitoredStatusEl || !monitoredListEl) return;
  if (refreshMonitoredBtn) refreshMonitoredBtn.disabled = true;

  try {
    const res = await fetch("/api/radarr-monitored");
    const data = await res.json();

    monitoredListEl.innerHTML = "";

    if (!data.configured) {
      monitoredStatusEl.textContent = "Radarr not configured.";
      return;
    }
    if (!data.ok) {
      monitoredStatusEl.textContent = `Error: ${data.message || "unknown"}`;
      return;
    }
    if (!data.movies.length) {
      monitoredStatusEl.textContent = "No movies tracked in Radarr.";
      return;
    }

    const stateLabels = {
      downloaded: "✓ Downloaded",
      waiting: "⏳ Available — Waiting",
      monitored: "👁 Monitored",
      unmonitored: "○ Unmonitored",
    };
    const stateClasses = {
      downloaded: "state-downloaded",
      waiting: "state-waiting",
      monitored: "state-monitored",
      unmonitored: "state-unmonitored",
    };

    const counts = { downloaded: 0, waiting: 0, monitored: 0, unmonitored: 0 };
    data.movies.forEach((m) => { counts[m.state] = (counts[m.state] || 0) + 1; });
    monitoredStatusEl.textContent = `${data.movies.length} movies — ${counts.downloaded} downloaded, ${counts.monitored + counts.waiting} monitored`;

    const radarrUrl = (data.radarr_base_url || "").replace(/\/$/, "");

    data.movies.forEach((m) => {
      const li = document.createElement("li");
      li.className = "monitored-item";

      const info = document.createElement("div");
      info.className = "monitored-info";

      if (radarrUrl && m.movie_id != null) {
        const title = document.createElement("a");
        title.href = `${radarrUrl}/movie/${m.movie_id}`;
        title.target = "_blank";
        title.rel = "noopener noreferrer";
        title.className = "monitored-title-link";
        title.innerHTML = `<strong>${escapeXml(m.title)}${m.year ? ` (${m.year})` : ""}</strong>`;
        info.appendChild(title);
      } else {
        const title = document.createElement("strong");
        title.textContent = `${m.title}${m.year ? ` (${m.year})` : ""}`;
        info.appendChild(title);
      }

      const badge = document.createElement("span");
      badge.className = `monitored-badge ${stateClasses[m.state] || ""}`;
      badge.textContent = stateLabels[m.state] || m.state;
      info.appendChild(badge);

      if (m.state !== "downloaded" && (m.digital_release || m.physical_release || m.in_cinemas)) {
        const dates = document.createElement("span");
        dates.className = "monitored-dates";
        const parts = [];
        if (m.digital_release) parts.push(`Digital: ${new Date(m.digital_release).toLocaleDateString()}`);
        if (m.physical_release) parts.push(`Physical: ${new Date(m.physical_release).toLocaleDateString()}`);
        if (m.in_cinemas) parts.push(`Cinema: ${new Date(m.in_cinemas).toLocaleDateString()}`);
        dates.textContent = parts.join(" • ");
        info.appendChild(dates);
      }

      li.appendChild(info);
      monitoredListEl.appendChild(li);
    });
  } catch (err) {
    monitoredStatusEl.textContent = err.message || "Failed to load.";
  } finally {
    if (refreshMonitoredBtn) refreshMonitoredBtn.disabled = false;
  }
}

function renderSwarm(agents) {
  if (!swarmMap || !agentLog) return;

  swarmMap.innerHTML = "";
  const center = { x: 400, y: 205 };
  const radius = 145;
  const ns = "http://www.w3.org/2000/svg";

  function svg(tag, attrs = {}) {
    const el = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    return el;
  }

  swarmMap.appendChild(svg("circle", { cx: center.x, cy: center.y, r: 58, fill: "#ff6a42", opacity: "0.95" }));

  const rootLabel = svg("text", {
    x: center.x, y: center.y + 5, "text-anchor": "middle", fill: "#fff",
    "font-size": "14", "font-weight": "700", "font-family": "Sora, sans-serif",
  });
  rootLabel.textContent = "Core";
  swarmMap.appendChild(rootLabel);

  agents.forEach((agent, idx) => {
    const angle = (Math.PI * 2 * idx) / agents.length - Math.PI / 2;
    const x = center.x + radius * Math.cos(angle);
    const y = center.y + radius * Math.sin(angle);
    const color = agent.status === "success" ? "#27d4a2" : agent.status === "skipped" ? "#f5ba53" : "#ff6f71";

    swarmMap.appendChild(svg("line", {
      x1: center.x, y1: center.y, x2: x, y2: y,
      stroke: "#8491be", "stroke-width": "1.7", opacity: "0.8",
    }));

    swarmMap.appendChild(svg("circle", { cx: x, cy: y, r: 28, fill: color, opacity: "0.96" }));

    const label = svg("text", {
      x, y: y + 4, "text-anchor": "middle", fill: "#fff",
      "font-size": "10.5", "font-family": "Sora, sans-serif",
    });
    label.textContent = agent.agent;
    swarmMap.appendChild(label);
  });

  agentLog.innerHTML = "";
  agents.forEach((agent) => {
    const li = document.createElement("li");
    const cls = agent.status === "success" ? "ok" : agent.status === "skipped" ? "skip" : "err";
    li.innerHTML = `<strong>${agent.agent}</strong> <span class="${cls}">${agent.status}</span> - ${agent.item_count} items`;
    agentLog.appendChild(li);
  });
}

function hashCode(input) {
  let hash = 0;
  for (let i = 0; i < input.length; i++) hash = ((hash << 5) - hash + input.charCodeAt(i)) | 0;
  return Math.abs(hash);
}

function monogramFromTitle(title) {
  const parts = title.split(/\s+/).map((p) => p.trim()).filter(Boolean);
  if (!parts.length) return "MV";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

function gradientForTitle(title) {
  const seed = hashCode(title);
  const hueA = seed % 360;
  const hueB = (seed * 1.7) % 360;
  const hueC = (seed * 2.3) % 360;
  return `linear-gradient(155deg, hsl(${hueA} 72% 56%) 0%, hsl(${hueB} 78% 42%) 52%, hsl(${hueC} 80% 32%) 100%)`;
}

function escapeXml(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function generatedPosterDataUrl(movie) {
  const title = (movie.title || "Movie").trim();
  const initials = monogramFromTitle(title);
  const safeInitials = escapeXml(initials);

  const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1000 1500'>
    <rect width='1000' height='1500' fill='#141414'/>
    <rect x='0' y='1100' width='1000' height='400' fill='rgba(229,9,20,0.06)'/>
    <text x='500' y='720' text-anchor='middle' fill='rgba(255,255,255,0.06)' font-size='360' font-family='Sora, sans-serif' font-weight='800'>${safeInitials}</text>
  </svg>`;

  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function sourceIcons(movie) {
  const tags = new Set(movie.source_tags || []);
  const icons = [];
  const hasRt = Number.isFinite(movie.rottentomatoes_score) || tags.has("rottentomatoes") || [...tags].some((t) => t.startsWith("rt-"));

  if (hasRt) {
    const rtLabel = Number.isFinite(movie.rottentomatoes_score) ? `${Math.round(movie.rottentomatoes_score)}` : "RT";
    icons.push({ cls: "rt", label: "Rotten Tomatoes", text: rtLabel });
  }
  if (tags.has("rogerebert")) icons.push({ cls: "rogerebert", label: "RogerEbert", text: "RE" });
  if (movie.available_on_plex || tags.has("plex")) icons.push({ cls: "plex", label: "Plex", text: "P" });
  if (movie.available_on_radarr || tags.has("radarr")) icons.push({ cls: "radarr", label: "Radarr", text: "R" });
  if (tags.has("nzbgeek") || tags.has("nzbgeek-rss")) icons.push({ cls: "nzb", label: "NZBGeek", text: "NZB" });
  if (tags.has("drunkenslug")) icons.push({ cls: "nzb", label: "DrunkenSlug", text: "DS" });
  if (tags.has("releases")) icons.push({ cls: "releases", label: "Releases", text: "REL" });
  return icons.slice(0, 4);
}

function applyCover(root, movie) {
  const coverArt = root.querySelector(".movie-poster") || root.querySelector(".cover-art");
  const imageEl = root.querySelector(".cover-image");
  const fallbackEl = root.querySelector(".cover-fallback");
  const monogramEl = root.querySelector(".cover-monogram");
  const yearEl = root.querySelector(".cover-year");
  const iconList = root.querySelector(".cover-icons");

  if (!imageEl || !fallbackEl || !monogramEl || !yearEl) return;

  monogramEl.textContent = monogramFromTitle(movie.title || "Movie");
  yearEl.textContent = movie.year || "Unknown";
  fallbackEl.style.background = gradientForTitle(movie.title || "Movie");

  if (iconList) {
    iconList.innerHTML = "";
  }

  const posterUrl = (movie.poster_url || "").trim();
  if (!posterUrl) {
    imageEl.src = generatedPosterDataUrl(movie);
    imageEl.style.display = "block";
    fallbackEl.style.display = "none";
    coverArt.classList.add("has-image");
    return;
  }

  imageEl.src = posterUrl;
  imageEl.style.display = "block";
  fallbackEl.style.display = "none";
  coverArt.classList.add("has-image");

  imageEl.onerror = () => {
    imageEl.src = generatedPosterDataUrl(movie);
  };
}

function renderHeroMovie(rec) {
  if (!movieDayContentEl) return;
  movieDayContentEl.innerHTML = "";

  if (!rec) {
    const p = document.createElement("p");
    p.className = "meta";
    p.textContent = "No recommendation available yet.";
    movieDayContentEl.appendChild(p);
    return;
  }

  const movie = rec.movie;
  const card = document.createElement("article");
  card.className = "hero-card";

  // Poster
  const posterDiv = document.createElement("div");
  posterDiv.className = "hero-poster";
  posterDiv.style.cursor = "pointer";
  posterDiv.title = "Watch trailer on YouTube";
  posterDiv.addEventListener("click", () => {
    window.open(getTrailerSearchUrl(movie), "_blank", "noopener,noreferrer");
  });
  const img = document.createElement("img");
  img.alt = movie.title;
  img.loading = "lazy";

  const posterUrl = (movie.poster_url || "").trim();
  if (posterUrl) {
    img.src = posterUrl;
    img.onerror = () => { img.src = generatedPosterDataUrl(movie); };
    if (heroBackdropEl) heroBackdropEl.style.backgroundImage = `url(${posterUrl})`;
  } else {
    img.src = generatedPosterDataUrl(movie);
  }
  posterDiv.appendChild(img);

  // Info
  const info = document.createElement("div");
  info.className = "hero-info";

  const title = document.createElement("h3");
  title.textContent = movie.title;
  title.style.cursor = "pointer";
  title.addEventListener("click", () => openMovieModal(rec));

  const meta = document.createElement("p");
  meta.className = "meta";
  const critic = criticLabel(movie);
  const genreText = (movie.genres || []).slice(0, 3).join(", ");
  meta.textContent = [movie.year, genreText, movie.release_date ? `Release: ${movie.release_date}` : null, critic].filter(Boolean).join(" \u2022 ");

  const scoreEl = document.createElement("div");
  scoreEl.className = "score-badge large";
  scoreEl.textContent = `${Math.round(rec.score)}`;

  const summary = document.createElement("p");
  summary.className = "overview";
  summary.textContent = movie.overview || "No synopsis available.";

  // Source links row
  const linksRow = document.createElement("div");
  linksRow.className = "hero-links";
  getSourceLinks(movie).slice(0, 5).forEach((link) => {
    const a = document.createElement("a");
    a.href = link.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = link.label;
    a.className = `source-link ${link.cls}`;
    linksRow.appendChild(a);
  });

  const reasons = document.createElement("ul");
  reasons.className = "hero-reasons";
  (rec.reasons || []).slice(0, 4).forEach((reason) => {
    const li = document.createElement("li");
    li.textContent = reason.label;
    reasons.appendChild(li);
  });

  const actions = document.createElement("div");
  actions.className = "hero-actions";

  const likeBtn = document.createElement("button");
  likeBtn.className = "btn btn-primary";
  likeBtn.textContent = "\u2764 Like";
  likeBtn.addEventListener("click", async () => {
    if (likeBtn.disabled) return;
    likeBtn.disabled = true;
    try {
      await sendFeedback(movie, true);
      likeBtn.textContent = "\u2713 Liked";
    } catch (err) {
      likeBtn.textContent = "Error";
    }
  });

  const dlBtn = document.createElement("button");
  dlBtn.className = "btn btn-ghost";
  dlBtn.textContent = "\u25B6 Download";
  dlBtn.addEventListener("click", async () => {
    if (dlBtn.disabled) return;
    dlBtn.disabled = true;
    dlBtn.textContent = "Sending...";
    try {
      const result = await sendDownload(movie);
      if (result?.status === "queued") {
        dlBtn.textContent = "\u2713 Queued!";
      } else if (result?.status === "exists") {
        dlBtn.textContent = "Already tracked";
      } else if (result?.status === "error") {
        dlBtn.textContent = "Error";
        dlBtn.title = result.message || "Radarr error";
      } else {
        dlBtn.textContent = "\u2713 Sent";
      }
      await loadDownloadActivity();
    } catch (err) {
      dlBtn.textContent = "Failed";
      dlBtn.title = err.message;
    }
  });

  const skipBtn = document.createElement("button");
  skipBtn.className = "btn btn-ghost";
  skipBtn.textContent = "Skip";
  skipBtn.addEventListener("click", async () => {
    if (skipBtn.disabled) return;
    skipBtn.disabled = true;
    try {
      await sendFeedback(movie, false);
      skipBtn.textContent = "Skipped";
    } catch (err) {
      skipBtn.textContent = "Error";
    }
  });

  actions.appendChild(likeBtn);
  actions.appendChild(dlBtn);
  actions.appendChild(skipBtn);

  info.appendChild(title);
  info.appendChild(meta);
  info.appendChild(scoreEl);
  info.appendChild(summary);
  info.appendChild(linksRow);
  info.appendChild(reasons);
  info.appendChild(actions);

  card.appendChild(posterDiv);
  card.appendChild(info);
  movieDayContentEl.appendChild(card);
}

async function sendFeedback(movie, liked) {
  console.log(`Sending feedback: ${movie.title}, liked: ${liked}`);
  const response = await fetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: currentUserId(),
      movie_id: movie.movie_id || `manual:${movie.title}:${movie.year || "na"}`,
      title: movie.title,
      liked,
      genres: movie.genres || [],
      year: movie.year,
      overview: movie.overview,
    }),
  });
  if (!response.ok) {
    const text = await response.text();
    console.error(`Feedback failed: ${response.status} - ${text}`);
    throw new Error(`Feedback failed (${response.status})`);
  }
  const result = await response.json();
  console.log("Feedback response:", result);
  return result;
}

async function sendDownload(movie) {
  console.log(`Sending download request: ${movie.title}`);
  const response = await fetch("/api/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: movie.title,
      year: movie.year,
    }),
  });
  if (!response.ok) {
    const text = await response.text();
    console.error(`Download failed: ${response.status} - ${text}`);
    throw new Error(`Download failed (${response.status})`);
  }
  const result = await response.json();
  console.log("Download response:", result);
  return result;
}

// Source link generators
function getSourceLinks(movie) {
  const links = [];
  const title = encodeURIComponent(movie.title || "");
  const year = movie.year || "";
  const titleYear = encodeURIComponent(`${movie.title} ${year}`.trim());

  // Rotten Tomatoes
  const rtSlug = (movie.title || "").toLowerCase().replace(/[^a-z0-9]+/g, "_");
  links.push({
    label: "RT",
    url: `https://www.rottentomatoes.com/search?search=${title}`,
    cls: "rt",
  });

  // RogerEbert
  links.push({
    label: "Ebert",
    url: `https://www.rogerebert.com/search?utf8=%E2%9C%93&q=${title}`,
    cls: "rogerebert",
  });

  // IMDB
  links.push({
    label: "IMDB",
    url: `https://www.imdb.com/find/?q=${titleYear}`,
    cls: "imdb",
  });

  // TMDB
  links.push({
    label: "TMDB",
    url: `https://www.themoviedb.org/search?query=${title}`,
    cls: "tmdb",
  });

  // Letterboxd
  links.push({
    label: "Letterboxd",
    url: `https://letterboxd.com/search/${title}/`,
    cls: "letterboxd",
  });

  // YouTube Trailer
  links.push({
    label: "Trailer",
    url: `https://www.youtube.com/results?search_query=${titleYear}+trailer`,
    cls: "trailer",
  });

  return links;
}

function getTrailerSearchUrl(movie) {
  const titleYear = encodeURIComponent(`${movie?.title || ""} ${movie?.year || ""}`.trim());
  return `https://www.youtube.com/results?search_query=${titleYear}+trailer`;
}

async function loadTrailerEmbed(container, movie) {
  container.innerHTML = `<div class="trailer-loading">Loading...</div>`;
  try {
    const params = new URLSearchParams({ title: movie.title || "" });
    if (movie.year) params.set("year", String(movie.year));
    const res = await fetch(`/api/trailer?${params}`);
    const data = await res.json();
    if (data.ok && data.video_key) {
      const url = `https://www.youtube.com/watch?v=${data.video_key}`;
      const thumb = `https://img.youtube.com/vi/${data.video_key}/hqdefault.jpg`;
      container.innerHTML = `<a class="trailer-thumb" href="${url}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()"><img src="${thumb}" alt="Trailer" /><span class="trailer-play-icon">▶</span></a>`;
    } else {
      const fallbackUrl = getTrailerSearchUrl(movie);
      container.innerHTML = `<a class="trailer-fallback" href="${fallbackUrl}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">▶ Search Trailer</a>`;
    }
  } catch {
    const fallbackUrl = getTrailerSearchUrl(movie);
    container.innerHTML = `<a class="trailer-fallback" href="${fallbackUrl}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">▶ Search Trailer</a>`;
  }
}

// Modal functions
function openMovieModal(rec) {
  if (!movieModal) return;

  currentModalMovie = rec.movie;
  const movie = rec.movie;

  // Set poster — click opens YouTube trailer
  const posterUrl = (movie.poster_url || "").trim();
  if (modalPosterImg) {
    modalPosterImg.src = posterUrl || generatedPosterDataUrl(movie);
    modalPosterImg.alt = movie.title;
    modalPosterImg.style.cursor = "pointer";
    modalPosterImg.title = "Watch trailer on YouTube";
    modalPosterImg.onclick = () => {
      window.open(getTrailerSearchUrl(movie), "_blank", "noopener,noreferrer");
    };
  }

  // Set title
  if (modalTitle) modalTitle.textContent = movie.title;

  // Set meta
  if (modalMeta) {
    const critic = criticLabel(movie);
    modalMeta.textContent = [
      movie.year,
      movie.release_date ? `Release: ${movie.release_date}` : null,
      critic,
      (movie.genres || []).slice(0, 3).join(", "),
    ].filter(Boolean).join(" • ");
  }

  // Set score
  if (modalScore) {
    modalScore.textContent = `${Math.round(rec.score)}`;
  }

  // Set overview
  if (modalOverview) {
    modalOverview.textContent = movie.overview || "No synopsis available.";
  }

  // Set source links
  if (modalSourceLinks) {
    modalSourceLinks.innerHTML = "";
    getSourceLinks(movie).forEach((link) => {
      const a = document.createElement("a");
      a.href = link.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = link.label;
      a.className = `source-link ${link.cls}`;
      modalSourceLinks.appendChild(a);
    });
  }

  // Setup action buttons
  const modalLikeBtn = document.getElementById("modal-like");
  if (modalLikeBtn) {
    modalLikeBtn.disabled = false;
    modalLikeBtn.textContent = "\u2764 Like";
    modalLikeBtn.onclick = async () => {
      if (modalLikeBtn.disabled) return;
      modalLikeBtn.disabled = true;
      try {
        await sendFeedback(movie, true);
        modalLikeBtn.textContent = "\u2713 Liked";
      } catch (err) {
        modalLikeBtn.textContent = "Error";
      }
    };
  }

  if (modalDownloadBtn) {
    modalDownloadBtn.disabled = false;
    modalDownloadBtn.textContent = "\u25B6 Download";
    modalDownloadBtn.onclick = async () => {
      if (modalDownloadBtn.disabled) return;
      modalDownloadBtn.disabled = true;
      modalDownloadBtn.textContent = "Sending...";
      try {
        const result = await sendDownload(movie);
        if (result?.status === "queued") {
          modalDownloadBtn.textContent = "\u2713 Queued!";
        } else if (result?.status === "exists") {
          modalDownloadBtn.textContent = "Already tracked";
        } else if (result?.status === "error") {
          modalDownloadBtn.textContent = "Error";
          modalDownloadBtn.title = result.message || "Radarr error";
        } else {
          modalDownloadBtn.textContent = "\u2713 Sent";
        }
        await loadDownloadActivity();
      } catch (err) {
        modalDownloadBtn.textContent = "Failed";
      }
    };
  }

  if (modalSkipBtn) {
    modalSkipBtn.disabled = false;
    modalSkipBtn.textContent = "Skip";
    modalSkipBtn.onclick = async () => {
      if (modalSkipBtn.disabled) return;
      modalSkipBtn.disabled = true;
      try {
        await sendFeedback(movie, false);
        modalSkipBtn.textContent = "Skipped";
        closeMovieModal();
      } catch (err) {
        modalSkipBtn.textContent = "Error";
      }
    };
  }

  // Show modal
  movieModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

function closeMovieModal() {
  if (!movieModal) return;
  movieModal.classList.add("hidden");
  document.body.style.overflow = "";
  currentModalMovie = null;
}

// Setup modal event listeners
if (movieModal) {
  // Close on backdrop click
  const backdrop = movieModal.querySelector(".modal-backdrop");
  if (backdrop) backdrop.addEventListener("click", closeMovieModal);

  // Close on X button
  const closeBtn = movieModal.querySelector(".modal-close");
  if (closeBtn) closeBtn.addEventListener("click", closeMovieModal);

  // Close on Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !movieModal.classList.contains("hidden")) {
      closeMovieModal();
    }
  });
}

function renderRecommendations(recommendations) {
  if (!recsEl || !template) return;
  recsEl.innerHTML = "";
  currentRecommendations = recommendations;

  recommendations.forEach((rec, index) => {
    const node = template.content.cloneNode(true);
    const card = node.querySelector(".flip-card");
    if (!card) {
      console.error("Could not find .flip-card in template");
      return;
    }
    card.dataset.movieIndex = String(index);

    const movie = rec.movie;
    const critic = criticLabel(movie);
    const genreText = (movie.genres || []).slice(0, 3).join(", ");
    const metaText = [movie.year || "Year unknown", genreText || null, critic].filter(Boolean).join(" \u2022 ");
    const scoreText = `${Math.round(rec.score)}`;

    // --- Front ---
    const frontTitle = node.querySelector(".flip-front-title");
    if (frontTitle) frontTitle.textContent = movie.title;

    const frontMeta = node.querySelector(".flip-front-meta");
    if (frontMeta) frontMeta.textContent = metaText;

    const frontScore = node.querySelector(".flip-front-score");
    if (frontScore) frontScore.textContent = scoreText;

    // Poster image
    const imageEl = node.querySelector(".cover-image");
    const fallbackEl = node.querySelector(".cover-fallback");
    const monogramEl = node.querySelector(".cover-monogram");
    const yearEl = node.querySelector(".cover-year");

    if (monogramEl) monogramEl.textContent = monogramFromTitle(movie.title || "Movie");
    if (yearEl) yearEl.textContent = movie.year || "";

    const posterUrl = (movie.poster_url || "").trim();
    if (posterUrl && imageEl) {
      imageEl.src = posterUrl;
      imageEl.style.display = "block";
      if (fallbackEl) fallbackEl.style.display = "none";
      imageEl.onerror = () => {
        imageEl.src = generatedPosterDataUrl(movie);
      };
    } else if (imageEl) {
      imageEl.src = generatedPosterDataUrl(movie);
      imageEl.style.display = "block";
      if (fallbackEl) fallbackEl.style.display = "none";
    }

    // --- Back ---
    const backTitles = node.querySelectorAll(".flip-card-back .title");
    backTitles.forEach((el) => {
      el.textContent = movie.title;
      el.addEventListener("click", (e) => { e.stopPropagation(); openMovieModal(rec); });
    });

    const backScore = node.querySelector(".back-score");
    if (backScore) backScore.textContent = scoreText;

    const backMeta = node.querySelector(".back-meta");
    if (backMeta) backMeta.textContent = metaText;

    const overviewEl = node.querySelector(".overview");
    if (overviewEl) overviewEl.textContent = movie.overview || "No overview available.";

    const sourceLinksEl = node.querySelector(".source-links");
    if (sourceLinksEl) {
      getSourceLinks(movie).slice(0, 4).forEach((link) => {
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = link.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = link.label;
        a.className = `source-link ${link.cls}`;
        a.addEventListener("click", (e) => e.stopPropagation());
        li.appendChild(a);
        sourceLinksEl.appendChild(li);
      });
    }

    // --- Trailer embed on back ---
    const trailerEmbed = node.querySelector(".trailer-embed");
    let trailerLoaded = false;

    // --- Flip on click ---
    card.addEventListener("click", () => {
      card.classList.toggle("flipped");
      if (card.classList.contains("flipped") && trailerEmbed && !trailerLoaded) {
        trailerLoaded = true;
        loadTrailerEmbed(trailerEmbed, movie);
      }
    });

    // --- Buttons ---
    const likeBtn = node.querySelector(".like");
    const dlBtn = node.querySelector(".download");
    const dislikeBtn = node.querySelector(".dislike");

    likeBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (likeBtn.disabled) return;
      likeBtn.disabled = true;
      likeBtn.textContent = "...";
      try {
        await sendFeedback(movie, true);
        const monRes = await fetch("/api/monitor", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: movie.title, year: movie.year }),
        });
        const monData = await monRes.json();
        if (monData.status === "monitored") {
          likeBtn.textContent = "✓ Monitoring";
        } else if (monData.status === "exists") {
          likeBtn.textContent = "✓ Liked";
        } else {
          likeBtn.textContent = "✓ Liked";
        }
        loadRadarrMonitored();
      } catch (err) {
        likeBtn.textContent = "Error";
      }
    });

    if (dlBtn) {
      dlBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (dlBtn.disabled) return;
        dlBtn.disabled = true;
        dlBtn.textContent = "Sending...";
        try {
          const result = await sendDownload(movie);
          if (result?.status === "queued") {
            dlBtn.textContent = "\u2713 Queued!";
          } else if (result?.status === "exists") {
            dlBtn.textContent = "Already tracked";
          } else if (result?.status === "error") {
            dlBtn.textContent = "Error";
            dlBtn.title = result.message || "Radarr error";
          } else {
            dlBtn.textContent = "\u2713 Sent";
          }
          await loadDownloadActivity();
        } catch (err) {
          dlBtn.textContent = "Failed";
          dlBtn.title = err.message || "Download failed";
        }
      });
    }

    dislikeBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (dislikeBtn.disabled) return;
      dislikeBtn.disabled = true;
      likeBtn.disabled = true;
      try {
        await sendFeedback(movie, false);
        card.style.opacity = "0.5";
        dislikeBtn.textContent = "Skipped";
      } catch (err) {
        dislikeBtn.textContent = "Error";
      }
    });

    recsEl.appendChild(node);
  });
}

async function downloadAllMovies() {
  if (!downloadAllBtn || !currentRecommendations.length) return;

  downloadAllBtn.disabled = true;
  downloadAllBtn.textContent = "Downloading...";

  let success = 0;
  let failed = 0;

  for (const rec of currentRecommendations) {
    try {
      const result = await sendDownload(rec.movie);
      if (result?.status === "queued" || result?.status === "exists") {
        success++;
      } else {
        failed++;
      }
    } catch {
      failed++;
    }
  }

  downloadAllBtn.textContent = `Done: ${success} queued, ${failed} failed`;
  await loadDownloadActivity();

  setTimeout(() => {
    downloadAllBtn.disabled = false;
    downloadAllBtn.textContent = "Download All";
  }, 3000);
}

function renderCalendarSourceFilters() {
  const counts = {};
  calendarItems.forEach((item) => {
    (item.sources || []).forEach((source) => {
      const key = canonicalSourceKey(source);
      if (key) counts[key] = (counts[key] || 0) + 1;
    });
  });

  const options = SOURCE_OPTIONS.filter((opt) => counts[opt.key]).map((opt) => ({
    key: opt.key,
    label: `${opt.label} (${counts[opt.key]})`,
  }));

  if (calendarSourceSelections.size === 0) {
    options.forEach((opt) => calendarSourceSelections.add(opt.key));
  }

  renderSourceFilters(calendarSourceFiltersEl, options, calendarSourceSelections, renderReleaseCalendar);
}

function renderReleaseCalendar() {
  if (!releaseCalendarEl) return;

  const { releaseFrom, releaseTo } = activeReleaseDateFilters();
  const hasDateFilter = Boolean(releaseFrom || releaseTo);
  const today = new Date();
  today.setHours(23, 59, 59, 999);
  const activeSources = activeCalendarSourceFilter();

  const cutoff = new Date("2026-01-01T00:00:00");

  const rows = (calendarItems || [])
    .filter((item) => {
      if (!activeSources) return true;
      return (item.sources || []).some((source) => {
        const key = canonicalSourceKey(source);
        return key && activeSources.has(key);
      });
    })
    .map((item) => {
      const dt = new Date(`${item.release_date}T00:00:00`);
      return Number.isNaN(dt.getTime()) ? null : {
        title: item.title,
        releaseDate: item.release_date,
        year: item.year,
        dt,
        sources: item.sources || [],
      };
    })
    .filter(Boolean)
    .filter((row) => row.dt >= cutoff)
    .sort((a, b) => a.dt - b.dt);

  releaseCalendarEl.innerHTML = "";
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No releases for selected filters.";
    releaseCalendarEl.appendChild(empty);
    return;
  }

  const byMonth = new Map();
  rows.forEach((row) => {
    const monthKey = row.dt.toLocaleString(undefined, { month: "long", year: "numeric" });
    const items = byMonth.get(monthKey) || [];
    items.push(row);
    byMonth.set(monthKey, items);
  });

  byMonth.forEach((items, monthKey) => {
    const wrap = document.createElement("section");
    wrap.className = "cal-month";

    const month = document.createElement("h4");
    month.textContent = monthKey;
    wrap.appendChild(month);

    const list = document.createElement("ul");
    list.className = "cal-list";

    items.forEach((item) => {
      const li = document.createElement("li");
      li.className = "cal-item";

      const day = item.dt.toLocaleString(undefined, { day: "2-digit" });
      const shortMonth = item.dt.toLocaleString(undefined, { month: "short" });
      const sourceText = [...new Set(item.sources.map((s) => sourceLabel(canonicalSourceKey(s) || s)))].slice(0, 2).join(", ");

      const info = document.createElement("div");
      info.className = "cal-info";
      info.innerHTML = `<span class="cal-date">${shortMonth} ${day}</span><span class="cal-title">${item.title}${item.year ? ` (${item.year})` : ""}<small class="cal-sources">${sourceText}</small></span>`;

      const dlBtn = document.createElement("button");
      dlBtn.type = "button";
      dlBtn.className = "cal-dl-btn";
      dlBtn.textContent = "⬇";
      dlBtn.title = `Download ${item.title}`;
      dlBtn.addEventListener("click", async () => {
        if (dlBtn.disabled) return;
        dlBtn.disabled = true;
        dlBtn.textContent = "…";
        try {
          const result = await sendDownload({ title: item.title, year: item.year });
          if (result?.status === "queued") {
            dlBtn.textContent = "✓";
          } else if (result?.status === "exists") {
            dlBtn.textContent = "✓";
            dlBtn.title = "Already tracked";
          } else {
            dlBtn.textContent = "✗";
          }
        } catch {
          dlBtn.textContent = "✗";
        }
      });

      li.appendChild(info);
      li.appendChild(dlBtn);
      list.appendChild(li);
    });

    wrap.appendChild(list);
    releaseCalendarEl.appendChild(wrap);
  });
}

async function loadReleaseCalendar(user) {
  const url = new URL("/api/release-calendar", window.location.origin);
  url.searchParams.set("user_id", user);
  const { releaseFrom, releaseTo } = activeReleaseDateFilters();
  if (releaseFrom) url.searchParams.set("release_from", releaseFrom);
  if (releaseTo) url.searchParams.set("release_to", releaseTo);

  const res = await fetch(url.toString());
  const data = await res.json();
  calendarItems = data.items || [];
  renderCalendarSourceFilters();
  renderReleaseCalendar();
}

function renderHomeSourceFilters() {
  renderSourceFilters(homeSourceFiltersEl, SOURCE_OPTIONS, homeSourceSelections, () => {
    debouncedLoadRecommendations();
  });
}

function getClientFilters() {
  return {
    minScore: Number(minScoreEl?.value) || 0,
    yearFrom: Number(yearFromEl?.value) || 0,
    yearTo: Number(yearToEl?.value) || 9999,
    genre: (genreFilterEl?.value || "").toLowerCase(),
  };
}

function sortRecommendations(recommendations) {
  const sortVal = sortSelect?.value || "score-desc";
  const sorted = [...recommendations];
  switch (sortVal) {
    case "score-desc":
      sorted.sort((a, b) => (b.score || 0) - (a.score || 0));
      break;
    case "score-asc":
      sorted.sort((a, b) => (a.score || 0) - (b.score || 0));
      break;
    case "year-desc":
      sorted.sort((a, b) => (b.movie?.year || 0) - (a.movie?.year || 0));
      break;
    case "year-asc":
      sorted.sort((a, b) => (a.movie?.year || 0) - (b.movie?.year || 0));
      break;
    case "title-asc":
      sorted.sort((a, b) => (a.movie?.title || "").localeCompare(b.movie?.title || ""));
      break;
    case "title-desc":
      sorted.sort((a, b) => (b.movie?.title || "").localeCompare(a.movie?.title || ""));
      break;
    case "rating-desc":
      sorted.sort((a, b) => {
        const rA = a.movie?.critic_score ?? a.movie?.rt_score ?? 0;
        const rB = b.movie?.critic_score ?? b.movie?.rt_score ?? 0;
        return rB - rA;
      });
      break;
  }
  return sorted;
}

function applyClientFilters(recommendations) {
  const filters = getClientFilters();
  return recommendations.filter((rec) => {
    const movie = rec.movie;

    // Score filter
    if (filters.minScore > 0 && rec.score < filters.minScore) return false;

    // Year filter
    const year = movie.year || 0;
    if (filters.yearFrom > 0 && year < filters.yearFrom) return false;
    if (filters.yearTo < 9999 && year > filters.yearTo) return false;

    // Genre filter
    if (filters.genre) {
      const genres = (movie.genres || []).map((g) => g.toLowerCase());
      if (!genres.some((g) => g.includes(filters.genre))) return false;
    }

    return true;
  });
}

async function loadRecommendations() {
  const user = currentUserId();
  const rawCount = Number.parseInt(countInput?.value, 10) || 12;
  const count = Math.max(1, Math.min(rawCount, MAX_RECOMMENDATION_COUNT));
  if (countInput) countInput.value = String(count);

  const recUrl = new URL("/api/recommendations", window.location.origin);
  recUrl.searchParams.set("user_id", user);
  const minScore = Number(minScoreEl?.value) || 0;
  const fetchMultiplier = minScore > 0 ? 5 : 2;
  recUrl.searchParams.set("count", String(Math.min(count * fetchMultiplier, MAX_RECOMMENDATION_COUNT)));

  const homeSources = activeHomeSourceQuery();
  if (homeSources) recUrl.searchParams.set("sources", homeSources);

  const { releaseFrom, releaseTo } = activeReleaseDateFilters();
  if (releaseFrom) recUrl.searchParams.set("release_from", releaseFrom);
  if (releaseTo) recUrl.searchParams.set("release_to", releaseTo);

  const yearFrom = Number(yearFromEl?.value) || 0;
  const yearTo = Number(yearToEl?.value) || 0;
  if (yearFrom > 0) recUrl.searchParams.set("year_from", String(yearFrom));
  if (yearTo > 0) recUrl.searchParams.set("year_to", String(yearTo));

  try {
    const [recRes] = await Promise.all([fetch(recUrl.toString()), loadReleaseCalendar(user)]);
    const data = await recRes.json();

    if (generatedAtEl) {
      generatedAtEl.textContent = `Generated ${new Date(data.generated_at).toLocaleString()}`;
    }

    renderSwarm(data.agents || []);

    // Apply client-side filters and sorting
    let filtered = applyClientFilters(data.recommendations || []);
    filtered = sortRecommendations(filtered);
    filtered = filtered.slice(0, count);

    const heroRec = filtered[0] || null;
    renderHeroMovie(heroRec);
    renderRecommendations(heroRec ? filtered.slice(1) : filtered);

    const prefAgent = (data.agents || []).find((a) => a.agent === "preferences");
    if (memoryCountEl) {
      memoryCountEl.textContent = prefAgent ? `Memory: ${prefAgent.item_count}` : "";
    }
  } catch (err) {
    console.error("Failed to load recommendations:", err);
  }
}

function debouncedLoadRecommendations() {
  if (filterDebounceTimer) clearTimeout(filterDebounceTimer);
  filterDebounceTimer = setTimeout(loadRecommendations, 200);
}

function clearAllFilters() {
  // Reset all filters
  if (minScoreEl) minScoreEl.value = "";
  if (yearFromEl) yearFromEl.value = "";
  if (yearToEl) yearToEl.value = "";
  if (genreFilterEl) genreFilterEl.value = "";
  if (releaseFromEl) releaseFromEl.value = "";
  if (releaseToEl) releaseToEl.value = "";

  // Reset source selections to all
  homeSourceSelections.clear();
  SOURCE_OPTIONS.forEach((opt) => homeSourceSelections.add(opt.key));
  renderHomeSourceFilters();

  loadRecommendations();
}

// ===== Movie Search =====
let searchTimer = null;

function closeSearch() {
  if (searchResultsEl) searchResultsEl.classList.remove("open");
}

async function performSearch(query) {
  if (!searchResultsEl) return;
  if (!query || query.length < 2) {
    closeSearch();
    return;
  }

  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
    const data = await res.json();

    searchResultsEl.innerHTML = "";

    if (!data.ok || !data.results.length) {
      const empty = document.createElement("div");
      empty.className = "search-empty";
      empty.textContent = data.message || "No results found.";
      searchResultsEl.appendChild(empty);
      searchResultsEl.classList.add("open");
      return;
    }

    data.results.forEach((m) => {
      const item = document.createElement("div");
      item.className = "search-result-item";

      if (m.poster_url) {
        const img = document.createElement("img");
        img.className = "search-result-poster";
        img.src = m.poster_url;
        img.alt = m.title;
        img.loading = "lazy";
        item.appendChild(img);
      }

      const info = document.createElement("div");
      info.className = "search-result-info";
      const title = document.createElement("div");
      title.className = "search-result-title";
      title.textContent = `${m.title}${m.year ? ` (${m.year})` : ""}`;
      info.appendChild(title);

      const meta = document.createElement("div");
      meta.className = "search-result-meta";
      const parts = [];
      if (m.vote_average) parts.push(`★ ${m.vote_average.toFixed(1)}`);
      if (m.release_date) parts.push(m.release_date);
      if (m.overview) parts.push(m.overview.slice(0, 80) + (m.overview.length > 80 ? "..." : ""));
      meta.textContent = parts.join(" • ");
      info.appendChild(meta);
      item.appendChild(info);

      const actions = document.createElement("div");
      actions.className = "search-result-actions";

      const addBtn = document.createElement("button");
      addBtn.className = "search-dl-btn search-add-btn";
      addBtn.textContent = "+ Add";
      addBtn.title = "Add to Radarr";
      addBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (addBtn.disabled) return;
        addBtn.disabled = true;
        addBtn.textContent = "...";
        try {
          const result = await sendDownload({ title: m.title, year: m.year });
          if (result?.status === "queued") {
            addBtn.textContent = "✓ Added";
          } else if (result?.status === "exists") {
            addBtn.textContent = "Exists";
          } else {
            addBtn.textContent = "✓ Added";
          }
          loadDownloadActivity(true);
          loadRadarrMonitored();
        } catch {
          addBtn.textContent = "Failed";
        }
      });
      actions.appendChild(addBtn);
      item.appendChild(actions);

      searchResultsEl.appendChild(item);
    });

    searchResultsEl.classList.add("open");
  } catch {
    searchResultsEl.innerHTML = "";
    const empty = document.createElement("div");
    empty.className = "search-empty";
    empty.textContent = "Search failed.";
    searchResultsEl.appendChild(empty);
    searchResultsEl.classList.add("open");
  }
}

if (movieSearchInput) {
  movieSearchInput.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => performSearch(movieSearchInput.value.trim()), 350);
  });

  movieSearchInput.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeSearch();
      movieSearchInput.blur();
    }
  });
}

document.addEventListener("click", (e) => {
  if (searchResultsEl && !searchResultsEl.contains(e.target) && e.target !== movieSearchInput) {
    closeSearch();
  }
});

// Event Listeners
document.getElementById("refresh")?.addEventListener("click", loadRecommendations);
refreshDownloadsBtn?.addEventListener("click", loadDownloadActivity);
refreshMonitoredBtn?.addEventListener("click", loadRadarrMonitored);
clearDownloadHistoryBtn?.addEventListener("click", clearDownloadHistory);
document.getElementById("cancel-all-downloads")?.addEventListener("click", cancelAllDownloads);
downloadAllBtn?.addEventListener("click", downloadAllMovies);

countInput?.addEventListener("input", debouncedLoadRecommendations);
countInput?.addEventListener("change", debouncedLoadRecommendations);
minScoreEl?.addEventListener("input", debouncedLoadRecommendations);
minScoreEl?.addEventListener("change", debouncedLoadRecommendations);
yearFromEl?.addEventListener("input", debouncedLoadRecommendations);
yearFromEl?.addEventListener("change", debouncedLoadRecommendations);
yearToEl?.addEventListener("input", debouncedLoadRecommendations);
yearToEl?.addEventListener("change", debouncedLoadRecommendations);
genreFilterEl?.addEventListener("input", debouncedLoadRecommendations);
genreFilterEl?.addEventListener("change", debouncedLoadRecommendations);

sortSelect?.addEventListener("change", debouncedLoadRecommendations);
clearAllFiltersBtn?.addEventListener("click", clearAllFilters);

// Auto-refresh downloads when active
let downloadRefreshInterval = null;
function startDownloadAutoRefresh() {
  if (downloadRefreshInterval) return;
  downloadRefreshInterval = setInterval(async () => {
    await Promise.all([loadDownloadActivity(true), updateStatusBanner()]);
  }, 10000); // Refresh every 10 seconds (silent)
}

function stopDownloadAutoRefresh() {
  if (downloadRefreshInterval) {
    clearInterval(downloadRefreshInterval);
    downloadRefreshInterval = null;
  }
}

// Initialize
(async function init() {
  initTheme();
  renderHomeSourceFilters();
  await Promise.all([fetchIntegrations(), loadDownloadActivity(), loadRadarrMonitored(), updateStatusBanner()]);
  await loadRecommendations();

  // Start auto-refresh for downloads
  startDownloadAutoRefresh();
})();
