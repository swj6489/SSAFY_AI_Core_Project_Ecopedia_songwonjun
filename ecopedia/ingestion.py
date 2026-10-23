import json
from pathlib import Path

from pypdf import PdfReader

from . import prompts
from .errors import AppError
from .sources import SourceCache, WikipediaSource, now
from .store import digest


class Collector:
    def __init__(self, settings, store, llm, source=None):
        self.settings, self.store, self.llm = settings, store, llm
        self.cache = SourceCache(settings)
        self._source = source

    @property
    def source(self):
        if self._source is None:
            self._source = WikipediaSource(self.settings)
        return self._source

    def ingest_candidate(self, species, candidate, query):
        key = f"doc:{species.species_id}:{candidate['document_id']}"
        document = self.cache.get(key)
        if document is None:
            document = self.source.fetch(candidate, query)
            # Store the body before indexing. If embeddings fail, retry from local body.
            self.cache.put(key, document)
        document['is_subject'] = candidate.get('is_subject', False)
        self.cache.put(key, document)
        self.store.index_document(species.species_id, document)
        return document

    def ensure(self, species, question, progress=lambda _: None):
        audit = {'species_id': species.species_id, 'queries': [], 'selected': [], 'rejected': [],
                 'cached_queries': [], 'notices': []}
        payload = self.llm.ask(prompts.QUERY, {'species': species.text(), 'question': question})
        extracted = payload.get('queries', [])
        if not isinstance(extracted, list):
            raise AppError('검색어 출력 형식을 확인하지 못했습니다. 다시 시도해 주세요.')
        queries = [species.korean_name + ' ' + species.scientific_name]
        for query in extracted:
            if isinstance(query, str) and query.strip() and query.strip() not in queries:
                queries.append(query.strip()[:200])
        queries = queries[:self.settings.max_queries]
        audit['queries'] = queries
        subject_key = f'subject:{species.species_id}'
        subject_record = self.cache.get(subject_key)
        if subject_record is None:
            progress(f'{species.korean_name}: 종 자체의 문서를 확인하고 있습니다.')
            subject = self.source.subject(species)
            if subject:
                subject['is_subject'] = True
                self.ingest_candidate(species, subject, queries[0])
                self.cache.put(subject_key, subject)
            else:
                audit['notices'].append(f'{species.korean_name}: 동일 종의 문서를 확인하지 못했습니다.')
        else:
            subject = subject_record
            subject['is_subject'] = True
            self.ingest_candidate(species, subject, queries[0])
        if subject:
            audit['selected'].append({'document_id': subject['document_id'], 'title': subject['title'],
                                      'reason': '선택한 종 자체의 문서: 선별·길이 제한보다 우선'})
        for query in queries:
            key = f'query:{species.species_id}:' + digest(query.casefold().strip())
            cached = self.cache.get(key)
            if cached is not None:
                audit['cached_queries'].append(query)
                # Reapply splitter settings to cached bodies without recollecting.
                for candidate in cached.get('selected', []):
                    self.ingest_candidate(species, candidate, query)
                audit['selected'].extend(cached.get('decisions_selected', []))
                audit['rejected'].extend(cached.get('rejected', []))
                continue
            progress(f'{species.korean_name}: 관련 문서를 찾고 있습니다.')
            candidates = self.source.search(query)
            candidates = [c for c in candidates if not subject or c['document_id'] != subject['document_id']]
            if not candidates:
                self.cache.put(key, {'selected': [], 'decisions_selected': [], 'rejected': []})
                continue
            decisions = self.llm.ask(prompts.SELECT, {'species': species.text(), 'question': question,
                                                        'candidates': candidates}).get('decisions')
            if not isinstance(decisions, list):
                raise AppError('후보 문서 선별 형식이 올바르지 않습니다. 다시 시도해 주세요.')
            by_id = {c['document_id']: c for c in candidates}
            selected, accepted, rejected, seen = [], [], [], set()
            for decision in decisions:
                if not isinstance(decision, dict):
                    continue
                cid = decision.get('document_id')
                if cid not in by_id or cid in seen:
                    continue
                seen.add(cid)
                entry = {'document_id': cid, 'title': by_id[cid]['title'],
                         'reason': str(decision.get('reason', ''))[:500]}
                if decision.get('selected') is True and len(selected) < self.settings.max_documents_per_query:
                    self.ingest_candidate(species, by_id[cid], query)
                    selected.append(by_id[cid])
                    accepted.append(entry)
                else:
                    rejected.append(entry)
            rejected.extend({'document_id': cid, 'title': c['title'], 'reason': '선별 결과에서 선택되지 않음'}
                            for cid,c in by_id.items() if cid not in seen)
            # A query is complete only after every selected body was successfully indexed.
            self.cache.put(key, {'selected': selected, 'decisions_selected': accepted, 'rejected': rejected})
            audit['selected'].extend(accepted)
            audit['rejected'].extend(rejected)
        return audit

    def import_manifest(self, manifest_path: Path, catalog):
        payload = json.loads(manifest_path.read_text(encoding='utf-8'))
        count = 0
        for entry in payload:
            if entry.get('license_confirmed') is not True or not entry.get('license') or not entry.get('license_evidence_url'):
                raise AppError('로컬 문서는 확인된 이용 조건과 근거 URL이 필요합니다.')
            species = catalog.get(entry['species_id'])
            path = (manifest_path.parent / entry['file']).resolve()
            if path.suffix.lower() == '.pdf':
                reader = PdfReader(path)
                selected_pages = entry.get('pages')
                if not selected_pages:
                    raise AppError('PDF는 해당 종의 페이지 목록을 지정해 주세요. 전체 도감을 모든 종에 연결하지 않습니다.')
                pages = [{'page_number': i, 'text': reader.pages[i-1].extract_text() or ''}
                         for i in selected_pages if type(i) is int and 1 <= i <= len(reader.pages)]
                if len(pages) != len(selected_pages):
                    raise AppError('PDF 페이지 번호가 범위를 벗어났습니다.')
                source_type = 'pdf'
            elif path.suffix.lower() == '.txt':
                pages = [{'text': path.read_text(encoding='utf-8')}]
                source_type = 'text'
            else:
                raise AppError('로컬 문서는 PDF 또는 UTF-8 TXT만 지원합니다.')
            source = {'document_id': entry['document_id'], 'document_title': entry['document_title'],
                'source_type': source_type, 'source_url': entry.get('source_url', ''),
                'source_file': path.name, 'license': entry['license'], 'collected_at': now(),
                'search_query': '로컬 문서 묶음', 'pages': pages,
                'license_evidence_url': entry['license_evidence_url']}
            added = self.store.index_document(species.species_id, source)
            if not added:
                raise AppError('추출된 본문이 없습니다. 스캔 PDF는 OCR한 텍스트를 사용해 주세요.')
            self.cache.put(f"doc:{species.species_id}:{source['document_id']}", source)
            count += added
        return count
