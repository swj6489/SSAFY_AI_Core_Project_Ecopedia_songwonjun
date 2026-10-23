"""실제 설정으로 소량의 종 질문·비교를 검증한다. API 호출 비용이 발생한다."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ecopedia.config import load_settings
from ecopedia.service import EcoService
from ecopedia.logging_utils import configure_logging


def main():
    settings = load_settings()
    configure_logging(settings.runtime / 'live-verification.log')
    service = EcoService(settings)
    ids = {s.korean_name: s.species_id for s in service.catalog.items}
    results = {'metadata_count': service.store.count('meta'), 'answers': []}
    cases = [(['삵'], '삵은 주로 무엇을 먹으며 어떤 시간대에 활동하는가?'),
             (['산양', '사향노루'], '산양과 사향노루의 서식 환경과 주요 위협 요인을 비교해줘.'),
             (['삵'], '2026년 10월 21일 국내 야생 삵의 정확한 개체수는 몇 마리인가? 문서에 없는 정보는 추측하지 마.')]
    for names, question in cases:
        print('VERIFY:', ', '.join(names), flush=True)
        result = service.answer([ids[name] for name in names], question, progress=lambda t: print(t, flush=True))
        results['answers'].append({'species': names, 'question': question, 'result': result})
        print('ANSWER:', result['answer'], flush=True)
        print('CITATIONS:', len(result['used_evidence']), 'SECONDS:', result['elapsed_seconds'], flush=True)
        (settings.runtime / 'live-verification.json').write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    matches = service.explore('Ⅱ급 포유류')
    results['condition_matches'] = [{'species_id': m['species'].species_id,
        'name': m['species'].korean_name, 'grade': m['species'].endangered_grade,
        'group': m['species'].taxon_group, 'reason': m['reason']} for m in matches]
    assert all(m['grade'] == 2 and m['group'] == '포유류' for m in results['condition_matches'])
    results['document_chunk_count'] = service.store.count('docs')
    (settings.runtime / 'live-verification.json').write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print('SAVED: runtime/live-verification.json', flush=True)


if __name__ == '__main__':
    main()
