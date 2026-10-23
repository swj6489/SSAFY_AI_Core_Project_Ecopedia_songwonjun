import json
import math
import os
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from ecopedia import prompts
from ecopedia.catalog import Catalog, Species, explicit_filters, normalize_query
from ecopedia.config import ROOT, Settings, load_settings
from ecopedia.errors import AppError, ConfigurationError, SourceError
from ecopedia.ingestion import Collector
from ecopedia.rag import build_graph, validate_answer
from ecopedia.sources import SourceCache, WikipediaSource
from ecopedia.store import VectorStore, merge_evidence
from ecopedia.logging_utils import RedactingFormatter


class TestEmbeddings(Embeddings):
    """테스트 전용 결정적 벡터. 실제 RAG 품질을 검증하는 모델이 아님."""
    def embed_documents(self, texts):
        import hashlib
        result = []
        for text in texts:
            vector = [0.0]*32
            for word in re.findall(r'\w+', text):
                vector[int(hashlib.sha256(word.encode()).hexdigest()[:8], 16) % 32] += 1
            length = math.sqrt(sum(v*v for v in vector)) or 1
            result.append([v/length for v in vector])
        return result

    def embed_query(self, text):
        return self.embed_documents([text])[0]


def source(doc_id='test-doc', body='직접 작성한 시험 문장입니다. '*140):
    return {'document_id': doc_id, 'document_title': '테스트 자체 작성 문서',
            'source_type': 'text', 'source_url': 'https://example.org/test',
            'license': '테스트 작성자 소유', 'collected_at': '2026-10-21T00:00:00+00:00',
            'pages': [{'text': body, 'page_number': 1}]}


class FakeLLM:
    def __init__(self):
        self.calls = []
    def ask(self, system, payload):
        self.calls.append((system, payload))
        if system == prompts.QUERY:
            return {'queries': []}
        if system == prompts.SELECT:
            return {'decisions': [{'document_id': c['document_id'], 'selected': True, 'reason': '테스트'}
                                   for c in payload['candidates']]}
        if system == prompts.ANSWER:
            return {'answer': '제공된 문서에서 확인되지 않습니다. [근거 1]', 'used_evidence_ids': [999]}
        return {'matches': []}


class FakeSource:
    def __init__(self):
        self.subject_calls = self.search_calls = self.fetch_calls = 0
        self.fail_fetch = False
    def subject(self, species):
        self.subject_calls += 1
        return {'document_id': 'subject', 'title': species.korean_name}
    def search(self, query):
        self.search_calls += 1
        return [{'document_id': 'related', 'title': '관련 문서'}]
    def fetch(self, candidate, query):
        self.fetch_calls += 1
        if self.fail_fetch:
            raise SourceError('시험용 실패')
        return source(candidate['document_id'])


