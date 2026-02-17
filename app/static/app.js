// DOM Elements
const integrationsEl = document.getElementById("integrations");
const recsEl = document.getElementById("recommendations");
const template = document.getElementById("rec-card-template");
const swarmMap = document.getElementById("swarm-map");
const agentLog = document.getElementById("agent-log");
const generatedAtEl = document.getElementById("generated-at");
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
const modalEvidenceEl = document.getElementById("modal-evidence");
const modalTrailerContainer = document.getElementById("modal-trailer-container");
const modalDownloadBtn = document.getElementById("modal-download");
const modalPlexWatchlistBtn = document.getElementById("modal-plex-watchlist");
const modalCheckUsenetBtn = document.getElementById("modal-check-usenet");
const modalDeleteBtn = document.getElementById("modal-delete");
const modalSkipBtn = document.getElementById("modal-skip");

// Login elements
const loginModal = document.getElementById("login-modal");
const loginBtn = document.getElementById("login-btn");
const logoutBtn = document.getElementById("logout-btn");
const userDropdown = document.getElementById("user-dropdown");
const userNameEl = document.getElementById("user-name");
const googleLoginSection = document.getElementById("google-login-section");
const googleNotConfigured = document.getElementById("google-not-configured");

const DOWNLOAD_HISTORY_CLEAR_KEY = "majic_download_history_cleared_at";
const AUTH_TOKEN_KEY = "majic_auth_token";
const AUTH_USER_KEY = "majic_auth_user";

// Just Added elements
const justAddedSection = document.getElementById("just-added-section");
const justAddedGrid = document.getElementById("just-added-grid");
const justAddedDateEl = document.getElementById("just-added-date");
const justAddedSyncBtn = document.getElementById("just-added-sync-btn");
let justAddedCheckedAt = null;
let justAddedLastPollAt = null;
let justAddedPollIntervalMinutes = null;
let justAddedMetaTimer = null;
let justAddedRefreshTimer = null;
const THEME_KEY = "majic_theme";
let downloadHistoryClearedAt = localStorage.getItem(DOWNLOAD_HISTORY_CLEAR_KEY);
let currentRecommendations = [];
let availabilityFilter = "all"; // all, ready, unreleased, unavailable
let currentModalMovie = null;
const RECOMMENDATION_BATCH_SIZE = 8;
const RECOMMENDATION_OBSERVER_ROOT_MARGIN = "500px 0px";
let renderedRecommendationCount = 0;
let recommendationObserver = null;
let recommendationSentinel = null;
let recommendationScrollActivated = false;

const SOURCE_OPTIONS = [
  { key: "rt", label: "RT" },
  { key: "rogerebert", label: "Ebert" },
  { key: "nzbgeek", label: "NZBGeek" },
  { key: "drunkenslug", label: "Drunken Slug" },
  { key: "releases", label: "Releases" },
  { key: "upcoming", label: "TMDB" },
  { key: "plex", label: "Plex" },
  { key: "oscars", label: "Oscars" },
  { key: "criterion", label: "Criterion" },
];

// Initialize with all sources selected
const homeSourceSelections = new Set(SOURCE_OPTIONS.map((opt) => opt.key));
const calendarSourceSelections = new Set();
let calendarItems = [];
let filterDebounceTimer = null;
const MAX_RECOMMENDATION_COUNT = 500;

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
      radarrStatusEl.innerHTML = '<span class="status-error">⚠ Download service not configured</span> — Downloads disabled. <a href="/integrations" style="color: var(--primary);">Configure in Settings</a>';
    } else if (!data.ok) {
      radarrStatusEl.innerHTML = `<span class="status-error">⚠ Download service error</span> — ${data.message || "Connection failed"}`;
    } else {
      const queueText = data.queue_count === 0 ? "No active downloads" : `${data.queue_count} in queue`;
      const rateText = data.download_rate_human ? ` • ${data.download_rate_human}` : "";
      radarrStatusEl.innerHTML = `<span class="status-ok">✓ Download service connected</span> — ${queueText}${rateText}`;
    }
  } catch (err) {
    radarrStatusEl.innerHTML = '<span class="status-error">⚠ Cannot check download service</span>';
  }
}

