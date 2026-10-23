"""생태 정보를 기본 목록과 분리 보관하고 원문 인용을 검증한다."""
import hashlib
import json
import re

from . import prompts
from .coverage import FIELDS, UNCERTAIN, relevant, subject_document
from .errors import AppError
from .sources import SourceCache, WikipediaSource, EnglishWikipediaSource, now


LABELS = dict(FIELDS)
HISTORICAL = re.compile(r'과거|예전|옛날|이전에는|서식하였|서식했|분포하였|멸종하였|19\d{2}년|formerly|historically|used to|extirpated|\b19\d{2}\b', re.I)


def fingerprint(document):
    body = {k: document.get(k) for k in ('document_id', 'revision_id', 'pages', 'source_url', 'license')}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def claim_quote(document, claim):
    index = claim.get('page_index')
    quote = claim.get('quote', '')
    if type(index) is not int or not 0 <= index < len(document.get('pages', [])):
        raise ValueError('page index')
    if not isinstance(quote, str) or not 7 <= len(quote.strip()) <= 1500:
        raise ValueError('quote length')
    pattern = r'\s+'.join(re.escape(token) for token in quote.strip().split())
    match = re.search(pattern, document['pages'][index].get('text', ''))
    if not match:
        raise ValueError('quote not in source')
    original = match.group()
    field = claim.get('field')
    if field not in LABELS or UNCERTAIN.search(original) or not relevant(field, original):
        raise ValueError('unsupported field evidence')
    return original


def validate_claims(species, document, payload):
    if not subject_document(species, document):
        raise ValueError('species identity')
    if not isinstance(payload.get('claims'), list):
        raise ValueError('claims array')
    accepted, rejected, seen, counts = [], [], set(), {}
    for claim in payload['claims'][:30]:
        try:
            if not isinstance(claim, dict):
                raise ValueError('claim object')
            quote = claim_quote(document, claim)
            field = claim['field']
            if claim.get('time_scope') not in ('historical', 'unspecified'):
                raise ValueError('invalid time scope')
            if (field, quote) in seen or counts.get(field, 0) >= 3:
                continue
            seen.add((field, quote))
            counts[field] = counts.get(field, 0) + 1
            scope = 'historical' if HISTORICAL.search(quote) or claim.get('time_scope') == 'historical' else 'unspecified'
            accepted.append({'field': field, 'quote': quote, 'page_index': claim['page_index'], 'time_scope': scope})
        except ValueError as exc:
            rejected.append({'reason': str(exc), 'field': str(claim.get('field', '')) if isinstance(claim, dict) else '',
                             'quote': str(claim.get('quote', ''))[:1500] if isinstance(claim, dict) else ''})
    return accepted, rejected


