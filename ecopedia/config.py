import json
import os
from dataclasses import dataclass, fields
from pathlib import Path

from dotenv import load_dotenv

from .errors import ConfigurationError

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    chunk_size: int = 1000
    chunk_overlap: int = 200
    top_k: int = 4
    search_type: str = 'similarity'
    mmr_fetch_k: int = 20
    mmr_lambda: float = 0.5
    catalog_candidates: int = 20
    max_queries: int = 3
    max_documents_per_query: int = 3
    request_interval_seconds: float = 1.0
    request_timeout_seconds: int = 30
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 2
    metadata_collection: str = 'species_meta'
    documents_collection: str = 'species_docs'
    metadata_source_basis_date: str = '2022-12-09'
    auto_collect: bool = True

    def __post_init__(self):
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ConfigurationError('청크 중복 길이는 0 이상, 청크 크기 미만이어야 합니다.')
        if not 100 <= self.chunk_size <= 10000:
            raise ConfigurationError('청크 크기는 100~10000자로 설정해 주세요.')
        if self.search_type not in ('similarity', 'mmr'):
            raise ConfigurationError('검색 방식은 similarity 또는 mmr이어야 합니다.')
        if not 1 <= self.top_k <= self.mmr_fetch_k <= 100:
            raise ConfigurationError('1 ≤ Top-k ≤ MMR 후보 수 ≤ 100으로 설정해 주세요.')
        if not 0 <= self.mmr_lambda <= 1:
            raise ConfigurationError('MMR lambda는 0~1이어야 합니다.')
        if min(self.request_interval_seconds, self.request_timeout_seconds) <= 0:
            raise ConfigurationError('호출 간격·제한 시간은 양수여야 합니다.')
        if not 1 <= self.max_queries <= 8 or not 1 <= self.max_documents_per_query <= 10:
            raise ConfigurationError('검색어와 문서 수 설정이 허용 범위를 벗어났습니다.')
        if self.metadata_collection == self.documents_collection:
            raise ConfigurationError('메타데이터와 문서 컬렉션 이름은 달라야 합니다.')

    @property
    def runtime(self):
        return self.root / 'runtime'

    def require_key(self):
        if not os.getenv('OPENAI_API_KEY', '').strip():
            raise ConfigurationError('API 키가 없습니다. .env의 OPENAI_API_KEY를 설정해 주세요.')


def load_settings(root=ROOT):
    load_dotenv(root / '.env', override=False)
    try:
        payload = json.loads((root / 'config.json').read_text(encoding='utf-8'))
        # Older config files may still contain a TTL. It cannot re-enable expiry.
        payload.pop('query_cache_hours', None)
        allowed = {f.name for f in fields(Settings)} - {'root'}
        if set(payload) - allowed:
            raise ValueError('unknown configuration')
        return Settings(root=root, **payload)
    except (ValueError, TypeError, OSError) as exc:
        raise ConfigurationError('config.json의 이름·값·JSON 형식을 확인해 주세요.') from exc