// Disk space display
const diskSpaceContainer = document.getElementById("disk-space-container");
async function loadDiskSpace() {
  if (!diskSpaceContainer) return;
  try {
    const res = await fetch("/api/disk-space");
    const data = await res.json();
    if (!data.ok || !data.disks || data.disks.length === 0) {
      diskSpaceContainer.innerHTML = '';
      return;
    }

    let html = '';
    for (const disk of data.disks) {
      const percent = disk.percent_used || 0;
      let levelClass = 'low';
      if (percent >= 90) levelClass = 'high';
      else if (percent >= 70) levelClass = 'medium';

      html += `
        <div class="disk-space-item">
          <div class="disk-space-header">
            <span class="disk-space-label">${disk.label || disk.path}</span>
            <span class="disk-space-info">${disk.free_human} free</span>
          </div>
          <div class="disk-space-bar">
            <div class="disk-space-fill ${levelClass}" style="width: ${percent}%"></div>
          </div>
          <div class="disk-space-details">
            <span>${disk.used_human} used</span>
            <span>${disk.total_human} total</span>
          </div>
        </div>
      `;
    }
    diskSpaceContainer.innerHTML = html;
  } catch (err) {
    console.error("Failed to load disk space:", err);
    diskSpaceContainer.innerHTML = '';
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
  // New agent sources
  if (value === "imdb_top250") return "imdb_top250";
  if (value === "a24") return "a24";
  if (value === "afi100") return "afi100";
  if (value === "cannes") return "cannes";
  if (value === "ghibli") return "ghibli";
  if (value === "sundance") return "sundance";
  if (value === "bafta") return "bafta";
  if (value === "golden_globes") return "golden_globes";
  if (value === "blumhouse") return "blumhouse";
  if (value === "marvel_dc") return "marvel_dc";
  if (value === "letterboxd") return "letterboxd";
  if (value === "mubi") return "mubi";
  if (value === "film_registry") return "film_registry";
  if (value === "metacritic") return "metacritic";
  if (value === "boxoffice") return "boxoffice";
  if (value === "hidden_gems") return "hidden_gems";
  if (value === "directors") return "directors";
  if (value === "decades") return "decades";
  if (value === "sight_sound") return "sight_sound";
  if (value === "pixar") return "pixar";
  if (value === "disney") return "disney";
  if (value === "horror_classics") return "horror_classics";
  if (value === "scifi") return "scifi";
  if (value === "anime") return "anime";
  if (value === "korean_cinema") return "korean_cinema";
  if (value === "film_noir") return "film_noir";
  if (value === "neon") return "neon";
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
  return keys;
}

function sourceLabel(key) {
  const overrides = {
    tmdb: "TMDB",
    upcoming: "Upcoming",
    rogerebert: "Ebert",
    releases: "Releases",
    rt: "RT",
    plex: "Plex",
    nzbgeek: "NZBGeek",
    drunkenslug: "DrunkenSlug",
    // New agent labels
    oscars: "Oscars",
    criterion: "Criterion",
    imdb_top250: "IMDB 250",
    a24: "A24",
    afi100: "AFI 100",
    cannes: "Cannes",
    ghibli: "Ghibli",
    sundance: "Sundance",
    bafta: "BAFTA",
    golden_globes: "Globes",
    blumhouse: "Blumhouse",
    marvel_dc: "Marvel/DC",
    letterboxd: "Letterboxd",
    mubi: "MUBI",
    film_registry: "Nat'l Registry",
    metacritic: "Metacritic",
    boxoffice: "Box Office",
    hidden_gems: "Hidden Gem",
    directors: "Directors",
    decades: "Decades",
    sight_sound: "Sight & Sound",
    pixar: "Pixar",
    disney: "Disney",
    horror_classics: "Horror",
    scifi: "Sci-Fi",
    anime: "Anime",
    korean_cinema: "Korean",
    film_noir: "Film Noir",
    neon: "Neon",
  };
  if (overrides[key]) return overrides[key];
  const option = SOURCE_OPTIONS.find((item) => item.key === key);
  return option ? option.label : key;
}

// Source tooltip labels for hover display
const SOURCE_TOOLTIP_LABELS = {
  oscars: "Academy Awards",
  criterion: "Criterion Collection",
  rottentomatoes: "Rotten Tomatoes",
  rt: "Rotten Tomatoes",
  rogerebert: "Roger Ebert",
  nzbgeek: "NZBGeek",
  drunkenslug: "DrunkenSlug",
  usenet: "Usenet",
  plex: "Plex Library",
  radarr: "Radarr",
  upcoming: "Coming Soon",
  tmdb: "TMDB",
  releases: "Releases.com",
  "tmdb-discover": "TMDB",
  "nzbgeek-rss": "NZBGeek",
  "2160p": "4K UHD",
  "1080p": "1080p HD",
  hdr: "HDR",
  "now-playing": "Now Playing",
  unreleased: "Unreleased",
  // New agent tooltips
  imdb_top250: "IMDB Top 250",
  a24: "A24 Films",
  afi100: "AFI 100 Years",
  cannes: "Cannes Palme d'Or",
  ghibli: "Studio Ghibli",
  sundance: "Sundance Winner",
  bafta: "BAFTA Winner",
  golden_globes: "Golden Globe Winner",
  blumhouse: "Blumhouse Productions",
  marvel_dc: "Marvel/DC Universe",
  letterboxd: "Letterboxd Top Rated",
  mubi: "MUBI Curated",
  film_registry: "National Film Registry",
  metacritic: "Metacritic 90+",
  boxoffice: "Box Office Hit",
  hidden_gems: "Hidden Gem",
  directors: "Director Spotlight",
  decades: "Decades Essential",
  sight_sound: "Sight & Sound Top 100",
  pixar: "Pixar Animation",
  disney: "Disney Classic",
  horror_classics: "Horror Classic",
  scifi: "Sci-Fi Essential",
  anime: "Anime Essential",
  korean_cinema: "Korean Cinema",
  film_noir: "Film Noir Classic",
  neon: "Neon Films",
};

function renderSourceIndicatorsHtml(movie) {
  const tags = movie.source_tags || [];
  if (!tags.length) return "";

  // Priority order for indicators
  const priorityOrder = [
    "oscars", "criterion", "rogerebert",
    "nzbgeek", "drunkenslug", "plex", "radarr", "upcoming", "tmdb",
    "releases", "2160p", "1080p", "hdr"
  ];

  // Normalize and dedupe
  const normalized = new Set();
  const indicatorList = [];

  for (const tag of tags) {
    const key = canonicalSourceKey(tag) || tag.toLowerCase();
    if (normalized.has(key)) continue;
    // Skip generic/duplicate tags and remove noisy dots on covers.
    if ([
      "usenet",
      "nzbgeek-rss",
      "tmdb-discover",
      "now-playing",
      "unreleased",
      "rt",
      "rottentomatoes",
      "upcoming",
      "tmdb",
    ].includes(key)) continue;
    normalized.add(key);
    const tooltip = SOURCE_TOOLTIP_LABELS[key] || sourceLabel(key);
    if (tooltip) {
      indicatorList.push({ key, tooltip, priority: priorityOrder.indexOf(key) });
    }
  }

  // Sort by priority and limit to 5 dots
  indicatorList.sort((a, b) => {
    const pa = a.priority >= 0 ? a.priority : 999;
    const pb = b.priority >= 0 ? b.priority : 999;
    return pa - pb;
  });

  const dots = indicatorList.slice(0, 5).map(({ key, tooltip }) => {
    const cssClass = key.replace(/[^a-z0-9]/gi, "-").toLowerCase();
    return `<span class="source-dot ${cssClass}" data-tooltip="${tooltip}"></span>`;
  });

  return dots.length ? `<div class="source-indicators">${dots.join("")}</div>` : "";
}

function sourceOriginText(movie) {
  if (!movie) return null;
  const keys = sourceKeysFromMovie(movie);
  // Priority order - curated/awards first, then platforms
  const priority = [
    // Awards & Festivals
    "oscars",
    "cannes",
    "bafta",
    "golden_globes",
    "sundance",
    // Curated Collections
    "criterion",
    "a24",
    "neon",
    "ghibli",
    "pixar",
    "disney",
    "blumhouse",
    "marvel_dc",
    // Critic Lists
    "afi100",
    "imdb_top250",
    "sight_sound",
    "letterboxd",
    "mubi",
    "film_registry",
    "metacritic",
    // Genre/Discovery
    "hidden_gems",
    "directors",
    "decades",
    "boxoffice",
    "horror_classics",
    "scifi",
    "anime",
    "korean_cinema",
    "film_noir",
    // Critics
    "rt",
    "rogerebert",
    // Usenet/Availability
    "drunkenslug",
    "nzbgeek",
    "releases",
    "upcoming",
    "plex",
    "radarr",
  ];
  const labels = [];
  priority.forEach((key) => {
    if (!keys.has(key)) return;
    const label = sourceLabel(key);
    if (!labels.includes(label)) labels.push(label);
  });
  if (!labels.length) {
    if (keys.has("usenet")) return "Usenet";
    return null;
  }
  return labels.slice(0, 3).join(" · ");
}

function frontSourceOriginText(movie) {
  const origin = sourceOriginText(movie);
  if (!origin) return null;
  // Filter out generic/uninformative sources
  const genericSources = ["TMDB", "UPCOMING", "NOW PLAYING", "RELEASES"];
  const filtered = origin
    .split("·")
    .map((part) => part.trim())
    .filter((part) => part && !genericSources.includes(part.toUpperCase()));
  return filtered.length ? filtered.join(" · ") : null;
}

function sourceAttributionText(movie) {
  if (!movie) return null;
  const keys = sourceKeysFromMovie(movie);
  const primaryOrder = [
    "drunkenslug",
    "nzbgeek",
    "releases",
    "tmdb",
    "upcoming",
    "rt",
    "rogerebert",
    "oscars",
    "criterion",
  ];
  const primaryLabels = [];
  primaryOrder.forEach((key) => {
    if (!keys.has(key)) return;
    const label = sourceLabel(key);
    if (!primaryLabels.includes(label)) primaryLabels.push(label);
  });
  if (primaryLabels.length) {
    return primaryLabels.join(" / ");
  }

  if (keys.has("usenet")) return "Usenet";

  const fallbackOrder = ["plex"];
  const fallbackLabels = fallbackOrder.filter((key) => keys.has(key)).map((key) => sourceLabel(key));
  return fallbackLabels.length ? fallbackLabels.join(" / ") : null;
}

function evidenceItems(movie) {
  const raw = Array.isArray(movie?.evidence) ? movie.evidence : [];
  const cleaned = raw
    .map((row) => String(row || "").trim())
    .filter(Boolean)
    .map((row) => row.replace(/\s+/g, " "));
  const unique = [...new Set(cleaned)];
  if (unique.length) return unique;
  const source = sourceAttributionText(movie);
  return source ? [`Aggregated from ${source}`] : [];
}

function titleWithSource(movie) {
  const baseTitle = String(movie?.title || "").trim();
  return baseTitle || "";
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

function parseMovieReleaseDate(movie) {
  const raw = String(movie?.release_date || "").trim();
  if (!raw) return null;
  const normalized = raw.slice(0, 10);
  const dt = new Date(`${normalized}T00:00:00`);
  return Number.isNaN(dt.getTime()) ? null : dt;
}

function movieReleaseSortValue(movie) {
  const dt = parseMovieReleaseDate(movie);
  if (dt) return dt.getTime();
  const year = Number(movie?.year || 0);
  if (Number.isFinite(year) && year > 0) return Date.UTC(year, 0, 1);
  return Number.NEGATIVE_INFINITY;
}

function releaseDateChip(movie) {
  const dt = parseMovieReleaseDate(movie);
  if (!dt) return null;
  return `Release ${dt.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`;
}

function isUpcomingRelease(movie) {
  const dt = parseMovieReleaseDate(movie);
  if (!dt) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return dt.getTime() >= today.getTime();
}

function isCurrentRelease(movie) {
  const dt = parseMovieReleaseDate(movie);
  if (!dt) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return dt.getTime() < today.getTime();
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
      drunkenslug: "Drunken Slug",
      tmdb: "TMDB",
      plex: "Plex",
      radarr: "Downloads",
      ollama: "AI",
    };

    // Put downloader status first since it affects downloads
    const entries = Object.entries(data).filter(([name]) => name !== "usenet");
    const radarrEntry = entries.find(([name]) => name === "radarr");
    const otherEntries = entries.filter(([name]) => name !== "radarr");
    const sortedEntries = radarrEntry ? [radarrEntry, ...otherEntries] : otherEntries;

    sortedEntries.forEach(([name, active]) => {
      const badge = document.createElement("span");
      badge.className = `badge ${active ? "active" : "inactive"}`;
      const statusText = active ? "on" : "off";
      badge.textContent = `${labelMap[name] || name}: ${statusText}`;

      // Add special styling for download service since it affects downloads
      if (name === "radarr" && !active) {
        badge.title = "Configure download service to enable movie downloads";
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

  if (radarrUrl && item.tmdb_id != null) {
    const title = document.createElement("a");
    title.href = `${radarrUrl}/movie/${item.tmdb_id}`;
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

  // Also update the status banner and disk space
  updateStatusBanner();
  loadDiskSpace();

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
      downloadHealthEl.textContent = health.message || "Download service not configured.";
      appendListItem(activeDownloadsEl, "Configure download service in Integrations.");
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
      appendListItem(downloadHistoryEl, "Download service not configured.");
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
      monitoredStatusEl.textContent = "Download service not configured.";
      return;
    }
    if (!data.ok) {
      monitoredStatusEl.textContent = `Error: ${data.message || "unknown"}`;
      return;
    }
    if (!data.movies.length) {
      monitoredStatusEl.textContent = "No tracked movies.";
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

      if (radarrUrl && m.tmdb_id != null) {
        const title = document.createElement("a");
        title.href = `${radarrUrl}/movie/${m.tmdb_id}`;
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

let currentSwarmAgents = [];

function renderSwarm(agents) {
  currentSwarmAgents = agents || [];

  // Update preview dots
  const previewEl = document.getElementById("swarm-preview");
  const countEl = document.getElementById("swarm-count");

  if (countEl) countEl.textContent = agents.length;

  if (previewEl) {
    previewEl.innerHTML = agents.map(a => {
      const cls = a.status === "success" ? "success" : a.status === "skipped" ? "skipped" : "error";
      return `<div class="agent-dot ${cls}" title="${a.agent}"></div>`;
    }).join("");
  }

  // Update stats in modal
  const successCount = agents.filter(a => a.status === "success").length;
  const errorCount = agents.filter(a => a.status !== "success" && a.status !== "skipped").length;

  const successEl = document.getElementById("swarm-success-count");
  const errorEl = document.getElementById("swarm-error-count");
  if (successEl) successEl.textContent = successCount;
  if (errorEl) errorEl.textContent = errorCount;

  // Render the full visualization
  renderSwarmVisualization(agents);
  renderSwarmAgentList(agents);
}

function renderSwarmVisualization(agents) {
  if (!swarmMap) return;

  const ns = "http://www.w3.org/2000/svg";
  const center = { x: 400, y: 400 };

  function svg(tag, attrs = {}) {
    const el = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    return el;
  }

  swarmMap.innerHTML = "";

  // Add defs for gradients and filters
  const defs = svg("defs");

  // Glow filter
  const glowFilter = svg("filter", { id: "glow", x: "-50%", y: "-50%", width: "200%", height: "200%" });
  glowFilter.appendChild(svg("feGaussianBlur", { stdDeviation: "4", result: "coloredBlur" }));
  const feMerge = svg("feMerge");
  feMerge.appendChild(svg("feMergeNode", { in: "coloredBlur" }));
  feMerge.appendChild(svg("feMergeNode", { in: "SourceGraphic" }));
  glowFilter.appendChild(feMerge);
  defs.appendChild(glowFilter);

  // Core gradient
  const coreGrad = svg("radialGradient", { id: "coreGrad", cx: "30%", cy: "30%" });
  coreGrad.appendChild(svg("stop", { offset: "0%", "stop-color": "#ff8f6a" }));
  coreGrad.appendChild(svg("stop", { offset: "100%", "stop-color": "#ff6a42" }));
  defs.appendChild(coreGrad);

  swarmMap.appendChild(defs);

  // Animated background rings
  const ringGroup1 = svg("g", { class: "swarm-ring-1", "transform-origin": `${center.x}px ${center.y}px` });
  ringGroup1.appendChild(svg("circle", { cx: center.x, cy: center.y, r: 120, fill: "none", stroke: "rgba(255,106,66,0.1)", "stroke-width": "1" }));
  ringGroup1.appendChild(svg("circle", { cx: center.x, cy: center.y, r: 120, fill: "none", stroke: "rgba(255,106,66,0.3)", "stroke-width": "2", "stroke-dasharray": "10 20" }));
  swarmMap.appendChild(ringGroup1);

  const ringGroup2 = svg("g", { class: "swarm-ring-2", "transform-origin": `${center.x}px ${center.y}px` });
  ringGroup2.appendChild(svg("circle", { cx: center.x, cy: center.y, r: 200, fill: "none", stroke: "rgba(39,212,162,0.1)", "stroke-width": "1" }));
  ringGroup2.appendChild(svg("circle", { cx: center.x, cy: center.y, r: 200, fill: "none", stroke: "rgba(39,212,162,0.2)", "stroke-width": "2", "stroke-dasharray": "5 15" }));
  swarmMap.appendChild(ringGroup2);

  const ringGroup3 = svg("g", { class: "swarm-ring-3", "transform-origin": `${center.x}px ${center.y}px` });
  ringGroup3.appendChild(svg("circle", { cx: center.x, cy: center.y, r: 280, fill: "none", stroke: "rgba(132,145,190,0.1)", "stroke-width": "1" }));
  ringGroup3.appendChild(svg("circle", { cx: center.x, cy: center.y, r: 280, fill: "none", stroke: "rgba(132,145,190,0.15)", "stroke-width": "2", "stroke-dasharray": "3 12" }));
  swarmMap.appendChild(ringGroup3);

  // Connection lines (draw first so they're behind nodes)
  const radii = [130, 210, 290, 350];
  agents.forEach((agent, idx) => {
    const ringIndex = Math.floor(idx / 12) % radii.length;
    const agentsInRing = agents.filter((_, i) => Math.floor(i / 12) % radii.length === ringIndex);
    const indexInRing = agentsInRing.indexOf(agent);
    const angleOffset = ringIndex * 0.15;
    const angle = (Math.PI * 2 * indexInRing) / Math.max(agentsInRing.length, 1) - Math.PI / 2 + angleOffset;
    const r = radii[ringIndex];
    const x = center.x + r * Math.cos(angle);
    const y = center.y + r * Math.sin(angle);

    const color = agent.status === "success" ? "#27d4a2" : agent.status === "skipped" ? "#f5ba53" : "#ff6f71";

    swarmMap.appendChild(svg("line", {
      x1: center.x, y1: center.y, x2: x, y2: y,
      stroke: color, "stroke-width": "1", opacity: "0.15",
    }));
  });

  // Core node
  const coreGlow = svg("circle", { cx: center.x, cy: center.y, r: 55, fill: "url(#coreGrad)", filter: "url(#glow)", opacity: "0.5" });
  swarmMap.appendChild(coreGlow);

  const core = svg("circle", { cx: center.x, cy: center.y, r: 45, fill: "url(#coreGrad)", class: "swarm-core" });
  swarmMap.appendChild(core);

  const coreText = svg("text", {
    x: center.x, y: center.y - 5, "text-anchor": "middle", fill: "#fff",
    "font-size": "16", "font-weight": "700", "font-family": "Sora, sans-serif",
  });
  coreText.textContent = "MAJIC";
  swarmMap.appendChild(coreText);

  const coreSubtext = svg("text", {
    x: center.x, y: center.y + 12, "text-anchor": "middle", fill: "rgba(255,255,255,0.7)",
    "font-size": "10", "font-family": "Sora, sans-serif",
  });
  coreSubtext.textContent = `${agents.length} agents`;
  swarmMap.appendChild(coreSubtext);

  // Agent nodes in multiple rings
  agents.forEach((agent, idx) => {
    const ringIndex = Math.floor(idx / 12) % radii.length;
    const agentsInRing = agents.filter((_, i) => Math.floor(i / 12) % radii.length === ringIndex);
    const indexInRing = agentsInRing.indexOf(agent);
    const angleOffset = ringIndex * 0.15;
    const angle = (Math.PI * 2 * indexInRing) / Math.max(agentsInRing.length, 1) - Math.PI / 2 + angleOffset;
    const r = radii[ringIndex];
    const x = center.x + r * Math.cos(angle);
    const y = center.y + r * Math.sin(angle);

    const color = agent.status === "success" ? "#27d4a2" : agent.status === "skipped" ? "#f5ba53" : "#ff6f71";
    const nodeSize = 22 - ringIndex * 2;

    // Glow (non-interactive)
    swarmMap.appendChild(svg("circle", { cx: x, cy: y, r: nodeSize + 5, fill: color, opacity: "0.2", filter: "url(#glow)", style: "pointer-events: none;" }));

    // Main node circle (non-interactive visual)
    const nodeCircle = svg("circle", { cx: x, cy: y, r: nodeSize, fill: color, opacity: "0.95", style: "pointer-events: none;" });
    swarmMap.appendChild(nodeCircle);

    // Label (non-interactive)
    const shortName = agent.agent.length > 8 ? agent.agent.slice(0, 7) + "…" : agent.agent;
    const label = svg("text", {
      x, y: y + 4, "text-anchor": "middle", fill: "#fff",
      "font-size": ringIndex === 0 ? "9" : "8", "font-family": "Sora, sans-serif", "font-weight": "500",
      style: "pointer-events: none;",
    });
    label.textContent = shortName;
    swarmMap.appendChild(label);

    // Clickable hit area (on top, handles all interaction)
    const hitArea = svg("circle", {
      cx: x, cy: y, r: nodeSize + 12,
      fill: "transparent",
      style: "cursor: pointer;",
      "data-agent": agent.agent,
    });

    hitArea.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const agentName = hitArea.getAttribute("data-agent");
      if (agentName) filterByAgent(agentName);
    });

    hitArea.addEventListener("mouseenter", () => {
      nodeCircle.setAttribute("r", String(nodeSize + 4));
      nodeCircle.setAttribute("opacity", "1");
    });

    hitArea.addEventListener("mouseleave", () => {
      nodeCircle.setAttribute("r", String(nodeSize));
      nodeCircle.setAttribute("opacity", "0.95");
    });

    swarmMap.appendChild(hitArea);
  });
}

// Current agent filter state
let currentAgentFilter = null;

// Filter recommendations by agent source
function filterByAgent(agentName) {
  // Close the swarm modal first
  if (swarmModal) swarmModal.classList.remove("open");

  // Small delay to let modal close smoothly
  setTimeout(() => {
    currentAgentFilter = agentName;

    // Filter current recommendations to show only movies from this agent
    const filtered = currentRecommendations.filter(rec => {
      const tags = rec.movie?.source_tags || [];
      return tags.some(t => t.toLowerCase() === agentName.toLowerCase());
    });

    if (filtered.length === 0) {
      // Show a message if no movies found
      if (recsEl) {
        recsEl.innerHTML = `
          <div style="grid-column: 1/-1; text-align: center; padding: 40px;">
            <p class="meta">No movies found from <strong>${agentName}</strong> agent.</p>
            <button class="btn btn-ghost" onclick="clearAgentFilter()" style="margin-top: 12px;">Show All Movies</button>
          </div>`;
      }
      updateResultsCount(`0 movies from ${agentName}`, true);
    } else {
      // Render the filtered movies
      renderRecommendations(filtered);
      updateResultsCount(`${filtered.length} movies from ${agentName}`, true);
    }

    // Scroll to recommendations
    recsEl?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, 150);
}

// Clear agent filter and show all recommendations
function clearAgentFilter() {
  currentAgentFilter = null;
  renderRecommendations(currentRecommendations);
  updateResultsCount(`${currentRecommendations.length} movies`, false);
}

function updateResultsCount(text, showClear = false) {
  const countEl = document.getElementById("results-count");
  if (countEl) {
    if (showClear && currentAgentFilter) {
      countEl.innerHTML = `${text} <button class="btn btn-ghost btn-sm" onclick="clearAgentFilter()" style="margin-left: 8px; font-size: 11px;">✕ Clear Filter</button>`;
    } else {
      countEl.textContent = text;
    }
  }
}

function renderSwarmAgentList(agents) {
  if (!agentLog) return;

  agentLog.innerHTML = agents.map(agent => {
    const cls = agent.status === "success" ? "success" : agent.status === "skipped" ? "skipped" : "error";
    const clickable = agent.item_count > 0 ? "clickable" : "";
    return `
      <div class="agent-list-item ${clickable}" data-agent="${agent.agent}" title="Click to show ${agent.item_count} movies from ${agent.agent}">
        <div class="agent-indicator ${cls}"></div>
        <span class="agent-name">${agent.agent}</span>
        <span class="agent-count">${agent.item_count || 0}</span>
      </div>
    `;
  }).join("");

  // Add click handlers to agent list items
  agentLog.querySelectorAll(".agent-list-item.clickable").forEach(item => {
    item.addEventListener("click", () => {
      const agentName = item.dataset.agent;
      if (agentName) filterByAgent(agentName);
    });
  });
}

// Swarm modal handlers
const swarmCard = document.getElementById("swarm-card");
const swarmModal = document.getElementById("swarm-modal");
const swarmModalBackdrop = document.getElementById("swarm-modal-backdrop");
const swarmModalClose = document.getElementById("swarm-modal-close");

if (swarmCard) {
  swarmCard.addEventListener("click", () => {
    if (swarmModal) swarmModal.classList.add("open");
  });
}

if (swarmModalBackdrop) {
  swarmModalBackdrop.addEventListener("click", () => {
    if (swarmModal) swarmModal.classList.remove("open");
  });
}

if (swarmModalClose) {
  swarmModalClose.addEventListener("click", () => {
    if (swarmModal) swarmModal.classList.remove("open");
  });
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && swarmModal && swarmModal.classList.contains("open")) {
    swarmModal.classList.remove("open");
  }
});

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

  // Agent/Curated source badges - these are the primary sources
  const agentBadges = [
    { tag: "oscars", cls: "oscar", label: "Academy Awards", text: "Oscar" },
    { tag: "criterion", cls: "criterion", label: "Criterion Collection", text: "Criterion" },
    { tag: "a24", cls: "a24", label: "A24 Films", text: "A24" },
    { tag: "imdb_top250", cls: "imdb", label: "IMDB Top 250", text: "IMDB" },
    { tag: "afi100", cls: "afi", label: "AFI 100", text: "AFI" },
    { tag: "cannes", cls: "cannes", label: "Cannes Palme d'Or", text: "Cannes" },
    { tag: "ghibli", cls: "ghibli", label: "Studio Ghibli", text: "Ghibli" },
    { tag: "sundance", cls: "sundance", label: "Sundance", text: "Sundance" },
    { tag: "bafta", cls: "bafta", label: "BAFTA", text: "BAFTA" },
    { tag: "golden_globes", cls: "globes", label: "Golden Globes", text: "Globes" },
    { tag: "blumhouse", cls: "blumhouse", label: "Blumhouse", text: "Blum" },
    { tag: "marvel_dc", cls: "superhero", label: "Marvel/DC", text: "Hero" },
    { tag: "letterboxd", cls: "letterboxd", label: "Letterboxd Top", text: "LB" },
    { tag: "mubi", cls: "mubi", label: "MUBI Curated", text: "MUBI" },
    { tag: "film_registry", cls: "registry", label: "National Film Registry", text: "NFR" },
    { tag: "metacritic", cls: "metacritic", label: "Metacritic 90+", text: "MC" },
    { tag: "boxoffice", cls: "boxoffice", label: "Box Office Hit", text: "Box" },
    { tag: "hidden_gems", cls: "gem", label: "Hidden Gem", text: "Gem" },
    { tag: "directors", cls: "director", label: "Director Spotlight", text: "Dir" },
    { tag: "decades", cls: "decade", label: "Decades Essential", text: "Era" },
    { tag: "sight_sound", cls: "sightsound", label: "Sight & Sound", text: "S&S" },
    { tag: "pixar", cls: "pixar", label: "Pixar", text: "Pixar" },
    { tag: "disney", cls: "disney", label: "Disney Classics", text: "Disney" },
    { tag: "horror_classics", cls: "horror", label: "Horror Classic", text: "Horror" },
    { tag: "scifi", cls: "scifi", label: "Sci-Fi Essential", text: "Sci-Fi" },
    { tag: "anime", cls: "anime", label: "Anime Essential", text: "Anime" },
    { tag: "korean_cinema", cls: "korean", label: "Korean Cinema", text: "Korean" },
    { tag: "film_noir", cls: "noir", label: "Film Noir", text: "Noir" },
    { tag: "neon", cls: "neon", label: "Neon Films", text: "Neon" },
  ];

  // Add agent badges first (most important)
  for (const badge of agentBadges) {
    if (tags.has(badge.tag)) {
      icons.push({ cls: badge.cls, label: badge.label, text: badge.text });
    }
  }

  // Then add availability/platform badges
  const hasRt = Number.isFinite(movie.rottentomatoes_score) || tags.has("rottentomatoes") || [...tags].some((t) => t.startsWith("rt-"));
  if (hasRt && icons.length < 4) {
    const rtLabel = Number.isFinite(movie.rottentomatoes_score) ? `${Math.round(movie.rottentomatoes_score)}` : "RT";
    icons.push({ cls: "rt", label: "Rotten Tomatoes", text: rtLabel });
  }
  if (tags.has("rogerebert") && icons.length < 4) icons.push({ cls: "rogerebert", label: "RogerEbert", text: "RE" });
  if ((movie.available_on_plex || tags.has("plex")) && icons.length < 4) icons.push({ cls: "plex", label: "Plex", text: "Plex" });
  if ((tags.has("nzbgeek") || tags.has("nzbgeek-rss")) && icons.length < 4) icons.push({ cls: "nzb", label: "NZBGeek", text: "NZB" });
  if (tags.has("drunkenslug") && icons.length < 4) icons.push({ cls: "nzb", label: "DrunkenSlug", text: "DS" });
  if (tags.has("releases") && icons.length < 4) icons.push({ cls: "releases", label: "Releases", text: "REL" });
  if (tags.has("upcoming") && icons.length < 4) icons.push({ cls: "upcoming", label: "Upcoming", text: "Soon" });
  if (tags.has("now-playing") && icons.length < 4) icons.push({ cls: "nowplaying", label: "Now Playing", text: "Now" });

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
  title.textContent = titleWithSource(movie);
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
        dlBtn.title = result.message || "Download service error";
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

  const explainBtn = document.createElement("button");
  explainBtn.className = "btn btn-ghost";
  explainBtn.textContent = "Why this?";
  explainBtn.title = "Get an AI explanation for this recommendation";
  explainBtn.addEventListener("click", async () => {
    if (explainBtn.disabled) return;
    explainBtn.disabled = true;
    explainBtn.textContent = "Thinking...";
    try {
      const explanation = await fetchExplanation(rec);
      if (explanation) {
        showExplanationTooltip(explainBtn, explanation);
      }
      explainBtn.textContent = "Why this?";
      explainBtn.disabled = false;
    } catch (err) {
      explainBtn.textContent = "Why this?";
      explainBtn.disabled = false;
    }
  });

  actions.appendChild(likeBtn);
  actions.appendChild(dlBtn);
  actions.appendChild(explainBtn);
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

async function fetchExplanation(rec) {
  const movie = rec.movie;
  try {
    const response = await fetch("/api/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: movie.title,
        year: movie.year,
        score: rec.score,
        reasons: rec.reasons || [],
        genres: movie.genres || [],
        overview: movie.overview,
      }),
    });
    const data = await response.json();
    return data.ok ? data.explanation : null;
  } catch (err) {
    console.error("Explanation fetch failed:", err);
    return null;
  }
}

function showExplanationTooltip(anchor, text) {
  // Remove existing tooltip
  const existingTooltip = document.querySelector(".explanation-tooltip");
  if (existingTooltip) existingTooltip.remove();

  const tooltip = document.createElement("div");
  tooltip.className = "explanation-tooltip";
  tooltip.textContent = text;

  // Position near the button
  document.body.appendChild(tooltip);
  const rect = anchor.getBoundingClientRect();
  tooltip.style.top = `${rect.bottom + 10 + window.scrollY}px`;
  tooltip.style.left = `${Math.max(10, rect.left - 100)}px`;

  // Auto-remove after 8 seconds or on click
  setTimeout(() => tooltip.remove(), 8000);
  tooltip.addEventListener("click", () => tooltip.remove());
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
  if (modalTitle) modalTitle.textContent = titleWithSource(movie);

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

  if (modalEvidenceEl) {
    modalEvidenceEl.innerHTML = "";
    const evidence = evidenceItems(movie).slice(0, 6);
    evidence.forEach((line) => {
      const li = document.createElement("li");
      li.textContent = line;
      modalEvidenceEl.appendChild(li);
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
          modalDownloadBtn.title = result.message || "Download service error";
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

  if (modalPlexWatchlistBtn) {
    modalPlexWatchlistBtn.disabled = false;
    modalPlexWatchlistBtn.textContent = "+ Plex Watchlist";
    modalPlexWatchlistBtn.onclick = async () => {
      if (modalPlexWatchlistBtn.disabled) return;
      modalPlexWatchlistBtn.disabled = true;
      modalPlexWatchlistBtn.textContent = "Adding...";
      try {
        const res = await fetch("/api/plex/watchlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: movie.title,
            year: movie.year,
            tmdb_id: movie.tmdb_id || null,
            imdb_id: movie.imdb_id || null,
          }),
        });
        const data = await res.json();
        if (data.ok) {
          modalPlexWatchlistBtn.textContent = "✓ Added";
        } else {
          modalPlexWatchlistBtn.textContent = data.message || "Failed";
          setTimeout(() => {
            modalPlexWatchlistBtn.textContent = "+ Plex Watchlist";
            modalPlexWatchlistBtn.disabled = false;
          }, 2000);
        }
      } catch (err) {
        modalPlexWatchlistBtn.textContent = "Error";
        setTimeout(() => {
          modalPlexWatchlistBtn.textContent = "+ Plex Watchlist";
          modalPlexWatchlistBtn.disabled = false;
        }, 2000);
      }
    };
  }

  // Check Usenet availability button
  if (modalCheckUsenetBtn) {
    modalCheckUsenetBtn.disabled = false;
    modalCheckUsenetBtn.textContent = "🔍 Check Usenet";
    modalCheckUsenetBtn.onclick = async () => {
      if (modalCheckUsenetBtn.disabled) return;
      modalCheckUsenetBtn.disabled = true;
      modalCheckUsenetBtn.textContent = "Checking...";
      try {
        const url = `/api/usenet/check?title=${encodeURIComponent(movie.title)}${movie.year ? `&year=${movie.year}` : ''}`;
        const res = await fetch(url);
        const data = await res.json();
        if (data.ok && data.available) {
          modalCheckUsenetBtn.textContent = `✓ Available (${data.result_count})`;
          modalCheckUsenetBtn.classList.add("btn-success");
          // Update the movie's status badge if it exists
          movie.available_on_usenet = true;
        } else if (data.ok) {
          modalCheckUsenetBtn.textContent = "✗ Not on Usenet";
        } else {
          modalCheckUsenetBtn.textContent = data.message || "Check failed";
          setTimeout(() => {
            modalCheckUsenetBtn.textContent = "🔍 Check Usenet";
            modalCheckUsenetBtn.disabled = false;
          }, 2000);
        }
      } catch (err) {
        modalCheckUsenetBtn.textContent = "Error";
        setTimeout(() => {
          modalCheckUsenetBtn.textContent = "🔍 Check Usenet";
          modalCheckUsenetBtn.disabled = false;
        }, 2000);
      }
    };
  }

  // Delete button (for downloaded movies)
  if (modalDeleteBtn) {
    // Check if movie is available in Radarr and show delete button
    const radarrId = movie.radarr_id || null;
    if (radarrId || movie.available_on_radarr) {
      modalDeleteBtn.style.display = "inline-flex";
      modalDeleteBtn.disabled = false;
      modalDeleteBtn.textContent = "🗑 Delete";
      modalDeleteBtn.onclick = async () => {
        if (modalDeleteBtn.disabled) return;
        if (!confirm(`Are you sure you want to delete "${movie.title}" from Radarr?`)) return;
        modalDeleteBtn.disabled = true;
        modalDeleteBtn.textContent = "Deleting...";
        try {
          const res = await fetch(`/api/radarr/movie/${radarrId}?delete_files=true`, { method: "DELETE" });
          const data = await res.json();
          if (data.ok) {
            modalDeleteBtn.textContent = "✓ Deleted";
            closeMovieModal();
            // Refresh recommendations
            debouncedLoadRecommendations();
          } else {
            modalDeleteBtn.textContent = data.message || "Delete failed";
            setTimeout(() => {
              modalDeleteBtn.textContent = "🗑 Delete";
              modalDeleteBtn.disabled = false;
            }, 2000);
          }
        } catch (err) {
          modalDeleteBtn.textContent = "Error";
          setTimeout(() => {
            modalDeleteBtn.textContent = "🗑 Delete";
            modalDeleteBtn.disabled = false;
          }, 2000);
        }
      };
    } else {
      modalDeleteBtn.style.display = "none";
    }
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

function disconnectRecommendationObserver() {
  if (!recommendationObserver) return;
  recommendationObserver.disconnect();
  recommendationObserver = null;
}

function resetRecommendationRenderState() {
  disconnectRecommendationObserver();
  renderedRecommendationCount = 0;
  recommendationScrollActivated = false;
  if (recommendationSentinel) recommendationSentinel.remove();
  recommendationSentinel = null;
}

function clearRecommendationsMessage(html) {
  if (!recsEl) return;
  resetRecommendationRenderState();
  currentRecommendations = [];
  renderAiSuggestions();
  recsEl.innerHTML = html;
}

function ensureRecommendationSentinel() {
  if (!recsEl) return null;
  if (!recommendationSentinel) {
    recommendationSentinel = document.createElement("div");
    recommendationSentinel.className = "recommendation-sentinel";
    recommendationSentinel.setAttribute("aria-hidden", "true");
    recommendationSentinel.style.gridColumn = "1 / -1";
    recommendationSentinel.style.height = "1px";
    recommendationSentinel.style.width = "100%";
  }
  if (!recommendationSentinel.isConnected) recsEl.appendChild(recommendationSentinel);
  return recommendationSentinel;
}

function buildRecommendationCardNode(rec, index) {
  const node = template.content.cloneNode(true);
  const card = node.querySelector(".flip-card");
  if (!card) {
    console.error("Could not find .flip-card in template");
    return null;
  }
  card.dataset.movieIndex = String(index);

  const movie = rec.movie;
  const critic = criticLabel(movie);
  const release = releaseDateChip(movie);
  const genreText = (movie.genres || []).slice(0, 3).join(", ");
  const frontMetaText = [movie.year || "Year unknown", release, genreText || null].filter(Boolean).join(" \u2022 ");
  const backMetaText = [movie.year || "Year unknown", release, genreText || null, critic].filter(Boolean).join(" \u2022 ");
  const scoreText = `${Math.round(rec.score)}`;

  // --- Front ---
  const frontTitle = node.querySelector(".flip-front-title");
  if (frontTitle) frontTitle.textContent = titleWithSource(movie);

  const frontMeta = node.querySelector(".flip-front-meta");
  if (frontMeta) frontMeta.textContent = frontMetaText;
  const originText = frontSourceOriginText(movie);

  const frontOriginEl = node.querySelector(".front-source-origin");
  if (frontOriginEl) {
    if (originText) {
      frontOriginEl.textContent = `From ${originText}`;
      frontOriginEl.style.display = "inline-flex";
    } else {
      frontOriginEl.textContent = "";
      frontOriginEl.style.display = "none";
    }
  }

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

  // --- Download Status Badge ---
  const frontEl = node.querySelector(".flip-card-front");
  if (frontEl) {
    const statusBadge = document.createElement("div");
    statusBadge.className = "download-status";
    const tags = movie.source_tags || [];
    const isUsenet = movie.available_on_usenet || tags.some(t => ["nzbgeek", "drunkenslug", "usenet"].includes(t.toLowerCase()));
    const isUnreleased = tags.some(t => ["unreleased", "upcoming"].includes(t.toLowerCase()));

    if (isUsenet) {
      statusBadge.classList.add("ready");
      statusBadge.innerHTML = '<span class="status-icon">⚡</span><span class="status-text">Ready</span>';
    } else if (isUnreleased) {
      statusBadge.classList.add("unreleased");
      statusBadge.innerHTML = '<span class="status-icon">🎬</span><span class="status-text">Soon</span>';
    } else {
      statusBadge.classList.add("unavailable");
      statusBadge.innerHTML = '<span class="status-icon">⏳</span><span class="status-text">Not Ready</span>';
    }
    frontEl.appendChild(statusBadge);
  }

  // --- Back ---
  const backTitles = node.querySelectorAll(".flip-card-back .title");
  backTitles.forEach((el) => {
    el.textContent = titleWithSource(movie);
    el.addEventListener("click", (e) => { e.stopPropagation(); openMovieModal(rec); });
  });

  const backScore = node.querySelector(".back-score");
  if (backScore) backScore.textContent = scoreText;

  const backMeta = node.querySelector(".back-meta");
  if (backMeta) backMeta.textContent = backMetaText;
  const backOriginEl = node.querySelector(".back-source-origin");
  const backSourceText = sourceAttributionText(movie);
  if (backOriginEl) {
    if (backSourceText) {
      backOriginEl.textContent = `From ${backSourceText}`;
      backOriginEl.style.display = "inline-flex";
    } else {
      backOriginEl.textContent = "";
      backOriginEl.style.display = "none";
    }
  }

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

  const reasonsEl = node.querySelector(".reasons");
  if (reasonsEl) {
    reasonsEl.innerHTML = "";
    const evidence = evidenceItems(movie).slice(0, 3);
    evidence.forEach((line) => {
      const li = document.createElement("li");
      li.textContent = line;
      reasonsEl.appendChild(li);
    });
    reasonsEl.style.display = evidence.length ? "grid" : "none";
  }

  // --- Availability Check Timestamp ---
  const backEl = node.querySelector(".flip-card-back");
  if (backEl) {
    const tags = movie.source_tags || [];
    const isUsenet = movie.available_on_usenet || tags.some(t => ["nzbgeek", "drunkenslug", "usenet"].includes(t.toLowerCase()));
    const isUnreleased = tags.some(t => ["unreleased", "upcoming"].includes(t.toLowerCase()));

    const checkTimestamp = document.createElement("div");
    checkTimestamp.className = "availability-check";

    let statusText = "Not Ready";
    let statusClass = "unavailable";
    if (isUsenet) {
      statusText = "Ready";
      statusClass = "ready";
    } else if (isUnreleased) {
      statusText = "Unreleased";
      statusClass = "unreleased";
    }

    checkTimestamp.innerHTML = `
      <span class="check-status ${statusClass}">${statusText}</span>
      <span class="check-time">Checked just now</span>
    `;
    backEl.appendChild(checkTimestamp);
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
          dlBtn.title = result.message || "Download service error";
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

  return node;
}

function appendRecommendationBatch() {
  if (!recsEl || renderedRecommendationCount >= currentRecommendations.length) return 0;
  const nextCount = Math.min(
    renderedRecommendationCount + RECOMMENDATION_BATCH_SIZE,
    currentRecommendations.length
  );
  const fragment = document.createDocumentFragment();
  let appended = 0;
  for (let i = renderedRecommendationCount; i < nextCount; i += 1) {
    const built = buildRecommendationCardNode(currentRecommendations[i], i);
    if (!built) continue;
    fragment.appendChild(built);
    appended += 1;
  }
  if (appended > 0) {
    if (recommendationSentinel && recommendationSentinel.isConnected) {
      recsEl.insertBefore(fragment, recommendationSentinel);
    } else {
      recsEl.appendChild(fragment);
    }
  }
  renderedRecommendationCount = nextCount;
  if (renderedRecommendationCount >= currentRecommendations.length) {
    disconnectRecommendationObserver();
    if (recommendationSentinel) recommendationSentinel.remove();
    recommendationSentinel = null;
  }
  return appended;
}

function recommendationSentinelNearViewport(offsetPx = 240) {
  if (!recommendationSentinel) return false;
  const rect = recommendationSentinel.getBoundingClientRect();
  return rect.top <= window.innerHeight + offsetPx;
}

function maybeAppendRecommendationBatch() {
  if (!recommendationScrollActivated) return;
  if (!recommendationSentinel || renderedRecommendationCount >= currentRecommendations.length) return;
  if (!recommendationSentinelNearViewport()) return;
  appendRecommendationBatch();
}

function setupRecommendationObserver() {
  if (!recommendationSentinel || renderedRecommendationCount >= currentRecommendations.length) return;
  if (typeof IntersectionObserver !== "function") {
    while (renderedRecommendationCount < currentRecommendations.length) {
      const appended = appendRecommendationBatch();
      if (!appended) break;
    }
    return;
  }

  disconnectRecommendationObserver();
  recommendationObserver = new IntersectionObserver((entries) => {
    if (!entries.some((entry) => entry.isIntersecting)) return;
    if (!recommendationScrollActivated) return;
    appendRecommendationBatch();
  }, {
    root: null,
    rootMargin: RECOMMENDATION_OBSERVER_ROOT_MARGIN,
    threshold: 0.01,
  });
  recommendationObserver.observe(recommendationSentinel);
}

function renderRecommendations(recommendations) {
  if (!recsEl || !template) return;
  resetRecommendationRenderState();
  recsEl.innerHTML = "";
  currentRecommendations = Array.isArray(recommendations) ? recommendations : [];
  renderAiSuggestions();
  if (!currentRecommendations.length) return;
  ensureRecommendationSentinel();
  appendRecommendationBatch();
  setupRecommendationObserver();
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
  const sortVal = sortSelect?.value || "year-desc";
  const sorted = [...recommendations];
  switch (sortVal) {
    case "score-desc":
      sorted.sort((a, b) => (b.score || 0) - (a.score || 0));
      break;
    case "score-asc":
      sorted.sort((a, b) => (a.score || 0) - (b.score || 0));
      break;
    case "year-desc":
      sorted.sort((a, b) => movieReleaseSortValue(b.movie) - movieReleaseSortValue(a.movie));
      break;
    case "year-asc":
      sorted.sort((a, b) => movieReleaseSortValue(a.movie) - movieReleaseSortValue(b.movie));
      break;
    case "release-upcoming":
      return sorted
        .filter((rec) => isUpcomingRelease(rec.movie))
        .sort((a, b) => movieReleaseSortValue(a.movie) - movieReleaseSortValue(b.movie));
    case "release-current":
      return sorted
        .filter((rec) => isCurrentRelease(rec.movie))
        .sort((a, b) => movieReleaseSortValue(b.movie) - movieReleaseSortValue(a.movie));
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

function getMovieAvailabilityStatus(movie) {
  const tags = movie.source_tags || [];
  const tagsLower = tags.map(t => t.toLowerCase());

  // Check if movie is unreleased first
  const isUnreleased = tagsLower.includes("unreleased");
  // "upcoming" alone doesn't mean unreleased - many "upcoming" movies are now released
  // Only treat as unreleased if explicitly marked or if it has a future release date
  const releaseDate = movie.release_date ? new Date(movie.release_date) : null;
  const isFutureRelease = releaseDate && releaseDate > new Date();

  if (isUnreleased || isFutureRelease) return "unreleased";

  // Check if movie is ready/available
  const isUsenet = movie.available_on_usenet ||
    tagsLower.some(t => ["nzbgeek", "nzbgeek-rss", "drunkenslug", "usenet", "2160p", "1080p", "720p"].includes(t));
  const isPlex = movie.available_on_plex || tagsLower.includes("plex");
  const isRadarr = movie.available_on_radarr;
  const isNowPlaying = tagsLower.includes("now-playing");

  if (isUsenet || isPlex || isRadarr || isNowPlaying) return "ready";

  return "unavailable";
}

function applyClientFilters(recommendations) {
  const filters = getClientFilters();
  return recommendations.filter((rec) => {
    const movie = rec.movie;

    // Availability filter
    if (availabilityFilter !== "all") {
      const status = getMovieAvailabilityStatus(movie);
      if (status !== availabilityFilter) return false;
    }

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
  const hiddenCountInput = countInput?.type === "hidden";
  // Use max limit when client-side filters (like availability) are active
  const hasClientFilters = availabilityFilter !== "all";
  const displayLimit = (hiddenCountInput || hasClientFilters) ? MAX_RECOMMENDATION_COUNT : count;

  const recUrl = new URL("/api/recommendations", window.location.origin);
  recUrl.searchParams.set("user_id", user);
  const minScore = Number(minScoreEl?.value) || 0;
  const sortVal = sortSelect?.value || "year-desc";
  recUrl.searchParams.set("sort", sortVal);
  const isDateSort = sortVal === "year-desc" || sortVal === "year-asc" || sortVal === "release-upcoming" || sortVal === "release-current";
  const fetchMultiplier = minScore > 0 ? 5 : 2;
  // Fetch max when client-side filters are active to ensure proper lazy loading
  const fetchCount = (hiddenCountInput || hasClientFilters)
    ? MAX_RECOMMENDATION_COUNT
    : (isDateSort
      ? MAX_RECOMMENDATION_COUNT
      : Math.min(count * fetchMultiplier, MAX_RECOMMENDATION_COUNT));
  recUrl.searchParams.set("count", String(fetchCount));

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
    filtered = filtered.slice(0, displayLimit);

    // Pick random movie from top 5 for hero section (Movie of the Day)
    const heroPoolSize = Math.min(5, filtered.length);
    const heroIndex = heroPoolSize > 0 ? Math.floor(Math.random() * heroPoolSize) : 0;
    const heroRec = filtered[heroIndex] || null;

    // Remove hero from grid to avoid duplication
    const gridRecs = heroRec ? filtered.filter((_, i) => i !== heroIndex) : filtered;

    renderHeroMovie(heroRec);
    renderRecommendations(gridRecs);
  } catch (err) {
    console.error("Failed to load recommendations:", err);
  }
}

function debouncedLoadRecommendations() {
  if (filterDebounceTimer) clearTimeout(filterDebounceTimer);
  filterDebounceTimer = setTimeout(() => {
    if (currentMood) {
      loadMoodRecommendations();
    } else {
      loadRecommendations();
    }
  }, 200);
}

function clearAllFilters() {
  // Reset all filters
  if (minScoreEl) {
    minScoreEl.value = "0";
    const scoreDisplay = document.getElementById("score-display");
    if (scoreDisplay) scoreDisplay.textContent = "Any";
  }
  if (yearFromEl) yearFromEl.value = "";
  if (yearToEl) yearToEl.value = "";
  if (genreFilterEl) genreFilterEl.value = "";
  if (releaseFromEl) releaseFromEl.value = "";
  if (releaseToEl) releaseToEl.value = "";

  // Reset era/decade buttons
  document.querySelectorAll(".decade-btn, .era-btn, .era-pill").forEach((b) => b.classList.remove("active"));

  // Reset mood
  currentMood = null;
  renderMoodChips();

  // Reset source selections to all
  homeSourceSelections.clear();
  SOURCE_OPTIONS.forEach((opt) => homeSourceSelections.add(opt.key));
  renderHomeSourceFilters();

  loadRecommendations();
}

// ===== Movie Search =====
let searchTimer = null;

function movieKey(title, year) {
  return `${String(title || "").trim().toLowerCase()}::${year || "na"}`;
}

function recommendationFromSearchResult(row) {
  const movie = {
    movie_id: row.tmdb_id ? `tmdb:${row.tmdb_id}` : `tmdb-search:${Date.now()}`,
    title: row.title || "Unknown title",
    year: row.year || null,
    release_date: row.release_date || null,
    poster_url: row.poster_url || null,
    backdrop_url: row.backdrop_url || null,
    rottentomatoes_score: null,
    rogerebert_score: null,
    genres: [],
    overview: row.overview || "",
    source_tags: ["tmdb"],
    evidence: ["TMDB search result"],
    available_on_plex: false,
    available_on_radarr: false,
    available_on_usenet: false,
  };
  return {
    movie,
    score: Number.isFinite(row.vote_average) ? Math.max(0, Math.min(row.vote_average * 10, 100)) : 50,
    reasons: [
      {
        label: "TMDB",
        value: 1.0,
        detail: "Selected from TMDB search",
      },
    ],
  };
}

function addSearchResultAsCard(row) {
  const candidate = recommendationFromSearchResult(row);
  const nextKey = movieKey(candidate.movie.title, candidate.movie.year);
  const existing = (currentRecommendations || []).filter(
    (rec) => movieKey(rec?.movie?.title, rec?.movie?.year) !== nextKey
  );
  renderRecommendations([candidate, ...existing]);
}

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
      item.addEventListener("click", () => {
        addSearchResultAsCard(m);
        closeSearch();
      });

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
      addBtn.title = "Add to recommendations and download queue";
      addBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (addBtn.disabled) return;
        addBtn.disabled = true;
        addBtn.textContent = "...";
        try {
          // Add to download queue
          const result = await sendDownload({ title: m.title, year: m.year });
          if (result?.status === "queued") {
            addBtn.textContent = "✓ Added";
          } else if (result?.status === "exists") {
            addBtn.textContent = "✓ Exists";
          } else {
            addBtn.textContent = "✓ Added";
          }

          // Add to main recommendations grid
          addSearchResultAsCard(m);

          // Refresh download activity
          loadDownloadActivity(true);
          loadRadarrMonitored();

          // Remove this item from search results after a short delay
          setTimeout(() => {
            item.style.opacity = "0";
            item.style.transform = "translateX(20px)";
            setTimeout(() => item.remove(), 200);
          }, 500);
        } catch {
          addBtn.textContent = "Failed";
        }
      });
      actions.appendChild(addBtn);

      const skipBtn = document.createElement("button");
      skipBtn.className = "search-dl-btn search-skip-btn";
      skipBtn.textContent = "Skip";
      skipBtn.title = "Remove from search results";
      skipBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        // Animate and remove
        item.style.transition = "all 0.2s ease";
        item.style.opacity = "0";
        item.style.transform = "translateX(-20px)";
        setTimeout(() => item.remove(), 200);
      });
      actions.appendChild(skipBtn);

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

window.addEventListener("scroll", () => {
  if (!recommendationSentinel || renderedRecommendationCount >= currentRecommendations.length) return;
  if (!recommendationScrollActivated && window.scrollY > 0) {
    recommendationScrollActivated = true;
  }
  maybeAppendRecommendationBatch();
}, { passive: true });

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

// Score slider display update
const scoreDisplayEl = document.getElementById("score-display");
function updateScoreDisplay() {
  if (!minScoreEl || !scoreDisplayEl) return;
  const val = Number(minScoreEl.value) || 0;
  scoreDisplayEl.textContent = val === 0 ? "Any" : `${val}+`;
}
if (minScoreEl) {
  minScoreEl.addEventListener("input", updateScoreDisplay);
  updateScoreDisplay();
}
yearFromEl?.addEventListener("input", debouncedLoadRecommendations);
yearFromEl?.addEventListener("change", debouncedLoadRecommendations);
yearToEl?.addEventListener("input", debouncedLoadRecommendations);
yearToEl?.addEventListener("change", debouncedLoadRecommendations);
genreFilterEl?.addEventListener("input", debouncedLoadRecommendations);
genreFilterEl?.addEventListener("change", debouncedLoadRecommendations);

sortSelect?.addEventListener("change", debouncedLoadRecommendations);
clearAllFiltersBtn?.addEventListener("click", clearAllFilters);

// Availability filter toggles
document.querySelectorAll(".availability-toggle").forEach((btn) => {
  btn.addEventListener("click", () => {
    const filter = btn.dataset.filter;
    availabilityFilter = filter;
    // Update active state
    document.querySelectorAll(".availability-toggle").forEach((b) => {
      b.classList.toggle("active", b.dataset.filter === filter);
    });
    debouncedLoadRecommendations();
  });
});

// Era/Decade quick-filter buttons
document.querySelectorAll(".decade-btn, .era-btn, .era-pill").forEach((btn) => {
  btn.addEventListener("click", () => {
    const from = btn.dataset.from;
    const to = btn.dataset.to;
    const isActive = btn.classList.contains("active");

    // Toggle - if already active, clear it
    if (isActive) {
      btn.classList.remove("active");
      if (yearFromEl) yearFromEl.value = "";
      if (yearToEl) yearToEl.value = "";
    } else {
      // Update the year inputs
      if (yearFromEl) yearFromEl.value = from;
      if (yearToEl) yearToEl.value = to;

      // Toggle active state
      document.querySelectorAll(".decade-btn, .era-btn, .era-pill").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
    }

    // Reload recommendations
    debouncedLoadRecommendations();
  });
});

// ===== Mood-Based Discovery =====
const moodChipsEl = document.getElementById("mood-chips");
let currentMood = null;
let availableMoods = [];

let suggestedMoods = [];

async function loadMoods() {
  if (!moodChipsEl) return;
  try {
    const res = await fetch("/api/moods");
    const data = await res.json();
    if (data.ok && data.moods) {
      availableMoods = data.moods;
      renderMoodChips();
    }
  } catch (err) {
    console.error("Failed to load moods:", err);
  }
}

async function loadSuggestedMoods() {
  try {
    const res = await fetch(`/api/moods/infer/${currentUserId()}`);
    const data = await res.json();
    if (data.ok && data.suggested_moods && data.suggested_moods.length > 0) {
      suggestedMoods = data.suggested_moods;
      renderMoodChips(); // Re-render with suggestions
    }
  } catch (err) {
    console.error("Failed to load suggested moods:", err);
  }
}

function renderMoodChips() {
  if (!moodChipsEl) return;
  moodChipsEl.innerHTML = "";

  // Create mood card helper
  const createMoodCard = (emoji, label, isActive, onClick, isSuggested = false) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `mood-card ${isActive ? "active" : ""} ${isSuggested ? "suggested" : ""}`;
    card.innerHTML = `
      <span class="mood-emoji">${emoji}</span>
      <span class="mood-label">${label}</span>
      ${isSuggested ? '<span class="mood-suggested-badge">For You</span>' : ""}
    `;
    card.addEventListener("click", onClick);
    return card;
  };

  // "All" card
  moodChipsEl.appendChild(
    createMoodCard("🎬", "All", !currentMood, () => {
      currentMood = null;
      renderMoodChips();
      debouncedLoadRecommendations();
    })
  );

  // Get suggested mood names
  const suggestedNames = new Set(suggestedMoods.map(m => m.name));

  // Show suggested moods first (if any)
  if (suggestedMoods.length > 0) {
    suggestedMoods.forEach((suggested) => {
      const mood = availableMoods.find(m => m.name === suggested.name);
      if (mood) {
        moodChipsEl.appendChild(
          createMoodCard(mood.emoji, mood.display_name, currentMood === mood.name, () => {
            currentMood = currentMood === mood.name ? null : mood.name;
            renderMoodChips();
            loadMoodRecommendations();
          }, true)
        );
      }
    });
  }

  // Mood cards - show all in horizontal scroll (excluding already shown suggested)
  availableMoods.forEach((mood) => {
    if (suggestedNames.has(mood.name)) return; // Skip if already shown as suggested
    moodChipsEl.appendChild(
      createMoodCard(mood.emoji, mood.display_name, currentMood === mood.name, () => {
        currentMood = currentMood === mood.name ? null : mood.name;
        renderMoodChips();
        loadMoodRecommendations();
      })
    );
  });
}

async function loadMoodRecommendations() {
  if (!currentMood) {
    loadRecommendations();
    return;
  }

  if (recsEl) {
    clearRecommendationsMessage('<div class="meta" style="text-align: center; padding: 40px;">Loading mood recommendations...</div>');
  }

  try {
    const rawCount = Number.parseInt(countInput?.value || "24", 10);
    const count = Math.max(1, Math.min(Number.isFinite(rawCount) ? rawCount : 24, MAX_RECOMMENDATION_COUNT));
    // Use max limit when client-side filters are active
    const hasClientFilters = availabilityFilter !== "all";
    const displayLimit = (countInput?.type === "hidden" || hasClientFilters) ? MAX_RECOMMENDATION_COUNT : count;
    const moodUrl = new URL(`/api/recommendations/mood/${currentMood}`, window.location.origin);
    moodUrl.searchParams.set("user_id", currentUserId());
    moodUrl.searchParams.set("count", String(MAX_RECOMMENDATION_COUNT));
    const yearFrom = Number(yearFromEl?.value) || 0;
    const yearTo = Number(yearToEl?.value) || 0;
    if (yearFrom > 0) moodUrl.searchParams.set("year_from", String(yearFrom));
    if (yearTo > 0) moodUrl.searchParams.set("year_to", String(yearTo));
    const res = await fetch(moodUrl.toString());
    const data = await res.json();

    if (data.ok && data.recommendations) {
      // Transform recommendations to match expected format
      const transformed = data.recommendations.map((r) => ({
        ...r,
        score: r.mood_score || r.score || 0,
      }));
      let filtered = applyClientFilters(transformed);
      filtered = sortRecommendations(filtered);
      filtered = filtered.slice(0, displayLimit);

      if (filtered.length === 0) {
        clearRecommendationsMessage(`<div class="meta" style="text-align: center; padding: 40px;">No ${currentMood} movies for this decade filter.</div>`);
        renderHeroMovie(null);
        return;
      }

      const heroIndex = Math.floor(Math.random() * Math.min(5, filtered.length));
      const heroRec = filtered[heroIndex] || null;
      const gridRecs = heroRec ? filtered.filter((_, i) => i !== heroIndex) : filtered;

      renderHeroMovie(heroRec);
      renderRecommendations(gridRecs);
    } else {
      clearRecommendationsMessage(`<div class="meta" style="text-align: center; padding: 40px;">No movies found for "${currentMood}" mood</div>`);
      renderHeroMovie(null);
    }
  } catch (err) {
    console.error("Failed to load mood recommendations:", err);
    clearRecommendationsMessage('<div class="meta" style="text-align: center; padding: 40px;">Error loading recommendations</div>');
    renderHeroMovie(null);
  }
}

// Initialize moods on load
loadMoods();

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

// ===== AI Chat =====
const aiChatCard = document.getElementById("ai-chat-card");
const aiChatToggle = document.getElementById("ai-chat-toggle");
const aiChatInput = document.getElementById("ai-chat-input");
const aiChatSend = document.getElementById("ai-chat-send");
const aiChatMessages = document.getElementById("ai-chat-messages");
const aiStatus = document.getElementById("ai-status");
const aiSuggestionChipsEl = document.getElementById("ai-suggestion-chips");
const aiFeaturedMovieEl = document.getElementById("ai-featured-movie");

const DEFAULT_AI_SUGGESTIONS = [
  {
    label: "Tonight Pick",
    prompt: "Pick one movie from my recommendations for tonight. Format exactly: Pick: <title> (<year>) - <one short reason>.",
  },
  {
    label: "Backup Pick",
    prompt: "Give one backup movie from my recommendations. Format exactly: Backup: <title> (<year>) - <one short reason>.",
  },
  {
    label: "Different Vibe",
    prompt: "Give one alternative with a different vibe from my top pick. Format exactly: Alt: <title> (<year>) - <one short reason>.",
  },
];

function recMovie(rec) {
  if (!rec || typeof rec !== "object") return null;
  if (rec.movie && typeof rec.movie === "object") return rec.movie;
  return rec;
}

function formatRecLabel(rec) {
  const movie = recMovie(rec);
  if (!movie?.title) return null;
  return movie.year ? `${movie.title} (${movie.year})` : movie.title;
}

function stripMovieYear(label) {
  return String(label || "").replace(/\s*\(\d{4}\)\s*$/, "").trim();
}

function clipChipLabel(text, limit = 18) {
  const raw = String(text || "").trim();
  if (raw.length <= limit) return raw;
  return `${raw.slice(0, limit - 1).trimEnd()}…`;
}

function normalizeAiResponse(raw) {
  const text = String(raw || "").replace(/\s+/g, " ").trim();
  if (!text) return "No response";
  if (text.length <= 220) return text;
  return `${text.slice(0, 217).trimEnd()}...`;
}

function findRecommendationFromText(raw) {
  const responseText = String(raw || "").toLowerCase();
  if (!responseText || !Array.isArray(currentRecommendations) || !currentRecommendations.length) return null;
  const candidates = currentRecommendations
    .map((rec) => ({ rec, title: String(recMovie(rec)?.title || "").trim() }))
    .filter((item) => item.title.length > 1)
    .sort((a, b) => b.title.length - a.title.length);

  for (const item of candidates) {
    if (responseText.includes(item.title.toLowerCase())) return item.rec;
  }
  return null;
}

function buildAiContext() {
  const parts = [];
  if (currentMood) parts.push(`mood:${currentMood}`);
  if (yearFromEl?.value) parts.push(`year_from:${yearFromEl.value}`);
  if (yearToEl?.value) parts.push(`year_to:${yearToEl.value}`);

  const topTitles = (currentRecommendations || [])
    .slice(0, 3)
    .map((rec) => formatRecLabel(rec))
    .filter(Boolean);

  if (topTitles.length) {
    parts.push(`top:${topTitles.join(" | ")}`);
  }
  parts.push("reply_style: short; choose one movie title from current recommendations when possible");
  return parts.join("; ");
}

function buildAiSuggestions() {
  const dynamic = [];
  const topMovie = formatRecLabel(currentRecommendations?.[0]);
  const secondMovie = formatRecLabel(currentRecommendations?.[1]);
  const thirdMovie = formatRecLabel(currentRecommendations?.[2]);

  const topTitle = clipChipLabel(stripMovieYear(topMovie), 11);
  const secondTitle = clipChipLabel(stripMovieYear(secondMovie), 11);
  const thirdTitle = clipChipLabel(stripMovieYear(thirdMovie), 11);

  if (topMovie && topTitle) {
    dynamic.push({
      label: `Pick ${topTitle}`,
      prompt: `Should I watch ${topMovie} tonight? Format exactly: Pick: ${topMovie} - <one short reason>.`,
      movieIndex: 0,
    });
  }
  if (topMovie && secondMovie && topTitle && secondTitle) {
    dynamic.push({
      label: `Backup ${secondTitle}`,
      prompt: `If ${topMovie} is unavailable, pick a backup from my current recommendations, preferably ${secondMovie}. Format exactly: Backup: <title> (<year>) - <one short reason>.`,
      movieIndex: 1,
    });
  }
  if (thirdMovie && thirdTitle) {
    dynamic.push({
      label: `Alt ${thirdTitle}`,
      prompt: `Give one alternative with a different vibe, leaning toward ${thirdMovie}. Format exactly: Alt: <title> (<year>) - <one short reason>.`,
      movieIndex: 2,
    });
  }

  const merged = dynamic.length ? dynamic : DEFAULT_AI_SUGGESTIONS;
  return merged
    .filter((item) => item?.label && item?.prompt)
    .slice(0, 3);
}

function renderAiSuggestions() {
  if (!aiSuggestionChipsEl) return;
  aiSuggestionChipsEl.innerHTML = "";

  if (aiFeaturedMovieEl) {
    const topMovie = recMovie(currentRecommendations?.[0]);
    if (topMovie?.title) {
      renderAiFeaturedMovie(currentRecommendations[0], "Recommended now");
    } else {
      aiFeaturedMovieEl.hidden = true;
      aiFeaturedMovieEl.innerHTML = "";
    }
  }

  const suggestions = buildAiSuggestions();
  suggestions.forEach((suggestion) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ai-suggestion-chip";
    button.textContent = suggestion.label;
    button.title = suggestion.prompt;
    button.addEventListener("click", () => {
      if (Number.isInteger(suggestion.movieIndex)) {
        renderAiFeaturedMovie(currentRecommendations?.[suggestion.movieIndex], "Selected pick");
      }
      sendAiMessage(suggestion.prompt);
    });
    aiSuggestionChipsEl.appendChild(button);
  });
}

function renderAiFeaturedMovie(rec, reason = "Recommended now") {
  if (!aiFeaturedMovieEl) return;
  const movie = recMovie(rec);
  if (!movie?.title) {
    aiFeaturedMovieEl.hidden = true;
    aiFeaturedMovieEl.innerHTML = "";
    return;
  }

  aiFeaturedMovieEl.hidden = false;
  aiFeaturedMovieEl.innerHTML = "";

  const poster = document.createElement("img");
  poster.className = "ai-featured-poster";
  poster.alt = `${movie.title} poster`;
  poster.src = (movie.poster_url || "").trim() || generatedPosterDataUrl(movie);
  poster.addEventListener("error", () => {
    poster.src = generatedPosterDataUrl(movie);
  });

  const details = document.createElement("div");
  details.className = "ai-featured-details";

  const title = document.createElement("div");
  title.className = "ai-featured-title";
  title.textContent = titleWithSource(movie);

  const meta = document.createElement("div");
  meta.className = "ai-featured-meta";
  const score = Number.isFinite(rec?.score) ? `Score ${Math.round(rec.score)}` : null;
  const origin = sourceOriginText(movie);
  meta.textContent = [movie.year || null, criticLabel(movie), score, origin ? `From ${origin}` : null]
    .filter(Boolean)
    .join(" • ");

  const reasonText = document.createElement("div");
  reasonText.className = "ai-featured-reason";
  reasonText.textContent = reason;

  const actions = document.createElement("div");
  actions.className = "ai-featured-actions";

  const detailsBtn = document.createElement("button");
  detailsBtn.type = "button";
  detailsBtn.className = "btn btn-ghost btn-sm";
  detailsBtn.textContent = "Details";
  detailsBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    openMovieModal(rec);
  });

  const downloadBtn = document.createElement("button");
  downloadBtn.type = "button";
  downloadBtn.className = "btn btn-primary btn-sm";
  downloadBtn.textContent = "Download";
  downloadBtn.addEventListener("click", async (event) => {
    event.stopPropagation();
    if (downloadBtn.disabled) return;
    downloadBtn.disabled = true;
    downloadBtn.textContent = "...";
    try {
      const result = await sendDownload(movie);
      if (result?.status === "queued") {
        downloadBtn.textContent = "Queued";
      } else if (result?.status === "exists") {
        downloadBtn.textContent = "Tracked";
      } else {
        downloadBtn.textContent = "Done";
      }
      await loadDownloadActivity();
    } catch {
      downloadBtn.textContent = "Error";
    }
  });

  actions.appendChild(detailsBtn);
  actions.appendChild(downloadBtn);

  details.appendChild(title);
  details.appendChild(meta);
  details.appendChild(reasonText);
  aiFeaturedMovieEl.appendChild(poster);
  aiFeaturedMovieEl.appendChild(details);
  aiFeaturedMovieEl.appendChild(actions);
  aiFeaturedMovieEl.title = "Open movie details";
  aiFeaturedMovieEl.style.cursor = "pointer";
  aiFeaturedMovieEl.onclick = () => openMovieModal(rec);
}

