const crawlBtn = document.getElementById("crawl-now");
const crawlMetaEl = document.getElementById("crawl-meta");
const crawlErrorsEl = document.getElementById("crawl-errors");
const rowsEl = document.getElementById("release-rows");
const releaseSearchEl = document.getElementById("release-search");
const releaseSortEl = document.getElementById("release-sort");

let allItems = [];

function clearRows() {
  if (rowsEl) {
    rowsEl.innerHTML = "";
  }
}

function addCell(rowEl, text) {
  const cell = document.createElement("td");
  cell.textContent = text || "";
  rowEl.appendChild(cell);
  return cell;
}

function renderRows(items) {
  if (!rowsEl) return;
  clearRows();

  if (!items.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 8;
    cell.className = "muted";
    cell.textContent = "No releases found from configured indexers.";
    row.appendChild(cell);
    rowsEl.appendChild(row);
    return;
  }

  items.forEach((item) => {
    const row = document.createElement("tr");
    const coverCell = document.createElement("td");
    if (item.poster_url) {
      const img = document.createElement("img");
      img.src = item.poster_url;
      img.alt = item.title ? `${item.title} cover` : "cover";
      img.className = "poster-thumb";
      img.loading = "lazy";
      coverCell.appendChild(img);
    }
    row.appendChild(coverCell);

    addCell(row, item.title || "");
    addCell(row, item.year ? String(item.year) : "");
    addCell(row, Number.isFinite(item.rottentomatoes_score) ? `${Math.round(item.rottentomatoes_score)}%` : "");
    addCell(row, item.indexer || "");

    const releasedCell = document.createElement("td");
    if (item.released_at_iso) {
      const dt = new Date(item.released_at_iso);
      releasedCell.textContent = Number.isNaN(dt.getTime()) ? item.released_at || "" : dt.toLocaleString();
    } else {
      releasedCell.textContent = item.released_at || "";
    }
    row.appendChild(releasedCell);

    const whereCell = document.createElement("td");
    if (item.where_url) {
      const link = document.createElement("a");
      link.href = item.where_url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = "open";
      whereCell.appendChild(link);
    }
    row.appendChild(whereCell);

    addCell(row, item.release_name || "");
    rowsEl.appendChild(row);
  });
}

function itemTimeMs(item) {
  if (!item || !item.released_at_iso) return 0;
  const dt = new Date(item.released_at_iso);
  return Number.isNaN(dt.getTime()) ? 0 : dt.getTime();
}

function filterAndSortRows() {
  const q = String(releaseSearchEl?.value || "").trim().toLowerCase();
  const sortMode = String(releaseSortEl?.value || "newest");

  let rows = [...allItems];
  if (q) {
    rows = rows.filter((item) => {
      const blob = [
        item.title,
        item.year,
        item.indexer,
        item.release_name,
        item.where_url,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return blob.includes(q);
    });
  }

  if (sortMode === "oldest") {
    rows.sort((a, b) => itemTimeMs(a) - itemTimeMs(b));
  } else if (sortMode === "title") {
    rows.sort((a, b) => String(a.title || "").localeCompare(String(b.title || ""), undefined, { sensitivity: "base" }));
  } else {
    rows.sort((a, b) => itemTimeMs(b) - itemTimeMs(a));
  }

  renderRows(rows);
}

function renderMeta(payload) {
  if (crawlMetaEl) {
    const generated = payload.generated_at ? new Date(payload.generated_at).toLocaleString() : "n/a";
    const indexers = Object.entries(payload.indexers || {})
      .map(([name, count]) => `${name}: ${count}`)
      .join(" | ");
    crawlMetaEl.textContent = `${payload.total_items || 0} releases • ${generated}${indexers ? ` • ${indexers}` : ""}`;
  }

  if (crawlErrorsEl) {
    const errors = payload.errors || [];
    crawlErrorsEl.textContent = errors.length ? `Warnings: ${errors.join(" | ")}` : "";
  }
}

async function crawlNow() {
  if (crawlBtn) crawlBtn.disabled = true;
  if (crawlMetaEl) crawlMetaEl.textContent = "Crawling indexers...";
  if (crawlErrorsEl) crawlErrorsEl.textContent = "";
  try {
    const res = await fetch("/api/usenet/releases?limit=500");
    if (!res.ok) {
      throw new Error(`crawl failed (${res.status})`);
    }
    const payload = await res.json();
    renderMeta(payload);
    allItems = payload.items || [];
    filterAndSortRows();
  } catch (err) {
    if (crawlErrorsEl) crawlErrorsEl.textContent = err.message || "Crawl failed";
    clearRows();
  } finally {
    if (crawlBtn) crawlBtn.disabled = false;
  }
}

crawlBtn?.addEventListener("click", crawlNow);
releaseSearchEl?.addEventListener("input", filterAndSortRows);
releaseSortEl?.addEventListener("change", filterAndSortRows);

(async function init() {
  await crawlNow();
})();
