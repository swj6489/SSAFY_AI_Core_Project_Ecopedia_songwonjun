import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from ecopedia.catalog import Species
from ecopedia.config import Settings
from ecopedia.errors import SourceError
from ecopedia.photos import SpeciesPhotos, rights_label


def image_info(**changes):
    result = {'title': 'File:Cat.jpg', 'imageinfo': [{
        'thumburl': 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Cat.jpg/640px-Cat.jpg',
        'descriptionurl': 'https://commons.wikimedia.org/wiki/File:Cat.jpg',
        'mime': 'image/jpeg', 'extmetadata': {
            'Artist': {'value': '<a href="/wiki/User:Photographer">촬영자</a>'},
            'Credit': {'value': 'Own work'},
            'LicenseShortName': {'value': 'CC BY-SA 4.0'},
            'LicenseUrl': {'value': 'https://creativecommons.org/licenses/by-sa/4.0/'}}}]}
    result['imageinfo'][0].update(changes)
    return result


class PhotoTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.settings = Settings(root=Path(folder.name))
        self.species = Species('sp_test', '삵', 'Prionailurus bengalensis', '포유류', 2, '')

    def source(self, summary='삵(Prionailurus bengalensis)은 고양이과 동물이다.', **page_changes):
        page = {'title': '삵', 'ns': 0, 'extract': summary, 'pageimage': 'Cat.jpg'}
        page.update(page_changes)
        source = Mock()
        source.request.side_effect = [
            {'query': {'pages': [page]}}, {'query': {'pages': [image_info()]}}]
        return source

    def test_photo_attribution_and_permanent_cache(self):
        source = self.source()
        photos = SpeciesPhotos(self.settings, source)
        result = photos.get_many([self.species])['sp_test']
        self.assertEqual(result['artist'], '촬영자')
        self.assertEqual(result['license'], 'CC BY-SA 4.0')
        self.assertIn('commons.wikimedia.org', result['source_url'])
        self.assertEqual(source.request.call_count, 2)
        offline = Mock()
        offline.request.side_effect = AssertionError('캐시 재수집 금지')
        again = SpeciesPhotos(self.settings, offline).get_many([self.species])
        self.assertEqual(again['sp_test'], result)
        offline.request.assert_not_called()

    def test_wrong_species_and_disambiguation_do_not_get_photos(self):
        for change in ({'extract': '다른 종 Felis catus'}, {'pageprops': {'disambiguation': ''}}):
            with self.subTest(change=change):
                source = self.source(**change)
                photos = SpeciesPhotos(self.settings, source)
                photos.cache.get = Mock(return_value=None)
                self.assertEqual(photos.primary_many([self.species])['sp_test'], {})
                self.assertEqual(source.request.call_count, 1)

    def test_missing_photo_is_cached_and_network_failure_is_not(self):
        source = self.source(pageimage='')
        photos = SpeciesPhotos(self.settings, source)
        self.assertEqual(photos.primary_many([self.species])['sp_test'], {})
        photos.primary_many([self.species])
        self.assertEqual(source.request.call_count, 1)
        photos.cache.get = Mock(return_value=None)
        photos.cache.put = Mock()
        source.request.side_effect = SourceError('오프라인')
        with self.assertRaises(SourceError):
            photos.primary_many([self.species])
        photos.cache.put.assert_not_called()

    def test_reject_unlicensed_icons_or_untrusted_urls(self):
        valid = image_info()['imageinfo'][0]
        self.assertTrue(SpeciesPhotos.parse(valid, 'Cat.jpg', '삵'))
        for changes in ({'mime': 'image/svg+xml'}, {'thumburl': 'https://example.com/cat.jpg'},
                        {'extmetadata': {}},
                        {'extmetadata': {**valid['extmetadata'], 'LicenseShortName': {'value': 'Fair use'}}},
                        {'extmetadata': {**valid['extmetadata'], 'Restrictions': {'value': 'restricted'}}}):
            with self.subTest(changes=changes):
                self.assertEqual(SpeciesPhotos.parse({**valid, **changes}, 'Cat.jpg', '삵'), {})

    def test_batch_and_redirect_identity(self):
        other = Species('sp_other', '살쾡이', self.species.scientific_name, '포유류', 2, '')
        source = self.source()
        responses = list(source.request.side_effect)
        responses[0]['query']['redirects'] = [{'from': '살쾡이', 'to': '삵'}]
        source.request.side_effect = responses
        result = SpeciesPhotos(self.settings, source).get_many([self.species, other])
        self.assertTrue(result['sp_test'])
        self.assertTrue(result['sp_other'])
        self.assertEqual(source.request.call_count, 2)

    def test_current_thumbnail_host_and_kogl_type_one_only(self):
        info = image_info()['imageinfo'][0]
        info['thumburl'] = info['thumburl'].replace('upload.wikimedia.org', 'thumb.wikimedia.org')
        info['extmetadata']['LicenseShortName']['value'] = 'KOGL Type 1'
        info['extmetadata']['LicenseUrl']['value'] = 'http://www.kogl.or.kr/info/licenseType1.do'
        photo = SpeciesPhotos.parse(info, 'Cat.jpg', '삵')
        self.assertEqual(photo['license'], 'KOGL Type 1')
        self.assertEqual(photo['license_url'], 'https://www.kogl.or.kr/info/licenseType1.do')
        info['extmetadata']['LicenseShortName']['value'] = 'KOGL Type 3'
        self.assertEqual(SpeciesPhotos.parse(info, 'Cat.jpg', '삵'), {})

    def test_public_domain_fallback_and_independent_permanent_cache(self):
        info = image_info()
        meta = info['imageinfo'][0]['extmetadata']
        meta['LicenseShortName']['value'] = 'Public domain'
        meta.pop('LicenseUrl')
        meta.pop('Artist')
        meta['ImageDescription'] = {'value': 'Prionailurus bengalensis in the wild'}
        commons = Mock()
        commons.request.return_value = {'query': {'pages': [info]}}
        photos = SpeciesPhotos(self.settings, self.source(pageimage=''), commons)
        result = photos.get_many([self.species])['sp_test']
        self.assertTrue(result['is_fallback'])
        self.assertIn('퍼블릭 도메인', rights_label(result))
        self.assertEqual(result['artist'], '촬영자 미상 (원문 참조)')
        offline = Mock()
        offline.request.side_effect = AssertionError('재수집 금지')
        again = SpeciesPhotos(self.settings, offline, offline).get_many([self.species])
        self.assertEqual(again['sp_test'], result)
        offline.request.assert_not_called()

    def test_fallback_rejects_wrong_species_and_copyrighted_photos(self):
        copyrighted = image_info()
        copyrighted['imageinfo'][0]['extmetadata']['ImageDescription'] = {'value': self.species.scientific_name}
        wrong = image_info()
        wrong['imageinfo'][0]['extmetadata']['LicenseShortName']['value'] = 'CC0'
        wrong['imageinfo'][0]['extmetadata']['ImageDescription'] = {'value': 'Felis catus'}
        commons = Mock()
        commons.request.return_value = {'query': {'pages': [copyrighted, wrong]}}
        wikidata = Mock()
        wikidata.request.return_value = {'search': []}
        photos = SpeciesPhotos(self.settings, self.source(pageimage=''), commons, wikidata)
        self.assertEqual(photos.get_many([self.species])['sp_test'], {})
        photos.get_many([self.species])
        commons.request.assert_called_once()

    def test_cc0_label_is_not_applied_to_cc_by_and_failures_retry(self):
        self.assertEqual(rights_label({'license': 'CC BY-SA 4.0'}), '')
        self.assertIn('CC0', rights_label({'license': 'CC0 1.0'}))
        commons = Mock()
        commons.request.side_effect = SourceError('오프라인')
        photos = SpeciesPhotos(self.settings, self.source(pageimage=''), commons)
        self.assertEqual(photos.get_many([self.species])['sp_test'], {})
        photos.get_many([self.species])
        self.assertEqual(commons.request.call_count, 2)


    @staticmethod
    def claim(value, rank='normal'):
        return {'rank': rank, 'mainsnak': {'snaktype': 'value', 'datavalue': {'value': value}}}

    def wikidata(self, scientific=None):
        source = Mock()
        source.request.side_effect = [
            {'search': [{'id': 'Q123'}]},
            {'entities': {'Q123': {'claims': {
                'P225': [self.claim(scientific or self.species.scientific_name)],
                'P18': [self.claim('Cat.jpg')]}}}}]
        return source

    def public_image(self):
        page = image_info()
        page['imageinfo'][0]['extmetadata']['LicenseShortName']['value'] = 'CC0'
        page['imageinfo'][0]['extmetadata']['LicenseUrl']['value'] = 'https://creativecommons.org/publicdomain/zero/1.0/'
        return page

    def test_wikidata_extends_cached_missing_photo_without_recollection(self):
        wikidata = self.wikidata()
        commons = Mock()
        commons.request.return_value = {'query': {'pages': [self.public_image()]}}
        offline = Mock()
        offline.request.side_effect = AssertionError('기존 검색 재수집 금지')
        photos = SpeciesPhotos(self.settings, offline, commons, wikidata)
        photos.cache.put(photos.key(self.species), {})
        photos.cache.put(f'photo-pd:v1:{self.species.species_id}:{self.species.scientific_name}', {})
        result = photos.get_many([self.species])['sp_test']
        self.assertEqual(result['discovery'], 'wikidata')
        self.assertEqual(result['wikidata_url'], 'https://www.wikidata.org/wiki/Q123')
        self.assertIn('CC0', rights_label(result))
        offline.request.assert_not_called()
        again = SpeciesPhotos(self.settings, offline, offline, offline).get_many([self.species])
        self.assertEqual(again['sp_test'], result)
        offline.request.assert_not_called()

    def test_wikidata_rejects_other_taxon_and_deprecated_names(self):
        commons = Mock()
        photos = SpeciesPhotos(self.settings, commons_source=commons, wikidata_source=self.wikidata('Felis catus'))
        self.assertEqual(photos.wikidata_photo(self.species), {})
        commons.request.assert_not_called()
        self.assertEqual(SpeciesPhotos.claim_values({'P225': [self.claim(self.species.scientific_name, 'deprecated')]}, 'P225'), [])
        self.assertEqual(SpeciesPhotos.claim_values({'P18': [{'mainsnak': {'snaktype': 'novalue'}}]}, 'P18'), [])

    def test_wikidata_does_not_expand_fallback_license_policy(self):
        commons = Mock()
        commons.request.return_value = {'query': {'pages': [image_info()]}}
        photos = SpeciesPhotos(self.settings, commons_source=commons, wikidata_source=self.wikidata())
        self.assertEqual(photos.wikidata_photo(self.species), {})

    def test_wikidata_file_retry_reuses_verified_entity_candidates(self):
        wikidata = self.wikidata()
        commons = Mock()
        commons.request.side_effect = [SourceError('파일 서버 실패'), {'query': {'pages': [self.public_image()]}}]
        photos = SpeciesPhotos(self.settings, commons_source=commons, wikidata_source=wikidata)
        with self.assertRaises(SourceError):
            photos.wikidata_photo(self.species)
        self.assertEqual(photos.wikidata_photo(self.species)['discovery'], 'wikidata')
        self.assertEqual(wikidata.request.call_count, 2)
        self.assertEqual(commons.request.call_count, 2)


if __name__ == '__main__':
    unittest.main()