class EcologyFacts:
    def __init__(self, settings, llm=None, store=None, source=None):
        self.settings, self.llm, self.store, self._source = settings, llm, store, source
        self.cache = SourceCache(settings)
        self._taxon_source = None

    @staticmethod
    def key(species, document):
        return f'ecology:v1:{species.species_id}:{document["document_id"]}:{fingerprint(document)}'

    def records(self, species):
        result = []
        for document in self.cache.documents(species.species_id):
            if not document.get('document_id') or not subject_document(species, document):
                continue
            record = self.cache.get(self.key(species, document))
            if not record:
                continue
            try:
                claims, _ = validate_claims(species, document, record)
            except ValueError:
                continue
            for claim in claims:
                page = document['pages'][claim['page_index']]
                result.append(claim | {'document_id': document['document_id'],
                    'title': document['document_title'], 'source_url': document.get('source_url', ''),
                    'license': document.get('license', ''), 'revision_id': document.get('revision_id', ''),
                    'page_number': page.get('page_number'), 'collected_at': document.get('collected_at', ''),
                    'extracted_at': record.get('extracted_at', ''), 'validation': 'source_quote_match'})
        return result

    def text(self, species):
        rows = []
        for item in self.records(species):
            scope = '과거 기록' if item['time_scope'] == 'historical' else '시점 미확인'
            rows.append(f"{LABELS[item['field']]} ({scope}): {item['quote']}\n출처: {item['source_url']}")
        return '\n'.join(rows)

    def enrich_species(self, species, progress=lambda _: None, retry_rejected=False, retry_incomplete=False):
        accepted = rejected = calls = 0
        for document in self.cache.documents(species.species_id):
            if not document.get('document_id') or not subject_document(species, document):
                continue
            key = self.key(species, document)
            record = self.cache.get(key)
            incomplete = record is not None and set(c['field'] for c in record['claims']) != set(LABELS)
            if record is None or (retry_rejected and record.get('rejected')) or (retry_incomplete and incomplete):
                if self.llm is None:
                    raise AppError('생태 정보 추출을 위한 AI 연결이 없습니다.')
                progress(f'{species.korean_name}: 저장된 문서에서 생태 정보를 원문과 대조하고 있습니다.')
                remaining, pages = 30000, []
                for index, page in enumerate(document['pages']):
                    if remaining <= 0:
                        break
                    text = page.get('text', '')[:remaining]
                    pages.append({'page_index': index, 'text': text})
                    remaining -= len(text)
                hints = []
                from .coverage import sentences
                for quote, _ in sentences(document):
                    for field in LABELS:
                        if relevant(field, quote) and sum(h['field'] == field for h in hints) < 5:
                            hints.append({'field': field, 'quote': quote})
                payload = self.llm.ask(prompts.ECOLOGY, {'species': species.text(), 'pages': pages,
                    'candidate_sentences_to_review': hints})
                calls += 1
                try:
                    claims, invalid = validate_claims(species, document, payload)
                except ValueError as exc:
                    raise AppError('생태 정보 추출 형식을 검증하지 못했습니다. 다음 실행에서 다시 시도할 수 있습니다.') from exc
                if record:
                    claims, _ = validate_claims(species, document, {'claims': claims + record['claims']})
                record = {'species_id': species.species_id, 'claims': claims, 'rejected': invalid,
                    'extracted_at': now(), 'source_fingerprint': fingerprint(document)}
                self.cache.put(key, record)
            accepted += len(record['claims'])
            rejected += len(record.get('rejected', []))
            if self.store and record['claims']:
                self.store.index_document(species.species_id, self.index_source(species, document, record))
        return {'species_id': species.species_id, 'claims': accepted, 'rejected': rejected, 'llm_calls': calls}

    @staticmethod
    def index_source(species, document, record):
        page_lines = {}
        for claim in record['claims']:
            scope = '과거 기록' if claim['time_scope'] == 'historical' else '시점 미확인; 현재성 보장 없음'
            page_lines.setdefault(claim['page_index'], []).append(f"{LABELS[claim['field']]} ({scope}): {claim['quote']}")
        pages = []
        for index, lines in sorted(page_lines.items()):
            page = {'text': '\n'.join(lines)}
            if document['pages'][index].get('page_number'):
                page['page_number'] = document['pages'][index]['page_number']
            pages.append(page)
        return {'document_id': 'ecology-' + document['document_id'],
            'document_title': species.korean_name + ' 생태 정보 — ' + document['document_title'],
            'source_type': document['source_type'], 'source_url': document.get('source_url', ''),
            'license': document.get('license', ''), 'revision_id': document.get('revision_id', ''),
            'collected_at': document.get('collected_at', record['extracted_at']),
            'pages': pages, 'source_file': document.get('source_file', ''), 'is_subject': False,
            'record_kind': 'ecology_fact', 'taxon_group': species.taxon_group,
            'endangered_grade': species.endangered_grade,
            'modification_notice': '원문에서 항목별 발췌·분류한 자료입니다. AI 자동 추출 후 원문 일치를 대조했으며, 사람의 사실 검증 완료를 뜻하지 않습니다.'}

    def collect_missing_subject(self, species, progress=lambda _: None):
        docs = self.cache.documents(species.species_id)
        verified = False
        for document in docs:
            if not subject_document(species, document) and self.verify_cached_identity(species, document):
                if self.store:
                    self.store.index_document(species.species_id, document)
                verified = True
        if verified:
            return 'cached_identity_verified'
        if any(subject_document(species, d) for d in docs):
            return 'cached'
        key = f'ecology-subject-lookup:v1:{species.species_id}:{species.scientific_name}'
        candidate = self.cache.get(key)
        if candidate is None:
            candidate = self.cache.get(f'subject:{species.species_id}')
        if candidate is None:
            if self._source is None:
                self._source = WikipediaSource(self.settings)
            progress(f'{species.korean_name}: 아직 수집하지 않은 종 자체 문서를 확인합니다.')
            candidate = self._source.subject(species) or {}
            self.cache.put(key, candidate)
        if not candidate:
            return 'not_found'
        doc_key = f'doc:{species.species_id}:{candidate["document_id"]}'
        document = self.cache.get(doc_key)
        if document is None:
            if self._source is None:
                self._source = WikipediaSource(self.settings)
            document = self._source.fetch(candidate, '항목별 생태 정보 보강')
            document['is_subject'] = True
            self.cache.put(doc_key, document)
        if not subject_document(species, document) and not self.verify_cached_identity(species, document):
            return 'identity_unconfirmed'
        self.cache.put(f'subject:{species.species_id}', candidate | {'is_subject': True})
        if self.store:
            self.store.index_document(species.species_id, document)
        return 'collected'

    def verify_cached_identity(self, species, document):
        # Some Korean extracts omit the scientific name stored in an infobox.
        # Check its Wikidata taxon, without fetching the article body again.
        if document.get('document_title') != species.korean_name or not document.get('document_id', '').startswith('ko-wiki-'):
            return False
        intro = '\n'.join(p.get('text', '') for p in document.get('pages', []))[:1800]
        if re.search(r'\b[A-Z][a-z]+\s+[a-z]+\b', intro):
            return False  # Never override an explicitly different scientific name.
        key = f'ecology-taxon:v1:{species.species_id}:{document["document_id"]}:{species.scientific_name}'
        checked = self.cache.get(key)
        if checked is None:
            if self._taxon_source is None:
                self._taxon_source = WikipediaSource(self.settings)
                self._taxon_source.api = 'https://www.wikidata.org/w/api.php'
            payload = self._taxon_source.request(action='wbgetentities', sites='kowiki',
                titles=species.korean_name, props='claims')
            checked = {}
            for qid, entity in payload.get('entities', {}).items():
                if not re.fullmatch(r'Q[1-9][0-9]*', qid):
                    continue
                for claim in entity.get('claims', {}).get('P225', []):
                    value = claim.get('mainsnak', {}).get('datavalue', {}).get('value')
                    if (claim.get('rank') != 'deprecated' and isinstance(value, str) and
                            ' '.join(value.split()).casefold() == ' '.join(species.scientific_name.split()).casefold()):
                        checked = {'scientific_name': value, 'wikidata_url': 'https://www.wikidata.org/wiki/' + qid}
                        break
            self.cache.put(key, checked)
        if not checked:
            return False
        document['taxon_validation'] = checked
        document['is_subject'] = True
        self.cache.put(f'doc:{species.species_id}:{document["document_id"]}', document)
        return True

    def collect_english_supplement(self, species, progress=lambda _: None):
        if any(d.get('document_id', '').startswith('en-wiki-') and subject_document(species, d)
               for d in self.cache.documents(species.species_id)):
            return 'cached'
        fields = {record['field'] for record in self.records(species)}
        if len(fields) == 3:
            return 'not_needed'
        source = None
        key = f'ecology-en-subject-lookup:v1:{species.species_id}:{species.scientific_name}'
        candidate = self.cache.get(key)
        if candidate is None:
            source = EnglishWikipediaSource(self.settings)
            progress(f'{species.korean_name}: 미확보 항목을 위해 학명이 일치하는 영문 문서를 확인합니다.')
            candidate = source.subject(species) or {}
            self.cache.put(key, candidate)
        if not candidate:
            return 'not_found'
        doc_key = f'doc:{species.species_id}:{candidate["document_id"]}'
        document = self.cache.get(doc_key)
        if document is None:
            source = source or EnglishWikipediaSource(self.settings)
            document = source.fetch(candidate, '항목별 생태 정보 보강 (영문 위키백과)')
            document['is_subject'] = True
            self.cache.put(doc_key, document)
        if not subject_document(species, document):
            return 'identity_unconfirmed'
        if self.store:
            self.store.index_document(species.species_id, document)
        return 'collected'
