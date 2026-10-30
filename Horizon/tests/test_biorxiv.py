from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from src.models import BiorxivSourceConfig
from src.scrapers.biorxiv import BiorxivScraper


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _record(
    doi: str,
    title: str = "Virtual cohorts for trial simulation",
    category: str = "health informatics",
    date: str = "2026-10-21",
    authors: str = "Doe J; Roe A; Smith B",
) -> dict:
    return {
        "doi": doi,
        "title": title,
        "category": category,
        "date": date,
        "authors": authors,
        "abstract": "An abstract about virtual clinical trials.",
        "server": "medrxiv",
    }


def _payload(records: list, total: int | None = None) -> dict:
    total = len(records) if total is None else total
    return {
        "messages": [{"status": "ok", "count": len(records), "total": str(total)}],
        "collection": records,
    }


def _response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _client(pages: list[dict]) -> AsyncMock:
    client = AsyncMock()
    client.get.side_effect = [_response(page) for page in pages]
    return client


def test_parses_records_into_content_items() -> None:
    client = _client([_payload([_record("10.1101/2026.10.21.000001")])])
    config = BiorxivSourceConfig(
        enabled=True,
        server="medrxiv",
        subjects=["health informatics"],
        profile="clinical-papers",
        feed_name="medRxiv｜健康信息学",
    )
    scraper = BiorxivScraper(config, client)

    items = asyncio.run(scraper.fetch(_now() - timedelta(days=2)))

    assert len(items) == 1
    item = items[0]
    assert item.id.startswith("biorxiv:article:")
    assert item.title == "Virtual cohorts for trial simulation"
    assert str(item.url) == "https://doi.org/10.1101/2026.10.21.000001"
    assert item.published_at == datetime(2026, 10, 21, tzinfo=timezone.utc)
    assert item.author == "Doe J; Roe A; Smith B"
    assert item.content == "An abstract about virtual clinical trials."
    assert item.metadata["feed_name"] == "medRxiv｜健康信息学"
    assert item.metadata["category"] == "health informatics"
    assert item.metadata["server"] == "medrxiv"
    assert item.profile == "clinical-papers"


def test_subject_whitelist_filters_records() -> None:
    records = [
        _record("10.1101/2026.10.21.000001", category="health informatics"),
        _record("10.1101/2026.10.21.000002", category="sports medicine"),
        _record("10.1101/2026.10.21.000003", category="Health Informatics"),
    ]
    client = _client([_payload(records)])
    config = BiorxivSourceConfig(
        enabled=True, server="medrxiv", subjects=["health informatics"]
    )
    scraper = BiorxivScraper(config, client)

    items = asyncio.run(scraper.fetch(_now() - timedelta(days=1)))

    assert {item.metadata["doi"] for item in items} == {
        "10.1101/2026.10.21.000001",
        "10.1101/2026.10.21.000003",  # matching is case-insensitive
    }


def test_empty_subjects_keeps_everything() -> None:
    records = [
        _record("10.1101/2026.10.21.000001", category="sports medicine"),
        _record("10.1101/2026.10.21.000002", category="genomics"),
    ]
    client = _client([_payload(records)])
    config = BiorxivSourceConfig(enabled=True, server="biorxiv", subjects=[])
    scraper = BiorxivScraper(config, client)

    assert len(asyncio.run(scraper.fetch(_now() - timedelta(days=1)))) == 2


def test_pagination_walks_offsets_in_page_steps() -> None:
    # The API cursor is a record offset; pages overlap for adjacent
    # cursors, so the scraper steps by the page size (30).
    page_one = _payload([_record(f"10.1101/x.{i}") for i in range(30)], total=45)
    page_two = _payload([_record(f"10.1101/y.{i}") for i in range(15)], total=45)
    page_three = _payload([], total=45)
    client = _client([page_one, page_two, page_three])
    config = BiorxivSourceConfig(
        enabled=True, server="medrxiv", subjects=["health informatics"]
    )
    scraper = BiorxivScraper(config, client)

    with patch("src.scrapers.biorxiv.asyncio.sleep", new=AsyncMock()):
        items = asyncio.run(scraper.fetch(_now() - timedelta(days=1)))

    assert len(items) == 45
    # 30 + 15 unique DOIs cover total=45, so the loop stops after page two.
    assert client.get.await_count == 2
    second_url = client.get.call_args_list[1].args[0]
    assert second_url.endswith("/30/json")  # cursor advanced by page size


