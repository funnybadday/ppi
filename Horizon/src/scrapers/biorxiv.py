"""bioRxiv / medRxiv API scraper.

Pulls recent preprints from the Cold Spring Harbor Laboratory API
(https://api.biorxiv.org) for a configured server and maps each record
into a ContentItem so the rest of the Horizon pipeline (deduplication,
AI scoring, enrichment, summarization) treats them the same way as RSS
or Google News items.

Design notes:

* No API key is required. The ``/details/{server}/{from}/{to}/{cursor}``
  endpoint returns pages of up to 30 records for a date interval. The
  ``cursor`` is a record *offset* (skip the first N records), not a page
  number: adjacent cursors overlap heavily, so the scraper steps the
  cursor by the page size and stops on an empty page, a page with no new
  DOIs, or when the reported unique ``total`` is covered. Requests are
  at least 1s apart per the API's fair-use guidance.
* The API exposes no server-side subject filter, so subject selection is
  a local whitelist match on the record's ``category`` field. This is
  source curation (which feeds to read), mirroring how RSS sources are
  chosen; content relevance is still judged downstream by the profile.
* Records are deduplicated by DOI (overlapping cursors and posted
  revisions of the same preprint), keeping the last version seen.
* ``published_at`` uses the record's ``date`` (posting date). Records
  with an unparseable date are skipped, not allowed to abort the batch.
* The old subject RSS endpoints (connect.biorxiv.com/*_xml.php) are dead
  (404); this API is the supported replacement.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

import httpx

from .base import BaseScraper
from ..models import BiorxivSourceConfig, ContentItem, SourceType

logger = logging.getLogger(__name__)

_PAGE_SIZE = 30
_PAGE_PAUSE_SECONDS = 1.0
_MAX_PAGES = 100  # hard stop: 100 pages x 30 records = 3000 records
_MAX_AUTHORS = 6


class BiorxivScraper(BaseScraper):
    """Scraper backed by the bioRxiv/medRxiv details API."""

    SOURCE_TYPE = SourceType.BIORXIV
    VALID_SERVERS = ("biorxiv", "medrxiv")

    def __init__(self, config: BiorxivSourceConfig, http_client: httpx.AsyncClient):
        """Initialize the scraper.

        Args:
            config: bioRxiv/medRxiv source configuration.
            http_client: Shared async HTTP client.
        """
        super().__init__({"biorxiv": config}, http_client)
        self.bx_config = config

    async def fetch(self, since: datetime) -> List[ContentItem]:
        """Fetch preprints posted since the given time.

        The API interval is date-granular, so the day containing ``since``
        is included whole and precise trimming happens downstream via
        ``published_at`` filtering.

        Args:
            since: Only fetch items posted after this time.

        Returns:
            List[ContentItem]: Fetched content items.
        """
        if not self.bx_config.enabled:
            return []
        if self.bx_config.server not in self.VALID_SERVERS:
            logger.warning(
                "Invalid biorxiv server %r (expected one of %s)",
                self.bx_config.server,
                self.VALID_SERVERS,
            )
            return []

        since_utc = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        from_date = since_utc.date().isoformat()
        to_date = datetime.now(timezone.utc).date().isoformat()
        subjects = {subject.strip().lower() for subject in self.bx_config.subjects if subject.strip()}

        matched: dict[str, ContentItem] = {}
        seen_dois: set[str] = set()
        cursor = 0
        for _ in range(_MAX_PAGES):
            url = (
                f"{self.bx_config.api_base}/details/{self.bx_config.server}/"
                f"{from_date}/{to_date}/{cursor}/json"
            )
            try:
                response = await self.client.get(url)
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                logger.warning("Error fetching %s details at offset %d: %s", self.bx_config.server, cursor, exc)
                break

            messages = payload.get("messages") or [{}]
            total = self._as_int(messages[0].get("total"))
            page = payload.get("collection") or []
            if not page:
                break

            new_records = 0
            for record in page:
                doi = str(record.get("doi") or "").strip()
                if doi and doi not in seen_dois:
                    seen_dois.add(doi)
                    new_records += 1
                if subjects and str(record.get("category", "")).strip().lower() not in subjects:
                    continue
                item = self._record_to_item(record)
                if item is None:
                    continue
                # Later versions of the same DOI overwrite earlier ones.
                matched[str(item.metadata.get("doi"))] = item
                if len(matched) >= self.bx_config.max_results:
                    return list(matched.values())

            # The cursor is a record offset and the reported total counts
            # unique records: stop once a page yields nothing new or the
            # interval is covered.
            if new_records == 0:
                break
            if total is not None and len(seen_dois) >= total:
                break
            cursor += _PAGE_SIZE
            await asyncio.sleep(_PAGE_PAUSE_SECONDS)

        return list(matched.values())

    @staticmethod
    def _as_int(raw: Any) -> Optional[int]:
        try:
            return int(str(raw))
        except (TypeError, ValueError):
            return None

    def _record_to_item(self, record: dict[str, Any]) -> Optional[ContentItem]:
        """Map one API record into a ContentItem.

        Returns None when the record has no title/DOI or an unparseable
        date (published_at is required), so a single bad record is skipped
        rather than aborting the batch.
        """
        try:
            title = str(record.get("title") or "").strip()
            doi = str(record.get("doi") or "").strip()
            if not title or not doi:
                return None

            published = self._parse_date(str(record.get("date") or ""))
            if published is None:
                return None

            entry_hash = hashlib.sha256(doi.encode("utf-8")).hexdigest()[:16]
            meta = {
                "feed_name": self.bx_config.feed_name,
                "doi": doi,
                "category": str(record.get("category") or "").strip() or None,
                "server": self.bx_config.server,
            }

            return ContentItem(
                id=self._generate_id("biorxiv", "article", entry_hash),
                source_type=self.SOURCE_TYPE,
                title=title,
                url=f"https://doi.org/{doi}",
                content=self._abstract_of(record),
                author=self._authors_of(str(record.get("authors") or "")),
                published_at=published,
                profile=self.bx_config.profile,
                metadata={k: v for k, v in meta.items() if v is not None},
            )
        except Exception as exc:
            logger.warning("Skipping invalid %s record: %s", self.bx_config.server, exc)
            return None

    @staticmethod
    def _abstract_of(record: dict[str, Any]) -> Optional[str]:
        abstract = str(record.get("abstract") or "").strip()
        return abstract or None

    @staticmethod
    def _authors_of(raw: str) -> Optional[str]:
        """Cap the API's "Last FM; ..." author string, with et al."""
        names = [name.strip() for name in raw.split(";") if name.strip()]
        if not names:
            return None
        if len(names) > _MAX_AUTHORS:
            return "; ".join(names[:_MAX_AUTHORS]) + ", et al."
        return "; ".join(names)

    @staticmethod
    def _parse_date(raw: str) -> Optional[datetime]:
        """Parse the API's "YYYY-MM-DD" posting date into aware UTC."""
        try:
            return datetime.strptime(raw.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