// Initialize collapsed state from localStorage
const aiChatCollapsed = localStorage.getItem("ai-chat-collapsed") === "true";
if (aiChatCollapsed && aiChatCard) {
  aiChatCard.classList.add("collapsed");
}

function toggleAiChat() {
  if (!aiChatCard) return;
  aiChatCard.classList.toggle("collapsed");
  aiChatCard.classList.toggle("expanded", !aiChatCard.classList.contains("collapsed"));
  localStorage.setItem("ai-chat-collapsed", aiChatCard.classList.contains("collapsed"));
}

aiChatToggle?.addEventListener("click", (e) => {
  // Don't toggle if clicking on input or buttons inside
  if (e.target.closest(".ai-chat-input-wrapper")) return;
  toggleAiChat();
});

function addChatMessage(content, role, sources = []) {
  const msg = document.createElement("div");
  msg.className = `ai-chat-message ${role}`;
  msg.textContent = content;

  if (sources.length > 0) {
    const sourcesEl = document.createElement("div");
    sourcesEl.className = "ai-chat-sources";
    sourcesEl.textContent = `Queried: ${sources.join(", ")}`;
    msg.appendChild(sourcesEl);
  }

  aiChatMessages?.appendChild(msg);
  aiChatMessages?.scrollTo({ top: aiChatMessages.scrollHeight, behavior: "smooth" });
  return msg;
}

