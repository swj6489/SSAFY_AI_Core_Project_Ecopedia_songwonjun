"""API 호출 없이 저장된 속성과 종 자체 문서의 항목별 보유 상태를 계산한다.

외부 문장의 키워드 판별은 사실 검증이 아니므로 '관련 근거 있음'으로만 표시한다.
"""
import re


FIELDS = (('habitat', '서식 환경'), ('domestic_distribution', '국내 분포'), ('threats', '주요 위협 요인'))
EMPTY = {'', '확인된 정보 없음', '정보 없음', '미확인', '미확보', 'unknown', 'n/a', '없음'}
UNCERTAIN = re.compile(r'확인.{0,8}(?:않|못|없)|알려져 있지|정보.{0,8}없|자료.{0,8}없|조사.{0,8}필요')
DOMESTIC = re.compile(r'대한민국|한국|한반도|남한|북한|강원|경기도?|경상|경북|경남|충청|충북|충남|전라|전북|전남|제주|울릉|설악산|지리산|태백산|비무장지대|울진|\bKorea\b|Korean Peninsula', re.I)
RANGE = re.compile(r'분포|서식|살고|산다|발견|관찰|목격|생존|기록되|번식|월동|도래|distribut|inhabit|native|found|occur|range|recorded|breed|winter|nest', re.I)
ENVIRONMENT = re.compile(r'산림|숲|수림|산악|산지|계곡|하천|강가|강변|습지|늪|갯벌|연안|바다|해안|해역|초지|초원|농경지|논|연못|호수|바위|절벽|동굴|산호초|담수|기수역|forest|woodland|mountain|river|stream|wetland|marsh|coast|grassland|lake|pond|cliff|cave|reef|freshwater|brackish|habitat|mudflat|intertidal|island|taiga|scrub|bamboo|tundra', re.I)
LIVING = re.compile(r'서식|살고|살며|살면서|산다|분포|머물|좋아하|생활하|inhabit|lives?|found|habitat|prefers?|occur|native|breed|winter|nest|depend|frequent|occup|resid', re.I)
THREATS = re.compile(r'밀렵|남획|불법.{0,8}포획|포획되|마구 잡|로드킬|혼획|환경.{0,8}(?:파괴|오염|나빠)|서식(?:지| 환경).{0,15}(?:파괴|감소|훼손|단절|악화)|기후.{0,8}변화|수질.{0,8}오염|먹이.{0,8}(?:감소|고갈)|사냥.{0,15}(?:감소|멸종|위기)|개발.{0,15}(?:감소|훼손|위협)|농약|외래종.{0,15}(?:경쟁|위협|피해)|poach|hunting|overfish|overharvest|bycatch|pollut|deforest|fragmentation|degradation|habitat.{0,40}(?:loss|destr|threat)|illegal.{0,25}(?:trade|captur)|pesticid|roadkill|climate change', re.I)
SKIP_SECTIONS = re.compile(r'각주|참고|같이 보기|외부 링크|다른 링크|사진|references|external links|see also', re.I)
THREATS = re.compile(THREATS.pattern + r'|\bhunt(?:ed|ing)?\b|destruction|drainage|human disturbance|habitat decline|collisions?', re.I)
ENVIRONMENT = re.compile(ENVIRONMENT.pattern + r'|수심', re.I)
LIVING = re.compile(LIVING.pattern + r'|자라|생육|생장|\bgrows?\b', re.I)


def meaningful(value):
    return isinstance(value, str) and value.strip().casefold() not in EMPTY


def scientific_identity(value):
    # ICZN 6.1: optional parenthesized subgenus, not a species/subspecies epithet.
    value = re.sub(r'^([A-Z][a-z]+)\s+\([A-Z][a-z]+\)\s+(?=[a-z])', r'\1 ', value)
    return ' '.join(value.casefold().split())


def subject_document(species, document):
    text = '\n'.join(p.get('text', '') for p in document.get('pages', []))
    scientific = scientific_identity(species.scientific_name)
    text = re.sub(r'\b([A-Z][a-z]+)\s+\([A-Z][a-z]+\)\s+(?=[a-z])', r'\1 ', text)
    intro = ' '.join(text[:1800].casefold().split())
    # Do not count an unrelated cached country/park/another species as coverage.
    if not re.search(r'(?<!\w)' + re.escape(scientific) + r'(?!\w)', intro):
        checked = document.get('taxon_validation', {})
        if (scientific_identity(checked.get('scientific_name', '')) != scientific or
                not re.fullmatch(r'https://www\.wikidata\.org/wiki/Q[1-9][0-9]*', checked.get('wikidata_url', ''))):
            return False
    return document.get('document_title', '').strip() == species.korean_name or bool(document.get('is_subject'))


def sentences(document):
    for page in document.get('pages', []):
        skip = False
        for line in page.get('text', '').splitlines():
            line = line.strip()
            heading = re.fullmatch(r'=+\s*(.*?)\s*=+', line)
            if heading:
                skip = bool(SKIP_SECTIONS.search(heading[1]))
                continue
            if skip or not line:
                continue
            for sentence in re.split(r'(?<=[.!?。])\s+', line):
                sentence = sentence.strip()
                if 7 <= len(sentence) <= 650 and not UNCERTAIN.search(sentence):
                    yield sentence, page.get('page_number')


def relevant(field, sentence):
    if re.search(r'전혀 다른|다른 종류|다른 종이다|별개의 종', sentence):
        return False
    if field == 'habitat':
        return bool(ENVIRONMENT.search(sentence) and LIVING.search(sentence))
    if field == 'domestic_distribution':
        return bool(DOMESTIC.search(sentence) and RANGE.search(sentence))
    return bool(THREATS.search(sentence))


def analyze_coverage(species, documents, facts=None):
    records = []
    subject_docs = [d for d in documents if subject_document(species, d)]
    for field, label in FIELDS:
        evidence = []
        value = getattr(species, field, '')
        if meaningful(value):
            evidence.append({'quote': value.strip(), 'title': '종 메타데이터',
                'source_url': species.source_url, 'basis_date': species.source_basis_date,
                'license': '공식 종 목록 / 이용 조건 검토 중'})
        extracted = [item for item in (facts or []) if item['field'] == field]
        evidence.extend(extracted[:2])
        seen = set()
        for document in subject_docs:
            for sentence, page in sentences(document):
                if relevant(field, sentence) and sentence not in seen:
                    seen.add(sentence)
                    evidence.append({'quote': sentence, 'title': document.get('document_title', ''),
                        'source_url': document.get('source_url', ''), 'license': document.get('license', ''),
                        'revision_id': document.get('revision_id', ''), 'page_number': page,
                        'collected_at': document.get('collected_at', '')})
                    if len(evidence) >= 2:
                        break
            if len(evidence) >= 2:
                break
        status = 'available' if meaningful(value) else ('extracted' if extracted else ('related' if evidence else 'missing'))
        records.append({'field': field, 'label': label, 'status': status, 'evidence': evidence[:2]})
    return records
