"""저장 정보 상태만 참고하는 추천 질문. 외부 수집·AI 호출 없음."""


def recommended_questions(species, coverage):
    name = species.korean_name
    items = [
        ('basic', '🏷️ 기본 정보', f'{name}의 국명, 학명, 분류군과 멸종위기 등급을 알려줘.'),
        ('overview', '📖 한눈에 알아보기', f'{name}에 대해 자료에서 확인되는 특징을 쉽게 정리해줘. 확인되지 않은 내용은 구분해줘.'),
    ]
    templates = {
        'habitat': ('🌳 서식 환경', f'{name}은 어떤 환경에서 살아? 자료에 나오는 서식 환경을 알려줘.'),
        'domestic_distribution': ('📍 국내 분포', f'{name}의 국내 분포를 알려줘. 과거 기록과 현재 확인 가능한 정보를 구분해줘.'),
        'threats': ('⚠️ 위협 요인', f'{name}을 위협하는 요인은 뭐야? 국내와 해외 기록을 구분해서 알려줘.'),
    }
    states = {item['field']: item['status'] for item in (coverage or [])}
    for field, (label, question) in templates.items():
        if states.get(field) in ('available', 'extracted', 'related'):
            items.append((field, label, question))
    return items
