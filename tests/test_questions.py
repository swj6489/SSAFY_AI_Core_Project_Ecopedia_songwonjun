import unittest

from ecopedia.catalog import Species
from ecopedia.questions import recommended_questions


class RecommendedQuestionsTests(unittest.TestCase):
    def setUp(self):
        self.species = Species('test', '삵', 'Prionailurus bengalensis', '포유류', 2, '')

    def test_basic_questions_always_available(self):
        items = recommended_questions(self.species, [])
        self.assertEqual([item[0] for item in items], ['basic', 'overview'])
        self.assertTrue(all('삵' in item[2] for item in items))

    def test_only_supported_ecology_fields_are_suggested(self):
        items = recommended_questions(self.species, [
            {'field': 'habitat', 'status': 'extracted'},
            {'field': 'domestic_distribution', 'status': 'missing'},
            {'field': 'threats', 'status': 'related'},
        ])
        self.assertEqual([item[0] for item in items], ['basic', 'overview', 'habitat', 'threats'])

    def test_distribution_question_distinguishes_historical_records(self):
        items = recommended_questions(self.species, [{'field': 'domestic_distribution', 'status': 'available'}])
        self.assertIn('과거 기록', items[-1][2])
