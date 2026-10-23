import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


def normalize_query(text):
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'(?<![A-Za-z])II\s*급', '2급', text, flags=re.I)
    return re.sub(r'(?<![A-Za-z])I\s*급', '1급', text, flags=re.I).strip()


@dataclass(frozen=True)
class Species:
    species_id: str
    korean_name: str
    scientific_name: str
    taxon_group: str
    endangered_grade: int
    source_url: str
    source_basis_date: str = '2022-12-09'
    domestic_distribution: str = ''
    habitat: str = ''
    threats: str = ''

    def __post_init__(self):
        if type(self.endangered_grade) is not int or self.endangered_grade not in (1, 2):
            raise ValueError('멸종위기 등급은 정수 1 또는 2여야 합니다.')
        if not all((self.species_id, self.korean_name, self.scientific_name, self.taxon_group)):
            raise ValueError('종 식별 정보가 누락되었습니다.')

    def text(self):
        return '\n'.join([
            f'국명: {self.korean_name}', f'학명: {self.scientific_name}',
            f'분류군: {self.taxon_group}', f'멸종위기 등급: {self.endangered_grade}급',
            f'국내 분포: {self.domestic_distribution or "확인된 정보 없음"}',
            f'서식 환경: {self.habitat or "확인된 정보 없음"}',
            f'주요 위협 요인: {self.threats or "확인된 정보 없음"}',
            f'자료 기준일: {self.source_basis_date}',
        ])

    def metadata(self):
        return {k: getattr(self, k) for k in (
            'species_id', 'korean_name', 'scientific_name', 'taxon_group',
            'endangered_grade', 'source_url', 'source_basis_date'
        )} | {'source_type': 'metadata', 'document_title': f'{self.korean_name} 종 메타데이터'}


class Catalog:
    def __init__(self, path: Path):
        payload = json.loads(path.read_text(encoding='utf-8'))
        self.items = [Species(**row) for row in payload]
        self.by_id = {s.species_id: s for s in self.items}
        if len(self.by_id) != len(self.items):
            raise ValueError('중복 종 ID가 있습니다.')

    def get(self, species_id):
        return self.by_id[species_id]

    def filter(self, name='', group='전체', grade=0):
        q = name.casefold().strip()
        return [s for s in self.items if (group == '전체' or s.taxon_group == group)
                and (not grade or s.endangered_grade == int(grade))
                and (not q or q in s.korean_name.casefold() or q in s.scientific_name.casefold())]


def explicit_filters(query):
    query = normalize_query(query)
    grades = set(re.findall(r'([12])\s*급', query))
    group_aliases = {'포유류': '포유류', '조류': '조류', '어류': '어류', '곤충': '곤충',
                     '무척추동물': '무척추동물', '식물': '식물', '해조류': '해조류',
                     '고등균류': '고등균류', '양서파충류': '양서파충류'}
    pattern = '|'.join(re.escape(key) for key in sorted(group_aliases, key=len, reverse=True))
    groups = list(dict.fromkeys(group_aliases[m.group()] for m in re.finditer(pattern, query)))
    filters = []
    if len(grades) == 1:
        filters.append({'endangered_grade': int(next(iter(grades)))})
    if len(groups) == 1:
        filters.append({'taxon_group': groups[0]})
    return {'$and': filters} if len(filters) > 1 else (filters[0] if filters else None)