async function sendAiMessage(presetMessage = null) {
  const isQuickPick = typeof presetMessage === "string" && presetMessage.trim().length > 0;
  const message = String(presetMessage ?? aiChatInput?.value ?? "").trim();
  if (!message) return;

  // Expand chat when sending
  aiChatCard?.classList.remove("collapsed");
  aiChatCard?.classList.add("expanded");

  if (aiChatInput) aiChatInput.value = "";
  if (!isQuickPick) {
    addChatMessage(message, "user");
  }

  const loadingMsg = addChatMessage("Picking...", "loading");

  try {
    const res = await fetch("/api/ai/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, context: buildAiContext() }),
    });
    const data = await res.json();

    loadingMsg.remove();
    const responseText = normalizeAiResponse(data.response || "No response");
    addChatMessage(responseText, "assistant", data.sources_queried || []);
    const mentionedRec = findRecommendationFromText(data.response);
    if (mentionedRec) {
      renderAiFeaturedMovie(mentionedRec, "AI pick");
    }
  } catch (err) {
    loadingMsg.remove();
    addChatMessage(`Error: ${err.message}`, "assistant");
  }
}

aiChatSend?.addEventListener("click", sendAiMessage);
aiChatInput?.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendAiMessage();
  }
});

// Focus input expands the chat
aiChatInput?.addEventListener("focus", () => {
  aiChatCard?.classList.remove("collapsed");
  aiChatCard?.classList.add("expanded");
});

