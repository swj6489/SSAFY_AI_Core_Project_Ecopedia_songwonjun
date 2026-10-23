import logging
import os
import importlib
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

from ecopedia.catalog import Catalog
from ecopedia.config import load_settings
from ecopedia.errors import AppError
from ecopedia.logging_utils import configure_logging
from ecopedia.service import EcoService
from ecopedia.photos import SpeciesPhotos, rights_label
from ecopedia.coverage import analyze_coverage
from ecopedia.sources import SourceCache
from ecopedia.ecology import EcologyFacts
from ecopedia.questions import recommended_questions
from ecopedia import ui

# Streamlit may retain the previous helper module during a running UI update.
# Reload this presentation-only module before accessing newly added functions.
ui = importlib.reload(ui)

st.set_page_config(page_title='EcoPedia | 멸종위기종 백과', page_icon='🌿', layout='wide')


def render_sources(evidence):
    if not evidence:
        st.caption('이 답변에 인용된 근거가 없습니다.')
        return
    with st.expander(f'답변에 사용된 근거 {len(evidence)}개'):
        for item in evidence:
            metadata = item['metadata']
            kind = '종 메타데이터' if metadata['source_type'] == 'metadata' else '외부 문서'
            title = metadata.get('document_title', '근거 문서')
            st.write(f"[근거 {item['evidence_id']}] {title}")
            st.caption(f"{kind} · {metadata['source_type']} · {metadata.get('license', '공식 종 목록 / 이용 조건 검토 중')}")
            url = metadata.get('source_url', '')
            if urlparse(url).scheme in ('http', 'https'):
                st.link_button('원문 보기', url)
            if metadata.get('source_file'):
                st.caption(f"파일: {metadata['source_file']} · PDF 파일 페이지: {metadata.get('page_number', '해당 없음')}")
            if metadata.get('revision_id'):
                st.caption(f"문서 리비전: {metadata['revision_id']}")
            if metadata.get('modification_notice'):
                st.caption(metadata['modification_notice'])
            st.text(item['text'])


def render_result(result):
    st.markdown(result['answer'])
    for notice in dict.fromkeys(result.get('notices', [])):
        st.info(notice)
    render_sources(result.get('used_evidence', []))
    st.caption(f"처리 시간 {result.get('elapsed_seconds', 0):.2f}초")


def safe_action(action):
    try:
        return action()
    except AppError as exc:
        st.warning(str(exc))
    except Exception:
        logging.exception('EcoPedia operation failed')
        st.error('처리하지 못했습니다. 연결·모델 설정을 확인한 뒤 다시 시도해 주세요.')
    return None


def load_photos(settings, species_list):
    try:
        with st.spinner('종의 대표 사진을 확인하고 있습니다.'):
            return SpeciesPhotos(settings).get_many(species_list)
    except AppError:
        st.caption('사진 제공 서버에 연결할 수 없거나 수집 설정이 없습니다. 사진 없이도 검색·질문할 수 있습니다.')
        return {}
    except Exception:
        logging.exception('Species photo lookup failed')
        st.caption('사진을 불러오지 못했습니다. 검색·질문은 계속 사용할 수 있습니다.')
        return {}


def render_photo(species, photos):
    photo = photos.get(species.species_id)
    if not photo:
        ui.empty_photo()
        st.caption('📷 종이 일치하는 대표 사진이나 퍼블릭 도메인·CC0 대체 사진을 확인하지 못했습니다.')
        return
    st.image(photo['url'], caption=f'{species.korean_name} 대표 이미지', width='stretch')
    label = rights_label(photo)
    if label:
        st.caption(label)
        if photo.get('is_fallback'):
            st.caption('기존 대표 사진 대신 표시한 대체 사진입니다.')
    with st.expander('사진 출처·이용 조건'):
        # External attribution remains plain text, never raw HTML.
        st.caption(f"사진: {photo['artist']} · {photo['license']} · 크기 조정 외 변경 없음")
        if photo.get('credit'):
            st.caption(photo['credit'])
        st.markdown(f"[사진 원문·이용 조건]({photo['source_url']}) · [라이선스]({photo['license_url']})")
        if photo.get('discovery') == 'wikidata':
            st.caption('Wikidata에서 학명이 일치하는 항목의 대표 이미지로 확인했습니다.')
            st.markdown(f"[종·대표 이미지 연결 확인]({photo['wikidata_url']})")


def keyword_condition():
    parts = [st.session_state.get('explore_grade', ''), st.session_state.get('explore_group', '')]
    keywords = ' '.join(part for part in parts if part)
    return f'{keywords} 찾아줘' if keywords else ''


