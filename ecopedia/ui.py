"""화면 스타일과 안전하게 이스케이프한 표시용 컴포넌트."""
from html import escape

import streamlit as st


PALETTES = {
    '라이트': {
        'scheme':'light', 'ink':'#173d32', 'leaf':'#24654c', 'muted':'#5c7065', 'line':'#d5dfd3',
        'bg':'#f6f7f2', 'sidebar':'#edf1e9', 'panel':'#ffffff', 'soft':'#e9f0e5',
        'selected':'#d8e8d2', 'link':'#216148', 'button':'#24654c', 'button-text':'#ffffff',
        'warm':'#fbefdf', 'warm-text':'#89512a', 'warm-line':'#eed8bb',
    },
    '다크': {
        'scheme':'dark', 'ink':'#e3ece4', 'leaf':'#a7d6a8', 'muted':'#acbdaf', 'line':'#3b5145',
        'bg':'#111b17', 'sidebar':'#17271f', 'panel':'#1c2d24', 'soft':'#263d30',
        'selected':'#34533e', 'link':'#b1dfb3', 'button':'#abd8a5', 'button-text':'#132719',
        'warm':'#423626', 'warm-text':'#f3ce98', 'warm-line':'#6b583d',
    },
}


CSS = '''
<style>
.stApp { background:var(--eco-bg); color:var(--eco-ink); color-scheme:var(--eco-scheme); }
[data-testid="stHeader"] { background:var(--eco-bg); color:var(--eco-ink); }
[data-testid="stMainBlockContainer"] { max-width:1240px; padding-top:2rem; padding-bottom:5rem; }
[data-testid="stSidebar"] { background:var(--eco-sidebar); border-right:1px solid var(--eco-line); }
[data-testid="stSidebarContent"] { padding-top:1.2rem; }
[data-testid="stSidebar"] h2 { font-size:1.05rem; }
[data-testid="stSidebar"] [data-testid="stRadio"] > div { gap:.45rem; }
[data-testid="stSidebar"] [data-testid="stRadio"] label { border:1px solid transparent; border-radius:12px; padding:.75rem .7rem; color:var(--eco-ink); }
.st-key-page label:hover { background:var(--eco-soft); }
.st-key-page label:has(input:checked) { background:var(--eco-selected); border-color:var(--eco-line) !important; box-shadow:inset 3px 0 0 var(--eco-leaf); }
.st-key-sidebar_appearance { background:var(--eco-panel); border:1px solid var(--eco-line); border-radius:16px; padding:.8rem; margin-bottom:.5rem; }
.st-key-sidebar_appearance [data-testid="stRadio"] label { padding:.35rem .6rem; }
.st-key-sidebar_appearance [data-testid="stRadio"] label:has(input:checked) { background:var(--eco-selected); }
.eco-sidebar-section { margin:.5rem 0 .3rem; font-size:.65rem; font-weight:700; letter-spacing:.18em; color:var(--eco-muted); }
.eco-sidebar-brand { background:linear-gradient(140deg,#143c30,#2a5740); border:1px solid #41644a; border-radius:20px; padding:1.2rem; margin-bottom:.7rem; color:#fff; }
.eco-sidebar-brand strong { display:block; color:#fff; font-size:1.55rem; letter-spacing:-.045em; margin:.5rem 0 .2rem; }
.eco-sidebar-brand small { display:block; color:#d3e3cc; font-size:.77rem; line-height:1.7; }
.eco-sidebar-emblem { display:inline-flex; align-items:center; justify-content:center; width:42px; height:42px; border:1px solid #7b9b76; border-radius:13px; background:#ffffff12; font-size:1.35rem; }
.eco-sidebar-inventory { border-top:1px solid #62825b; margin-top:.85rem; padding-top:.75rem; color:#d3e3cc; font-size:.75rem; }
.eco-sidebar-note { padding:.9rem 1rem; background:var(--eco-soft); border:1px solid var(--eco-line); border-radius:14px; color:var(--eco-muted); font-size:.78rem; line-height:1.8; }
h1,h2,h3,h4 { color:var(--eco-ink) !important; letter-spacing:-.045em; }
h1 { font-weight:800 !important; } h3 { font-size:1.65rem !important; }
p,li { line-height:1.75; } a { color:var(--eco-link); text-underline-offset:3px; }
[data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"] p { color:var(--eco-ink); }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color:var(--eco-muted); overflow-wrap:anywhere; }
[data-testid="stVerticalBlockBorderWrapper"] > div { border-radius:18px; }
[data-testid="stForm"] { background:var(--eco-panel); border:1px solid var(--eco-line); border-radius:18px; padding:1.35rem; }
[data-testid="stTextInput"] input, [data-baseweb="select"] > div { border-radius:10px; }
div[data-baseweb="input"], div[data-baseweb="base-input"], div[data-baseweb="textarea"], [data-baseweb="select"] > div { background:var(--eco-panel) !important; color:var(--eco-ink) !important; border-color:var(--eco-line) !important; }
input,textarea,[role="combobox"] { color:var(--eco-ink) !important; caret-color:var(--eco-leaf); }
input,textarea { background:transparent !important; }
input::placeholder, textarea::placeholder { color:var(--eco-muted) !important; opacity:1; }
[data-baseweb="popover"], [role="listbox"], [role="option"] { background:var(--eco-panel) !important; color:var(--eco-ink) !important; }
[role="option"]:hover, [role="option"][aria-selected="true"] { background:var(--eco-selected) !important; }
[data-baseweb="select"] svg { fill:var(--eco-ink); }
/* Streamlit 1.62 uses React Aria controls, not the former BaseWeb roots. */
[data-testid="stTextInputRootElement"],
[data-testid="stTextArea"] > div,
[data-testid="stSelectbox"] [role="group"],
[data-testid="stSelectbox"] .react-aria-Group,
[data-testid="stSelectbox"] div:has(> input[role="combobox"]) {
 background-color:var(--eco-panel) !important;
 color:var(--eco-ink) !important;
 border-color:var(--eco-line) !important;
 border-radius:10px;
}
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stSelectbox"] input[role="combobox"] {
 background-color:var(--eco-panel) !important;
 color:var(--eco-ink) !important;
 -webkit-text-fill-color:var(--eco-ink) !important;
 opacity:1 !important;
}
[data-testid="stTextInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder,
[data-testid="stSelectbox"] input::placeholder {
 color:var(--eco-muted) !important;
 -webkit-text-fill-color:var(--eco-muted) !important;
 opacity:1 !important;
}
[data-testid="stSelectbox"] button,
[data-testid="stTextInputRootElement"] button { color:var(--eco-ink) !important; }
[data-testid="stSelectboxVirtualDropdown"],
[data-testid="stSelectboxVirtualDropdown"] [role="listbox"],
[data-testid="stSelectboxVirtualDropdown"] [role="option"] {
 background-color:var(--eco-panel) !important;
 color:var(--eco-ink) !important;
 border-color:var(--eco-line) !important;
}
[data-testid="stSelectboxVirtualDropdown"] [role="option"]:is([data-hovered],[data-focused],[aria-selected="true"]),
[data-testid="stSelectboxVirtualDropdown"] [role="option"]:is([data-hovered],[data-focused]) [data-item-hl] {
 background-color:var(--eco-selected) !important;
 color:var(--eco-ink) !important;
}
[data-testid="stCaptionContainer"] [data-testid="stMarkdownContainer"],
[data-testid="stCaptionContainer"] p,
[data-testid="stCaptionContainer"] span { color:var(--eco-muted) !important; }
.stButton button, .stFormSubmitButton button, .stLinkButton a { border-radius:10px; min-height:2.65rem; font-weight:600; }
.stButton button, .stFormSubmitButton button, .stLinkButton a { background:var(--eco-panel); color:var(--eco-ink); border-color:var(--eco-line); }
.stButton button p, .stFormSubmitButton button p { color:inherit; }
button[kind="primary"], [data-testid="stBaseButton-primary"], .stFormSubmitButton button { background:var(--eco-button) !important; color:var(--eco-button-text) !important; border-color:var(--eco-button) !important; }
.stButton button:hover { border-color:var(--eco-leaf); color:var(--eco-leaf); }
button:focus-visible,a:focus-visible { outline:3px solid #b08c39 !important; outline-offset:3px; }
button:disabled { opacity:.55; }
/* Tooltips render in a body portal, outside .stApp. Theme the actual content
   surface as well as its nested Markdown so light defaults cannot leak in. */
[data-testid="stTooltipContent"], [data-testid="stTooltipErrorContent"] {
 background-color:var(--eco-panel) !important;
 color:var(--eco-ink) !important;
 border:1px solid var(--eco-line) !important;
 box-shadow:0 6px 24px #00000035;
}
[data-testid="stTooltipContent"] *, [data-testid="stTooltipErrorContent"] * {
 color:var(--eco-ink) !important;
 -webkit-text-fill-color:var(--eco-ink) !important;
}
[data-testid="stTooltipContent"] a, [data-testid="stTooltipErrorContent"] a {
 color:var(--eco-link) !important;
 -webkit-text-fill-color:var(--eco-link) !important;
}
.st-key-brand_hero { background:linear-gradient(115deg,#143c30,#285b43); border-radius:24px; padding:1.8rem 2rem; margin-bottom:1rem; }
.st-key-brand_hero h1 { color:#fff !important; font-size:2.65rem; letter-spacing:-.055em; padding-top:.1rem; }
.st-key-brand_hero p { color:#e1ebe1; }
.st-key-brand_hero [data-testid="stCaptionContainer"] p,
.st-key-brand_hero [data-testid="stCaptionContainer"] [data-testid="stMarkdownContainer"] { color:#c0d2c0 !important; font-size:.8rem; }
.eco-eyebrow { font-size:.68rem; letter-spacing:.2em; color:#bfd7b8; font-weight:700; margin-bottom:.2rem; }
.eco-hero-count { text-align:right; padding-top:.8rem; color:#eaf1e3; }
.eco-hero-count strong { display:block; font-size:3rem; font-weight:700; line-height:1.15; letter-spacing:-.05em; }
.eco-hero-count span { font-size:.8rem; color:#c9d9c3; }
.eco-badges { display:flex; flex-wrap:wrap; gap:.45rem; margin:.5rem 0 1rem; }
.eco-badge { padding:.3rem .7rem; background:var(--eco-soft); color:var(--eco-ink); border:1px solid var(--eco-line); border-radius:100px; font-size:.78rem; font-weight:600; }
.eco-badge.grade-1 { color:var(--eco-warm-text); background:var(--eco-warm); border-color:var(--eco-warm-line); }
.eco-badge.grade-2 { color:var(--eco-leaf); background:var(--eco-soft); }
.eco-empty-photo { min-height:205px; display:flex; flex-direction:column; align-items:center; justify-content:center; background:var(--eco-soft); border-radius:14px; color:var(--eco-muted); gap:.6rem; margin-bottom:.7rem; }
.eco-empty-photo span { font-size:2.3rem; } .eco-empty-photo small { font-size:.85rem; }
.st-key-species_profile,.st-key-keyword_panel,.st-key-compare_first_card,.st-key-compare_second_card,
[class*="st-key-result_card_"] { background:var(--eco-panel); border:1px solid var(--eco-line); border-radius:20px; padding:1.4rem; }
.st-key-species_profile { margin-bottom:.8rem; }
[data-testid="stImage"] img { border-radius:14px; max-height:320px; object-fit:contain; background:var(--eco-soft); }
[class*="st-key-result_card_"] [data-testid="stImage"] img { width:100%; height:210px; object-fit:contain; }
[class*="st-key-keyword_"] button { border-radius:100px; font-size:.85rem; }
[data-testid="stChatMessage"] { background:var(--eco-panel); color:var(--eco-ink); border:1px solid var(--eco-line); border-radius:16px; padding:1.2rem; }
[data-testid="stBottom"], [data-testid="stBottomBlockContainer"] { background:var(--eco-bg); }
[data-testid="stChatInput"] { background:var(--eco-panel); border-radius:16px; border:1px solid var(--eco-line); }
[data-testid="stChatInput"] > div {
 background-color:var(--eco-panel) !important;
 color:var(--eco-ink) !important;
 border-color:var(--eco-line) !important;
}
[data-testid="stChatInput"] > div:focus-within { border-color:var(--eco-leaf) !important; }
[data-testid="stChatInputTextArea"] {
 background-color:transparent !important;
 color:var(--eco-ink) !important;
 -webkit-text-fill-color:var(--eco-ink) !important;
 caret-color:var(--eco-leaf);
 opacity:1 !important;
}
[data-testid="stChatInputTextArea"]::placeholder {
 color:var(--eco-muted) !important;
 -webkit-text-fill-color:var(--eco-muted) !important;
 opacity:1 !important;
}
[data-testid="stChatInput"] button { color:var(--eco-leaf) !important; }
#stChatInputInstructions, #stChatInputInstructions * { color:var(--eco-muted) !important; }
[data-testid="stExpander"] details { background:var(--eco-panel); border-color:var(--eco-line); color:var(--eco-ink); border-radius:12px; }
[data-testid="stExpander"] summary {
 background-color:var(--eco-soft) !important;
 color:var(--eco-ink) !important;
}
[data-testid="stExpander"] summary:hover,
[data-testid="stExpander"] summary:focus-visible {
 background-color:var(--eco-selected) !important;
}
[data-testid="stExpander"] summary :is(p,span,svg) { color:var(--eco-ink) !important; }
[data-testid="stExpanderDetails"] { border-color:var(--eco-line) !important; }
/* st.text uses a span with its own Streamlit foreground, not Markdown. */
[data-testid="stText"], [data-testid="stText"] span {
 color:var(--eco-ink) !important;
 -webkit-text-fill-color:var(--eco-ink) !important;
}
[data-testid="stSpinner"], [data-testid="stSpinner"] p {
 color:var(--eco-ink) !important;
}
[data-testid="stAlert"] { background:var(--eco-soft); color:var(--eco-ink); border-radius:12px; }
pre,code { background:var(--eco-soft) !important; color:var(--eco-ink) !important; }
table,th,td { border-color:var(--eco-line) !important; color:var(--eco-ink); }
hr { border-color:var(--eco-line); }
.eco-footer { margin-top:1.6rem; font-size:.72rem; letter-spacing:.035em; color:var(--eco-muted); }
.st-key-information_coverage { background:var(--eco-panel); border:1px solid var(--eco-line); border-radius:20px; padding:1.35rem; margin-bottom:1rem; }
.eco-coverage-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.75rem; margin:.5rem 0 .7rem; }
.eco-coverage-card { background:var(--eco-soft); border:1px solid var(--eco-line); border-radius:14px; padding:1rem; }
.eco-coverage-card small { display:block; color:var(--eco-muted); font-size:.78rem; margin-bottom:.4rem; }
.eco-coverage-card strong { color:var(--eco-ink); font-size:.95rem; }
.eco-coverage-card.related strong { color:var(--eco-warm-text); }
.eco-coverage-card.related { background:var(--eco-warm); border-color:var(--eco-warm-line); }
.eco-coverage-card.available strong { color:var(--eco-leaf); }
.eco-coverage-card.extracted strong { color:var(--eco-leaf); }
@media (max-width:700px) {
 .eco-coverage-grid { grid-template-columns:1fr; }
 [data-testid="stMainBlockContainer"] { padding:1rem 1rem 5rem; }
 .st-key-brand_hero { padding:1.3rem; border-radius:18px; }
 .st-key-brand_hero h1 { font-size:2.15rem; }
 .eco-hero-count { text-align:left; padding-top:0; }
 .eco-hero-count strong { font-size:2rem; }
 [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
 [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { min-width:min(100%,220px); flex:1 1 220px; }
 .st-key-keyword_panel [data-testid="stColumn"] { min-width:100px; flex:1 1 100px; }
 .st-key-species_profile,.st-key-keyword_panel,.st-key-compare_first_card,.st-key-compare_second_card { padding:1rem; }
}
@media (prefers-reduced-motion:reduce) { *,*::before,*::after { scroll-behavior:auto !important; animation:none !important; transition:none !important; } }
</style>
'''


