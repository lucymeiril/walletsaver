"""One normal public Ruliweb feed, with explicit title quotes kept as observations."""
from __future__ import annotations
import asyncio
import json
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from core.models import CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus, HotdealPost
from crawlers.hotdeals.algumon.crawler import AlgumonCrawler
from crawlers.hotdeals.common import apply_source_facts, dedupe_hotdeal_posts


class RuliwebCrawler(AlgumonCrawler):
    SOURCE_ID = 'ruliweb'
    DEAL_URL = 'https://bbs.ruliweb.com/market/board/1020'
    BASE_URL = 'https://bbs.ruliweb.com'

    @property
    def info(self):
        return CrawlerInfo(name='루리웹', version='1.0', group=CrawlerGroup.HOTDEAL,
            description='단일 정상 공개 목록의 원문 표시가; 결제·회원·옵션은 별도 미확인',
            target_url=self.DEAL_URL, strategies=['requests'])

    @staticmethod
    def business_nodes(html: str) -> list[dict]:
        soup = BeautifulSoup(html, 'html.parser')
        nodes = []
        seen = set()
        for row in soup.select('tr'):
            identity = row.select_one('td.id')
            anchor = row.select_one('td.subject a.subject_link[href]')
            if identity is None or anchor is None:
                continue
            url = str(anchor.get('href') or '')
            match = re.fullmatch(r'https://bbs\.ruliweb\.com/market/board/1020/read/(\d+)(?:[?#].*)?', url)
            if not match:
                continue
            native = match.group(1)
            cell_native = identity.get_text(strip=True)
            if native in seen or (cell_native.isdigit() and cell_native != native):
                continue
            expected = f'https://bbs.ruliweb.com/market/board/1020/read/{native}'
            if url.split('?', 1)[0].split('#', 1)[0] != expected:
                continue
            copy = BeautifulSoup(str(anchor), 'html.parser')
            for ignored in copy.select('.num_reply, script, style'):
                ignored.decompose()
            content = copy.select_one('strong') or copy
            title = content.get_text(' ', strip=True)
            for reply in row.select('.num_reply'):
                suffix = reply.get_text(' ', strip=True)
                if suffix and title.endswith(suffix):
                    title = title[:-len(suffix)].rstrip()
            if len(title) < 3:
                continue
            seen.add(native)
            nodes.append({'native_id': native, 'url': expected, 'title': title,
                'title_anchor_html': str(copy),
                'category_text': (row.select_one('td.divsn').get_text(' ', strip=True) if row.select_one('td.divsn') else ''),
                'closed_explicit': '[종료]' in row.select_one('td.subject').get_text(' ', strip=True),
                'post_time_text': (row.select_one('td.time').get_text(' ', strip=True) if row.select_one('td.time') else '')})
            if len(nodes) == 25:
                break
        return nodes

    @staticmethod
    def parse_nodes(nodes: list[dict], received_at: datetime) -> list[HotdealPost]:
        items = []
        for node in nodes:
            title = node['title']
            matches = re.findall(r'(?<![\d,])([1-9][\d,]*)\s*원', title)
            complete = '...' not in title and '…' not in title
            price = int(matches[0].replace(',', '')) if complete and len(matches) == 1 else None
            # An incomplete title or currency-free number is not a confirmed quote.
            if price is None:
                continue
            shop = re.match(r'^\[([^\]]+)\]', title)
            tags = ['source_label:루리웹', 'currency:KRW', 'price_basis:community_quote',
                'condition:커뮤니티 원문 표시가이며 판매처 결제 금액·회원·쿠폰·배송·옵션·현재 재고는 미확인']
            if node.get('closed_explicit'):
                tags.extend(['source_closed:true', 'condition:원문 종료 표시 — 현재 구매행사로 해석하지 않음'])
            if node.get('post_time_text'):
                tags.append('condition:원문 게시시간 ' + node['post_time_text'] + ' (명시 날짜·시간대는 별도 확인)')
            item = HotdealPost(title=title, url=node['url'], source_community='루리웹',
                source_native_id='ruliweb:' + node['native_id'], price=price,
                price_evidence=matches[0] + '원', category=node.get('category_text', ''),
                crawled_at=received_at, tags=tags)
            items.append(apply_source_facts(item, source_id='ruliweb'))
        return dedupe_hotdeal_posts(items)

    def crawl_list(self, html=None):
        if html is None:
            raise ValueError("Ruliweb requires genuine supplied source HTML; no offline fallback")
        return self.parse_nodes(self.business_nodes(html), datetime.now(timezone.utc))

    async def parse(self, raw_data):
        return self.parse_nodes(self.business_nodes(raw_data), datetime.now(timezone.utc))

    async def crawl(self):
        started = datetime.now(timezone.utc)
        capture, nodes, items = {}, [], []
        reason = None
        try:
            capture, body = await asyncio.to_thread(self._fetch_source_once)
            if capture['status_code'] != 200:
                reason = 'http_access_denied' if capture['status_code'] in {401, 403, 429} else 'nonproduct_response'
            elif not capture['body_capture_complete']:
                reason = 'response_capture_incomplete'
            elif capture['content_type'] not in {'text/html', 'application/xhtml+xml'}:
                reason = 'unsupported_content_type'
            else:
                html = body.decode('utf-8', errors='replace')
                visible = BeautifulSoup(html, 'html.parser').get_text(' ', strip=True).lower()
                if any(marker in visible for marker in ['verify you are human', 'complete the captcha', 'access denied', '접근이 차단']):
                    reason = 'visible_access_challenge'
                else:
                    nodes = self.business_nodes(html)
                    received = datetime.fromisoformat(capture['source_response_received_at'])
                    items = self.parse_nodes(nodes, received)
                    if not items:
                        reason = 'no_explicit_source_quotes'
        except Exception as exc:
            reason = 'transport_unavailable'
            capture['failure_type'] = type(exc).__name__
        finished = datetime.now(timezone.utc)
        return CrawlResult(status=CrawlStatus.SUCCESS if items else CrawlStatus.FAILED,
            crawler_name=self.info.name, strategy_used='requests', items_count=len(items), items=items,
            started_at=started, finished_at=finished, duration_seconds=(finished-started).total_seconds(),
            error_msg=reason, quality_details={'fetch': capture, 'source_stopped': not bool(items),
                'source_stop_reason': reason, 'fixture_fallback': False,
                'source_nodes': len(nodes), 'quotes': len(items), 'unresolved_quotes': len(nodes)-len(items)},
            raw_data=json.dumps({'fetch': capture, 'source_business_nodes': nodes}, ensure_ascii=False))

# Registry resolves this explicit class before imported base classes.
Crawler = RuliwebCrawler