def fill_recommended_question(key, question):
    st.session_state[key] = question


def render_recommended_questions(species, records, enabled):
    with st.container(key='recommended_questions'):
        st.markdown('#### 어떤 점이 궁금하세요?')
        st.caption('버튼을 누르면 입력창에 질문이 채워집니다. 수정한 뒤 전송해 주세요. 선택만으로 AI를 호출하지 않습니다.')
        items = recommended_questions(species, records)
        for start in range(0, len(items), 3):
            row = items[start:start + 3]
            for column, (kind, label, question) in zip(st.columns(len(row)), row):
                column.button(label, key=f'recommend_{species.species_id}_{kind}', width='stretch',
                    disabled=not enabled, help=question, on_click=fill_recommended_question,
                    args=(f'question_{species.species_id}', question))
        st.caption('생태 질문은 저장 자료에 관련 근거가 있는 항목만 제안합니다. 답변 가능 여부와 최신성은 실제 근거에 따라 달라집니다.')


def render_information_status(settings, species):
    try:
        documents = SourceCache(settings).documents(species.species_id)
        records = analyze_coverage(species, documents, EcologyFacts(settings).records(species))
    except Exception:
        logging.exception('Species information status lookup failed')
        st.info('저장된 자료의 확보 상태를 확인하지 못했습니다. 질문 기능은 계속 이용할 수 있습니다.')
        return []
    with st.container(key='information_coverage'):
        st.markdown('#### 정보 확보 상태')
        st.caption('현재 저장된 자료 기준 · 확보 상태 계산에는 추가 수집이나 AI 호출이 없습니다.')
        ui.render_coverage_cards(records)
        st.caption('원문 대조 정보는 자동 추출한 인용을 원문과 대조한 자료입니다. 관련 근거 있음은 표현 탐지 결과이며, 두 상태 모두 사람의 사실 검증 완료나 현재 분포를 보장하지 않습니다.')
        with st.expander('판별 기준과 항목별 근거 보기'):
            st.caption('정보 확보: 메타데이터 값 / 원문 대조 정보: 저장된 항목별 인용·출처를 원문과 대조 / 관련 근거 있음: 관련 표현 자동 검출 / 미확보: 아직 찾지 못함. 미확보가 실제 정보 부재를 뜻하지는 않습니다.')
            for record in records:
                st.write(record['label'])
                if not record['evidence']:
                    st.caption('아직 저장된 자료에서 관련 설명을 확인하지 못했습니다.')
                for number, item in enumerate(record['evidence'], 1):
                    st.write(item['quote'])
                    st.caption(f"{item['title']} · {item.get('license', '')}")
                    if item.get('basis_date'):
                        st.caption(f"자료 기준일: {item['basis_date']}")
                    if item.get('collected_at'):
                        st.caption(f"수집 시각: {item['collected_at']}")
                    if item.get('revision_id'):
                        st.caption(f"문서 리비전: {item['revision_id']}")
                    if item.get('page_number'):
                        st.caption(f"PDF 파일 페이지: {item['page_number']}")
                    if item.get('time_scope'):
                        st.caption('과거 기록 · 현재 서식으로 단정하지 않습니다.' if item['time_scope'] == 'historical'
                                   else '시점 미확인 · 현재성 보장 없음')
                    if urlparse(item.get('source_url', '')).scheme in ('http', 'https'):
                        st.link_button(f"{record['label']} 근거 {number} 원문", item['source_url'])
    return records


def choose_explore_keyword(kind, value):
    key = f'explore_{kind}'
    st.session_state[key] = '' if st.session_state.get(key) == value else value
    st.session_state.explore_condition = keyword_condition()


def clear_explore_keywords():
    st.session_state.update(explore_grade='', explore_group='', explore_condition='')
    st.session_state.pop('search_results', None)
    st.session_state.pop('searched_condition', None)


def render_explore_keywords(catalog):
    st.write('검색 키워드 고르기')
    st.caption('등급과 분류군을 하나씩 고르면 조건이 자동 입력됩니다. 선택한 키워드를 다시 누르면 해제됩니다.')
    for label, kind, values in (
        ('멸종위기 등급', 'grade', ['1급', '2급']),
        ('분류군', 'group', sorted({s.taxon_group for s in catalog.items})),
    ):
        st.caption(label)
        for start in range(0, len(values), 5):
            row = values[start:start + 5]
            for column, value in zip(st.columns(len(row)), row):
                column.button(value, key=f'keyword_{kind}_{value}', width='stretch',
                    type='primary' if st.session_state.get(f'explore_{kind}') == value else 'secondary',
                    on_click=choose_explore_keyword, args=(kind, value))
    st.button('키워드·검색 결과 초기화', key='clear_explore_keywords', on_click=clear_explore_keywords)
    if 'explore_condition' not in st.session_state:
        st.session_state.explore_condition = keyword_condition()