class CoreTests(unittest.TestCase):
    def setUp(self):
        test_root = ROOT / 'runtime' / 'tests'
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.settings = Settings(root=Path(self.temp.name))
        self.catalog = Catalog(ROOT / 'data' / 'species.json')

    def tearDown(self):
        self.temp.cleanup()

    def test_catalog_counts_grades_and_unknown_fields(self):
        self.assertEqual(len(self.catalog.items), 282)
        self.assertEqual(len({s.species_id for s in self.catalog.items}), 282)
        self.assertEqual(sum(s.endangered_grade == 1 for s in self.catalog.items), 68)
        self.assertIn('확인된 정보 없음', self.catalog.items[0].text())

    def test_roman_grade_inputs_and_constraints(self):
        for value in ('Ⅱ급', 'II급', '2급'):
            self.assertEqual(normalize_query(value), '2급')
        self.assertEqual(normalize_query('Ⅰ급'), '1급')
        self.assertEqual(explicit_filters('II급 포유류'),
            {'$and': [{'endangered_grade': 2}, {'taxon_group': '포유류'}]})
        self.assertEqual(explicit_filters('해조류'), {'taxon_group': '해조류'})

    def test_invalid_chunk_configuration(self):
        with self.assertRaises(ConfigurationError):
            replace(self.settings, chunk_overlap=1000)

    def test_deduplicate_without_losing_comparison_species(self):
        doc = Document(page_content='동일 본문', metadata={'chunk_id': 'a', 'species_id': 'sp1'})
        same = Document(page_content='동일  본문', metadata={'chunk_id': 'b', 'species_id': 'sp1'})
        other = Document(page_content='동일 본문', metadata={'chunk_id': 'c', 'species_id': 'sp2'})
        self.assertEqual(len(merge_evidence([doc, same, other])), 2)

    def test_citations_use_actual_body_and_reject_unknown(self):
        evidence = [{'evidence_id': 1, 'text': 'x', 'metadata': {}}]
        result = validate_answer({'answer': '내용 [근거 1]', 'used_evidence_ids': [9]}, evidence)
        self.assertEqual(result['used_evidence'], evidence)
        with self.assertRaises(ValueError):
            validate_answer({'answer': '내용 [근거 9]'}, evidence)
        self.assertTrue(validate_answer({'answer': '확인되지 않습니다.'}, evidence)['notices'])

    def test_old_cache_persists_across_restarts_without_expiration(self):
        cache = SourceCache(self.settings)
        with patch('ecopedia.sources.now', return_value='2000-01-01T00:00:00+00:00'):
            cache.put('키', {'국명': '삵'})
            cache.put('검색결과없음', {})
        restarted = SourceCache(self.settings)
        self.assertEqual(restarted.get('키'), {'국명': '삵'})
        self.assertEqual(restarted.get('검색결과없음'), {})
        self.assertIsNone(restarted.get('미수집'))

    def test_legacy_ttl_config_cannot_enable_expiration(self):
        (self.settings.root / 'config.json').write_text(
            json.dumps({'query_cache_hours': 1}), encoding='utf-8')
        configuration = load_settings(self.settings.root)
        self.assertFalse(hasattr(configuration, 'query_cache_hours'))

    def test_old_collected_query_and_bodies_never_call_source_after_restart(self):
        class DummyStore:
            def index_document(self, sid, doc): return 1
        provider = FakeSource()
        species = self.catalog.items[0]
        with patch('ecopedia.sources.now', return_value='2000-01-01T00:00:00+00:00'):
            Collector(self.settings, DummyStore(), FakeLLM(), provider).ensure(species, '질문')
        blocked_source = unittest.mock.Mock()
        blocked_source.subject.side_effect = AssertionError('종 문서를 다시 요청함')
        blocked_source.search.side_effect = AssertionError('검색어를 다시 수집함')
        blocked_source.fetch.side_effect = AssertionError('본문을 다시 수집함')
        audit = Collector(self.settings, DummyStore(), FakeLLM(), blocked_source).ensure(species, '질문')
        self.assertEqual(audit['cached_queries'], audit['queries'])
        blocked_source.subject.assert_not_called()
        blocked_source.search.assert_not_called()
        blocked_source.fetch.assert_not_called()

    def test_recollection_uses_cache_and_retries_failure(self):
        class DummyStore:
            def __init__(self): self.sources = []
            def index_document(self, sid, doc): self.sources.append(doc); return 1
        provider, store = FakeSource(), DummyStore()
        collector = Collector(self.settings, store, FakeLLM(), provider)
        species = self.catalog.items[0]
        collector.ensure(species, '질문')
        calls = (provider.subject_calls, provider.search_calls, provider.fetch_calls)
        collector.ensure(species, '질문')
        self.assertEqual(calls, (provider.subject_calls, provider.search_calls, provider.fetch_calls))
        self.assertTrue(any(doc['document_id'] == 'subject' for doc in store.sources))
        provider2 = FakeSource()
        provider2.fail_fetch = True
        another = self.catalog.items[1]
        with self.assertRaises(SourceError):
            Collector(self.settings, store, FakeLLM(), provider2).ensure(another, '질문')
        provider2.fail_fetch = False
        Collector(self.settings, store, FakeLLM(), provider2).ensure(another, '질문')
        self.assertGreaterEqual(provider2.fetch_calls, 2)

    def test_local_manifest_requires_license(self):
        path = self.settings.root / 'manifest.json'
        path.write_text(json.dumps([{'license_confirmed': False}]))
        with self.assertRaises(AppError):
            Collector(self.settings, None, None).import_manifest(path, self.catalog)

    def test_approved_local_text_import_keeps_source(self):
        class DummyStore:
            def index_document(self, sid, document):
                self.saved = (sid, document)
                return 1
        text = self.settings.root / 'own.txt'
        text.write_text('시험 작성자가 직접 작성한 문장.', encoding='utf-8')
        manifest = self.settings.root / 'manifest.json'
        manifest.write_text(json.dumps([{'species_id': self.catalog.items[0].species_id,
            'document_id': 'own', 'document_title': '시험 문서', 'file': 'own.txt',
            'license': '작성자 소유', 'license_evidence_url': 'https://example.org/license',
            'license_confirmed': True}]), encoding='utf-8')
        store = DummyStore()
        count = Collector(self.settings, store, None).import_manifest(manifest, self.catalog)
        self.assertEqual(count, 1)
        self.assertEqual(store.saved[1]['source_file'], 'own.txt')
        self.assertEqual(store.saved[1]['pages'][0]['text'], text.read_text(encoding='utf-8'))

    def test_missing_api_key_and_user_agent(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': '', 'WIKIMEDIA_USER_AGENT': ''}):
            with self.assertRaises(ConfigurationError): self.settings.require_key()
            with self.assertRaises(ConfigurationError): WikipediaSource(self.settings)

    def test_log_redacts_configured_credentials(self):
        import logging
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fake-secret-for-unit-test'}):
            record = logging.LogRecord('test', logging.ERROR, '', 1, 'failure fake-secret-for-unit-test', (), None)
            result = RedactingFormatter('%(message)s').format(record)
            self.assertNotIn('fake-secret-for-unit-test', result)
            self.assertIn('[REDACTED]', result)

    def test_disambiguation_is_not_a_subject(self):
        self.assertIsNone(WikipediaSource.candidate({'pageid': 1, 'title': '모호함', 'pageprops': {'disambiguation': ''}}))


class VectorIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Keep real Chroma files until process exit on Windows: Rust file handles remain open.
        import atexit
        import shutil
        test_root = ROOT / 'runtime' / 'tests'
        test_root.mkdir(parents=True, exist_ok=True)
        cls.root = Path(tempfile.mkdtemp(prefix='ecopedia-tests-', dir=test_root))
        atexit.register(shutil.rmtree, cls.root, ignore_errors=True)
        cls.settings = Settings(root=cls.root)
        cls.catalog = Catalog(ROOT / 'data' / 'species.json')
        cls.store = VectorStore(cls.settings, TestEmbeddings())

    def test_real_chroma_upsert_282_and_grade_filter(self):
        self.assertEqual(self.store.index_catalog(self.catalog), 282)
        self.assertEqual(self.store.index_catalog(self.catalog), 282)
        docs = self.store.search_catalog('2급 포유류', explicit_filters('2급 포유류'))
        self.assertTrue(docs)
        self.assertTrue(all(d.metadata['endangered_grade'] == 2 and d.metadata['taxon_group'] == '포유류' for d in docs))

    def test_rechunk_removes_stale_and_isolates_species(self):
        a, b = self.catalog.items[:2]
        self.store.index_document(a.species_id, source())
        before = len(self.store.docs.get(where={'species_id': a.species_id})['ids'])
        self.assertGreater(before, 1)
        self.store.index_document(a.species_id, source(body='짧은 문서'))
        self.assertEqual(len(self.store.docs.get(where={'species_id': a.species_id})['ids']), 1)
        self.store.index_document(b.species_id, source(body='다른 종의 문서'))
        docs = self.store.retrieve_external(a.species_id, '다른 종')
        self.assertTrue(all(d.metadata['species_id'] == a.species_id for d in docs))

    def test_graph_retrieve_generate_and_missing_index(self):
        self.store.index_catalog(self.catalog)
        graph = build_graph(self.store, FakeLLM())
        self.assertEqual(set(graph.nodes), {'__start__', 'retrieve', 'generate'})
        result = graph.invoke({'species_ids': [self.catalog.items[0].species_id], 'question': '알 수 없는 내용'})
        self.assertEqual(result['evidence'][0]['metadata']['source_type'], 'metadata')
        self.assertIn('확인되지 않습니다', result['answer'])
        with self.assertRaises(AppError):
            graph.invoke({'species_ids': ['missing'], 'question': '질문'})

    def test_mmr_runs_with_real_chroma(self):
        self.store.index_catalog(self.catalog)
        previous = self.store.settings
        self.store.settings = replace(previous, search_type='mmr')
        try:
            self.store.index_document(self.catalog.items[2].species_id, source(body='서식지 생태 위협 '*300))
            docs = self.store.retrieve_external(self.catalog.items[2].species_id, '생태')
            self.assertTrue(docs)
            self.assertLessEqual(len(docs), self.settings.top_k)
        finally:
            self.store.settings = previous

    def test_subject_document_cannot_be_crowded_out(self):
        sid = self.catalog.items[3].species_id
        self.store.index_document(sid, source('subject-primary', '선택 종의 고유 생태 본문') | {'is_subject': True})
        for i in range(6):
            self.store.index_document(sid, source(f'context-{i}', f'광범위한 서식 환경 위협 요인 문서 {i}'))
        docs = self.store.retrieve_external(sid, '광범위한 서식 환경 위협 요인')
        self.assertTrue(any(d.metadata.get('is_subject') for d in docs))
        self.assertLessEqual(len(docs), self.settings.top_k)


    def test_ecology_candidate_filters_and_unchanged_index_skip_embeddings(self):
        species = self.catalog.items[-1]
        record = source('ecology-filter-test', '산림 서식 환경 · 원문 대조 생태 근거') | {
            'record_kind': 'ecology_fact', 'taxon_group': species.taxon_group,
            'endangered_grade': species.endangered_grade, 'modification_notice': '원문 발췌·분류'}
        with patch.object(self.store.docs, 'add_documents', wraps=self.store.docs.add_documents) as add:
            self.store.index_document(species.species_id, record)
            self.store.index_document(species.species_id, record)
            self.assertEqual(add.call_count, 1)
        result = self.store.search_ecology_candidates('산림', {'taxon_group': species.taxon_group})
        self.assertTrue(result)
        self.assertTrue(all(doc.metadata['record_kind'] == 'ecology_fact' for doc in result))
        self.assertTrue(all(doc.metadata['taxon_group'] == species.taxon_group for doc in result))


if __name__ == '__main__':
    unittest.main()
