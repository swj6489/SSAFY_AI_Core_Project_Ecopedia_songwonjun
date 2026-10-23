"""GMS 설정으로 실제 채팅 UI를 검증한다. API 호출 비용이 발생한다."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from streamlit.testing.v1 import AppTest


def main():
    app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=120).run()
    assert not app.exception, '앱 초기화 실패'
    assert not app.chat_input[0].disabled, '키를 읽지 못함'
    app.text_input(key='name_filter').input('삵').run()
    app.chat_input[0].set_value('삵은 주로 무엇을 먹으며 어떤 시간대에 활동하는가?').run(timeout=120)
    assert not app.exception, '채팅 실행 실패'
    histories = app.session_state['histories']
    messages = next(history for history in histories.values() if any(m['role']=='assistant' for m in history))
    result = messages[-1]['result']
    assert result['used_evidence'], '인용 근거가 없는 답변'
    summary = {'page_title': app.title[0].value, 'selected_species': app.subheader[0].value,
        'answer': result['answer'], 'cited_evidence_count': len(result['used_evidence']),
        'source_links_rendered': len(app.get('link_button')), 'exceptions': len(app.exception),
        'elapsed_seconds': result['elapsed_seconds']}
    (ROOT / 'runtime' / 'live-ui-verification.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
