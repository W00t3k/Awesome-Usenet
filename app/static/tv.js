const nameEl = document.getElementById("tv-name");
const countEl = document.getElementById("tv-count");
const minYearEl = document.getElementById("tv-min-year");
const maxYearEl = document.getElementById("tv-max-year");
const startBtn = document.getElementById("tv-start");
const nextBtn = document.getElementById("tv-next");
const stopBtn = document.getElementById("tv-stop");
const refreshBtn = document.getElementById("tv-refresh");
const metaEl = document.getElementById("tv-meta");
const errorEl = document.getElementById("tv-error");
const nowEl = document.getElementById("tv-now-playing");
const upNextEl = document.getElementById("tv-up-next");

let stationId = null;

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function cardHtml(item, badgeText) {
  if (!item) return "";
  const title = escapeHtml(item.title || "Unknown");
  const year = item.year ? ` (${item.year})` : "";
  const poster = (item.poster_url || "").trim();
  const badge = badgeText ? `<span class="source-origin front-source-origin">${escapeHtml(badgeText)}</span>` : "";
  const openBtn = item.web_url
    ? `<a class="btn btn-ghost btn-sm" href="${escapeHtml(item.web_url)}" target="_blank" rel="noopener noreferrer">Open in Plex</a>`
    : "";

  const art = poster
    ? `<img class="cover-image" src="${escapeHtml(poster)}" alt="${title}" loading="lazy" />`
    : `<div class="cover-fallback"><span class="cover-monogram">${title.slice(0, 2).toUpperCase()}</span></div>`;

  return `
    <article class="flip-card">
      <div class="flip-card-inner">
        <div class="flip-card-front">
          ${art}
          <div class="flip-front-overlay">
            <div class="flip-front-title">${title}${year}</div>
            <p class="flip-front-meta">${escapeHtml(item.summary || "")}</p>
            ${badge}
            ${openBtn}
          </div>
        </div>
      </div>
    </article>
  `;
}

function setMeta(station) {
  if (!metaEl) return;
  if (!station) {
    metaEl.textContent = "No station running";
    return;
  }
  metaEl.textContent = `${station.name} • ${station.queue_size} movies • Cycle ${station.cycle}`;
}

function setError(message = "") {
  if (errorEl) errorEl.textContent = message;
}

function renderStation(station) {
  setMeta(station);
  if (!station) {
    if (nowEl) nowEl.innerHTML = '<p class="just-added-empty">No station running.</p>';
    if (upNextEl) upNextEl.innerHTML = "";
    return;
  }

  const nowCard = station.now_playing ? cardHtml(station.now_playing, "NOW PLAYING") : "";
  if (nowEl) nowEl.innerHTML = nowCard || '<p class="just-added-empty">Queue is empty.</p>';

  const upcoming = Array.isArray(station.up_next) ? station.up_next : [];
  if (upNextEl) {
    upNextEl.innerHTML = upcoming.length
      ? upcoming.map((item, idx) => cardHtml(item, `UP NEXT #${idx + 1}`)).join("")
      : '<p class="just-added-empty">Nothing queued.</p>';
  }

  stationId = station.station_id || null;
  const hasStation = Boolean(stationId);
  if (nextBtn) nextBtn.disabled = !hasStation;
  if (stopBtn) stopBtn.disabled = !hasStation;
  if (refreshBtn) refreshBtn.disabled = !hasStation;
}

async function requestJson(url, options = {}) {
  const res = await fetch(url, options);
  const data = await res.json();
  if (!res.ok || data.ok === false) {
    throw new Error(data.message || `Request failed (${res.status})`);
  }
  return data;
}

async function startStation() {
  setError("");
  if (startBtn) {
    startBtn.disabled = true;
    startBtn.textContent = "Starting...";
  }
  try {
    const count = Number.parseInt(countEl?.value || "30", 10);
    const minYear = Number.parseInt(minYearEl?.value || "", 10);
    const maxYear = Number.parseInt(maxYearEl?.value || "", 10);
    const payload = {
      name: (nameEl?.value || "Random Plex TV").trim(),
      count: Number.isFinite(count) ? count : 30,
      min_year: Number.isFinite(minYear) ? minYear : null,
      max_year: Number.isFinite(maxYear) ? maxYear : null,
    };
    const data = await requestJson("/api/plex/station/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    renderStation(data.station);
  } catch (err) {
    setError(err.message || "Could not start station.");
  } finally {
    if (startBtn) {
      startBtn.disabled = false;
      startBtn.textContent = "Start Station";
    }
  }
}

async function refreshStation() {
  if (!stationId) return;
  try {
    const data = await requestJson(`/api/plex/station/${encodeURIComponent(stationId)}`);
    renderStation(data.station);
  } catch (err) {
    setError(err.message || "Failed to refresh station.");
  }
}

async function nextMovie() {
  if (!stationId) return;
  setError("");
  if (nextBtn) {
    nextBtn.disabled = true;
    nextBtn.textContent = "Advancing...";
  }
  try {
    const data = await requestJson(`/api/plex/station/${encodeURIComponent(stationId)}/next`, {
      method: "POST",
    });
    renderStation(data.station);
  } catch (err) {
    setError(err.message || "Failed to advance station.");
  } finally {
    if (nextBtn) {
      nextBtn.disabled = false;
      nextBtn.textContent = "Next Movie";
    }
  }
}

async function stopStation() {
  if (!stationId) return;
  setError("");
  try {
    await requestJson(`/api/plex/station/${encodeURIComponent(stationId)}`, {
      method: "DELETE",
    });
    stationId = null;
    renderStation(null);
  } catch (err) {
    setError(err.message || "Failed to stop station.");
  }
}

async function loadExistingStation() {
  try {
    const data = await requestJson("/api/plex/station");
    const first = Array.isArray(data.stations) && data.stations.length ? data.stations[0] : null;
    renderStation(first);
  } catch (err) {
    setError(err.message || "Failed to load station.");
  }
}

startBtn?.addEventListener("click", startStation);
nextBtn?.addEventListener("click", nextMovie);
stopBtn?.addEventListener("click", stopStation);
refreshBtn?.addEventListener("click", refreshStation);

loadExistingStation();