async function checkAiStatus() {
  if (!aiStatus) return;
  try {
    const res = await fetch("/api/integrations");
    const data = await res.json();
    if (data.ollama) {
      aiStatus.textContent = "Ready";
      aiStatus.className = "ai-status-badge connected";
    } else {
      aiStatus.textContent = "Setup";
      aiStatus.className = "ai-status-badge disconnected";
    }
  } catch {
    aiStatus.textContent = "Offline";
    aiStatus.className = "ai-status-badge disconnected";
  }
}

// === Year Picker Logic ===
const yearSlider = document.getElementById("year-slider");
const yearDisplay = document.getElementById("year-display");
const clearYearBtn = document.getElementById("clear-year-btn");
const decadeChips = document.querySelectorAll(".decade-chip");
const resultsCountEl = document.getElementById("results-count");
const loadAllBtn = document.getElementById("load-all-btn");

let selectedYear = null;
let selectedDecade = null;

function updateYearDisplay(year, isDecade = false) {
  if (!yearDisplay) return;
  if (year === null) {
    yearDisplay.textContent = "Any Year";
    yearDisplay.style.color = "var(--text-muted)";
  } else if (isDecade) {
    yearDisplay.textContent = `${year}s`;
    yearDisplay.style.color = "var(--primary)";
  } else {
    yearDisplay.textContent = year;
    yearDisplay.style.color = "var(--primary)";
  }
}

