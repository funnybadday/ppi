"""PubMed E-utilities scraper.

Pulls recent papers from NCBI PubMed via the key-less E-utilities API
(esearch + efetch) for a configured search term and maps each record into
a ContentItem so the rest of the Horizon pipeline (deduplication, AI
scoring, enrichment, summarization) treats them the same way as RSS or
Google News items.

Design notes:

* No API key is required; anonymous E-utilities access allows 3 requests
  per second, and this scraper issues exactly two sequential requests per
  fetch (one esearch, then one efetch per batch of PMIDs) with a 0.4s
  pause in between.
* The desired time window is expressed via the esearch ``reldate``
  parameter (whole days back, computed from ``since``); ``reldate`` in the
  config acts as a floor so narrow windows still return fresh records.
* ``datetype=edat`` (Entrez date) approximates "when the record first
  became searchable", which tracks new papers better than print dates.
* efetch returns PubMed XML; titles/abstracts may contain inline markup,
  so text is reassembled with ``itertext()``. Abstract sections keep
  their structural labels (e.g. "METHODS: ...") for downstream scoring.
* A record with an unparseable date is skipped, not allowed to abort the
  batch; HTTP 429/503 from NCBI is retried once after a short backoff.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from typing import Any, List, Optional

import httpx

from .base import BaseScraper
from ..models import ContentItem, PubmedSourceConfig, SourceType

logger = logging.getLogger(__name__)

_EFETCH_BATCH = 200
_MAX_AUTHORS = 6


class PubmedScraper(BaseScraper):
    """Scraper backed by the PubMed E-utilities esearch/efetch endpoints."""

    SOURCE_TYPE = SourceType.PUBMED

    def __init__(self, config: PubmedSourceConfig, http_client: httpx.AsyncClient):
        """Initialize the scraper.

        Args:
            config: PubMed source configuration.
            http_client: Shared async HTTP client.
        """
        super().__init__({"pubmed": config}, http_client)
        self.pm_config = config

    async def fetch(self, since: datetime) -> List[ContentItem]:
        """Fetch papers indexed since the given time.

        Args:
            since: Only fetch items published after this time (converted to
                an esearch ``reldate`` window; a floor of ``reldate`` days
                from the config applies).

        Returns:
            List[ContentItem]: Fetched content items.
        """
        if not self.pm_config.enabled:
            return []
        term = (self.pm_config.term or "").strip()
        if not term:
            return []

        reldate = self._effective_reldate(since)
        params: dict[str, Any] = {
            "db": "pubmed",
            "term": term,
            "reldate": reldate,
            "datetype": "edat",
            "retmode": "json",
            "retmax": self.pm_config.max_results,
        }
        if self.pm_config.email:
            params["email"] = self.pm_config.email

        try:
            search_response = await self._get(
                f"{self.pm_config.api_base}/esearch.fcgi", params
            )
            result = (search_response.json() or {}).get("esearchresult", {})
            pmids = [str(pmid) for pmid in result.get("idlist", [])]
            if not pmids:
                return []
        except Exception as exc:
            logger.warning("Error searching PubMed: %s", exc)
            return []

        items: List[ContentItem] = []
        for start in range(0, len(pmids), _EFETCH_BATCH):
            batch = pmids[start : start + _EFETCH_BATCH]
            await asyncio.sleep(0.4)
            try:
                fetch_response = await self._get(
                    f"{self.pm_config.api_base}/efetch.fcgi",
                    {"db": "pubmed", "id": ",".join(batch), "retmode": "xml"},
                )
                items.extend(self._parse_articles(fetch_response.text))
            except Exception as exc:
                logger.warning("Error fetching PubMed details: %s", exc)
                continue
        return items

    async def _get(self, url: str, params: dict[str, Any]) -> httpx.Response:
        """GET with a single retry on NCBI throttling responses."""
        response = await self.client.get(url, params=params)
        if response.status_code in (429, 503):
            await asyncio.sleep(2.0)
            response = await self.client.get(url, params=params)
        response.raise_for_status()
        return response

    def _effective_reldate(self, since: datetime) -> int:
        """Whole-day esearch window: days covering ``since``→now, at least
        the configured ``reldate`` floor."""
        since_utc = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        days = math.ceil(
            (datetime.now(timezone.utc) - since_utc).total_seconds() / 86400
        )
        return max(self.pm_config.reldate, max(1, days))

    def _parse_articles(self, xml_text: str) -> List[ContentItem]:
        """Parse an efetch XML payload into ContentItems, skipping bad rows."""
        items: List[ContentItem] = []
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as exc:
            logger.warning("Skipping invalid PubMed XML payload: %s", exc)
            return items
        for article in root.iter("PubmedArticle"):
            item = self._article_to_item(article)
            if item is not None:
                items.append(item)
        return items

    def _article_to_item(self, article: ElementTree.Element) -> Optional[ContentItem]:
        """Map one PubmedArticle element into a ContentItem.

        Returns None when the record has no PMID/title or an unparseable
        date (published_at is required), so a single bad record is skipped
        rather than aborting the batch.
        """
        try:
            citation = article.find("MedlineCitation")
            if citation is None:
                return None
            pmid_el = citation.find("PMID")
            pmid = (pmid_el.text or "").strip() if pmid_el is not None else ""
            record = citation.find("Article")
            if not pmid or record is None:
                return None

            title = self._text_of(record.find("ArticleTitle"))
            if not title:
                return None

            published = self._parse_date(record)
            if published is None:
                return None

            doi = ""
            pubmed_data = article.find("PubmedData")
            if pubmed_data is not None:
                for article_id in pubmed_data.iter("ArticleId"):
                    if article_id.get("IdType") == "doi":
                        doi = (article_id.text or "").strip()
                        break

            meta = {
                "feed_name": self.pm_config.feed_name,
                "pmid": pmid,
                "doi": doi or None,
                "journal": self._text_of(record.find("Journal/Title")) or None,
                "category": self.pm_config.category,
            }

            return ContentItem(
                id=self._generate_id("pubmed", "article", pmid),
                source_type=self.SOURCE_TYPE,
                title=title,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                content=self._abstract_of(record),
                author=self._authors_of(record),
                published_at=published,
                profile=self.pm_config.profile,
                metadata={k: v for k, v in meta.items() if v is not None},
            )
        except Exception as exc:
            logger.warning("Skipping invalid PubMed article: %s", exc)
            return None

    @staticmethod
    def _text_of(element: Optional[ElementTree.Element]) -> str:
        """Reassemble the text of an element that may contain inline markup."""
        if element is None:
            return ""
        return "".join(element.itertext()).strip()

    @staticmethod
    def _abstract_of(record: ElementTree.Element) -> Optional[str]:
        """Join abstract sections, keeping their structural labels."""
        abstract = record.find("Abstract")
        if abstract is None:
            return None
        sections: List[str] = []
        for part in abstract.findall("AbstractText"):
            label = part.get("Label")
            text = "".join(part.itertext()).strip()
            if not text:
                continue
            sections.append(f"{label}: {text}" if label else text)
        return "\n".join(sections) if sections else None

    @staticmethod
    def _authors_of(record: ElementTree.Element) -> Optional[str]:
        """Format the author list ("Last FM; ...", capped, with et al.)."""
        author_list = record.find("AuthorList")
        if author_list is None:
            return None
        names: List[str] = []
        for author in author_list.findall("Author"):
            last = PubmedScraper._text_of(author.find("LastName"))
            initials = PubmedScraper._text_of(author.find("Initials"))
            if not last:
                continue
            names.append(f"{last} {initials}".strip())
            if len(names) >= _MAX_AUTHORS:
                break
        if not names:
            return None
        total = len(author_list.findall("Author"))
        suffix = ", et al." if total > _MAX_AUTHORS else ""
        return "; ".join(names) + suffix

    @staticmethod
    def _parse_date(record: ElementTree.Element) -> Optional[datetime]:
        """Parse the article date into aware UTC.

        Prefers ArticleDate (electronic/pubmed), then Journal PubDate.
        Missing day/month default to the 1st; an unparseable record
        yields None so the caller skips it.
        """
        for path, prefer_types in (
            ("ArticleDate", ("electronic", "pubmed")),
            ("Journal/JournalIssue/PubDate", ()),
        ):
            for element in record.findall(path):
                if prefer_types and (element.get("DateType") or "") not in prefer_types:
                    continue
                parsed = PubmedScraper._date_from_parts(element)
                if parsed is not None:
                    return parsed
        return None

    @staticmethod
    def _date_from_parts(element: ElementTree.Element) -> Optional[datetime]:
        year_text = PubmedScraper._text_of(element.find("Year"))
        if not year_text.isdigit():
            return None
        year = int(year_text)
        month = PubmedScraper._month_of(PubmedScraper._text_of(element.find("Month")))
        day_text = PubmedScraper._text_of(element.find("Day"))
        day = int(day_text) if day_text.isdigit() else 1
        if day < 1 or day > 31 or month is None:
            return None
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _month_of(raw: str) -> Optional[int]:
        """Map a PubMed month ("10", "Oct", "OCT") to its number."""
        raw = raw.strip()
        if not raw:
            return 1
        if raw.isdigit():
            month = int(raw)
            return month if 1 <= month <= 12 else None
        months = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        return months.get(raw[:3].lower())
