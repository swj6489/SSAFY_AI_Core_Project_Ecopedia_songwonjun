import json
import os
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .errors import ConfigurationError, SourceError


def now():
    return datetime.now(timezone.utc).isoformat()


class SourceCache:
    """성공적으로 저장한 수집 결과를 만료 없이 재사용하는 영속 캐시."""

    def __init__(self, settings):
        settings.runtime.mkdir(parents=True, exist_ok=True)
        self.path = settings.runtime / 'source-cache.sqlite3'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)')

    def get(self, key):
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute('SELECT payload FROM cache WHERE key=?', (key,)).fetchone()
        if row is not None:
            return json.loads(row[0])
        return None

    def put(self, key, payload):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',
                       (key, json.dumps(payload, ensure_ascii=False), now()))

    def documents(self, species_id):
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute('SELECT payload FROM cache WHERE key LIKE ?', (f'doc:{species_id}:%',)).fetchall()
        # Rechunk saved source bodies locally without making external collection requests.
        return [json.loads(row[0]) for row in rows]


class WikipediaSource:
    api = 'https://ko.wikipedia.org/w/api.php'
    language = 'ko'

    def __init__(self, settings):
        agent = os.getenv('WIKIMEDIA_USER_AGENT', '').strip()
        if not agent or not re.search(r'@|https?://', agent):
            raise ConfigurationError('외부 수집을 위해 .env의 WIKIMEDIA_USER_AGENT에 프로젝트명과 실제 연락처를 설정해 주세요.')
        self.settings = settings
        self.session = requests.Session()
        self.session.headers['User-Agent'] = agent
        retry = Retry(total=3, backoff_factor=1, status_forcelist=(429,500,502,503,504),
                      allowed_methods=('GET',), respect_retry_after_header=True)
        self.session.mount('https://', HTTPAdapter(max_retries=retry))
        self.last_request = 0.0

    def request(self, **parameters):
        wait = self.settings.request_interval_seconds - (time.monotonic()-self.last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            self.last_request = time.monotonic()
            response = self.session.get(self.api, params={'format': 'json', 'formatversion': 2,
                'maxlag': 5, **parameters}, timeout=self.settings.request_timeout_seconds)
            response.raise_for_status()
            payload = response.json()
            if 'error' in payload:
                raise SourceError('문서 제공 서버가 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.')
            return payload
        except (requests.RequestException, ValueError) as exc:
            raise SourceError('외부 문서 연결에 실패했습니다. 네트워크와 호출 설정을 확인해 주세요.') from exc

    @classmethod
    def candidate(cls, page):
        if 'missing' in page or page.get('ns', 0) != 0 or page.get('pageprops', {}).get('disambiguation') is not None:
            return None
        title = page['title']
        return {'document_id': f"{cls.language}-wiki-{page['pageid']}", 'page_id': page['pageid'],
                'title': title, 'summary': page.get('extract', '')[:1500],
                'url': f'https://{cls.language}.wikipedia.org/wiki/' + quote(title.replace(' ', '_'))}

    def subject(self, species):
        payload = self.request(action='query', titles=species.korean_name, redirects=1,
                               prop='extracts|pageprops', exintro=1, explaintext=1)
        pages = payload.get('query', {}).get('pages', [])
        for page in pages:
            candidate = self.candidate(page)
            if not candidate:
                continue
            # Do not trust a redirect to a broader taxon without the supplied scientific name.
            if page['title'] == species.korean_name or species.scientific_name.casefold() in candidate['summary'].casefold():
                return candidate
        return None

    def search(self, query):
        payload = self.request(action='query', list='search', srsearch=query, srnamespace=0, srlimit=8)
        hits = payload.get('query', {}).get('search', [])
        return [{'document_id': f"{self.language}-wiki-{h['pageid']}", 'page_id': h['pageid'],
                 'title': h['title'], 'summary': re.sub('<[^>]*>', '', h.get('snippet', '')),
                 'url': f'https://{self.language}.wikipedia.org/wiki/' + quote(h['title'].replace(' ', '_'))}
                for h in hits]

    def fetch(self, candidate, query):
        payload = self.request(action='query', pageids=candidate['page_id'],
                              prop='extracts|pageprops|revisions', explaintext=1, rvprop='ids')
        page = payload.get('query', {}).get('pages', [{}])[0]
        if not self.candidate(page) or not page.get('extract', '').strip():
            raise SourceError('문서 본문을 확보하지 못했습니다. 다음 실행에서 다시 시도할 수 있습니다.')
        return {'document_id': candidate['document_id'], 'document_title': page['title'],
                'source_type': 'web', 'source_url': candidate['url'], 'source_file': '',
                'revision_id': page.get('revisions', [{}])[0].get('revid', ''),
                'license': 'CC BY-SA 4.0 (문서별 예외 확인)', 'collected_at': now(),
                'search_query': query, 'pages': [{'text': page['extract']}]}


class EnglishWikipediaSource(WikipediaSource):
    api = 'https://en.wikipedia.org/w/api.php'
    language = 'en'

    def subject(self, species):
        payload = self.request(action='query', titles=species.scientific_name, redirects=1,
            prop='extracts|pageprops', exintro=1, explaintext=1)
        for page in payload.get('query', {}).get('pages', []):
            candidate = self.candidate(page)
            if candidate and re.search(r'(?<!\w)' + re.escape(species.scientific_name) + r'(?!\w)',
                                       candidate['summary'], re.I):
                return candidate
        return None