def render_compare_picker(catalog, label, prefix, default=None, exclude=None):
    with st.container(key=f'{prefix}_card'):
        st.markdown(f'#### {label}')
        name = st.text_input('국명 또는 학명으로 찾기', key=f'{prefix}_name', placeholder='예: 삵, Prionailurus')
        group = st.selectbox('분류군', ['전체'] + sorted({s.taxon_group for s in catalog.items}), key=f'{prefix}_group')
        grade = st.selectbox('멸종위기 등급', [0, 1, 2],
            format_func=lambda value: '전체' if value == 0 else f'{value}급', key=f'{prefix}_grade')
        options = [s.species_id for s in catalog.filter(name, group, grade) if s.species_id != exclude]
        key = f'{prefix}_picker'
        if key not in st.session_state:
            st.session_state[key] = default if default in options else None
        elif st.session_state[key] not in options:
            st.session_state[key] = None
        selected = st.selectbox(label, options, index=None, key=key,
            placeholder='비교할 종을 선택하세요', disabled=not options,
            format_func=lambda sid: f'{catalog.get(sid).korean_name} · {catalog.get(sid).taxon_group} · {catalog.get(sid).endangered_grade}급')
        st.caption(f'선택 가능한 종 {len(options)}종' + (' · 첫 번째 종은 목록에서 제외됩니다.' if exclude else ''))
        if not options:
            st.info('선택 가능한 종이 없습니다. 검색어나 필터를 바꿔 주세요.')
        if selected:
            st.caption(catalog.get(selected).scientific_name)
        return selected