def test_pagination_stops_on_repeat_page() -> None:
    # A page that yields no new DOIs means the interval is exhausted.
    records = [_record(f"10.1101/x.{i}") for i in range(30)]
    repeat = _payload(records, total=45)
    client = _client([_payload(records, total=45), repeat, repeat])
    config = BiorxivSourceConfig(
        enabled=True, server="medrxiv", subjects=["health informatics"]
    )
    scraper = BiorxivScraper(config, client)

    with patch("src.scrapers.biorxiv.asyncio.sleep", new=AsyncMock()):
        items = asyncio.run(scraper.fetch(_now() - timedelta(days=1)))

    assert len(items) == 30
    assert client.get.await_count == 2


def test_pagination_stops_when_total_covered() -> None:
    page_one = _payload([_record(f"10.1101/x.{i}") for i in range(30)], total=30)
    page_two = _payload([_record("10.1101/late")], total=30)
    client = _client([page_one, page_two])
    config = BiorxivSourceConfig(
        enabled=True, server="medrxiv", subjects=["health informatics"]
    )
    scraper = BiorxivScraper(config, client)

    with patch("src.scrapers.biorxiv.asyncio.sleep", new=AsyncMock()):
        items = asyncio.run(scraper.fetch(_now() - timedelta(days=1)))

    assert len(items) == 30
    assert client.get.await_count == 1  # total=30 covered by the first page


def test_max_results_caps_filtered_items() -> None:
    records = [_record(f"10.1101/x.{i}") for i in range(10)]
    client = _client([_payload(records)])
    config = BiorxivSourceConfig(
        enabled=True, server="medrxiv", subjects=["health informatics"], max_results=3
    )
    scraper = BiorxivScraper(config, client)

    assert len(asyncio.run(scraper.fetch(_now() - timedelta(days=1)))) == 3


def test_bad_date_or_missing_fields_skipped() -> None:
    records = [
        _record("10.1101/2026.10.21.000001", date="not-a-date"),
        _record("", title="No DOI paper"),
        _record("10.1101/2026.10.21.000003", title=""),
    ]
    client = _client([_payload(records)])
    config = BiorxivSourceConfig(
        enabled=True, server="medrxiv", subjects=["health informatics"]
    )
    scraper = BiorxivScraper(config, client)

    assert asyncio.run(scraper.fetch(_now() - timedelta(days=1))) == []


def test_invalid_server_returns_empty() -> None:
    client = _client([_payload([_record("10.1101/x")])])
    config = BiorxivSourceConfig(enabled=True, server="chemrxiv")
    scraper = BiorxivScraper(config, client)

    assert asyncio.run(scraper.fetch(_now() - timedelta(days=1))) == []
    client.get.assert_not_called()


def test_disabled_returns_empty() -> None:
    client = _client([_payload([_record("10.1101/x")])])
    config = BiorxivSourceConfig(enabled=False, server="medrxiv")
    scraper = BiorxivScraper(config, client)

    assert asyncio.run(scraper.fetch(_now())) == []


def test_http_error_returns_collected_items() -> None:
    ok_page = _payload([_record("10.1101/a")], total=60)
    client = AsyncMock()
    client.get.side_effect = [_response(ok_page), httpx.HTTPError("boom")]
    config = BiorxivSourceConfig(
        enabled=True, server="medrxiv", subjects=["health informatics"]
    )
    scraper = BiorxivScraper(config, client)

    with patch("src.scrapers.biorxiv.asyncio.sleep", new=AsyncMock()):
        items = asyncio.run(scraper.fetch(_now() - timedelta(days=1)))

    # First page's match survives; the failed follow-up page ends the loop.
    assert len(items) == 1


def test_revised_versions_dedup_by_doi() -> None:
    records = [
        _record("10.1101/2026.10.21.000001", title="Virtual cohorts (v1)"),
        _record("10.1101/2026.10.21.000002", title="Other paper"),
        _record("10.1101/2026.10.21.000001", title="Virtual cohorts (v2)"),
    ]
    client = _client([_payload(records)])
    config = BiorxivSourceConfig(
        enabled=True, server="medrxiv", subjects=["health informatics"]
    )
    scraper = BiorxivScraper(config, client)

    items = asyncio.run(scraper.fetch(_now() - timedelta(days=1)))

    assert len(items) == 2
    by_doi = {item.metadata["doi"]: item for item in items}
    assert by_doi["10.1101/2026.10.21.000001"].title == "Virtual cohorts (v2)"


def test_long_author_list_is_capped() -> None:
    authors = "; ".join(f"Author{i} A" for i in range(10))
    client = _client([_payload([_record("10.1101/a", authors=authors)])])
    config = BiorxivSourceConfig(
        enabled=True, server="medrxiv", subjects=["health informatics"]
    )
    scraper = BiorxivScraper(config, client)

    items = asyncio.run(scraper.fetch(_now() - timedelta(days=1)))
    assert items[0].author.endswith(", et al.")
    assert items[0].author.count(";") == 5
