import time

from . import prompts
from .catalog import Catalog, explicit_filters, normalize_query
from .errors import AppError, ConfigurationError
from .ingestion import Collector
from .llm import JsonLLM, make_embeddings
from .rag import build_graph
from .store import VectorStore
from .ecology import EcologyFacts


class EcoService:
    def __init__(self, settings):
        self.settings = settings
        self.catalog = Catalog(settings.root / 'data' / 'species.json')
        self.llm = JsonLLM(settings)
        self.store = VectorStore(settings, make_embeddings(settings))
        self.collector = Collector(settings, self.store, self.llm)
        self.ecology = EcologyFacts(settings, self.llm, self.store)
        self.graph = build_graph(self.store, self.llm)

    def answer(self, species_ids, question, history=None, progress=lambda _: None):
        if not question.strip():
            raise AppError('질문을 입력해 주세요.')
        if not 1 <= len(set(species_ids)) <= 2:
            raise AppError('종은 한 개 또는 두 개를 선택해 주세요.')
        started = time.perf_counter()
        species_ids = list(dict.fromkeys(species_ids))
        for sid in species_ids:
            self.catalog.get(sid)
            if not self.store.metadata_for(sid):
                raise AppError('종 메타데이터 색인이 없습니다. 먼저 색인 버튼을 눌러 주세요.')
        audits, notices = [], []
        if self.settings.auto_collect:
            for sid in species_ids:
                try:
                    audits.append(self.collector.ensure(self.catalog.get(sid), question, progress))
                except AppError as exc:
                    notices.append(str(exc))
                    # Retrieval can continue from already indexed/metadata-only evidence.
                try:
                    self.ecology.enrich_species(self.catalog.get(sid), progress)
                except Exception:
                    import logging
                    logging.exception('Ecology enrichment failed; continue from saved evidence')
                    notices.append('생태 정보 추가 정리를 완료하지 못해 기존 근거로 답변했습니다.')
        progress('검색한 근거를 바탕으로 답변을 작성하고 있습니다.')
        result = self.graph.invoke({'species_ids': species_ids, 'question': normalize_query(question),
                                    'history': history or []})
        result['notices'].extend(notices)
        for audit in audits:
            result['notices'].extend(audit['notices'])
        if not any(e['metadata']['source_type'] != 'metadata' for e in result['evidence']):
            result['notices'].append('외부 문서 근거가 없어 종 메타데이터 범위에서만 답변했습니다.')
        result['audit'] = audits
        result['elapsed_seconds'] = round(time.perf_counter()-started, 2)
        return result

    def explore(self, query):
        query = normalize_query(query)
        if not query:
            raise AppError('찾을 조건을 입력해 주세요.')
        if not self.store.count('meta'):
            raise AppError('조건 탐색 전에 종 메타데이터를 색인해 주세요.')
        filters = explicit_filters(query)
        documents = self.store.search_catalog(query, filters)
        candidates = {d.metadata['species_id']: d for d in documents}
        for document in self.store.search_ecology_candidates(query, filters):
            sid = document.metadata['species_id']
            if sid not in candidates:
                base = self.store.metadata_for(sid)
                if base:
                    candidates[sid] = base[0]
        if not candidates:
            return []
        payload = self.llm.ask(prompts.EXPLORE, {'conditions': query, 'candidates': [
            {'species_id': sid, 'text': doc.page_content + '\n출처 연결 생태 정보:\n' +
                self.ecology.text(self.catalog.get(sid))} for sid,doc in candidates.items()]})
        matches = payload.get('matches')
        if not isinstance(matches, list):
            raise AppError('조건 탐색 결과의 형식이 올바르지 않습니다.')
        result, seen = [], set()
        for match in matches:
            if not isinstance(match, dict):
                continue
            sid = match.get('species_id')
            if sid in candidates and sid not in seen:
                seen.add(sid)
                result.append({'species': self.catalog.get(sid), 'reason': str(match.get('reason', ''))})
        return result
