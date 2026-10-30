from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx

from src.models import PubmedSourceConfig
from src.scrapers.pubmed import PubmedScraper


def _now() -> datetime:
    return datetime.now(timezone.utc)


_ESEARCH_JSON = {"esearchresult": {"idlist": ["111", "222"]}}


_EFETCH_XML = """<?xml version="1.0"?>
<!DOCTYPE PubmedArticleSet>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>111</PMID>
      <Article>
        <Journal><Title>Trials</Title></Journal>
        <ArticleTitle>Digital twins for <i>clinical trials</i></ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">We study virtual patients.</AbstractText>
          <AbstractText Label="METHODS">Simulation on synthetic cohorts.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><LastName>Doe</LastName><Initials>J</Initials></Author>
          <Author><LastName>Roe</LastName><Initials>A</Initials></Author>
        </AuthorList>
        <ArticleDate DateType="electronic">
          <Year>2026</Year><Month>10</Month><Day>21</Day>
        </ArticleDate>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList><ArticleId IdType="doi">10.1186/s111-026-00001-1</ArticleId></ArticleIdList>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>222</PMID>
      <Article>
        <Journal><Title>JAMA</Title></Journal>
        <ArticleTitle>Unparseable date paper</ArticleTitle>
        <ArticleDate DateType="electronic">
          <Year>2026</Year><Month>Spring</Month><Day>2</Day>
        </ArticleDate>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


def _client(search_json=None, fetch_xml: str = _EFETCH_XML) -> AsyncMock:
    """Client whose GET dispatches on the eutils endpoint."""
    search_json = _ESEARCH_JSON if search_json is None else search_json
    search_response = MagicMock()
    search_response.status_code = 200
    search_response.json.return_value = search_json
    search_response.raise_for_status.return_value = None
    fetch_response = MagicMock()
    fetch_response.status_code = 200
    fetch_response.text = fetch_xml
    fetch_response.raise_for_status.return_value = None
    client = AsyncMock()

    async def get(url, params=None):
        if url.endswith("esearch.fcgi"):
            return search_response
        return fetch_response

    client.get.side_effect = get
    return client


def test_parses_records_into_content_items() -> None:
    client = _client()
    config = PubmedSourceConfig(
        enabled=True,
        term="digital twin",
        profile="clinical-papers",
        feed_name="PubMed｜AI临床试验检索",
        category="journal-pubmed",
    )
    scraper = PubmedScraper(config, client)

    items = asyncio.run(scraper.fetch(_now() - timedelta(days=2)))

    assert len(items) == 1  # the unparseable-date record is skipped
    item = items[0]
    assert item.id == "pubmed:article:111"
    assert item.title == "Digital twins for clinical trials"
    assert str(item.url) == "https://pubmed.ncbi.nlm.nih.gov/111/"
    assert item.published_at == datetime(2026, 10, 21, tzinfo=timezone.utc)
    assert item.metadata["feed_name"] == "PubMed｜AI临床试验检索"
    assert item.metadata["journal"] == "Trials"
    assert item.metadata["doi"] == "10.1186/s111-026-00001-1"
    assert item.metadata["pmid"] == "111"
    assert "BACKGROUND: We study virtual patients." in item.content
    assert "METHODS: Simulation on synthetic cohorts." in item.content
    assert item.author == "Doe J; Roe A"
    assert item.profile == "clinical-papers"


def test_reldate_grows_with_window() -> None:
    client = _client()
    config = PubmedSourceConfig(enabled=True, term="ai", reldate=3)
    scraper = PubmedScraper(config, client)

    asyncio.run(scraper.fetch(_now() - timedelta(days=5)))

    params = client.get.call_args_list[0].kwargs["params"]
    assert params["reldate"] >= 5
    assert params["datetype"] == "edat"
    assert params["retmode"] == "json"
    assert params["db"] == "pubmed"


def test_reldate_floor_applies_for_narrow_window() -> None:
    client = _client()
    config = PubmedSourceConfig(enabled=True, term="ai", reldate=3)
    scraper = PubmedScraper(config, client)

    asyncio.run(scraper.fetch(_now() - timedelta(hours=6)))

    params = client.get.call_args_list[0].kwargs["params"]
    assert params["reldate"] == 3


def test_efetch_batches_pmids() -> None:
    pmids = [str(1000 + i) for i in range(250)]
    client = _client(search_json={"esearchresult": {"idlist": pmids}})
    config = PubmedSourceConfig(enabled=True, term="ai")
    scraper = PubmedScraper(config, client)

    asyncio.run(scraper.fetch(_now() - timedelta(days=1)))

    efetch_calls = [
        call for call in client.get.call_args_list
        if call.args[0].endswith("efetch.fcgi")
    ]
    assert len(efetch_calls) == 2  # 200 + 50
    first_ids = efetch_calls[0].kwargs["params"]["id"].split(",")
    assert len(first_ids) == 200
    assert efetch_calls[1].kwargs["params"]["id"].split(",")[0] == "1200"


def test_disabled_or_empty_term_returns_empty() -> None:
    client = _client()
    scraper = PubmedScraper(PubmedSourceConfig(enabled=False, term="ai"), client)
    assert asyncio.run(scraper.fetch(_now())) == []

    client = _client()
    scraper = PubmedScraper(PubmedSourceConfig(enabled=True, term="  "), client)
    assert asyncio.run(scraper.fetch(_now())) == []
    client.get.assert_not_called()


def test_empty_idlist_returns_empty() -> None:
    client = _client(search_json={"esearchresult": {"idlist": []}})
    scraper = PubmedScraper(PubmedSourceConfig(enabled=True, term="ai"), client)

    assert asyncio.run(scraper.fetch(_now() - timedelta(days=1))) == []


def test_http_error_returns_empty() -> None:
    client = AsyncMock()
    client.get.side_effect = httpx.HTTPError("boom")
    scraper = PubmedScraper(PubmedSourceConfig(enabled=True, term="ai"), client)

    assert asyncio.run(scraper.fetch(_now() - timedelta(days=1))) == []


def test_throttled_response_is_retried_once() -> None:
    throttled = MagicMock()
    throttled.status_code = 429
    ok_search = MagicMock()
    ok_search.status_code = 200
    ok_search.json.return_value = {"esearchresult": {"idlist": []}}
    ok_search.raise_for_status.return_value = None

    client = AsyncMock()
    client.get.side_effect = [throttled, ok_search]
    scraper = PubmedScraper(PubmedSourceConfig(enabled=True, term="ai"), client)

    assert asyncio.run(scraper.fetch(_now() - timedelta(days=1))) == []
    assert client.get.await_count == 2
