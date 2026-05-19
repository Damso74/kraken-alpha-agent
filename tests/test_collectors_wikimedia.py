"""Hermetic tests for :mod:`src.data.collectors.wikimedia`."""



from __future__ import annotations



import json
from datetime import date, datetime, timezone

from pathlib import Path

from unittest.mock import MagicMock, patch



import httpx

import pytest



from src.data.collectors.wikimedia import (

    CollectorError,

    DEFAULT_WIKIMEDIA_USER_AGENT,

    WIKIMEDIA_USER_AGENT_ENV,

    build_pageviews_url,

    default_pageviews_fetcher,

    fetch_pageviews,

    parse_pageviews_payload,

    resolve_wikimedia_user_agent,

    wikimedia_http_get_json,

    wikimedia_request_headers,

)





def _ts(d: date) -> int:

    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())





PAGEVIEWS_FIXTURE = {

    "items": [

        {

            "project": "en.wikipedia",

            "article": "Bitcoin",

            "timestamp": "2026051700",

            "views": 12000,

        },

        {

            "project": "en.wikipedia",

            "article": "Bitcoin",

            "timestamp": "2026051800",

            "views": 15000,

        },

        {"timestamp": "bad", "views": 1},

    ]

}





def test_build_pageviews_url_encodes_article() -> None:

    url = build_pageviews_url(

        article="Bitcoin Cash",

        start=date(2026, 5, 17),

        end=date(2026, 5, 18),

    )

    assert "Bitcoin_Cash" in url

    assert "2026051700" in url

    assert "2026051823" in url





def test_parse_pageviews_payload() -> None:

    rows = parse_pageviews_payload(

        PAGEVIEWS_FIXTURE, project="en.wikipedia", article="Bitcoin"

    )

    assert len(rows) == 2

    assert rows[0]["views"] == 12000

    assert rows[0]["timestamp"] == _ts(date(2026, 5, 17))

    assert rows[1]["date"] == "2026-05-18"





def test_parse_pageviews_payload_rejects_bad_shape() -> None:

    with pytest.raises(CollectorError):

        parse_pageviews_payload([], project="en.wikipedia", article="Bitcoin")





def test_resolve_wikimedia_user_agent_default(monkeypatch: pytest.MonkeyPatch) -> None:

    monkeypatch.delenv(WIKIMEDIA_USER_AGENT_ENV, raising=False)

    assert resolve_wikimedia_user_agent() == DEFAULT_WIKIMEDIA_USER_AGENT





def test_resolve_wikimedia_user_agent_from_env(monkeypatch: pytest.MonkeyPatch) -> None:

    monkeypatch.setenv(WIKIMEDIA_USER_AGENT_ENV, "CustomBot/2.0 (test@example.com)")

    assert resolve_wikimedia_user_agent() == "CustomBot/2.0 (test@example.com)"





def test_wikimedia_request_headers_include_user_agent(

    monkeypatch: pytest.MonkeyPatch,

) -> None:

    monkeypatch.setenv(WIKIMEDIA_USER_AGENT_ENV, "HdrTest/1.0")

    headers = wikimedia_request_headers()

    assert headers["User-Agent"] == "HdrTest/1.0"

    assert headers["Accept"] == "application/json"





@patch("src.data.collectors.wikimedia.httpx.get")

def test_wikimedia_http_get_json_sends_user_agent(mock_get: MagicMock) -> None:

    mock_resp = MagicMock()

    mock_resp.status_code = 200

    mock_resp.json.return_value = PAGEVIEWS_FIXTURE

    mock_get.return_value = mock_resp



    out = wikimedia_http_get_json("https://wikimedia.org/api/rest_v1/test")

    assert out == PAGEVIEWS_FIXTURE

    mock_get.assert_called_once()

    _url, kwargs = mock_get.call_args

    assert kwargs["headers"]["User-Agent"] == DEFAULT_WIKIMEDIA_USER_AGENT

    assert kwargs["timeout"] == 20.0





@patch("src.data.collectors.wikimedia.httpx.get")

def test_wikimedia_http_get_json_403_clear_error(mock_get: MagicMock) -> None:

    mock_resp = MagicMock()

    mock_resp.status_code = 403

    mock_resp.text = "Please set a user-agent"

    mock_get.return_value = mock_resp



    with pytest.raises(CollectorError, match="403") as exc_info:

        wikimedia_http_get_json("https://wikimedia.org/api/rest_v1/forbidden")

    assert WIKIMEDIA_USER_AGENT_ENV in str(exc_info.value)

    assert "User-Agent" in str(exc_info.value)