function updateResultsCount(shown, total, yearLabel = null) {
  if (!resultsCountEl) return;
  if (total === 0) {
    resultsCountEl.innerHTML = "";
    return;
  }
  const label = yearLabel ? ` from <strong>${yearLabel}</strong>` : "";
  if (shown < total) {
    resultsCountEl.innerHTML = `Showing <strong>${shown}</strong> of <strong>${total}</strong> movies${label}`;
    if (loadAllBtn) loadAllBtn.style.display = "inline-block";
  } else {
    resultsCountEl.innerHTML = `<strong>${total}</strong> movies${label}`;
    if (loadAllBtn) loadAllBtn.style.display = "none";
  }
}

function clearDecadeChipActive() {
  decadeChips.forEach((chip) => chip.classList.remove("active"));
}

function applyYearFilter(yearFrom, yearTo) {
  // Set hidden inputs for the recommendation API
  if (yearFromEl) yearFromEl.value = yearFrom || "";
  if (yearToEl) yearToEl.value = yearTo || "";
  // Trigger recommendations reload
  loadRecommendations();
}

function handleYearSliderRelease() {
  const year = parseInt(yearSlider.value, 10);
  selectedYear = year;
  selectedDecade = null;
  clearDecadeChipActive();
  updateYearDisplay(year);
  // Filter to just this year
  applyYearFilter(year, year);
}

