import unittest
from dataclasses import replace

from ecopedia.catalog import Species
from ecopedia.coverage import analyze_coverage, scientific_identity, subject_document, relevant


class CoverageTests(unittest.TestCase):
    def test_optional_subgenus_but_not_subspecies_is_normalized(self):
        self.assertEqual(scientific_identity('Callipogon (Eoxenus) relictus'), 'callipogon relictus')
        self.assertNotEqual(scientific_identity('Pteromys volans aluco'), scientific_identity('Pteromys volans'))
        species = replace(self.species, scientific_name='Callipogon (Eoxenus) relictus')
        self.assertTrue(subject_document(species, self.document('', pages=[{'text': 'Callipogon relictus'}])))

    def test_plant_growth_is_habitat_evidence(self):
        self.assertTrue(relevant('habitat', 'Euryale ferox grows in freshwater ponds.'))
        self.assertTrue(relevant('habitat', '수심이 깊지도 않고 얕지도 않은 곳에서 자라며 물에 뜬다.'))

    def setUp(self):
        self.species = Species('sp_test', '산양', 'Naemorhedus caudatus', '포유류', 1, 'https://example.org/catalog')

    def document(self, text, **changes):
        record = {'document_title': '산양', 'is_subject': True,
            'pages': [{'text': '산양(학명: Naemorhedus caudatus)은 소과 동물이다.\n' + text, 'page_number': 3}],
            'source_url': 'https://ko.wikipedia.org/wiki/산양', 'revision_id': 123,
            'license': 'CC BY-SA 4.0', 'collected_at': '2026-10-22T00:00:00+00:00'}
        return record | changes

    def test_empty_and_placeholder_metadata_are_missing(self):
        species = replace(self.species, habitat='확인된 정보 없음', threats='미확인')
        self.assertEqual([r['status'] for r in analyze_coverage(species, [])], ['missing'] * 3)

    def test_real_metadata_is_available_with_provenance(self):
        species = replace(self.species, habitat='바위가 많은 산림에 서식한다.')
        record = analyze_coverage(species, [])[0]
        self.assertEqual(record['status'], 'available')
        self.assertEqual(record['evidence'][0]['source_url'], species.source_url)
        self.assertEqual(record['evidence'][0]['basis_date'], species.source_basis_date)

    def test_subject_sentences_are_related_not_verified_and_keep_source(self):
        doc = self.document('바위가 많은 산림에서 서식한다.\n한국 강원도 산지에 분포한다.\n서식지 파괴로 개체수가 감소하였다.')
        records = analyze_coverage(self.species, [doc])
        self.assertEqual([r['status'] for r in records], ['related'] * 3)
        for record in records:
            item = record['evidence'][0]
            self.assertIn(item['quote'], doc['pages'][0]['text'])
            self.assertEqual(item['revision_id'], 123)
            self.assertEqual(item['page_number'], 3)
            self.assertEqual(item['license'], 'CC BY-SA 4.0')

    def test_foreign_range_and_legal_grade_do_not_imply_coverage(self):
        doc = self.document('러시아와 중국에 분포한다.\n한국에서는 멸종위기 1급으로 지정하여 보호한다.')
        records = analyze_coverage(self.species, [doc])
        self.assertEqual([r['status'] for r in records], ['missing'] * 3)

    def test_unrelated_documents_and_wrong_scientific_name_are_excluded(self):
        doc = self.document('산림에서 서식한다. 한국에 분포한다. 밀렵으로 감소한다.', document_title='다른 동물', is_subject=False)
        wrong = self.document('한국 산림에서 서식한다.', pages=[{'text': '산양(학명: Capra hircus)은 한국 산림에 서식한다.'}])
        records = analyze_coverage(self.species, [doc, wrong])
        self.assertEqual([r['status'] for r in records], ['missing'] * 3)

    def test_unconfirmed_text_and_link_sections_do_not_count(self):
        doc = self.document('한국 분포는 확인되지 않았다.\n서식지 파괴의 피해는 확인할 수 없다.\n== 외부 링크 ==\n한국 산림에서 서식한다.\n서식지 파괴로 줄었다.')
        self.assertEqual([r['status'] for r in analyze_coverage(self.species, [doc])], ['missing'] * 3)

    def test_deduplication_and_no_mutation_of_saved_documents(self):
        doc = self.document('산림에서 서식한다.\n산림에서 서식한다.')
        before = str(doc)
        result = analyze_coverage(self.species, [doc, doc])
        self.assertEqual(len(result[0]['evidence']), 1)
        self.assertEqual(str(doc), before)


if __name__ == '__main__':
    unittest.main()