def theme_variables(mode):
    palette = PALETTES.get(mode, PALETTES['라이트'])
    return '<style>:root{' + ''.join(f'--eco-{key}:{value};' for key, value in palette.items()) + '}</style>'


def apply_theme():
    st.markdown(theme_variables(st.session_state.get('appearance', '라이트')), unsafe_allow_html=True)
    st.markdown(CSS, unsafe_allow_html=True)


def render_sidebar_brand(catalog):
    st.markdown('<div class="eco-sidebar-brand"><span class="eco-sidebar-emblem" aria-hidden="true">🌿</span>'
        '<strong>EcoPedia</strong><small>알아갈수록 지키고 싶은 생명들</small>'
        f'<div class="eco-sidebar-inventory">멸종위기종 {len(catalog.items)}종 · 근거 기반 백과</div></div>', unsafe_allow_html=True)


def sidebar_section(title):
    st.markdown(f'<div class="eco-sidebar-section">{escape(title)}</div>', unsafe_allow_html=True)


def render_brand(catalog, basis_date):
    with st.container(key='brand_hero'):
        left, right = st.columns([4, 1])
        with left:
            st.markdown('<div class="eco-eyebrow">DISCOVER · UNDERSTAND · PROTECT</div>', unsafe_allow_html=True)
            st.title('🌿 EcoPedia')
            st.write('국내 멸종위기 야생생물의 생태와 위협 요인을 근거와 함께 알아보세요.')
            st.caption(f'공식 목록 {len(catalog.items)}종 · 자료 기준 {basis_date} · 법정 등급 1급 / 2급')
        with right:
            st.markdown(f'<div class="eco-hero-count"><strong>{len(catalog.items)}</strong><span>기록된 멸종위기종</span></div>', unsafe_allow_html=True)


def species_badges(species):
    # Only escaped data and fixed markup enter these HTML components.
    group = escape(species.taxon_group)
    grade = species.endangered_grade
    st.markdown(f'<div class="eco-badges"><span class="eco-badge">{group}</span>'
                f'<span class="eco-badge grade-{grade}">멸종위기 {grade}급</span></div>', unsafe_allow_html=True)


def empty_photo():
    st.markdown('<div class="eco-empty-photo"><span aria-hidden="true">🌱</span><small>확인된 대표 이미지가 없어요</small></div>', unsafe_allow_html=True)


def render_coverage_cards(records):
    states = {'available': '✓ 정보 확보', 'extracted': '✓ 원문 대조 정보', 'related': '◐ 관련 근거 있음', 'missing': '— 미확보'}
    cards = ''.join(f'<div class="eco-coverage-card {escape(item["status"])}">'
        f'<small>{escape(item["label"])}</small><strong>{states[item["status"]]}</strong></div>' for item in records)
    st.markdown(f'<div class="eco-coverage-grid">{cards}</div>', unsafe_allow_html=True)