function handleDecadeClick(decade) {
  selectedDecade = decade;
  selectedYear = null;
  clearDecadeChipActive();

  if (decade === "classic") {
    // Classic = pre-1970
    updateYearDisplay("Classic");
    applyYearFilter(1900, 1969);
  } else {
    const decadeStart = parseInt(decade, 10);
    const decadeEnd = decadeStart + 9;
    if (yearSlider) yearSlider.value = decadeStart;
    updateYearDisplay(decadeStart, true);
    applyYearFilter(decadeStart, decadeEnd);
  }

  decadeChips.forEach((chip) => {
    if (chip.dataset.decade === decade) {
      chip.classList.add("active");
    }
  });
}

function clearYearFilter() {
  selectedYear = null;
  selectedDecade = null;
  clearDecadeChipActive();
  updateYearDisplay(null);
  if (yearSlider) yearSlider.value = 2026;
  applyYearFilter(null, null);
}

// Event listeners for year picker
if (yearSlider) {
  // Update display as user drags
  yearSlider.addEventListener("input", () => {
    updateYearDisplay(parseInt(yearSlider.value, 10));
  });
  // Fetch when user releases slider
  yearSlider.addEventListener("change", handleYearSliderRelease);
}

if (clearYearBtn) {
  clearYearBtn.addEventListener("click", clearYearFilter);
}

decadeChips.forEach((chip) => {
  chip.addEventListener("click", () => {
    handleDecadeClick(chip.dataset.decade);
  });
});

if (loadAllBtn) {
  loadAllBtn.addEventListener("click", () => {
    // Render all remaining cards
    while (renderedRecommendationCount < currentRecommendations.length) {
      appendRecommendationBatch();
    }
    const yearLabel = selectedYear || (selectedDecade ? `${selectedDecade}s` : null);
    updateResultsCount(renderedRecommendationCount, currentRecommendations.length, yearLabel);
  });
}

// Update results count after recommendations render
const originalRenderRecommendations = renderRecommendations;
renderRecommendations = function(recommendations) {
  originalRenderRecommendations(recommendations);
  const yearLabel = selectedYear || (selectedDecade ? `${selectedDecade}s` : null);
  setTimeout(() => {
    updateResultsCount(renderedRecommendationCount, currentRecommendations.length, yearLabel);
  }, 100);
};

// ============================================================================
// Just Added Section (Today's Releases)
// ============================================================================

function parseTimestamp(raw) {
  if (!raw) return null;
  const value = String(raw).trim();
  if (!value) return null;
  const normalized = value.includes("T")
    ? value
    : `${value.replace(" ", "T")}Z`;
  const dt = new Date(normalized);
  return Number.isNaN(dt.getTime()) ? null : dt;
}

function relativeTimeFromNow(raw) {
  const dt = raw instanceof Date ? raw : parseTimestamp(raw);
  if (!dt) return null;
  const deltaSec = Math.max(0, Math.floor((Date.now() - dt.getTime()) / 1000));
  if (deltaSec < 60) return "just now";
  const deltaMin = Math.floor(deltaSec / 60);
  if (deltaMin < 60) return `${deltaMin}m ago`;
  const deltaHr = Math.floor(deltaMin / 60);
  if (deltaHr < 24) return `${deltaHr}h ago`;
  const deltaDay = Math.floor(deltaHr / 24);
  return `${deltaDay}d ago`;
}

function formatJustAddedMeta() {
  // Show auto-refresh interval if configured
  if (Number.isFinite(justAddedPollIntervalMinutes) && justAddedPollIntervalMinutes > 0) {
    return `Auto-refresh ${justAddedPollIntervalMinutes}m`;
  }
  return "New Releases";
}

function updateJustAddedMeta() {
  if (justAddedDateEl) {
    justAddedDateEl.textContent = formatJustAddedMeta();
  }
  // Also update sync button with time
  if (justAddedSyncBtn && !justAddedSyncBtn.disabled) {
    const syncText = justAddedSyncBtn.querySelector(".sync-text");
    if (syncText) {
      const timeLabel = relativeTimeFromNow(justAddedLastPollAt || justAddedCheckedAt);
      syncText.textContent = timeLabel || "Sync";
    }
  }
}

function startJustAddedMetaTimer() {
  if (justAddedMetaTimer) return;
  justAddedMetaTimer = setInterval(updateJustAddedMeta, 60000);
}

