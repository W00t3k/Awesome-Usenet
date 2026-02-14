const integrationsEl = document.getElementById("integrations");
const integrationSettingsEl = document.getElementById("integration-settings");
const saveSettingsBtn = document.getElementById("save-settings");
const settingsFeedbackEl = document.getElementById("settings-feedback");
const importPlexBtn = document.getElementById("import-plex");
const loadPlexLibraryBtn = document.getElementById("load-plex-library");
const addSelectedPlexBtn = document.getElementById("add-selected-plex");
const plexLibraryEl = document.getElementById("plex-library");
const manualSeenForm = document.getElementById("manual-seen-form");
const seenTitleInput = document.getElementById("seen-title");
const seenYearInput = document.getElementById("seen-year");
const seenSearchInput = document.getElementById("seen-search");
const seenRefreshBtn = document.getElementById("refresh-seen");
const seenFeedbackEl = document.getElementById("seen-feedback");
const seenListEl = document.getElementById("seen-list");

const SETTINGS_SCHEMA = [
  {
    integration: "tmdb",
    label: "TMDB",
    fields: [{ name: "tmdb_api_key", label: "API Key", type: "password", placeholder: "Enter API key" }],
  },
  {
    integration: "rottentomatoes",
    label: "Rotten Tomatoes",
    fields: [
      {
        name: "rottentomatoes_list_url",
        label: "List URL",
        type: "text",
        placeholder: "https://www.rottentomatoes.com/browse/movies_at_home/sort:popular",
      },
    ],
  },
  {
    integration: "releases",
    label: "Releases.com",
    fields: [{ name: "releases_url", label: "Page URL", type: "text", placeholder: "https://www.releases.com/calendar/movie" }],
  },
  {
    integration: "rogerebert",
    label: "RogerEbert",
    fields: [
      {
        name: "rogerebert_reviews_url",
        label: "Reviews URL",
        type: "text",
        placeholder: "https://www.rogerebert.com/reviews",
      },
    ],
  },
  {
    integration: "plex",
    label: "Plex",
    fields: [
      { name: "plex_base_url", label: "Base URL", type: "text", placeholder: "http://localhost:32400" },
      { name: "plex_token", label: "Token", type: "password", placeholder: "Enter Plex token" },
    ],
  },
  {
    integration: "radarr",
    label: "Downloader",
    fields: [
      { name: "radarr_base_url", label: "Service URL", type: "text", placeholder: "http://localhost:7878" },
      { name: "radarr_api_key", label: "API Key", type: "password", placeholder: "Enter downloader API key" },
    ],
  },
  {
    integration: "nzbgeek",
    label: "NZBGeek RSS",
    fields: [
      {
        name: "nzbgeek_rss_url",
        label: "RSS URL",
        type: "text",
        placeholder: "https://api.nzbgeek.info/rss?t=search&cat=2000&apikey={API_KEY}",
      },
      { name: "nzbgeek_api_key", label: "API Key", type: "password", placeholder: "Enter NZBGeek API key" },
    ],
  },
  {
    integration: "drunkenslug",
    label: "DrunkenSlug",
    fields: [
      {
        name: "drunkenslug_base_url",
        label: "Base URL",
        type: "text",
        placeholder: "https://api.drunkenslug.com",
      },
      {
        name: "drunkenslug_api_key",
        label: "API Key",
        type: "password",
        placeholder: "Enter DrunkenSlug API key",
      },
    ],
  },
  {
    integration: "usenet",
    label: "Usenet/Newznab",
    fields: [
      { name: "usenet_base_url", label: "Base URL", type: "text", placeholder: "http://localhost:5076" },
      { name: "usenet_api_key", label: "API Key", type: "password", placeholder: "Enter API key" },
    ],
  },
  {
    integration: "ollama",
    label: "Ollama (AI)",
    fields: [
      { name: "ollama_base_url", label: "Base URL", type: "text", placeholder: "http://localhost:11434" },
      { name: "ollama_model", label: "Model", type: "text", placeholder: "llama3.2" },
    ],
  },
];

const settingsRows = new Map();
let settingsDefaults = {};
let seenSearchTimer = null;
let plexLibraryRows = [];

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

function stableManualMovieId(title, year) {
  const normalized = title.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return `manual:${normalized || "movie"}::${year || "na"}`;
}

