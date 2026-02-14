"""Catalog sync tasks for Oscars and Criterion data."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Data directory for JSON backups
DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"


def sync_catalog(catalog_type: str) -> dict:
    """Sync a catalog from web source.

    Args:
        catalog_type: One of 'oscars' or 'criterion'

    Returns:
        Result dict with status and item count
    """
    # Import here to avoid circular imports
    from app.config import settings
    from app.services.embedding import EmbeddingService
    from app.services.memory_store import MemoryStore

    project_root = Path(__file__).resolve().parent.parent.parent.parent
    store = MemoryStore(
        db_path=project_root / settings.memory_db_path,
        embedding_service=EmbeddingService(),
    )

    job_id = store.create_sync_job(catalog_type)

    try:
        if catalog_type == "oscars":
            items = _scrape_oscars()
        elif catalog_type == "criterion":
            items = _scrape_criterion()
        else:
            raise ValueError(f"Unknown catalog type: {catalog_type}")

        # Save to cache
        store.set_catalog_cache(catalog_type, items)

        # Backup to JSON file
        json_path = DATA_DIR / f"{catalog_type}_collection.json"
        if catalog_type == "oscars":
            json_path = DATA_DIR / "oscars_best_picture.json"
        json_path.write_text(json.dumps(items, indent=2))
        logger.info(f"Backed up {len(items)} items to {json_path}")

        store.complete_sync_job(job_id, items_processed=len(items))
        return {"status": "success", "items": len(items)}

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Sync failed for {catalog_type}: {error_msg}")
        store.complete_sync_job(job_id, items_processed=0, error_message=error_msg)
        return {"status": "error", "error": error_msg}


def _scrape_oscars() -> list[dict]:
    """Scrape Oscar Best Picture data from Wikipedia."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("beautifulsoup4 not installed - using fallback")
        return _load_fallback_json("oscars_best_picture.json")

    url = "https://en.wikipedia.org/wiki/Academy_Award_for_Best_Picture"

    try:
        response = httpx.get(url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch Oscar page: {e}")
        return _load_fallback_json("oscars_best_picture.json")

    soup = BeautifulSoup(response.text, "html.parser")
    results: list[dict] = []

    # Find tables with winners/nominees
    tables = soup.find_all("table", class_="wikitable")

    for table in tables:
        rows = table.find_all("tr")
        current_year = None

        for row in rows:
            cells = row.find_all(["th", "td"])
            if not cells:
                continue

            # Try to extract year from first cell
            first_cell_text = cells[0].get_text(strip=True)
            year_match = re.search(r"\b(19\d{2}|20\d{2})\b", first_cell_text)
            if year_match:
                current_year = int(year_match.group(1))

            if not current_year:
                continue

            # Look for movie links
            for cell in cells:
                links = cell.find_all("a")
                for link in links:
                    title = link.get_text(strip=True)
                    if (
                        title
                        and len(title) > 2
                        and not title.isdigit()
                        and "ceremony" not in title.lower()
                        and "award" not in title.lower()
                    ):
                        # Check if winner (usually bold or first in cell)
                        is_winner = bool(link.find_parent("b") or link.find_parent("strong"))

                        # Check if this year already exists
                        existing = next((r for r in results if r["year"] == current_year), None)
                        if existing:
                            if is_winner and not existing.get("winner"):
                                existing["winner"] = title
                            elif title not in existing.get("nominees", []) and title != existing.get("winner"):
                                existing.setdefault("nominees", []).append(title)
                        else:
                            entry = {"year": current_year}
                            if is_winner:
                                entry["winner"] = title
                            else:
                                entry["nominees"] = [title]
                            results.append(entry)

    if not results:
        logger.warning("No Oscar data scraped - using fallback")
        return _load_fallback_json("oscars_best_picture.json")

    # Sort by year descending
    results.sort(key=lambda x: x.get("year", 0), reverse=True)
    logger.info(f"Scraped {len(results)} Oscar years")
    return results


def _scrape_criterion() -> list[dict]:
    """Scrape Criterion Collection catalog."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("beautifulsoup4 not installed - using fallback")
        return _load_fallback_json("criterion_collection.json")

    url = "https://www.criterion.com/shop/browse/list?sort=spine_number"

    try:
        response = httpx.get(
            url,
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "MajicMovieSelector/1.0"},
        )
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch Criterion page: {e}")
        return _load_fallback_json("criterion_collection.json")

    soup = BeautifulSoup(response.text, "html.parser")
    results: list[dict] = []

    # Find film entries
    film_items = soup.find_all("tr", class_="gridFilm")

    for item in film_items:
        try:
            # Extract title
            title_el = item.find("td", class_="g-title")
            if not title_el:
                continue
            title_link = title_el.find("a")
            title = title_link.get_text(strip=True) if title_link else title_el.get_text(strip=True)

            if not title:
                continue

            # Extract spine number
            spine_el = item.find("td", class_="g-spine")
            spine = spine_el.get_text(strip=True) if spine_el else None

            # Extract year
            year_el = item.find("td", class_="g-year")
            year_text = year_el.get_text(strip=True) if year_el else ""
            year_match = re.search(r"\b(19\d{2}|20\d{2})\b", year_text)
            year = int(year_match.group(1)) if year_match else None

            # Extract director
            director_el = item.find("td", class_="g-director")
            director = director_el.get_text(strip=True) if director_el else None

            results.append(
                {
                    "title": title,
                    "year": year,
                    "spine": spine,
                    "director": director,
                }
            )
        except Exception as e:
            logger.debug(f"Error parsing Criterion item: {e}")
            continue

    if not results:
        logger.warning("No Criterion data scraped - using fallback")
        return _load_fallback_json("criterion_collection.json")

    logger.info(f"Scraped {len(results)} Criterion films")
    return results


def _load_fallback_json(filename: str) -> list[dict]:
    """Load fallback JSON data."""
    path = DATA_DIR / filename
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.error(f"Failed to load fallback {filename}: {e}")
    return []
