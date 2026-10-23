import argparse
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path

from .catalog import Catalog
from .config import load_settings
from .errors import AppError
from .logging_utils import configure_logging


def main():
    parser = argparse.ArgumentParser(description='EcoPedia 데이터·색인 관리')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('check-data')
    commands.add_parser('index-metadata')
    commands.add_parser('graph')
    commands.add_parser('reindex-documents')
    collect = commands.add_parser('collect')
    collect.add_argument('species_id')
    collect.add_argument('question')
    ecology = commands.add_parser('enrich-ecology')
    ecology.add_argument('--species-ids', nargs='+')
    ecology.add_argument('--collect-missing', action='store_true')
    ecology.add_argument('--english-supplement', action='store_true')
    ecology.add_argument('--retry-rejected', action='store_true', help='이전에 거부된 인용이 있는 문서만 기존 본문에서 재추출; 재수집하지 않음')
    ecology.add_argument('--retry-incomplete', action='store_true', help='누락 항목이 있는 저장 문서를 명시적으로 재검토; AI 호출료 발생, 본문 재수집 없음')
    ecology.add_argument('--limit', type=int, default=20)
    ecology.add_argument('--output', type=Path, default=Path('runtime/ecology-enrichment.json'))
    local = commands.add_parser('import-documents')
    local.add_argument('manifest', type=Path)
    evaluate = commands.add_parser('compare-rag')
    evaluate.add_argument('questions', type=Path)
    evaluate.add_argument('--output', type=Path, default=Path('runtime/rag-comparison.json'))
    args = parser.parse_args()
    settings = load_settings()
    catalog = Catalog(settings.root / 'data' / 'species.json')
    if args.command == 'check-data':
        names = {s.korean_name for s in catalog.items}
        print(json.dumps({'species': len(catalog.items), 'unique_names': len(names),
            'grade_1': sum(s.endangered_grade == 1 for s in catalog.items),
            'grade_2': sum(s.endangered_grade == 2 for s in catalog.items),
            'basis_date': settings.metadata_source_basis_date}, ensure_ascii=False, indent=2))
        return
    if args.command == 'graph':
        from .rag import build_graph
        print(build_graph(None, None).get_graph().draw_mermaid())
        return
    from .service import EcoService
    service = EcoService(settings)
    if args.command == 'enrich-ecology':
        from .coverage import analyze_coverage, subject_document
        from .sources import now
        if not 1 <= args.limit <= len(catalog.items):
            raise AppError('처리할 종 수는 1~282 사이로 지정해 주세요.')
        if args.species_ids:
            selected = [catalog.get(sid) for sid in args.species_ids]
        elif args.collect_missing:
            names = json.loads((settings.root / 'data/ecology-priority.json').read_text(encoding='utf-8'))
            selected = [next(s for s in catalog.items if s.korean_name == name) for name in names]
        else:
            selected = [s for s in catalog.items if any(subject_document(s, d)
                for d in service.ecology.cache.documents(s.species_id))]
        report = {'started_at': now(), 'collection_enabled': args.collect_missing, 'species': []}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        for species in selected[:args.limit]:
            collection = service.ecology.collect_missing_subject(species, lambda t: print(t, flush=True)) if args.collect_missing else 'cache_only'
            result = service.ecology.enrich_species(species, lambda t: print(t, flush=True), retry_rejected=args.retry_rejected, retry_incomplete=args.retry_incomplete)
            if args.english_supplement:
                supplement = service.ecology.collect_english_supplement(species, lambda t: print(t, flush=True))
                extra = service.ecology.enrich_species(species, lambda t: print(t, flush=True))
                result['llm_calls'] += extra['llm_calls']
                result['claims'], result['rejected'] = extra['claims'], extra['rejected']
                result['english_supplement'] = supplement
            facts = service.ecology.records(species)
            status = analyze_coverage(species, service.ecology.cache.documents(species.species_id), facts)
            result.update(name=species.korean_name, collection=collection,
                fields={r['field']: r['status'] for r in status}, evidence=facts)
            report['species'].append(result)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({k: v for k, v in result.items() if k != 'evidence'}, ensure_ascii=False), flush=True)
        print('saved:', args.output, flush=True)
    elif args.command == 'index-metadata':
        print('metadata chunks:', service.store.index_catalog(catalog))
    elif args.command == 'collect':
        result = service.collector.ensure(catalog.get(args.species_id), args.question, print)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == 'reindex-documents':
        count = 0
        for species in catalog.items:
            for doc in service.collector.cache.documents(species.species_id):
                count += service.store.index_document(species.species_id, doc)
        print('document chunks:', count)
    elif args.command == 'import-documents':
        print('document chunks:', service.collector.import_manifest(args.manifest.resolve(), catalog))
    elif args.command == 'compare-rag':
        questions = json.loads(args.questions.read_text(encoding='utf-8'))
        if len(questions) < 5:
            raise AppError('대표 질문을 5개 이상 지정해 주세요.')
        comparisons = []
        for item in questions:
            species = catalog.get(item['species_id'])
            without = service.llm.ask(
                '질문에 답하고 JSON {"answer":"답변"}만 출력하세요. 외부 도구를 사용하지 마세요.',
                {'species': species.korean_name, 'question': item['question']})
            with_rag = service.answer([species.species_id], item['question'], progress=print)
            comparisons.append(item | {'without_rag': without, 'with_rag': with_rag,
                'human_review': {'factual_accuracy': None, 'citations': None, 'abstention': None}})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(comparisons, ensure_ascii=False, indent=2), encoding='utf-8')
        print('saved:', args.output)


if __name__ == '__main__':
    try:
        main()
    except AppError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except Exception:
        Path('runtime').mkdir(exist_ok=True)
        configure_logging(Path('runtime/cli.log'))
        logging.exception('Command failed')
        print('처리에 실패했습니다. 입력·모델·연결 설정을 확인하세요. 상세 내용은 runtime/cli.log에 기록했습니다.', file=sys.stderr)
        sys.exit(1)
