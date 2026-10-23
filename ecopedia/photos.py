"""종 문서의 대표 사진과 파일별 이용 조건을 확인하고 영구 캐시한다."""
import html
import re
from urllib.parse import quote, urlparse

from .sources import SourceCache, WikipediaSource, now
from .errors import SourceError


def plain(value):
    return ' '.join(html.unescape(re.sub(r'<[^>]*>', '', value or '')).split())


def trusted_url(value, hosts):
    parsed = urlparse(value or '')
    return parsed.scheme == 'https' and parsed.hostname in hosts


class SpeciesPhotos:
    def __init__(self, settings, source=None, commons_source=None, wikidata_source=None):
        self.settings = settings
        self.cache = SourceCache(settings)
        self.source = source
        self.commons_source = commons_source
        self.wikidata_source = wikidata_source

    @staticmethod
    def key(species):
        return f'photo:v2:{species.species_id}:{species.korean_name}:{species.scientific_name}'

    def get_many(self, species_list):
        results = self.primary_many(species_list)
        for species in species_list:
            if results.get(species.species_id):
                continue
            key = f'photo-pd:v1:{species.species_id}:{species.scientific_name}'
            saved = self.cache.get(key)
            if saved is None:
                try:
                    saved = self.public_domain_photo(species)
                except SourceError:
                    # A failed optional lookup does not hide other cached photographs.
                    continue
                self.cache.put(key, saved)
            results[species.species_id] = saved
            if saved:
                continue
            key = f'photo-wikidata:v1:{species.species_id}:{species.scientific_name}'
            saved = self.cache.get(key)
            if saved is None:
                try:
                    saved = self.wikidata_photo(species)
                except SourceError:
                    continue
                self.cache.put(key, saved)
            results[species.species_id] = saved
        return results

    def wikidata_photo(self, species):
        key = f'photo-wikidata-candidates:v1:{species.species_id}:{species.scientific_name}'
        record = self.cache.get(key)
        if record is None:
            if self.wikidata_source is None:
                self.wikidata_source = WikipediaSource(self.settings)
                self.wikidata_source.api = 'https://www.wikidata.org/w/api.php'
            scientific = ' '.join(species.scientific_name.split())
            search = self.wikidata_source.request(action='wbsearchentities', search=scientific,
                language='en', type='item', limit=8)
            ids = list(dict.fromkeys(hit.get('id', '') for hit in search.get('search', [])
                                    if re.fullmatch(r'Q[1-9][0-9]*', hit.get('id', ''))))
            candidates = []
            if ids:
                payload = self.wikidata_source.request(action='wbgetentities', ids='|'.join(ids), props='claims')
                for qid in ids:
                    entity = payload.get('entities', {}).get(qid, {})
                    claims = entity.get('claims', {})
                    names = self.claim_values(claims, 'P225')
                    if not any(' '.join(name.split()).casefold() == scientific.casefold() for name in names):
                        continue
                    for filename in self.claim_values(claims, 'P18')[:3]:
                        if filename and '|' not in filename:
                            candidates.append({'entity_id': qid, 'filename': filename})
            record = {'candidates': candidates[:20], 'collected_at': now()}
            # Keep verified identity links if the subsequent file server call fails.
            self.cache.put(key, record)
        candidates = record['candidates']
        if not candidates:
            return {}
        if self.commons_source is None:
            self.commons_source = WikipediaSource(self.settings)
            self.commons_source.api = 'https://commons.wikimedia.org/w/api.php'
        payload = self.commons_source.request(action='query', redirects=1,
            titles='|'.join('File:' + item['filename'] for item in candidates),
            prop='imageinfo', iiprop='url|extmetadata|mime', iiurlwidth=640)
        query = payload.get('query', {})
        aliases = {item['from']: item['to'] for kind in ('normalized', 'redirects')
                   for item in query.get(kind, [])}
        pages = {page.get('title'): page for page in query.get('pages', [])}
        for candidate in candidates:
            title = 'File:' + candidate['filename']
            seen = set()
            while title in aliases and title not in seen:
                seen.add(title)
                title = aliases[title]
            page = pages.get(title, {})
            info = page.get('imageinfo', [{}])[0]
            photo = self.parse(info, candidate['filename'], species.korean_name)
            # This change expands discovery, not the user's PD/CC0 fallback policy.
            if photo and photo['license'].casefold() in ('public domain', 'cc0', 'cc0 1.0'):
                photo.update(is_fallback=True, discovery='wikidata',
                    wikidata_url='https://www.wikidata.org/wiki/' + candidate['entity_id'])
                return photo
        return {}

    @staticmethod
    def claim_values(claims, property_id):
        statements = sorted(claims.get(property_id, []), key=lambda claim: claim.get('rank') != 'preferred')
        values = []
        for claim in statements:
            if claim.get('rank') == 'deprecated':
                continue
            snak = claim.get('mainsnak', {})
            value = snak.get('datavalue', {}).get('value')
            if snak.get('snaktype') == 'value' and isinstance(value, str):
                values.append(value)
        return values

    def public_domain_photo(self, species):
        if self.commons_source is None:
            self.commons_source = WikipediaSource(self.settings)
            self.commons_source.api = 'https://commons.wikimedia.org/w/api.php'
        scientific = ' '.join(species.scientific_name.split())
        payload = self.commons_source.request(action='query', generator='search',
            gsrsearch=f'"{scientific}" filetype:bitmap', gsrnamespace=6, gsrlimit=20,
            prop='imageinfo', iiprop='url|extmetadata|mime', iiurlwidth=640,
            iiextmetadatafilter='Artist|Credit|LicenseShortName|LicenseUrl|Copyrighted|AttributionRequired|Restrictions|ImageDescription|ObjectName|Categories')
        pages = sorted(payload.get('query', {}).get('pages', []), key=lambda p: p.get('index', 999))
        for page in pages:
            info = page.get('imageinfo', [{}])[0]
            metadata = info.get('extmetadata', {})
            # Search snippets alone are insufficient evidence of species identity.
            identity = ' '.join([page.get('title', '').replace('_', ' ')] +
                [plain(metadata.get(field, {}).get('value', '')).replace('_', ' ')
                 for field in ('ImageDescription', 'ObjectName', 'Categories')])
            if not re.search(r'(?<![\w])' + re.escape(scientific) + r'(?![\w])', identity, re.I):
                continue
            photo = self.parse(info, page.get('title', '').split(':', 1)[-1], species.korean_name)
            if photo and photo['license'].casefold() in ('public domain', 'cc0', 'cc0 1.0'):
                photo['is_fallback'] = True
                return photo
        return {}

    def primary_many(self, species_list):
        results, pending = {}, []
        for species in species_list:
            saved = self.cache.get(self.key(species))
            if saved is None:
                pending.append(species)
            else:
                results[species.species_id] = saved
        if not pending:
            return results
        source = self.source or WikipediaSource(self.settings)
        # Batch requests avoid an HTTP request for every result card.
        for start in range(0, len(pending), 20):
            batch = pending[start:start + 20]
            payload = source.request(action='query', titles='|'.join(s.korean_name for s in batch),
                redirects=1, prop='extracts|pageprops|pageimages', exintro=1, explaintext=1,
                exlimit='max', piprop='name', pilicense='free', pilimit=20)
            query = payload.get('query', {})
            aliases = {item['from']: item['to'] for kind in ('normalized', 'redirects')
                       for item in query.get(kind, [])}
            pages = {p.get('title'): p for p in query.get('pages', [])}
            candidates = {}
            for species in batch:
                title = species.korean_name
                seen = set()
                while title in aliases and title not in seen:
                    seen.add(title)
                    title = aliases[title]
                page = pages.get(title, {})
                summary = plain(page.get('extract', '')).casefold()
                scientific = re.escape(' '.join(species.scientific_name.casefold().split()))
                # Namesakes / broader taxa must not silently receive another animal's photo.
                matches = re.search(r'(?<![\w])' + scientific + r'(?![\w])', summary)
                if (matches and 'missing' not in page and page.get('ns', 0) == 0
                        and 'disambiguation' not in page.get('pageprops', {}) and page.get('pageimage')):
                    candidates[species.species_id] = (page['pageimage'], title)
            files = {}
            if candidates:
                info = source.request(action='query',
                    titles='|'.join('File:' + name for name in sorted({v[0] for v in candidates.values()})),
                    prop='imageinfo', iiprop='url|extmetadata|mime', iiurlwidth=640)
                for page in info.get('query', {}).get('pages', []):
                    name = page.get('title', '').split(':', 1)[-1].replace('_', ' ')
                    files[name] = page.get('imageinfo', [{}])[0]
            for species in batch:
                photo = {}
                if species.species_id in candidates:
                    filename, title = candidates[species.species_id]
                    photo = self.parse(files.get(filename.replace('_', ' '), {}), filename, title)
                # Empty successful results are cached too; connection failures never reach here.
                self.cache.put(self.key(species), photo)
                results[species.species_id] = photo
        return results

    @staticmethod
    def parse(info, filename, title):
        metadata = info.get('extmetadata', {})
        value = lambda name: plain(metadata.get(name, {}).get('value', ''))
        license_name = value('LicenseShortName')
        license_url = value('LicenseUrl')
        if license_url.startswith('//'):
            license_url = 'https:' + license_url
        if license_name == 'KOGL Type 1':
            # Only the attribution-only type; do not infer permission for types 2–4.
            if license_url in ('http://www.kogl.or.kr/info/licenseType1.do',
                               'https://www.kogl.or.kr/info/licenseType1.do'):
                license_url = 'https://www.kogl.or.kr/info/licenseType1.do'
            else:
                return {}
        if license_name.casefold() == 'public domain' and not license_url:
            license_url = 'https://commons.wikimedia.org/wiki/Commons:Public_domain'
        is_public = license_name.casefold() in ('public domain', 'cc0', 'cc0 1.0')
        if license_name.casefold().startswith('cc0') and not license_url:
            license_url = 'https://creativecommons.org/publicdomain/zero/1.0/'
        if is_public and value('AttributionRequired').casefold() == 'true':
            return {}
        if is_public and value('Copyrighted').casefold() == 'true':
            return {}
        artist = value('Artist')
        if is_public and not artist:
            artist = '촬영자 미상 (원문 참조)'
        image_url = info.get('thumburl', '')
        source_url = info.get('descriptionurl', '')
        allowed = re.fullmatch(r'CC BY(?:-SA)? [1-4]\.0|CC0(?: 1\.0)?|Public domain|KOGL Type 1', license_name, re.I)
        if (not allowed or not artist or value('Restrictions')
                or info.get('mime') not in ('image/jpeg', 'image/png', 'image/webp')
                or not trusted_url(image_url, {'upload.wikimedia.org', 'thumb.wikimedia.org'})
                or not trusted_url(source_url, {'commons.wikimedia.org', 'ko.wikipedia.org'})
                or not trusted_url(license_url, {'creativecommons.org', 'commons.wikimedia.org', 'www.kogl.or.kr'})):
            return {}
        return {'url': image_url, 'file_title': filename, 'artist': artist,
                'credit': value('Credit'), 'license': license_name, 'license_url': license_url,
                'source_url': source_url, 'article_url': 'https://ko.wikipedia.org/wiki/' + quote(title),
                'collected_at': now()}


def rights_label(photo):
    license_name = photo.get('license', '').casefold()
    if license_name == 'public domain':
        return '저작권 제한 없는 사진 · 퍼블릭 도메인 (원문 표기 기준)'
    if license_name in ('cc0', 'cc0 1.0'):
        return '저작권 제한 없는 사진 · CC0 (권리 포기 선언)'
    return ''
