"""Registry contracts for the current explicit crawler allowlist."""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import threading
from datetime import datetime

import pytest

from crawlers.registry.registry import CrawlerRegistry
from crawlers.hotdeals.algumon.crawler import AlgumonCrawler


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,status,expected', [
    ('placeholder', 200, 'offline_fixture_body'),
    ('fixture_json', 200, 'offline_fixture_body'),
    ('legacy_offline', 200, 'unsupported_live_body'),
    ('sdk_only', 200, 'unsupported_live_body'),
    ('visible_challenge', 200, 'visible_access_challenge'),
    ('empty', 200, 'unsupported_live_body'),
    ('ordinary', 401, 'http_access_denied'),
    ('ordinary', 403, 'http_access_denied'),
    ('ordinary', 429, 'http_access_denied'),
    ('sdk_only', 202, 'nonproduct_response'),
    ('non_html', 200, 'unsupported_content_type'),
    ('over_limit', 200, 'response_capture_limit'),
])
async def test_algumon_normal_transport_never_promotes_offline_or_unverified_rows(monkeypatch, kind, status, expected):
    import requests
    crawler = AlgumonCrawler()
    bodies = {
        'placeholder': crawler.FIXTURE_PATH.read_bytes(),
        'fixture_json': b'<script type="application/json" data-fixture="algumon-list">{"items":[{"title":"PRIVATE"}]}</script>',
        'legacy_offline': b'<div class="deal-card-content"><a href="/l/d/100001">Offline sample item</a><span class="deal-price-text">79000</span></div>',
        'sdk_only': b'<script>awsWafCookieDomainList=[];captchaSDK={token:"PRIVATE"};</script><body>public shell</body>',
        'visible_challenge': b'<body>Verify you are human</body>',
        'empty': b'', 'ordinary': b'public response', 'non_html': b'{"items":[]}',
        'over_limit': b'<body>' + b'x' * 80 + b'</body>',
    }
    body = bodies[kind]
    calls, closures = [], []
    main_thread = threading.get_ident()
    response_url = crawler.DEAL_URL + '?page=1'
    class Response:
        status_code, url = status, response_url
        headers = {'Content-Type': 'application/json' if kind == 'non_html' else 'text/html; charset=utf-8'}
        def iter_content(self, chunk_size):
            assert chunk_size == 65536
            yield body
        def close(self): closures.append('response')
    original_close = requests.Session.close
    def close(session):
        closures.append('session')
        original_close(session)
    def get(session, url, **kwargs):
        assert threading.get_ident() != main_thread
        assert session.trust_env is True and session.verify is True
        assert callable(session.auth)  # No implicit provider netrc credentials.
        assert kwargs == {'timeout': (5, 10), 'allow_redirects': False, 'stream': True}
        calls.append(url)
        return Response()
    def no_offline_parser(*_args, **_kwargs):
        raise AssertionError('Normal HTTP must never call fixture/legacy parser helpers')
    monkeypatch.setattr(requests.Session, 'get', get)
    monkeypatch.setattr(requests.Session, 'close', close)
    monkeypatch.setattr(crawler, '_load_fixture_html', no_offline_parser)
    monkeypatch.setattr(crawler, 'parse_list_html', no_offline_parser)
    if kind == 'over_limit':
        monkeypatch.setattr(crawler, 'MAX_RESPONSE_BYTES', 32)
    result = await crawler.crawl()
    assert calls == [crawler.DEAL_URL] and closures == ['response', 'session']
    assert result.status.name == 'FAILED' and result.items == [] and result.items_count == 0
    assert result.strategy_used == 'requests' and result.error_msg == expected
    quality = result.quality_details
    assert quality['source_stopped'] is True and quality['source_stop_status'] == status
    assert quality['source_stop_reason'] == expected and quality['fixture_fallback'] is False
    assert quality['live_parser_verified'] is False
    capture = quality['fetch']
    assert capture['response_url'] == response_url and capture['request_url'] == crawler.DEAL_URL
    assert datetime.fromisoformat(capture['source_response_received_at']).tzinfo is not None
    assert capture['http_receipt_status'] == 'received_response'
    assert capture['body_capture_complete'] == (kind != 'over_limit')
    assert capture['body_sha256'] == (None if kind == 'over_limit' else hashlib.sha256(body).hexdigest())
    assert capture['raw_body_retained'] is False
    diagnostic = json.loads(result.raw_data)
    assert diagnostic['diagnostic_kind'] == 'algumon_transport_only'
    assert diagnostic['fetch'] == capture
    assert 'PRIVATE' not in result.raw_data and 'Offline sample item' not in result.raw_data


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['before_response', 'during_body'])
async def test_algumon_single_transport_failure_closes_without_fallback_or_secret_error(monkeypatch, stage):
    import requests
    calls, closures = [], []
    class Response:
        status_code, url, headers = 200, AlgumonCrawler.DEAL_URL, {'Content-Type': 'text/html'}
        def iter_content(self, chunk_size):
            raise requests.Timeout('PRIVATE proxy credentials or response token')
            yield b''
        def close(self): closures.append('response')
    def get(session, url, **kwargs):
        calls.append(url)
        if stage == 'before_response':
            raise requests.ConnectionError('PRIVATE proxy credentials')
        return Response()
    original_close = requests.Session.close
    def close(session):
        closures.append('session')
        original_close(session)
    monkeypatch.setattr(requests.Session, 'get', get)
    monkeypatch.setattr(requests.Session, 'close', close)
    result = await AlgumonCrawler().crawl()
    assert calls == [AlgumonCrawler.DEAL_URL] and closures[-1] == 'session'
    assert len(closures) == (1 if stage == 'before_response' else 2)
    assert result.items == [] and result.status.name == 'FAILED'
    assert result.quality_details['source_stopped'] is True
    assert result.error_msg == ('transport_unavailable' if stage == 'before_response' else 'response_body_unavailable')
    capture = result.quality_details['fetch']
    assert capture['failure_type'] == ('ConnectionError' if stage == 'before_response' else 'Timeout')
    assert capture['http_receipt_status'] == ('not_recorded' if stage == 'before_response' else 'received_response')
    if stage == 'during_body':
        assert datetime.fromisoformat(capture['source_response_received_at']).tzinfo is not None
        assert capture['body_sha256'] is None and capture['body_capture_complete'] is False
    assert 'PRIVATE' not in result.model_dump_json()