function renderStatusBadges(data) {
  integrationsEl.innerHTML = "";
  const labelMap = {
    rottentomatoes: "RT",
    releases: "Releases",
    nzbgeek: "NZBGeek",
    drunkenslug: "DrunkenSlug",
    rogerebert: "RogerEbert",
    tmdb: "TMDB",
    plex: "Plex",
    radarr: "Downloader",
    usenet: "Usenet",
    ollama: "Ollama",
  };
  Object.entries(data).forEach(([name, active]) => {
    const badge = document.createElement("span");
    badge.className = `badge ${active ? "active" : "inactive"}`;
    badge.textContent = `${labelMap[name] || name}: ${active ? "connected" : "off"}`;
    integrationsEl.appendChild(badge);
  });
}

async function fetchIntegrations() {
  const res = await fetch("/api/integrations");
  const data = await res.json();
  renderStatusBadges(data);
}

function createFieldControl(field, values) {
  const wrap = document.createElement("label");
  wrap.textContent = field.label;
  const input = document.createElement("input");
  input.type = field.type;
  input.placeholder = settingsDefaults[field.name] || field.placeholder || "";
  input.value = values[field.name] || "";
  wrap.appendChild(input);
  return { wrap, input };
}

function createSettingRow(config, values) {
  const row = document.createElement("div");
  row.className = "integration-row";

  const header = document.createElement("div");
  header.className = "integration-row-head";
  const title = document.createElement("h3");
  title.textContent = config.label;
  const actions = document.createElement("div");
  actions.className = "integration-row-actions";
  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "secondary";
  saveBtn.textContent = "Save";
  const testBtn = document.createElement("button");
  testBtn.type = "button";
  testBtn.className = "secondary";
  testBtn.textContent = "Test";
  actions.appendChild(saveBtn);
  actions.appendChild(testBtn);
  header.appendChild(title);
  header.appendChild(actions);
  row.appendChild(header);

  const fieldControls = [];
  config.fields.forEach((field) => {
    const control = createFieldControl(field, values);
    row.appendChild(control.wrap);
    fieldControls.push({ name: field.name, input: control.input });
  });

  const testResult = document.createElement("p");
  testResult.className = "test-result muted";
  row.appendChild(testResult);

  const controls = {
    config,
    fields: fieldControls,
    saveBtn,
    testBtn,
    testResult,
  };

  saveBtn.addEventListener("click", () => saveIntegrationRow(controls));
  testBtn.addEventListener("click", () => runIntegrationTest(controls));
  settingsRows.set(config.integration, controls);

  return row;
}

function renderSettings(values, defaults) {
  settingsDefaults = defaults || {};
  settingsRows.clear();
  integrationSettingsEl.innerHTML = "";
  SETTINGS_SCHEMA.forEach((config) => {
    integrationSettingsEl.appendChild(createSettingRow(config, values || {}));
  });
}

async function loadSettings() {
  const res = await fetch("/api/settings");
  const data = await res.json();
  renderSettings(data.values || {}, data.defaults || {});
}

function buildSettingsPayload() {
  const payload = {};
  settingsRows.forEach((controls) => {
    controls.fields.forEach(({ name, input }) => {
      const value = input.value.trim();
      payload[name] = value;
    });
  });
  return payload;
}

async function saveSettings() {
  saveSettingsBtn.disabled = true;
  settingsFeedbackEl.textContent = "Saving settings...";

  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildSettingsPayload()),
    });
    if (!res.ok) {
      throw new Error(`Failed to save (${res.status})`);
    }

    settingsFeedbackEl.textContent = "Settings saved.";
    await fetchIntegrations();
    await loadSettings();
  } catch (err) {
    settingsFeedbackEl.textContent = `Save failed: ${err.message}`;
  } finally {
    saveSettingsBtn.disabled = false;
  }
}

function rowPayload(controls) {
  const payload = {};
  controls.fields.forEach(({ name, input }) => {
    payload[name] = input.value.trim();
  });
  return payload;
}