def main():
    settings = load_settings()
    settings.runtime.mkdir(parents=True, exist_ok=True)
    configure_logging(settings.runtime / 'app.log')
    catalog = Catalog(settings.root / 'data' / 'species.json')
    ui.apply_theme()
    ui.render_brand(catalog, settings.metadata_source_basis_date)

    if 'selected_species_id' not in st.session_state:
        st.session_state.selected_species_id = catalog.items[0].species_id
    if 'histories' not in st.session_state:
        st.session_state.histories = {}
    if 'pending_species' in st.session_state:
        target = st.session_state.pop('pending_species')
        st.session_state.update({'name_filter': '', 'group_filter': '전체', 'grade_filter': 0,
                                 'species_picker': target, 'selected_species_id': target,
                                 'page': '종별 질문'})

    @st.cache_resource(show_spinner=False)
    def get_service(configuration):
        return EcoService(configuration)

    service = None
    with st.sidebar:
        ui.render_sidebar_brand(catalog)
        with st.container(key='sidebar_appearance'):
            st.radio('화면 모드', ['라이트', '다크'], key='appearance', horizontal=True,
                     format_func=lambda mode: '☀ 라이트' if mode == '라이트' else '☾ 다크')
        ui.sidebar_section('EXPLORE / 탐색 메뉴')
        menu_labels = {'종별 질문': '🌱  종별 질문', '자연어 조건 탐색': '🔎  자연어 조건 탐색', '두 종 생태 비교': '⚖  두 종 생태 비교'}
        page = st.radio('메뉴', list(menu_labels), key='page', label_visibility='collapsed',
                        format_func=lambda value: menu_labels[value])
        st.divider()
        if page == '종별 질문':
            ui.sidebar_section('FIELD GUIDE / 종 찾기')
            st.header('질문할 종 선택')
            name = st.text_input('국명 또는 학명', placeholder='예: 삵', key='name_filter')
            group = st.selectbox('분류군', ['전체'] + sorted({s.taxon_group for s in catalog.items}), key='group_filter')
            grade = st.selectbox('멸종위기 등급', [0, 1, 2], format_func=lambda x: '전체' if x == 0 else f'{x}급', key='grade_filter')
            options = catalog.filter(name, group, grade)
            if options:
                ids = [s.species_id for s in options]
                current = st.session_state.selected_species_id
                if st.session_state.get('species_picker') not in ids:
                    st.session_state.species_picker = current if current in ids else ids[0]
                selected = st.selectbox('질문할 종', ids,
                                         format_func=lambda sid: catalog.get(sid).korean_name, key='species_picker')
                st.session_state.selected_species_id = selected
            else:
                st.info('조건에 맞는 종이 없습니다.')
            st.caption(f'목록 {len(options)}종')
        elif page == '자연어 조건 탐색':
            st.caption('선택한 종과 관계없이 전체 종 목록에서 조건에 맞는 종을 찾습니다.')
        else:
            st.caption('비교 화면에서 서로 다른 두 종을 선택해 주세요.')
        st.divider()
        ui.sidebar_section('WORKSPACE / 이용 상태')
        if not os.getenv('OPENAI_API_KEY', '').strip():
            st.info('종 목록은 바로 탐색할 수 있습니다. AI 질문·조건 탐색은 .env에 API 키를 설정한 뒤 사용할 수 있습니다.')
        else:
            service = safe_action(lambda: get_service(settings))
        if service:
            with st.expander('데이터 관리'):
                st.caption(f"종 색인 {service.store.count('meta')}개 · 외부 문서 청크 {service.store.count('docs')}개")
                if st.button('종 메타데이터 색인', help='282종의 텍스트를 임베딩합니다. API 사용료가 발생할 수 있습니다.'):
                    with st.spinner('종 데이터를 색인하고 있습니다.'):
                        count = safe_action(lambda: service.store.index_catalog(catalog))
                    if count is not None:
                        st.success(f'{count}개 색인 완료')
                        st.rerun()
        st.markdown('<div class="eco-sidebar-note">🌱 <strong>근거로 알아보고, 함께 지켜요.</strong><br>자료에서 확인되는 정보만 안내합니다. 사진과 답변의 출처도 함께 확인해 주세요.</div>', unsafe_allow_html=True)
        st.markdown('<div class="eco-footer">ECOPEDIA · DISCOVER & PROTECT</div>', unsafe_allow_html=True)

    species = catalog.get(st.session_state.selected_species_id)
    if page == '종별 질문':
        with st.container(key='species_profile'):
            identity, portrait = st.columns([1.1, 1])
            with identity:
                st.caption('SPECIES PROFILE · 종 알아보기')
                st.subheader(species.korean_name)
                st.caption(species.scientific_name)
                ui.species_badges(species)
                st.write('이 종이 궁금한가요?')
                st.caption('특징과 생활 습성부터 생태 정보까지, 확인된 자료를 바탕으로 질문해 보세요.')
            with portrait:
                render_photo(species, load_photos(settings, [species]))
        coverage_records = render_information_status(settings, species)
        render_recommended_questions(species, coverage_records, enabled=service is not None)
        history = st.session_state.histories.setdefault(species.species_id, [])
        st.markdown('#### 근거와 함께 나누는 대화')
        if not history:
            st.caption('예시 질문 · “국명, 학명과 멸종위기 등급을 알려줘” / “자료에서 확인되는 특징과 생활 습성을 정리해줘”')
        if st.button('이 종의 대화 지우기', key=f'clear_{species.species_id}'):
            st.session_state.histories[species.species_id] = []
            st.rerun()
        for message in history:
            with st.chat_message(message['role']):
                if message['role'] == 'assistant':
                    render_result(message['result'])
                else:
                    st.write(message['content'])
        question = st.chat_input(f'{species.korean_name}에 대해 질문하세요', key=f'question_{species.species_id}', disabled=service is None)
        if question and service:
            previous = [{'role': m['role'], 'content': m['content']} for m in history]
            history.append({'role': 'user', 'content': question})
            with st.chat_message('user'):
                st.write(question)
            with st.chat_message('assistant'):
                with st.status('질문을 처리하고 있습니다.', expanded=True) as status:
                    result = safe_action(lambda: service.answer([species.species_id], question, previous, status.write))
                    status.update(label='처리 완료' if result else '처리를 완료하지 못했습니다.',
                                  state='complete' if result else 'error', expanded=False)
                if result:
                    render_result(result)
                    history.append({'role': 'assistant', 'content': result['answer'], 'result': result})
                    # Refresh the coverage panel after newly collected evidence is saved.
                    st.rerun()

    elif page == '자연어 조건 탐색':
        st.subheader('전체 종 자연어 조건 탐색')
        st.write(f'선택한 종과 관계없이 전체 {len(catalog.items)}종에서 검색합니다. 예: “2급 포유류 찾아줘”')
        st.caption('서식지·국내 분포·위협 조건은 출처가 연결된 생태 정보가 확보된 종에서만 확인합니다. 과거 기록을 현재 서식으로 추측하지 않습니다.')
        with st.container(key='keyword_panel'):
            render_explore_keywords(catalog)
        with st.form('explore'):
            condition = st.text_input('원하는 조건', key='explore_condition', placeholder='키워드를 고르거나 직접 입력하세요. 예: 2급 포유류 찾아줘')
            submit = st.form_submit_button('조건으로 찾기', type='primary', disabled=service is None)
        if submit and service:
            if not condition.strip():
                st.warning('키워드를 고르거나 원하는 조건을 입력해 주세요.')
            else:
                with st.spinner('조건에 맞는 종을 확인하고 있습니다.'):
                    matches = safe_action(lambda: service.explore(condition))
                if matches is not None:
                    st.session_state.search_results = [{'species_id': m['species'].species_id, 'reason': m['reason']} for m in matches]
                    st.session_state.searched_condition = condition
        if 'search_results' in st.session_state:
            if st.session_state.get('searched_condition'):
                st.caption(f"검색 결과 기준: {st.session_state.searched_condition}")
            found_species = [catalog.get(m['species_id']) for m in st.session_state.search_results]
            photos = load_photos(settings, found_species) if found_species else {}
            if not st.session_state.search_results:
                st.info('확인된 정보에서 조건에 맞는 종을 찾지 못했습니다.')
            if st.session_state.search_results:
                st.markdown(f"#### 검색 결과 · {len(st.session_state.search_results)}종")
            result_columns = st.columns(2)
            for index, match in enumerate(st.session_state.search_results):
                found = catalog.get(match['species_id'])
                with result_columns[index % 2].container(key=f'result_card_{found.species_id}'):
                    st.markdown(f'#### {found.korean_name}')
                    st.caption(found.scientific_name)
                    ui.species_badges(found)
                    render_photo(found, photos)
                    st.write(match['reason'])
                    if st.button('이 종 질문하기', key=f'open_{found.species_id}', width='stretch'):
                        # Navigation must not be overridden by the previous sidebar filters.
                        st.session_state.selected_species_id = found.species_id
                        st.session_state.pending_species = found.species_id
                        st.rerun()

    elif page == '두 종 생태 비교':
        st.subheader('두 종 생태 비교')
        st.caption('각 영역에서 종을 검색하고 선택해 주세요. 종 선택과 필터 변경만으로 AI가 호출되지는 않습니다.')
        left, right = st.columns(2)
        with left:
            first = render_compare_picker(catalog, '첫 번째 종', 'compare_first', default=species.species_id)
        with right:
            second = render_compare_picker(catalog, '두 번째 종', 'compare_second', exclude=first)
        selected_ids = [sid for sid in (first, second) if sid]
        valid_pair = len(selected_ids) == 2 and first != second
        if valid_pair:
            st.write(f'비교 대상: {catalog.get(first).korean_name} ↔ {catalog.get(second).korean_name}')
        else:
            st.info('서로 다른 두 종을 모두 선택하면 비교할 수 있습니다.')
        with st.form('compare'):
            compare_question = st.text_input('비교 질문', value='두 종의 서식 환경, 국내 분포, 주요 위협 요인을 비교해줘.')
            compare = st.form_submit_button('근거로 비교하기', type='primary', disabled=service is None or not valid_pair)
        if compare and service:
            if not valid_pair:
                st.warning('서로 다른 두 종을 선택해 주세요.')
            elif not compare_question.strip():
                st.warning('비교 질문을 입력해 주세요.')
            else:
                with st.status('두 종의 근거를 확인하고 있습니다.', expanded=True) as status:
                    result = safe_action(lambda: service.answer(selected_ids, compare_question, progress=status.write))
                    status.update(label='비교 완료' if result else '비교를 완료하지 못했습니다.',
                                  state='complete' if result else 'error', expanded=False)
                if result:
                    st.session_state.comparison = {'ids': selected_ids, 'result': result}
        if 'comparison' in st.session_state:
            comparison = st.session_state.comparison
            if comparison['ids'] != selected_ids:
                st.caption('아래는 이전에 실행한 비교 결과입니다. 새로 선택한 두 종은 비교 버튼을 눌러 확인해 주세요.')
            st.write(' / '.join(catalog.get(sid).korean_name for sid in comparison['ids']))
            render_result(comparison['result'])


if __name__ == '__main__':
    try:
        main()
    except AppError as exc:
        st.error(str(exc))
    except Exception:
        logging.exception('EcoPedia startup failed')
        st.error('앱을 시작하지 못했습니다. 데이터 파일과 실행 설정을 확인해 주세요.')
