"""1차 생태 보강 결과의 재사용과 실제 질문·조건 탐색 검증. API 비용 발생."""
import json
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ecopedia.config import load_settings
from ecopedia.ecology import EcologyFacts
from ecopedia.logging_utils import configure_logging
from ecopedia.service import EcoService
from ecopedia.sources import now


def main():
    settings = replace(load_settings(), auto_collect=False)
    configure_logging(settings.runtime / 'ecology-verification.log')
    service = EcoService(settings)
    names = json.loads((ROOT / 'data/ecology-priority.json').read_text(encoding='utf-8'))
    species = [next(s for s in service.catalog.items if s.korean_name == name) for name in names]
    offline = Mock()
    offline.ask.side_effect = AssertionError('추출 API 재호출 금지')
    reuse = EcologyFacts(settings, offline, service.store)
    with (patch('requests.Session.get', side_effect=AssertionError('수집 재호출 금지')),
          patch.object(service.store.docs, 'add_documents', side_effect=AssertionError('동일 자료 재임베딩 금지'))):
        for item in species:
            result = reuse.enrich_species(item)
            assert result['llm_calls'] == 0
    report = {'checked_at': now(), 'reuse_without_http_llm_embedding': True, 'species': len(species), 'answers': []}
    print('REUSE: no source / extraction / embedding calls for unchanged records', flush=True)
    for items, question in [(['산양', '사향노루'], '두 종의 서식 환경, 국내 분포, 주요 위협 요인을 비교해줘. 과거 기록은 구분해줘.'),
                            (['삵'], '서식 환경과 주요 위협 요인을 자료에서 확인되는 만큼 알려줘.')]:
        ids = [next(s.species_id for s in service.catalog.items if s.korean_name == name) for name in items]
        result = service.answer(ids, question, progress=lambda t: print(t, flush=True))
        assert result['used_evidence']
        report['answers'].append({'species': items, 'question': question,
            'answer': result['answer'], 'sources': [e['metadata'] for e in result['used_evidence']],
            'elapsed_seconds': result['elapsed_seconds']})
        print(json.dumps({'species': items, 'answer': result['answer'], 'sources': len(result['used_evidence'])}, ensure_ascii=False), flush=True)
    matches = service.explore('산림에 서식하는 1급 포유류')
    assert matches and all(m['species'].endangered_grade == 1 and m['species'].taxon_group == '포유류' for m in matches)
    report['condition_results'] = [{'name': m['species'].korean_name, 'reason': m['reason']} for m in matches]
    print('CONDITIONS:', ', '.join(x['name'] for x in report['condition_results']), flush=True)
    (settings.runtime / 'ecology-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