async function saveIntegrationRow(controls) {
  controls.saveBtn.disabled = true;
  controls.testResult.className = "test-result muted";
  controls.testResult.textContent = "Saving...";

  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rowPayload(controls)),
    });
    if (!res.ok) {
      throw new Error(`Failed to save (${res.status})`);
    }
    const data = await res.json();
    renderStatusBadges(data.integrations || {});

    // Auto-test after save to verify the key actually works
    controls.testResult.textContent = "Saved. Testing connection...";
    try {
      const testRes = await fetch("/api/integrations/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          integration: controls.config.integration,
          values: rowPayload(controls),
        }),
      });
      const testData = await testRes.json();
      if (testData.ok) {
        controls.testResult.className = "test-result ok";
        controls.testResult.textContent = `Saved & verified: ${testData.message || "OK"}`;
      } else {
        controls.testResult.className = "test-result err";
        controls.testResult.textContent = `Saved but test failed: ${testData.message || "Connection error"}`;
      }
    } catch {
      controls.testResult.className = "test-result err";
      controls.testResult.textContent = "Saved but could not verify connection.";
    }
  } catch (err) {
    controls.testResult.className = "test-result err";
    controls.testResult.textContent = `Save failed: ${err.message}`;
  } finally {
    controls.saveBtn.disabled = false;
  }
}

async function runIntegrationTest(controls) {
  controls.testBtn.disabled = true;
  controls.testResult.className = "test-result muted";
  controls.testResult.textContent = "Testing...";

  try {
    const res = await fetch("/api/integrations/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        integration: controls.config.integration,
        values: rowPayload(controls),
      }),
    });
    const data = await res.json();
    controls.testResult.className = `test-result ${data.ok ? "ok" : "err"}`;
    controls.testResult.textContent = data.message || (data.ok ? "OK" : "Failed");
  } catch (err) {
    controls.testResult.className = "test-result err";
    controls.testResult.textContent = err.message;
  } finally {
    controls.testBtn.disabled = false;
  }
}

function renderPlexLibrary(rows) {
  if (!plexLibraryEl) {
    return;
  }

  plexLibraryEl.innerHTML = "";
  if (!rows.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "No Plex movies loaded.";
    plexLibraryEl.appendChild(p);
    return;
  }

  rows.forEach((row) => {
    const label = document.createElement("label");
    label.className = "plex-row";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = row.movie_id;

    const text = document.createElement("span");
    text.textContent = `${row.title}${row.year ? ` (${row.year})` : ""}`;

    label.appendChild(checkbox);
    label.appendChild(text);
    plexLibraryEl.appendChild(label);
  });
}

async function loadPlexLibrary() {
  if (!loadPlexLibraryBtn) {
    return;
  }
  loadPlexLibraryBtn.disabled = true;
  seenFeedbackEl.textContent = "Loading Plex library...";
  try {
    const res = await fetch("/api/plex/library?limit=400");
    const data = await res.json();
    if (!data.ok) {
      throw new Error(data.message || "Plex not available");
    }
    plexLibraryRows = data.movies || [];
    renderPlexLibrary(plexLibraryRows);
    seenFeedbackEl.textContent = `Loaded ${plexLibraryRows.length} Plex titles. Select and add.`;
  } catch (err) {
    seenFeedbackEl.textContent = `Load Plex library failed: ${err.message}`;
  } finally {
    loadPlexLibraryBtn.disabled = false;
  }
}

async function addSelectedFromPlex() {
  if (!addSelectedPlexBtn || !plexLibraryEl) {
    return;
  }

  const selectedIds = new Set(
    [...plexLibraryEl.querySelectorAll("input[type='checkbox']:checked")].map((el) => el.value)
  );
  const selected = plexLibraryRows.filter((row) => selectedIds.has(row.movie_id));
  if (!selected.length) {
    seenFeedbackEl.textContent = "Select at least one Plex movie first.";
    return;
  }

  addSelectedPlexBtn.disabled = true;
  seenFeedbackEl.textContent = `Adding ${selected.length} selected Plex movies...`;
  let added = 0;

  try {
    for (const row of selected) {
      const res = await fetch("/api/seen", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: currentUserId(),
          movie_id: row.movie_id,
          title: row.title,
          year: row.year || null,
          source: "plex",
        }),
      });
      if (res.ok) {
        added += 1;
      }
    }
    seenFeedbackEl.textContent = `Added ${added} selected Plex movies to seen inventory.`;
    await loadSeenInventory();
  } catch (err) {
    seenFeedbackEl.textContent = `Add selected failed: ${err.message}`;
  } finally {
    addSelectedPlexBtn.disabled = false;
  }
}

function seenCategory(source) {
  const normalized = String(source || "").trim().toLowerCase();
  if (normalized === "skip" || normalized === "skipped") {
    return "Skipped";
  }
  if (
    normalized === "watch" ||
    normalized === "played" ||
    normalized === "liked" ||
    normalized === "like"
  ) {
    return "Watch";
  }
  return "Inventory";
}

