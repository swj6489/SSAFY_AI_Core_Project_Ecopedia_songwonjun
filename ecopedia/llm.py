import json
import os

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from .errors import AppError
from . import prompts


def output_format(system):
    string = {'type': 'string'}
    def obj(properties):
        return {'type': 'object', 'properties': properties,
                'required': list(properties), 'additionalProperties': False}
    def array(item):
        return {'type': 'array', 'items': item}
    schemas = {
        prompts.QUERY: obj({'queries': array(string)}),
        prompts.SELECT: obj({'decisions': array(obj({'document_id': string,
            'selected': {'type': 'boolean'}, 'reason': string}))}),
        prompts.ANSWER: obj({'answer': string, 'used_evidence_ids': array({'type': 'integer'})}),
        prompts.EXPLORE: obj({'matches': array(obj({'species_id': string, 'reason': string}))}),
        prompts.ECOLOGY: obj({'claims': array(obj({
            'field': {'type': 'string', 'enum': ['habitat', 'domestic_distribution', 'threats']},
            'quote': string, 'page_index': {'type': 'integer'},
            'time_scope': {'type': 'string', 'enum': ['historical', 'unspecified']}}))}),
    }
    schema = schemas.get(system)
    if schema:
        return {'type': 'json_schema', 'json_schema': {'name': 'ecopedia_result', 'strict': True, 'schema': schema}}
    return {'type': 'json_object'}


class JsonLLM:
    def __init__(self, settings):
        settings.require_key()
        options = {'api_key': os.environ['OPENAI_API_KEY']}
        if os.getenv('OPENAI_BASE_URL'):
            options['base_url'] = os.environ['OPENAI_BASE_URL']
        self.client = ChatOpenAI(model=os.getenv('CHAT_MODEL', '').strip() or 'gpt-5.4-mini',
                                 temperature=0, timeout=settings.llm_timeout_seconds,
                                 max_retries=settings.llm_max_retries, **options)

    def ask(self, system, payload):
        for attempt in range(2):
            messages = [('system', system), ('human', json.dumps(payload, ensure_ascii=False))]
            if attempt:
                messages.append(('human', '유효한 JSON 객체만 출력하세요. 코드 블록은 제외하세요.'))
            response = self.client.bind(response_format=output_format(system)).invoke(messages)
            content = response.content
            if isinstance(content, list):
                content = ''.join(block.get('text', '') for block in content if isinstance(block, dict))
            try:
                text = content.strip()
                if text.startswith('```'):
                    text = text.split('\n', 1)[1].rsplit('```', 1)[0]
                value = json.loads(text)
                if isinstance(value, dict):
                    return value
            except (ValueError, TypeError, AttributeError):
                pass
        raise AppError('답변 형식을 처리하지 못했습니다. 다시 시도해 주세요.')


def make_embeddings(settings):
    settings.require_key()
    options = {'api_key': os.environ['OPENAI_API_KEY']}
    if os.getenv('OPENAI_BASE_URL'):
        options['base_url'] = os.environ['OPENAI_BASE_URL']
    return OpenAIEmbeddings(model=os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small'),
                            request_timeout=settings.llm_timeout_seconds, **options)