function startJustAddedRefreshTimer() {
  // Clear any existing timer
  if (justAddedRefreshTimer) {
    clearInterval(justAddedRefreshTimer);
    justAddedRefreshTimer = null;
  }
  // Only start if we have a valid interval
  const intervalMinutes = justAddedPollIntervalMinutes || 30;
  const intervalMs = intervalMinutes * 60 * 1000;
  justAddedRefreshTimer = setInterval(() => {
    console.log(`[Just Added] Auto-refreshing (every ${intervalMinutes}m)...`);
    loadJustAdded();
  }, intervalMs);
  console.log(`[Just Added] Refresh timer started: every ${intervalMinutes} minutes`);
}

async function loadJustAdded() {
  if (!justAddedGrid || !justAddedSection) {
    console.log("[Just Added] Grid or section not found");
    return;
  }

  console.log("[Just Added] Loading...");
  justAddedCheckedAt = new Date().toISOString();
  justAddedLastPollAt = null;
  justAddedPollIntervalMinutes = 30; // Default
  updateJustAddedMeta();

  try {
    // First try usenet releases
    let releases = [];
    try {
      console.log("[Just Added] Fetching from /api/usenet/latest...");
      const usenetRes = await fetch("/api/usenet/latest?limit=16");
      console.log("[Just Added] Response status:", usenetRes.status);
      if (usenetRes.ok) {
        const usenetData = await usenetRes.json();
        console.log("[Just Added] Got data:", usenetData.count, "releases");
        releases = usenetData.releases || [];
        justAddedCheckedAt = usenetData.checked_at || justAddedCheckedAt;
        justAddedLastPollAt = usenetData.last_poll_at || null;
        const interval = Number(usenetData.poll_interval_minutes);
        justAddedPollIntervalMinutes = Number.isFinite(interval) ? interval : 30;
        updateJustAddedMeta();
        startJustAddedMetaTimer();
        startJustAddedRefreshTimer();
      }
    } catch (fetchErr) {
      console.error("[Just Added] Fetch error:", fetchErr);
    }

    // If no usenet, get from recommendations (now-playing + upcoming)
    if (releases.length === 0) {
      const recRes = await fetch("/api/recommendations?count=50&sort=release-current");
      if (recRes.ok) {
        const recData = await recRes.json();
        const recs = recData.recommendations || [];
        // Filter to recent releases (now-playing, upcoming with release dates)
        releases = recs
          .filter(r => {
            const tags = r.movie?.source_tags || [];
            return tags.includes("now-playing") || tags.includes("nzbgeek") || tags.includes("drunkenslug");
          })
          .slice(0, 10)
          .map(r => ({
            title: r.movie.title,
            year: r.movie.year,
            poster_url: r.movie.poster_url,
            score: r.movie.rottentomatoes_score,
          }));
      }
    }

    if (releases.length === 0) {
      justAddedSection.classList.add("hidden");
      return;
    }

    renderJustAdded(releases.slice(0, 14));
  } catch (err) {
    console.error("Failed to load just added:", err);
    justAddedSection.classList.add("hidden");
  }
}

function renderJustAdded(releases) {
  if (!justAddedGrid) return;

  if (releases.length === 0) {
    justAddedGrid.innerHTML = '<p class="just-added-empty">No new releases today</p>';
    return;
  }

  justAddedGrid.innerHTML = releases
    .map((release) => {
      const posterUrl = release.poster_url || "";
      const title = release.title || "Unknown";
      const year = release.year || "";
      const score = release.score || null;

      const posterHtml = posterUrl
        ? `<img class="cover-image" src="${posterUrl}" alt="${title}" loading="lazy" />`
        : `<div class="cover-fallback"><span class="cover-monogram">${title.substring(0, 2).toUpperCase()}</span></div>`;

      const scoreHtml = score
        ? `<div class="flip-front-score score-badge">${score}</div>`
        : "";

      // Download status badge - Just Added are always from NZBGeek so they're ready
      const statusBadge = `<div class="download-status ready"><span class="status-icon">⚡</span><span class="status-text">Ready</span></div>`;

      const overview = (release.overview || "").replace(/"/g, '&quot;');
      return `
        <article class="flip-card is-ready" data-title="${title}" data-year="${year}" data-poster="${posterUrl}" data-overview="${overview}">
          <div class="flip-card-inner">
            <div class="flip-card-front">
              ${posterHtml}
              ${scoreHtml}
              ${statusBadge}
              <div class="flip-front-overlay">
                <div class="flip-front-title">${title}</div>
                <p class="flip-front-meta">${year}</p>
              </div>
            </div>
          </div>
        </article>
      `;
    })
    .join("");

  // Add click handlers
  justAddedGrid.querySelectorAll(".flip-card").forEach((card) => {
    card.addEventListener("click", async () => {
      const title = card.dataset.title;
      const year = card.dataset.year;
      const posterUrl = card.dataset.poster || "";
      const overview = card.dataset.overview || "";

      // First try to find in recommendations
      const found = currentRecommendations.find(
        (r) => r.movie.title.toLowerCase() === title.toLowerCase() && String(r.movie.year) === String(year)
      );
      if (found) {
        openMovieModal(found);
        return;
      }

      // Create a movie object for the modal
      const movieData = {
        movie: {
          title: title,
          year: parseInt(year) || null,
          poster_url: posterUrl,
          overview: overview,
          source_tags: ["nzbgeek"],
          available_on_usenet: true,
        },
        score: 0,
        reason: "New release from NZBGeek",
      };
      openMovieModal(movieData);
    });
  });

  justAddedSection.classList.remove("hidden");
}

// ============================================================================
// Authentication
// ============================================================================

function getAuthToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

function setAuthToken(token) {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

function clearAuth() {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(AUTH_USER_KEY);
}

function getAuthUser() {
  const data = localStorage.getItem(AUTH_USER_KEY);
  return data ? JSON.parse(data) : null;
}

function setAuthUser(user) {
  localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
}

function updateAuthUI() {
  const user = getAuthUser();
  if (user && loginBtn && userDropdown && userNameEl) {
    loginBtn.classList.add("hidden");
    userDropdown.classList.remove("hidden");
    userNameEl.textContent = user.username;
  } else if (loginBtn && userDropdown) {
    loginBtn.classList.remove("hidden");
    userDropdown.classList.add("hidden");
  }
}

async function checkGoogleOAuthEnabled() {
  try {
    const res = await fetch("/api/auth/google/enabled");
    const data = await res.json();
    if (!data.enabled) {
      if (googleLoginSection) googleLoginSection.classList.add("hidden");
      if (googleNotConfigured) googleNotConfigured.classList.remove("hidden");
    }
  } catch {
    if (googleLoginSection) googleLoginSection.classList.add("hidden");
    if (googleNotConfigured) googleNotConfigured.classList.remove("hidden");
  }
}

async function fetchCurrentUser() {
  const token = getAuthToken();
  if (!token) return null;

  try {
    const res = await fetch("/api/auth/me", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      clearAuth();
      return null;
    }
    const user = await res.json();
    setAuthUser(user);
    return user;
  } catch {
    clearAuth();
    return null;
  }
}

function showModal(modal) {
  if (modal) {
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
  }
}

function hideModal(modal) {
  if (modal) {
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
  }
}

function initAuth() {
  // Check for token in URL (from Google OAuth callback)
  const urlParams = new URLSearchParams(window.location.search);
  const tokenFromUrl = urlParams.get("token");
  if (tokenFromUrl) {
    setAuthToken(tokenFromUrl);
    // Remove token from URL
    window.history.replaceState({}, document.title, window.location.pathname);
    // Fetch user info
    fetchCurrentUser().then(() => updateAuthUI());
  }

  // Check Google OAuth availability
  checkGoogleOAuthEnabled();

  // Login button - show modal
  if (loginBtn) {
    loginBtn.addEventListener("click", () => showModal(loginModal));
  }

  // Logout button
  if (logoutBtn) {
    logoutBtn.addEventListener("click", () => {
      clearAuth();
      updateAuthUI();
    });
  }

  // Close login modal
  if (loginModal) {
    const closeBtn = loginModal.querySelector(".modal-close");
    const backdrop = loginModal.querySelector(".modal-backdrop");
    if (closeBtn) closeBtn.addEventListener("click", () => hideModal(loginModal));
    if (backdrop) backdrop.addEventListener("click", () => hideModal(loginModal));
  }

  // Load current user and update UI
  fetchCurrentUser().then(() => updateAuthUI());
}

// Just Added Sync button handler
if (justAddedSyncBtn) {
  justAddedSyncBtn.addEventListener("click", async () => {
    console.log("[Just Added] Sync button clicked");
    justAddedSyncBtn.disabled = true;
    justAddedSyncBtn.innerHTML = `
      <svg class="sync-icon spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 12a9 9 0 1 1-6.219-8.56"></path>
      </svg>
      <span class="sync-text">Syncing...</span>
    `;
    try {
      await loadJustAdded();
      console.log("[Just Added] Sync completed successfully");
    } catch (err) {
      console.error("[Just Added] Sync failed:", err);
    } finally {
      justAddedSyncBtn.disabled = false;
      justAddedSyncBtn.innerHTML = `
        <svg class="sync-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 2v6h-6"></path>
          <path d="M3 12a9 9 0 0 1 15-6.7L21 8"></path>
          <path d="M3 22v-6h6"></path>
          <path d="M21 12a9 9 0 0 1-15 6.7L3 16"></path>
        </svg>
        <span class="sync-text">just now</span>
      `;
      // Update meta after button is re-enabled
      setTimeout(updateJustAddedMeta, 100);
    }
  });
}

// Initialize
(async function init() {
  initTheme();
  initAuth();
  renderHomeSourceFilters();
  renderAiSuggestions();
  await Promise.all([
    fetchIntegrations(),
    loadDownloadActivity(),
    loadRadarrMonitored(),
    updateStatusBanner(),
    loadDiskSpace(),
    checkAiStatus(),
    loadMoods(),
    loadJustAdded(),
  ]);
  await loadRecommendations();

  // Load suggested moods after recommendations (needs feedback data)
  loadSuggestedMoods();

  // Start auto-refresh for downloads
  startDownloadAutoRefresh();

  // Initialize smart sticky sidebar
  initSmartStickySidebar();
})();

// Smart sticky sidebar - sticks at top when scrolling up, bottom when scrolling down
function initSmartStickySidebar() {
  const sidebar = document.querySelector(".sidebar");
  if (!sidebar) return;

  let lastScrollY = window.scrollY;
  let sidebarTop = 0;
  let ticking = false;

  function updateSidebar() {
    const scrollY = window.scrollY;
    const viewportHeight = window.innerHeight;
    const sidebarHeight = sidebar.offsetHeight;
    const sidebarRect = sidebar.getBoundingClientRect();

    // If sidebar fits in viewport, just stick to top
    if (sidebarHeight <= viewportHeight - 48) {
      sidebar.style.position = "sticky";
      sidebar.style.top = "24px";
      sidebar.style.bottom = "";
      ticking = false;
      return;
    }

    const scrollingDown = scrollY > lastScrollY;
    const scrollingUp = scrollY < lastScrollY;

    if (scrollingDown) {
      // Scrolling down - stick to bottom when we reach it
      if (sidebarRect.bottom <= viewportHeight) {
        sidebar.style.position = "sticky";
        sidebar.style.top = `${viewportHeight - sidebarHeight - 24}px`;
        sidebar.style.bottom = "";
      } else {
        sidebar.style.position = "relative";
        sidebar.style.top = `${Math.max(0, sidebarTop)}px`;
        sidebar.style.bottom = "";
      }
      sidebarTop = scrollY - sidebar.parentElement.offsetTop + sidebarRect.top - 24;
    } else if (scrollingUp) {
      // Scrolling up - stick to top when we reach it
      if (sidebarRect.top >= 24) {
        sidebar.style.position = "sticky";
        sidebar.style.top = "24px";
        sidebar.style.bottom = "";
      } else {
        sidebar.style.position = "relative";
        sidebar.style.top = `${Math.max(0, sidebarTop)}px`;
        sidebar.style.bottom = "";
      }
      sidebarTop = scrollY - sidebar.parentElement.offsetTop + sidebarRect.top - 24;
    }

    lastScrollY = scrollY;
    ticking = false;
  }

  window.addEventListener("scroll", () => {
    if (!ticking) {
      requestAnimationFrame(updateSidebar);
      ticking = true;
    }
  }, { passive: true });

  // Initial setup
  updateSidebar();
}