function renderSeenList(rows) {
  seenListEl.innerHTML = "";
  if (!rows.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "No seen inventory yet.";
    seenListEl.appendChild(p);
    return;
  }

  const grouped = {
    Watch: [],
    Skipped: [],
    Inventory: [],
  };
  rows.forEach((row) => {
    const category = seenCategory(row.source);
    grouped[category].push(row);
  });

  ["Watch", "Skipped", "Inventory"].forEach((category) => {
    const items = grouped[category] || [];
    if (!items.length) {
      return;
    }

    const section = document.createElement("section");
    section.className = "seen-group";
    const heading = document.createElement("h4");
    heading.className = "seen-group-title";
    heading.textContent = `${category} (${items.length})`;
    section.appendChild(heading);

    items.forEach((row) => {
      const item = document.createElement("article");
      item.className = "seen-item";

      const text = document.createElement("div");
      text.className = "seen-item-text";
      const title = document.createElement("strong");
      title.textContent = row.title;
      const meta = document.createElement("p");
      meta.className = "muted";
      meta.textContent = `${row.year || "year unknown"} • ${row.source} • updated ${new Date(row.updated_at).toLocaleString()}`;
      text.appendChild(title);
      text.appendChild(meta);

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "secondary";
      removeBtn.textContent = "Remove";
      removeBtn.addEventListener("click", async () => {
        removeBtn.disabled = true;
        try {
          await fetch("/api/seen", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: currentUserId(), movie_id: row.movie_id }),
          });
          await loadSeenInventory();
        } catch (err) {
          seenFeedbackEl.textContent = `Remove failed: ${err.message}`;
        } finally {
          removeBtn.disabled = false;
        }
      });

      item.appendChild(text);
      item.appendChild(removeBtn);
      section.appendChild(item);
    });

    seenListEl.appendChild(section);
  });
}

async function loadSeenInventory() {
  const query = seenSearchInput.value.trim();
  const url = new URL(`/api/seen/${encodeURIComponent(currentUserId())}`, window.location.origin);
  if (query) {
    url.searchParams.set("q", query);
  }
  const res = await fetch(url.toString());
  const rows = await res.json();
  renderSeenList(rows || []);
}

async function importFromPlex() {
  importPlexBtn.disabled = true;
  seenFeedbackEl.textContent = "Importing from Plex...";

  try {
    const res = await fetch(`/api/seen/import/plex?user_id=${encodeURIComponent(currentUserId())}`, {
      method: "POST",
    });
    const data = await res.json();
    seenFeedbackEl.textContent = data.message || (data.ok ? "Import complete." : "Import failed.");
    await loadSeenInventory();
  } catch (err) {
    seenFeedbackEl.textContent = `Plex import failed: ${err.message}`;
  } finally {
    importPlexBtn.disabled = false;
  }
}

async function addSeenManual(event) {
  event.preventDefault();
  const title = seenTitleInput.value.trim();
  const yearRaw = seenYearInput.value.trim();
  const year = yearRaw ? Number.parseInt(yearRaw, 10) : null;
  if (!title) {
    seenFeedbackEl.textContent = "Title is required.";
    return;
  }

  try {
    const res = await fetch("/api/seen", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: currentUserId(),
        movie_id: stableManualMovieId(title, year),
        title,
        year,
        source: "manual",
      }),
    });
    if (!res.ok) {
      throw new Error(`Failed (${res.status})`);
    }
    seenFeedbackEl.textContent = "Saved to seen inventory.";
    manualSeenForm.reset();
    await loadSeenInventory();
  } catch (err) {
    seenFeedbackEl.textContent = `Manual add failed: ${err.message}`;
  }
}

saveSettingsBtn?.addEventListener("click", saveSettings);
importPlexBtn?.addEventListener("click", importFromPlex);
loadPlexLibraryBtn?.addEventListener("click", loadPlexLibrary);
addSelectedPlexBtn?.addEventListener("click", addSelectedFromPlex);
manualSeenForm?.addEventListener("submit", addSeenManual);
seenRefreshBtn?.addEventListener("click", loadSeenInventory);
seenSearchInput?.addEventListener("input", () => {
  if (seenSearchTimer) {
    clearTimeout(seenSearchTimer);
  }
  seenSearchTimer = setTimeout(() => {
    loadSeenInventory();
  }, 220);
});
seenSearchInput?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    loadSeenInventory();
  }
});

(async function init() {
  await fetchIntegrations();
  await loadSettings();
  await loadSeenInventory();
})();
