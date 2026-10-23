import os
import unittest
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

from ecopedia.catalog import Catalog
from ecopedia.config import ROOT


class UiTests(unittest.TestCase):
    def test_recommended_question_prefills_without_sending_and_tracks_species(self):
        import streamlit as st
        st.cache_resource.clear()
        self.addCleanup(st.cache_resource.clear)
        service = Mock()
        service.store.count.return_value = 0
        service.answer.return_value = {'answer': '시험 답변', 'used_evidence': [], 'elapsed_seconds': 0}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), patch('ecopedia.service.EcoService', return_value=service):
            app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
            sid = app.session_state['selected_species_id']
            app.button(key=f'recommend_{sid}_basic').click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(app.chat_input[0].proto.set_value)
            self.assertIn('국명, 학명', app.chat_input[0].proto.value)
            self.assertEqual(app.session_state['histories'][sid], [])
            service.answer.assert_not_called()
            service.collector.ensure.assert_not_called()
            app.text_input(key='name_filter').input('삵').run()
            new_sid = app.session_state['selected_species_id']
            app.button(key=f'recommend_{new_sid}_basic').click().run()
            self.assertIn('삵의 국명', app.chat_input[0].proto.value)
            app.chat_input[0].set_value('삵의 등급은?').run()
            service.answer.assert_called_once()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state['histories'][new_sid][-1]['content'], '시험 답변')

    def setUp(self):
        patcher = patch('ecopedia.photos.SpeciesPhotos.get_many', return_value={})
        self.photos = patcher.start()
        self.addCleanup(patcher.stop)

    def start(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
        self.assertEqual(len(app.exception), 0)
        return app

    def test_theme_and_profile_layout_are_present(self):
        app = self.start()
        markup = '\n'.join(item.value for item in app.markdown)
        self.assertIn('eco-hero-count', markup)
        self.assertIn('eco-badges', markup)
        self.assertIn('eco-empty-photo', markup)
        self.assertIn('@media (max-width:700px)', markup)
        self.assertTrue(any('SPECIES PROFILE' in item.value for item in app.caption))
        self.assertEqual(len(app.exception), 0)

    def test_no_key_browsing_and_filtering(self):
        app = self.start()
        self.assertEqual(app.title[0].value, '🌿 EcoPedia')
        self.assertTrue(app.chat_input[0].disabled)
        app.text_input(key='name_filter').input('삵').run()
        self.assertEqual(app.subheader[0].value, '삵')
        app.text_input(key='name_filter').input('존재하지않는종').run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('조건에 맞는 종이 없습니다' in x.value for x in app.info))

    def test_card_navigation_resets_filters_and_separate_history(self):
        app = self.start()
        catalog = Catalog(ROOT / 'data' / 'species.json')
        target = next(s for s in catalog.items if s.korean_name == '삵')
        first = catalog.items[0]
        app.session_state['histories'] = {first.species_id: [{'role':'user','content':'첫 종 전용 질문'}]}
        app.session_state['search_results'] = [{'species_id':target.species_id,'reason':'시험 결과'}]
        app.text_input(key='name_filter').input(first.korean_name).run()
        app.radio(key='page').set_value('자연어 조건 탐색').run()
        app.button(key=f'open_{target.species_id}').click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.subheader[0].value, target.korean_name)
        self.assertEqual(app.radio(key='page').value, '종별 질문')
        self.assertEqual(app.text_input(key='name_filter').value, '')
        self.assertNotIn('첫 종 전용 질문', [m.value for m in app.markdown])
        self.assertEqual(len(app.session_state['histories'][first.species_id]), 1)

    def test_explore_and_compare_are_independent_pages(self):
        app = self.start()
        app.text_input(key='name_filter').input('삵').run()
        app.radio(key='page').set_value('자연어 조건 탐색').run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.subheader[0].value, '전체 종 자연어 조건 탐색')
        self.assertEqual(len(app.chat_input), 0)
        self.assertFalse(any(x.label == '국명 또는 학명' for x in app.text_input))
        self.assertTrue(any('전체 282종에서 검색' in x.value for x in app.markdown))
        app.radio(key='page').set_value('두 종 생태 비교').run()
        self.assertEqual(app.subheader[0].value, '두 종 생태 비교')
        app.radio(key='page').set_value('종별 질문').run()
        self.assertEqual(app.subheader[0].value, '삵')

    def test_photos_in_species_page_and_search_cards(self):
        photo = {'url': 'https://upload.wikimedia.org/example.jpg', 'artist': '촬영자',
                 'license': 'CC BY-SA 4.0', 'license_url': 'https://creativecommons.org/licenses/by-sa/4.0/',
                 'source_url': 'https://commons.wikimedia.org/wiki/File:Example.jpg'}
        self.photos.side_effect = lambda items: {s.species_id: photo for s in items}
        app = self.start()
        self.assertEqual(len(app.get('image')), 1)
        self.assertTrue(any('촬영자' in x.value and 'CC BY-SA' in x.value for x in app.caption))
        sid = app.session_state['selected_species_id']
        app.session_state['search_results'] = [{'species_id': sid, 'reason': '시험 결과'}]
        app.radio(key='page').set_value('자연어 조건 탐색').run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.get('image')), 1)

    def test_public_domain_photo_is_labeled(self):
        photo = {'url': 'https://upload.wikimedia.org/example.jpg', 'artist': '촬영자 미상',
                 'license': 'Public domain', 'license_url': 'https://commons.wikimedia.org/wiki/Commons:Public_domain',
                 'source_url': 'https://commons.wikimedia.org/wiki/File:Example.jpg', 'is_fallback': True}
        self.photos.side_effect = lambda items: {s.species_id: photo for s in items}
        app = self.start()
        self.assertTrue(any('저작권 제한 없는 사진' in x.value for x in app.caption))
        self.assertTrue(any('대체 사진' in x.value for x in app.caption))
        sid = app.session_state['selected_species_id']
        app.session_state['search_results'] = [{'species_id': sid, 'reason': '시험 결과'}]
        app.radio(key='page').set_value('자연어 조건 탐색').run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.get('image')), 1)
        self.assertTrue(any('저작권 제한 없는 사진' in x.value for x in app.caption))

    def test_explore_keyword_composition_toggle_and_reset(self):
        app = self.start()
        app.radio(key='page').set_value('자연어 조건 탐색').run()
        catalog = Catalog(ROOT / 'data' / 'species.json')
        for group in {s.taxon_group for s in catalog.items}:
            self.assertEqual(app.button(key=f'keyword_group_{group}').label, group)
        app.button(key='keyword_grade_2급').click().run()
        self.assertEqual(app.text_input(key='explore_condition').value, '2급 찾아줘')
        app.button(key='keyword_group_포유류').click().run()
        self.assertEqual(app.text_input(key='explore_condition').value, '2급 포유류 찾아줘')
        app.button(key='keyword_grade_1급').click().run()
        self.assertEqual(app.text_input(key='explore_condition').value, '1급 포유류 찾아줘')
        app.button(key='keyword_group_포유류').click().run()
        self.assertEqual(app.text_input(key='explore_condition').value, '1급 찾아줘')
        app.text_input(key='explore_condition').input('2급 어류 찾아줘').run()
        self.assertEqual(app.text_input(key='explore_condition').value, '2급 어류 찾아줘')
        app.session_state['search_results'] = []
        app.button(key='clear_explore_keywords').click().run()
        self.assertEqual(app.text_input(key='explore_condition').value, '')
        self.assertEqual(app.session_state['explore_grade'], '')
        self.assertEqual(app.session_state['explore_group'], '')
        self.assertNotIn('search_results', app.session_state)
        self.assertEqual(len(app.exception), 0)


    def test_comparison_has_independent_search_and_filters(self):
        app = self.start()
        catalog = Catalog(ROOT / 'data' / 'species.json')
        wildcat = next(s for s in catalog.items if s.korean_name == '삵')
        goral = next(s for s in catalog.items if s.korean_name == '산양')
        app.radio(key='page').set_value('두 종 생태 비교').run()
        self.assertEqual(len(app.multiselect), 0)
        self.assertIsNone(app.selectbox(key='compare_second_picker').value)
        app.text_input(key='compare_first_name').input('삵').run()
        app.selectbox(key='compare_first_picker').select(wildcat.species_id).run()
        app.selectbox(key='compare_second_group').select('포유류').run()
        app.selectbox(key='compare_second_grade').select(1).run()
        app.text_input(key='compare_second_name').input('Naemorhedus').run()
        app.selectbox(key='compare_second_picker').select(goral.species_id).run()
        self.assertEqual(app.selectbox(key='compare_first_picker').value, wildcat.species_id)
        self.assertEqual(app.selectbox(key='compare_second_picker').value, goral.species_id)
        self.assertTrue(any('삵 ↔ 산양' in x.value for x in app.markdown))
        app.text_input(key='compare_second_name').input('존재하지않는종').run()
        self.assertTrue(app.selectbox(key='compare_second_picker').disabled)
        self.assertIsNone(app.selectbox(key='compare_second_picker').value)
        self.assertEqual(app.selectbox(key='compare_first_picker').value, wildcat.species_id)
        self.assertEqual(len(app.exception), 0)

    def test_comparison_prevents_selecting_the_same_species(self):
        app = self.start()
        app.radio(key='page').set_value('두 종 생태 비교').run()
        first = app.selectbox(key='compare_first_picker').value
        catalog = Catalog(ROOT / 'data' / 'species.json')
        app.text_input(key='compare_second_name').input(catalog.get(first).korean_name).run()
        self.assertTrue(app.selectbox(key='compare_second_picker').disabled)
        self.assertIsNone(app.selectbox(key='compare_second_picker').value)
        self.assertEqual(len(app.exception), 0)


    def test_theme_toggle_preserves_search_and_navigation(self):
        app = self.start()
        self.assertEqual(app.radio(key='appearance').value, '라이트')
        app.text_input(key='name_filter').input('삵').run()
        selected = app.session_state['selected_species_id']
        app.radio(key='appearance').set_value('다크').run()
        self.assertEqual(app.session_state['selected_species_id'], selected)
        self.assertEqual(app.text_input(key='name_filter').value, '삵')
        markup = '\n'.join(item.value for item in app.markdown)
        self.assertIn('--eco-bg:#111b17', markup)
        self.assertIn('--eco-scheme:dark', markup)
        app.radio(key='page').set_value('자연어 조건 탐색').run()
        app.button(key='keyword_grade_2급').click().run()
        app.button(key='keyword_group_포유류').click().run()
        app.radio(key='appearance').set_value('라이트').run()
        self.assertEqual(app.radio(key='page').value, '자연어 조건 탐색')
        self.assertEqual(app.text_input(key='explore_condition').value, '2급 포유류 찾아줘')
        markup = '\n'.join(item.value for item in app.markdown)
        self.assertIn('--eco-bg:#f6f7f2', markup)
        self.assertNotIn('--eco-bg:#111b17', markup)
        self.assertEqual(len(app.exception), 0)


    def test_start_recovers_stale_ui_module_missing_new_helpers(self):
        import importlib
        from ecopedia import ui
        del ui.render_sidebar_brand
        del ui.sidebar_section
        try:
            app = self.start()
            self.assertEqual(app.title[0].value, '🌿 EcoPedia')
            self.assertTrue(callable(ui.render_sidebar_brand))
            self.assertTrue(callable(ui.sidebar_section))
            app.radio(key='appearance').set_value('다크').run()
            self.assertEqual(len(app.exception), 0)
        finally:
            importlib.reload(ui)


    def test_information_status_and_provenance_without_api_key(self):
        catalog = Catalog(ROOT / 'data' / 'species.json')
        first = catalog.items[0]
        document = {'document_title': first.korean_name, 'is_subject': True,
            'source_url': 'https://example.org/species', 'license': 'CC BY-SA 4.0',
            'pages': [{'text': f'{first.korean_name}({first.scientific_name})의 설명이다.\n한국 산림에서 서식한다.\n서식지 파괴로 개체수가 감소하였다.'}]}
        with patch('ecopedia.sources.SourceCache.documents', return_value=[document]):
            app = self.start()
        markup = '\n'.join(x.value for x in app.markdown)
        self.assertIn('정보 확보 상태', markup)
        self.assertIn('서식 환경', markup)
        self.assertIn('국내 분포', markup)
        self.assertIn('주요 위협 요인', markup)
        self.assertEqual(markup.count('◐ 관련 근거 있음'), 3)
        self.assertTrue(any('사실 검증 완료' in x.value for x in app.caption))
        self.assertTrue(any('한국 산림에서 서식한다.' in x.value for x in app.markdown))
        self.assertTrue(app.chat_input[0].disabled)


if __name__ == '__main__':
    unittest.main()
