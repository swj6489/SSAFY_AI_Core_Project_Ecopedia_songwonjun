import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ecopedia.catalog import Catalog, Species, explicit_filters
from ecopedia.config import ROOT, Settings
from ecopedia.coverage import analyze_coverage
from ecopedia.ecology import EcologyFacts, validate_claims
from ecopedia.errors import AppError
from ecopedia.llm import output_format
from ecopedia import prompts
from ecopedia.service import EcoService
from langchain_core.documents import Document


class EcologyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.settings = Settings(root=Path(folder.name))
        self.species = Species('sp_test', '산양', 'Naemorhedus caudatus', '포유류', 1, 'https://example.org/catalog')
        self.doc = {'document_id': 'wiki-1', 'document_title': '산양', 'is_subject': True,
            'source_type': 'web', 'source_url': 'https://ko.wikipedia.org/wiki/산양',
            'license': 'CC BY-SA 4.0', 'revision_id': 123, 'collected_at': '2026-10-22',
            'pages': [{'text': '산양(Naemorhedus caudatus)은 소과 동물이다.\n바위가 많은 산림에서 서식한다.\n한국 강원도 산지에 분포한다.\n서식지 파괴로 개체수가 감소한다.\n1960년 강원도에 서식하였다.', 'page_number': 3}]}

    @staticmethod
    def claim(field='habitat', quote='바위가 많은 산림에서 서식한다.', scope='unspecified'):
        return {'field': field, 'quote': quote, 'page_index': 0, 'time_scope': scope}

    def engine(self, payload=None):
        llm, store = Mock(), Mock()
        llm.ask.return_value = payload if payload is not None else {'claims': [self.claim()]}
        engine = EcologyFacts(self.settings, llm, store)
        engine.cache.put('doc:sp_test:wiki-1', self.doc)
        return engine, llm, store

    def test_only_literal_relevant_quotes_are_accepted(self):
        claims = [self.claim(), self.claim(quote='이 종은 아프리카 사막에서 서식한다.'),
            self.claim('domestic_distribution', '바위가 많은 산림에서 서식한다.'),
            self.claim('threats', '한국 강원도 산지에 분포한다.')]
        accepted, rejected = validate_claims(self.species, self.doc, {'claims': claims})
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 3)

    def test_historical_dates_are_not_present_day_claims(self):
        accepted, _ = validate_claims(self.species, self.doc, {'claims': [
            self.claim('domestic_distribution', '1960년 강원도에 서식하였다.')]})
        self.assertEqual(accepted[0]['time_scope'], 'historical')

    def test_cached_extraction_and_provenance_survive_restart(self):
        engine, llm, store = self.engine()
        result = engine.enrich_species(self.species)
        self.assertEqual(result['claims'], 1)
        self.assertEqual(result['llm_calls'], 1)
        llm.ask.assert_called_once()
        offline = Mock()
        offline.ask.side_effect = AssertionError('추출 결과 재생성 금지')
        engine = EcologyFacts(self.settings, offline, store)
        self.assertEqual(engine.enrich_species(self.species)['llm_calls'], 0)
        record = engine.records(self.species)[0]
        self.assertEqual(record['revision_id'], 123)
        self.assertEqual(record['page_number'], 3)
        self.assertEqual(record['source_url'], self.doc['source_url'])
        self.assertEqual(analyze_coverage(self.species, [self.doc], [record])[0]['status'], 'extracted')
        source = store.index_document.call_args.args[1]
        self.assertEqual(source['pages'][0]['page_number'], 3)
        self.assertIn('원문', source['modification_notice'])
        offline.ask.assert_not_called()

    def test_empty_results_cached_and_bad_shapes_retry(self):
        engine, llm, _ = self.engine({'claims': []})
        engine.enrich_species(self.species)
        engine.enrich_species(self.species)
        llm.ask.assert_called_once()
        changed = dict(self.doc, revision_id=124)
        engine.cache.put('doc:sp_test:wiki-1', changed)
        llm.ask.return_value = {'claims': 'bad shape'}
        with self.assertRaises(AppError):
            engine.enrich_species(self.species)
        self.assertIsNone(engine.cache.get(engine.key(self.species, changed)))

    def test_source_changes_invalidate_only_the_extracted_view(self):
        engine, llm, _ = self.engine()
        engine.enrich_species(self.species)
        changed = dict(self.doc, revision_id=124)
        engine.cache.put('doc:sp_test:wiki-1', changed)
        self.assertEqual(engine.records(self.species), [])
        engine.enrich_species(self.species)
        self.assertEqual(llm.ask.call_count, 2)
        self.assertEqual(engine.records(self.species)[0]['revision_id'], 124)

    def test_existing_source_body_is_never_refetched(self):
        engine, _, _ = self.engine()
        source = Mock()
        source.subject.side_effect = AssertionError('재수집 금지')
        source.fetch.side_effect = AssertionError('재수집 금지')
        engine._source = source
        self.assertEqual(engine.collect_missing_subject(self.species), 'cached')
        source.subject.assert_not_called()
        source.fetch.assert_not_called()

    def test_missing_subject_lookup_is_cached(self):
        source = Mock()
        source.subject.return_value = None
        engine = EcologyFacts(self.settings, source=source)
        self.assertEqual(engine.collect_missing_subject(self.species), 'not_found')
        self.assertEqual(engine.collect_missing_subject(self.species), 'not_found')
        source.subject.assert_called_once()
        source.fetch.assert_not_called()

    def test_invalid_identity_body_is_not_used_or_refetched(self):
        source = Mock()
        source.subject.return_value = {'document_id': 'wiki-1', 'title': '산양'}
        source.fetch.return_value = dict(self.doc, pages=[{'text': 'Capra hircus는 다른 동물이다.'}])
        store = Mock()
        engine = EcologyFacts(self.settings, store=store, source=source)
        self.assertEqual(engine.collect_missing_subject(self.species), 'identity_unconfirmed')
        self.assertEqual(engine.collect_missing_subject(self.species), 'identity_unconfirmed')
        source.subject.assert_called_once()
        source.fetch.assert_called_once()
        store.index_document.assert_not_called()

    def test_embedding_retry_does_not_repeat_extraction(self):
        engine, llm, store = self.engine()
        store.index_document.side_effect = [RuntimeError('temporary embedding failure'), 1]
        with self.assertRaises(RuntimeError):
            engine.enrich_species(self.species)
        engine.enrich_species(self.species)
        llm.ask.assert_called_once()

    def test_extraction_schema_is_strict(self):
        schema = output_format(prompts.ECOLOGY)['json_schema']
        self.assertTrue(schema['strict'])
        self.assertFalse(schema['schema']['additionalProperties'])

    def test_english_quote_and_korean_range_validation(self):
        document = dict(self.doc, pages=[{'text': 'Naemorhedus caudatus lives in mountain forests.\nIt is native to South Korea.\nIts main threats are habitat loss and hunting.'}])
        payload = {'claims': [self.claim('habitat', 'Naemorhedus caudatus lives in mountain forests.'),
            self.claim('domestic_distribution', 'It is native to South Korea.'),
            self.claim('threats', 'Its main threats are habitat loss and hunting.')]}
        accepted, rejected = validate_claims(self.species, document, payload)
        self.assertEqual(len(accepted), 3)
        self.assertEqual(rejected, [])

    def test_english_missing_lookup_is_not_repeated(self):
        engine = EcologyFacts(self.settings)
        with patch('ecopedia.ecology.EnglishWikipediaSource') as constructor:
            constructor.return_value.subject.return_value = None
            self.assertEqual(engine.collect_english_supplement(self.species), 'not_found')
            self.assertEqual(engine.collect_english_supplement(self.species), 'not_found')
            constructor.return_value.subject.assert_called_once()
            constructor.assert_called_once()

    def test_english_breeding_range_and_reverse_habitat_threat_expression(self):
        document = dict(self.doc, pages=[{'text': 'Naemorhedus caudatus. It is dependent on forest habitats. It breeds in South Korea. Its decline is caused by the destruction of its habitat.'}])
        payload = {'claims': [self.claim('habitat', 'It is dependent on forest habitats.'),
            self.claim('domestic_distribution', 'It breeds in South Korea.'),
            self.claim('threats', 'Its decline is caused by the destruction of its habitat.')]}
        accepted, rejected = validate_claims(self.species, document, payload)
        self.assertEqual(len(accepted), 3)
        self.assertEqual(rejected, [])

    def test_omitted_scientific_name_can_be_checked_without_refetch(self):
        engine = EcologyFacts(self.settings)
        source = Mock()
        source.request.return_value = {'entities': {'Q123': {'claims': {'P225': [
            {'rank': 'normal', 'mainsnak': {'datavalue': {'value': self.species.scientific_name}}}]}}}}
        engine._taxon_source = source
        document = dict(self.doc, document_id='ko-wiki-1', pages=[{'text': '산양은 한국의 산림에서 서식한다.'}])
        self.assertTrue(engine.verify_cached_identity(self.species, document))
        self.assertEqual(document['taxon_validation']['scientific_name'], self.species.scientific_name)
        self.assertTrue(engine.verify_cached_identity(self.species, document))
        source.request.assert_called_once()
        accepted, _ = validate_claims(self.species, document, {'claims': [self.claim('habitat', '산양은 한국의 산림에서 서식한다.')]})
        self.assertEqual(len(accepted), 1)

    def test_condition_exploration_includes_ecology_candidates_and_sources(self):
        service = EcoService.__new__(EcoService)
        service.catalog = Catalog(ROOT / 'data/species.json')
        species = service.catalog.items[0]
        service.store, service.llm, service.ecology = Mock(), Mock(), Mock()
        service.store.count.return_value = 282
        service.store.search_catalog.return_value = []
        service.store.search_ecology_candidates.return_value = [Document(page_content='산림', metadata={'species_id': species.species_id})]
        service.store.metadata_for.return_value = [Document(page_content=species.text(), metadata={'species_id': species.species_id})]
        service.ecology.text.return_value = '서식 환경: 산림\n출처: https://example.org/species'
        service.llm.ask.return_value = {'matches': [{'species_id': species.species_id, 'reason': '산림 근거'}]}
        result = service.explore('1급 포유류 중 산림에 사는 종')
        self.assertEqual(result[0]['species'].species_id, species.species_id)
        self.assertIn('https://example.org/species', service.llm.ask.call_args.args[1]['candidates'][0]['text'])
        service.store.search_ecology_candidates.assert_called_once_with('1급 포유류 중 산림에 사는 종', explicit_filters('1급 포유류 중 산림에 사는 종'))


if __name__ == '__main__':
    unittest.main()
