import re
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from . import prompts
from .errors import AppError
from .store import merge_evidence


class RagState(TypedDict, total=False):
    species_ids: list[str]
    question: str
    history: list[dict]
    evidence: list[dict]
    answer: str
    used_evidence: list[dict]
    notices: list[str]


def validate_answer(payload, evidence):
    text = payload.get('answer')
    if not isinstance(text, str) or not text.strip():
        raise AppError('빈 답변을 받았습니다. 다시 시도해 주세요.')
    available = {e['evidence_id']: e for e in evidence}
    cited = [int(n) for n in re.findall(r'\[근거\s*(\d+)\]', text)]
    unknown = sorted(set(cited) - set(available))
    if unknown:
        raise ValueError('unknown evidence citation')
    # The answer body is authoritative, not the model's separate used-ID field.
    used = [available[i] for i in dict.fromkeys(cited)]
    return {'answer': text, 'used_evidence': used,
            'notices': [] if used else ['이 답변에 인용된 근거가 없습니다.']}


def build_graph(store, llm):
    def retrieve(state):
        documents = []
        for sid in state['species_ids']:
            meta = store.metadata_for(sid)
            if not meta:
                raise AppError('선택한 종의 메타데이터 색인이 없습니다. 먼저 종 데이터를 색인해 주세요.')
            documents.extend(meta)
            query = meta[0].metadata.get('korean_name', '') + ' ' + state['question']
            documents.extend(store.retrieve_external(sid, query))
        return {'evidence': merge_evidence(documents)}

    def generate(state):
        ordered = sorted(state['evidence'], key=lambda e: (e['metadata'].get('record_kind') != 'ecology_fact',
                                                         e['metadata']['source_type'] == 'metadata'))
        context = '\n\n'.join(
            f"[근거 {e['evidence_id']}] 종 ID: {e['metadata']['species_id']} / "
            f"{e['metadata']['document_title']} / 출처 유형: {e['metadata']['source_type']}\n{e['text']}"
            for e in ordered)
        payload = {'question': state['question'], 'history': state.get('history', [])[-6:],
                   'context': context}
        for attempt in range(2):
            result = llm.ask(prompts.ANSWER, payload)
            try:
                validated = validate_answer(result, state['evidence'])
                refusal = re.search(r'확인되지|확인할 수 없|알 수 없|근거가 없|정보가 없', validated['answer'])
                if not validated['used_evidence'] and not refusal:
                    raise ValueError('factual answer without citations')
                return validated
            except ValueError:
                payload['format_correction'] = ('앞선 답변은 인용이 없거나 번호가 잘못되었습니다. '
                    '사실을 말하는 문장마다 반드시 제공된 evidence_id를 [근거 1] 같은 형식으로 붙이세요. '
                    '근거로 답할 수 없다면 제공된 문서에서 확인되지 않는다고만 답하세요.')
        raise AppError('답변의 근거 번호를 검증하지 못했습니다. 다시 시도해 주세요.')

    graph = StateGraph(RagState)
    graph.add_node('retrieve', retrieve)
    graph.add_node('generate', generate)
    graph.add_edge(START, 'retrieve')
    graph.add_edge('retrieve', 'generate')
    graph.add_edge('generate', END)
    return graph.compile()