def test_algumon_explicit_fixture_helpers_stay_offline_and_do_not_fetch(monkeypatch):
    import requests
    monkeypatch.setattr(requests.Session, 'get', lambda *_args, **_kwargs: pytest.fail('offline parser fetched provider'))
    crawler = AlgumonCrawler()
    records = crawler.crawl_list()
    assert records and all(record.source_site == 'algumon' for record in records)
    # Offline construction clocks remain the legacy parser contract; they are
    # not an actual response receipt and never enter normal crawl() output.
    def source_facts(records):
        return [{key: value for key, value in record.model_dump(mode='json').items()
                 if key != 'fetched_at'} for record in records]
    assert source_facts(records) == source_facts(crawler.parse_list_html(crawler.FIXTURE_PATH.read_text()))


def test_default_registry_contains_only_four_core_marts(monkeypatch):
    monkeypatch.delenv("WALLETSAVIOR_OPTIONAL_CRAWLERS", raising=False)
    registry = CrawlerRegistry()
    registry.discover()

    names = {row["name"] for row in registry.list_crawlers()}
    assert names == {"emart", "homeplus", "lottemart", "costco"}
    assert {row["category"] for row in registry.list_crawlers()} == {"mart"}


def test_optional_crawlers_are_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("WALLETSAVIOR_OPTIONAL_CRAWLERS", "musinsa,algumon")
    registry = CrawlerRegistry()
    registry.discover()

    names = {row["name"] for row in registry.list_crawlers()}
    assert names == {"emart", "homeplus", "lottemart", "costco", "musinsa", "algumon"}

    config = registry._registry["algumon"]["config"]
    assert config["output"]["model"] == "HotdealPost"
    assert config["schedule"]["cron"] == "manual"


def test_plugin_yaml_files_do_not_create_runtime_crawlers(tmp_path, monkeypatch):
    monkeypatch.delenv("WALLETSAVIOR_OPTIONAL_CRAWLERS", raising=False)
    ghost = tmp_path / "delivery" / "ghost"
    ghost.mkdir(parents=True)
    (ghost / "plugin.yaml").write_text(
        "name: ghost\ndisplay_name: Ghost\ncategory: delivery\n",
        encoding="utf-8",
    )

    registry = CrawlerRegistry(crawlers_dir=Path(tmp_path))
    registry.discover()

    assert "ghost" not in registry._registry
    assert {row["name"] for row in registry.list_crawlers()} == {
        "emart",
        "homeplus",
        "lottemart",
        "costco",
    }


def test_unknown_optional_name_is_ignored(monkeypatch):
    monkeypatch.setenv("WALLETSAVIOR_OPTIONAL_CRAWLERS", "ghost,musinsa")
    registry = CrawlerRegistry()
    registry.discover()

    assert "ghost" not in registry._registry
    assert "musinsa" in registry._registry