@patch("src.data.collectors.wikimedia.httpx.get")

def test_wikimedia_http_get_json_retries_503(mock_get: MagicMock) -> None:

    ok = MagicMock()

    ok.status_code = 200

    ok.json.return_value = {"items": []}

    fail = MagicMock()

    fail.status_code = 503

    fail.text = "unavailable"

    mock_get.side_effect = [fail, ok]



    with patch("src.data.collectors.wikimedia.time.sleep"):

        out = wikimedia_http_get_json("https://wikimedia.org/api/rest_v1/retry")

    assert out == {"items": []}

    assert mock_get.call_count == 2





@patch("src.data.collectors.wikimedia.wikimedia_http_get_json")

def test_default_pageviews_fetcher_delegates(mock_http: MagicMock) -> None:

    mock_http.return_value = PAGEVIEWS_FIXTURE

    payload = default_pageviews_fetcher(

        "en.wikipedia",

        "Bitcoin",

        "all-access",

        "all-agents",

        "2026-05-17",

        "2026-05-18",

    )

    assert payload == PAGEVIEWS_FIXTURE

    mock_http.assert_called_once()

    url = mock_http.call_args[0][0]

    assert "Bitcoin" in url

    assert "2026051700" in url





def test_fetch_pageviews_cache_hit(tmp_path: Path) -> None:

    cache_path = tmp_path / "wiki.json"

    parsed = parse_pageviews_payload(

        PAGEVIEWS_FIXTURE, project="en.wikipedia", article="Bitcoin"

    )

    cache_path.write_text(

        json.dumps(

            {

                "entries": {

                    "pageviews_en.wikipedia_Bitcoin": parsed,

                }

            }

        ),

        encoding="utf-8",

    )



    def explode(*_a: object, **_k: object) -> dict:

        raise AssertionError("fetcher must not run on cache hit")



    rows = fetch_pageviews(

        "Bitcoin",

        "2026-05-17",

        "2026-05-18",

        cache_path=cache_path,

        fetcher=explode,

    )

    assert len(rows) == 2





def test_fetch_pageviews_multi_article_cache_keys(tmp_path: Path) -> None:
    """Distinct articles share one cache file under separate entry keys."""
    cache_path = tmp_path / "wiki.json"
    btc = parse_pageviews_payload(
        PAGEVIEWS_FIXTURE, project="en.wikipedia", article="Bitcoin"
    )
    eth_fixture = {
        "items": [
            {
                "timestamp": "2026051700",
                "views": 900,
            }
        ]
    }
    eth = parse_pageviews_payload(
        eth_fixture, project="en.wikipedia", article="Ethereum"
    )
    cache_path.write_text(
        json.dumps(
            {
                "entries": {
                    "pageviews_en.wikipedia_Bitcoin": btc,
                    "pageviews_en.wikipedia_Ethereum": eth,
                }
            }
        ),
        encoding="utf-8",
    )

    def explode(*_a: object, **_k: object) -> dict:
        raise AssertionError("fetcher must not run on cache hit")

    btc_rows = fetch_pageviews(
        "Bitcoin",
        "2026-05-17",
        "2026-05-18",
        cache_path=cache_path,
        fetcher=explode,
    )
    eth_rows = fetch_pageviews(
        "Ethereum",
        "2026-05-17",
        "2026-05-17",
        cache_path=cache_path,
        fetcher=explode,
    )
    assert len(btc_rows) == 2
    assert len(eth_rows) == 1
    assert eth_rows[0]["views"] == 900


def test_fetch_pageviews_cache_miss(tmp_path: Path) -> None:

    cache_path = tmp_path / "wiki.json"



    def fake_fetcher(

        project: str,

        article: str,

        access: str,

        agent: str,

        start_iso: str,

        end_iso: str,

    ) -> dict:

        assert project == "en.wikipedia"

        assert article == "Bitcoin"

        return PAGEVIEWS_FIXTURE



    rows = fetch_pageviews(

        "Bitcoin",

        "2026-05-17",

        "2026-05-18",

        cache_path=cache_path,

        fetcher=fake_fetcher,

    )

    assert len(rows) == 2

    assert cache_path.exists()

