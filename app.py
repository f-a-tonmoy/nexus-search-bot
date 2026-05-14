import re
import time
import queue
import threading
import streamlit as st

from term_frequency_analyzer import run_frequency
from web_search_scraper import run_pipeline, SEARCH_ENGINES
from database_operations import (
    get_db_connection,
    get_all_search_terms,
    get_recent_searches,
    get_results_for_term,
    get_search_term_id,
    has_frequency_data,
    clear_data_for_search_term,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title='NEXUS',
    page_icon='◆',
    layout='wide',
    initial_sidebar_state='expanded',
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------

st.markdown('''
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap');

    /* -----------------------------------------------------------------------
       Accent palette -- light mode uses deep indigo, dark mode uses lighter
       indigo so text remains readable on dark backgrounds.
    ----------------------------------------------------------------------- */
    :root {
        --nexus-accent:        #2d3a8c;
        --nexus-accent-hover:  #1e2a6e;
        --nexus-accent-light:  #e8ecfb;
        --nexus-accent-border: #b0bcee;
    }

    @media (prefers-color-scheme: dark) {
        :root {
            --nexus-accent:        #7b8ff5;
            --nexus-accent-hover:  #9aaaf8;
            --nexus-accent-light:  rgba(123, 143, 245, 0.12);
            --nexus-accent-border: #4a5bbf;
        }
    }

    /* Dark mode -- Streamlit sets this class on the root stApp element */
    .stApp.st-emotion-cache-dark,
    [data-testid="stAppViewContainer"].dark {
        --nexus-accent:        #7b8ff5;
        --nexus-accent-hover:  #9aaaf8;
        --nexus-accent-light:  #1a2060;
        --nexus-accent-border: #3d4fa0;
    }

    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
    }

    h1, h2, h3 {
        font-family: 'Space Mono', monospace;
    }

    /* Title inherits Streamlit's text color so it works in both themes */
    .main-title {
        font-family: 'Space Mono', monospace;
        font-size: 2.2rem;
        font-weight: 700;
        letter-spacing: -1px;
        color: var(--text-color);
        margin-bottom: 0;
    }

    .sidebar-title {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 24px;
    }

    .sidebar-title-hex {
        font-family: 'Space Mono', monospace;
        font-size: 5rem;
        font-weight: 700;
        line-height: 1;
        color: var(--text-color);
    }

    .sidebar-title-text {
        font-family: 'Space Mono', monospace;
        font-size: 3rem;
        font-weight: 700;
        letter-spacing: -1px;
        line-height: 1;
        color: var(--text-color);
    }

    .subtitle {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.95rem;
        color: var(--text-color);
        font-weight: 500;
        opacity: 0.65;
        margin-top: 4px;
        margin-bottom: 32px;
    }

    @media (prefers-color-scheme: dark) {
        .subtitle { color: var(--text-color); opacity: 0.7; }
        .section-label { color: var(--text-color); opacity: 0.6; }
        .stSelectbox label, .stMultiSelect label { color: var(--text-color) !important; opacity: 0.6; }
    }

    /* Search button -- force deep indigo */
    div[data-testid="stButton"] button[kind="primary"],
    div[data-testid="stButton"] button[kind="primary"]:active,
    div[data-testid="stButton"] button[kind="primary"]:focus,
    div[data-testid="stButton"] button[kind="primary"]:hover {
        background-color: #2d3a8c !important;
        border-color: #2d3a8c !important;
        color: #ffffff !important;
        font-family: 'Space Mono', monospace;
        font-size: 0.9rem;
        font-weight: 700;
        letter-spacing: 1px;
    }

    div[data-testid="stButton"] button[kind="primary"]:hover {
        background-color: #1e2a6e !important;
        border-color: #1e2a6e !important;
    }

    div[data-testid="stButton"] button {
        font-family: 'Space Mono', monospace;
        font-size: 0.8rem;
    }

    /* Result cards -- transparent bg, theme handles it */
    .result-card {
        background: transparent;
        border: 1px solid var(--nexus-accent-border);
        border-left: 4px solid var(--nexus-accent);
        border-radius: 6px;
        padding: 14px 18px;
        margin-bottom: 10px;
        transition: border-left-color 0.2s, background 0.2s;
    }

    .result-card:hover {
        background: rgba(45, 58, 140, 0.06);
    }

    @media (prefers-color-scheme: dark) {
        .result-card:hover {
            background: rgba(123, 143, 245, 0.1);
        }
    }

    .result-rank {
        font-family: 'Space Mono', monospace;
        font-size: 1rem;
        color: var(--text-color);
        margin-bottom: 6px;
        font-weight: 700;
        opacity: 0.75;
    }

    .result-url {
        font-size: 0.92rem;
        font-weight: 600;
        color: var(--nexus-accent);
        word-break: break-all;
        text-decoration: none;
    }

    .result-url:hover {
        color: var(--nexus-accent-hover);
        text-decoration: underline;
    }

    .section-label {
        font-family: 'Space Mono', monospace;
        font-size: 0.7rem;
        letter-spacing: 2px;
        color: var(--nexus-accent);
        text-transform: uppercase;
        margin-bottom: 8px;
        font-weight: 800;
    }

    .stSelectbox label, .stSlider label, .stMultiSelect label {
        font-family: 'Space Mono', monospace;
        font-size: 0.7rem;
        letter-spacing: 2px;
        color: var(--nexus-accent) !important;
        text-transform: uppercase;
        font-weight: 800;
    }

    @media (prefers-color-scheme: dark) {
        .section-label {
            color: var(--text-color) !important;
            opacity: 0.6;
        }
        .stSelectbox label, .stSlider label, .stMultiSelect label {
            color: var(--text-color) !important;
            opacity: 0.6;
        }
        .subtitle {
            color: var(--text-color) !important;
            opacity: 0.6;
        }
    }

    .danger-label {
        font-family: 'Space Mono', monospace;
        font-size: 0.7rem;
        letter-spacing: 2px;
        color: #dc2626 !important;
        text-transform: uppercase;
        font-weight: 800;
        margin-bottom: 8px;
    }



    /* Tighten sidebar spacing slightly */
    section[data-testid="stSidebar"] hr {
        margin: 1rem 0 !important;
    }

    section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {
        gap: 0.75rem !important;
    }

    /* Green color for completed status label */
    div[data-testid="stStatusWidget"] div[data-testid="stMarkdownContainer"] p {
        color: #16a34a !important;
        font-weight: 700 !important;
    }
    div[data-testid="stSlider"] div[role="slider"] {
        background-color: #2d3a8c !important;
        border-color: #2d3a8c !important;
        box-shadow: none !important;
    }

    /* Remove red focus ring */
    div[data-testid="stSlider"] div[role="slider"]:focus {
        box-shadow: 0 0 0 4px rgba(45, 58, 140, 0.3) !important;
    }

    /* Grey out entire track including left fill */
    div[data-testid="stSlider"] > div > div > div {
        background-color: #d0d5dd !important;
    }
</style>
''', unsafe_allow_html=True)

# Inject JS to detect dark mode and update CSS variables
st.markdown('''
<!-- Theme-aware accent: check actual background to detect dark/light -->
<script>
function applyNexusTheme() {
    const bg = getComputedStyle(document.body).backgroundColor;
    const rgb = bg.match(/[0-9]+/g);
    const isDark = rgb && (parseInt(rgb[0]) + parseInt(rgb[1]) + parseInt(rgb[2])) < 150;
    const root = document.documentElement;
    if (isDark) {
        root.style.setProperty('--nexus-accent', '#7b8ff5');
        root.style.setProperty('--nexus-accent-hover', '#9aaaf8');
        root.style.setProperty('--nexus-accent-light', '#1a2060');
        root.style.setProperty('--nexus-accent-border', '#4a5bbf');
    } else {
        root.style.setProperty('--nexus-accent', '#2d3a8c');
        root.style.setProperty('--nexus-accent-hover', '#1e2a6e');
        root.style.setProperty('--nexus-accent-light', '#e8ecfb');
        root.style.setProperty('--nexus-accent-border', '#b0bcee');
    }
}
applyNexusTheme();
// Re-run on any body class or style change (theme switch)
new MutationObserver(applyNexusTheme).observe(document.body, {
    attributes: true, childList: false, subtree: false,
    attributeFilter: ['class', 'style']
});
</script>
''', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_ENGINES = list(SEARCH_ENGINES.keys())


# Cached so we don't hammer the DB on every keystroke / rerun.
# The cache is cleared explicitly after a search runs so new history shows up
# immediately instead of waiting for the TTL to expire.
@st.cache_data(ttl=60, show_spinner=False)
def load_search_terms():
    conn = get_db_connection()
    if not conn:
        return []
    terms = get_all_search_terms(conn)
    conn.close()
    return [t['term'] for t in terms]


@st.cache_data(ttl=60, show_spinner=False)
def load_recent_searches(limit=3):
    conn = get_db_connection()
    if not conn:
        return []
    recent = get_recent_searches(conn, limit=limit)
    conn.close()
    return recent


def invalidate_search_caches():
    """Call after any pipeline run so the sidebar shows fresh data."""
    load_search_terms.clear()
    load_recent_searches.clear()


def load_results(search_term_id, engines):
    conn = get_db_connection()
    if not conn:
        return []
    # Set comparison so order from the multiselect widget doesn't matter --
    # if every engine is selected, pass None to skip the JOIN filter entirely.
    all_selected = set(engines) == set(ALL_ENGINES)
    results = get_results_for_term(
        conn, search_term_id, None if all_selected else engines)
    conn.close()
    return results


def check_existing(term):
    conn = get_db_connection()
    if not conn:
        return None, False
    term_id = get_search_term_id(conn, term)
    has_freq = has_frequency_data(conn, term_id) if term_id else False
    conn.close()
    return term_id, has_freq


def clear_existing_search_data(search_term_id):
    conn = get_db_connection()
    if not conn:
        return None
    try:
        return clear_data_for_search_term(conn, search_term_id)
    finally:
        conn.close()


SESSION_DEFAULTS = {
    'results': [],
    'search_term_id': None,
    'last_search': '',
    'running': False,
    'showed_existing': False,
    'pending_search': False,
}


# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------

for key, default in SESSION_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown('''
    <div class="sidebar-title">
        <span class="sidebar-title-hex">⬡</span>
        <span class="sidebar-title-text">NEXUS</span>
    </div>
    ''',
                unsafe_allow_html=True)

    st.markdown('---')

    st.markdown('<div class="section-label">Search Engines</div>',
                unsafe_allow_html=True)
    selected_engines = st.multiselect(
        'Engines',
        options=ALL_ENGINES,
        default=ALL_ENGINES,
        label_visibility='collapsed',
    )

    st.markdown('<div class="section-label">Pages per Engine</div>',
                unsafe_allow_html=True)
    pages = st.number_input('Pages', min_value=1, max_value=5,
                            value=2, step=1, label_visibility='collapsed')

    st.markdown('---')
    st.markdown('<div class="section-label">Recent Searches</div>',
                unsafe_allow_html=True)

    recent = load_recent_searches(limit=3)
    if recent:
        for r in recent:
            ts = r['searched_at'].strftime('%H:%M') if hasattr(
                r['searched_at'], 'strftime') else ''
            # Two columns: timestamp pinned to the left, button on the right.
            # vertical_alignment='top' keeps the timestamp aligned with the
            # first line of the term when the button wraps to multiple lines.
            ts_col, btn_col = st.columns(
                [0.8, 5], gap='small', vertical_alignment='top')
            with ts_col:
                st.markdown(
                    f'<div style="font-family:Space Mono,monospace;'
                    f'font-size:0.8rem;color:var(--text-color);opacity:0.55;'
                    f'padding:9px 0 0 0;white-space:nowrap;text-align:right;">'
                    f'{ts}</div>',
                    unsafe_allow_html=True,
                )
            with btn_col:
                if st.button(
                    r['search_term'],
                    key=f"recent_{r['search_term']}_{r['searched_at']}",
                    use_container_width=True,
                ):
                    st.session_state['last_search'] = r['search_term']
                    st.session_state['pending_search'] = True
                    st.rerun()
    else:
        st.caption('No recent searches yet.')

    st.markdown('---')
    st.markdown('<div class="danger-label">⚠ Danger Zone</div>',
                unsafe_allow_html=True)
    st.caption(
        'Clears all existing data for the current search term and reruns the full pipeline from scratch.')
    st.markdown('''
    <style>
    .danger-btn button {
        background-color: transparent !important;
        border: 1px solid #dc2626 !important;
        color: #dc2626 !important;
        font-family: Space Mono, monospace !important;
    }
    .danger-btn button:hover {
        background-color: #dc2626 !important;
        color: #ffffff !important;
    }
    </style>
    <div class="danger-btn">
    ''', unsafe_allow_html=True)
    rerun_btn = st.button('⟳  Rerun from scratch',
                          use_container_width=True, key='rerun_scratch')
    st.markdown('</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------

st.markdown('<div class="main-title">NEXUS</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">One query, all engines — results ranked by relevance</div>',
            unsafe_allow_html=True)

# Search input with autocomplete
existing_terms = load_search_terms()
search_input = st.text_input(
    'Search term',
    value=st.session_state.get('last_search', ''),
    placeholder='e.g. childhood cancer early diagnosis methods',
    label_visibility='collapsed',
)

# Autofill suggestions
if search_input and len(search_input) >= 3 and existing_terms:
    matches = [t for t in existing_terms if search_input.lower(
    ) in t.lower() and t.lower() != search_input.lower()]
    if matches:
        st.caption('Suggestions from database:')
        cols = st.columns(min(len(matches), 3))
        for i, match in enumerate(matches[:3]):
            with cols[i]:
                if st.button(match, key=f'suggest_{i}', use_container_width=True):
                    st.session_state['last_search'] = match
                    st.rerun()

search_btn = st.button('Search', use_container_width=True, type='primary')

# ---------------------------------------------------------------------------
# Search logic
# ---------------------------------------------------------------------------


def render_log(placeholder, messages, animate_last=False):
    if not messages:
        return

    completed = messages[:-1]
    last_msg, last_color = messages[-1]

    completed_html = ''.join(
        f'<div style="font-family:Space Mono,monospace;font-size:0.95rem;'
        f'color:{c if c else "var(--text-color)"};'
        f'font-weight:{"700" if c else "600"};'
        f'padding:2px 0;line-height:1.5;">› {m}</div>'
        for m, c in completed
    )

    if animate_last:
        words = last_msg.split()
        word_spans = ''.join(
            f'<span id="w{i}" style="opacity:0;transition:opacity 0.05s;">{w} </span>'
            for i, w in enumerate(words)
        )
        last_html = (
            f'<div style="font-family:Space Mono,monospace;font-size:0.95rem;'
            f'color:{last_color if last_color else "var(--text-color)"};'
            f'font-weight:{"700" if last_color else "600"};'
            f'padding:2px 0;line-height:1.5;">› {word_spans}</div>'
        )
        js = f'''
        <script>
        (function() {{
            var n = {len(words)};
            for (var i = 0; i < n; i++) {{
                (function(idx) {{
                    setTimeout(function() {{
                        var el = document.getElementById("w" + idx);
                        if (el) el.style.opacity = "1";
                        var log = document.getElementById("nexus-log");
                        if (log) log.scrollTop = log.scrollHeight;
                    }}, idx * 60);
                }})(i);
            }}
        }})();
        </script>'''
    else:
        last_html = (
            f'<div style="font-family:Space Mono,monospace;font-size:0.95rem;'
            f'color:{last_color if last_color else "var(--text-color)"};'
            f'font-weight:{"700" if last_color else "600"};'
            f'padding:2px 0;line-height:1.5;">› {last_msg}</div>'
        )
        js = '<script>var l=document.getElementById("nexus-log");if(l)l.scrollTop=l.scrollHeight;</script>'

    html = f'''
    <div id="nexus-log" style="max-height:300px;overflow-y:auto;padding-right:4px;">
        {completed_html}{last_html}
    </div>
    {js}
    '''
    with placeholder:
        st.iframe(html, height=320)


def run_full_pipeline(term, engines, pages, force_rerun=False, status_queue=None):
    """Run scraper + frequency in a background thread, posting to status_queue."""
    ACCENT = '#4361ee'

    # Messages that mark phase transitions -- shown in blue
    PHASE_MARKERS = {
        'All engines scraped.',
        'Scraping complete.',
        'Frequency analysis done.',
    }

    def post(msg, color=None):
        if status_queue is not None:
            if color is None:
                for marker in PHASE_MARKERS:
                    if msg.startswith(marker):
                        color = ACCENT
                        break
            status_queue.put((msg, color) if color else msg)

    post(f'Initializing pipeline for: "{term}"', color=ACCENT)

    if force_rerun:
        existing_term_id, _ = check_existing(term)
        if existing_term_id:
            deleted_counts = clear_existing_search_data(existing_term_id)
            if deleted_counts is None:
                post('Failed to clear existing data. Check database logs.')
                status_queue.put(None)
                return
            if sum(deleted_counts.values()) > 0:
                post(
                    'Cleared old data: '
                    f'{deleted_counts.get("raw_urls", 0)} raw URLs, '
                    f'{deleted_counts.get("clean_url_engines", 0)} engine links, '
                    f'{deleted_counts.get("clean_urls", 0)} clean URLs, '
                    f'{deleted_counts.get("url_frequency", 0)} scores, '
                    f'{deleted_counts.get("search_history", 0)} history rows.',
                    color=ACCENT
                )

    term_id, clean_urls = run_pipeline(
        search_term=term,
        pages=pages,
        engines=engines,
        status_callback=lambda m: post(m),
    )

    if not term_id:
        post('Pipeline failed. Check logs.')
        status_queue.put(None)
        return

    # Check total URLs in DB for this term vs what was just scraped
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT COUNT(*) FROM clean_urls WHERE search_term_id = %s', (term_id,))
        total_in_db = cursor.fetchone()[0]
        cursor.close()
        conn.close()

        new_count = len(clean_urls)
        if total_in_db > new_count:
            post(f'{new_count} new URLs added from this run.')
            post(
                f'{total_in_db} URLs total in DB for this term.',
                color='#f59e0b'
            )

    post('Scraping complete. Starting frequency analysis...', color=ACCENT)

    run_frequency(
        search_term_id=term_id,
        search_term=term,
        status_callback=lambda m: post(m),
        force_rerun=force_rerun,
    )

    post('Analysis complete. Loading results...')
    status_queue.put(('DONE', term_id))


def do_search(term, engines, pages, force_rerun=False):
    term = term.strip().lower()
    if not term:
        st.warning('Please enter a search term.')
        return

    # Must contain at least one real word (letters), not just digits / punctuation
    if not re.search(r'[a-z]', term):
        st.warning('Please enter at least one word to search.')
        return

    if not engines:
        st.warning('Please select at least one search engine.')
        return

    st.session_state['results'] = []
    st.session_state['last_search'] = term
    st.session_state['showed_existing'] = False

    term_id, has_freq = check_existing(term)

    # Term exists and has frequency data -- show results directly
    if term_id and has_freq and not force_rerun:
        st.session_state['search_term_id'] = term_id
        st.session_state['results'] = load_results(term_id, engines)
        st.session_state['showed_existing'] = True
        return

    # Frequency only -- run silently, no rerun offered
    if term_id and not has_freq and not force_rerun:
        start_time = time.time()
        with st.status('Running frequency analysis...', expanded=True) as s:
            log_placeholder = st.empty()
            messages = []

            def update(msg):
                messages.append(msg)
                log_placeholder.markdown(
                    '<div id="nexus-log" style="padding-right:4px;">' +
                    ''.join(
                        f'<div style="font-family:Space Mono,monospace;font-size:0.82rem;color:var(--text-color);font-weight:600;padding:2px 0;line-height:1.4;">› {m}</div>'
                        for m in messages
                    ) +
                    '</div>'
                    '<script>const el=document.getElementById("nexus-log");if(el)el.scrollTop=el.scrollHeight;</script>',
                    unsafe_allow_html=True
                )

            run_frequency(
                search_term_id=term_id,
                search_term=term,
                status_callback=update,
                force_rerun=False,
            )
            elapsed = time.time() - start_time
            mins, secs = divmod(int(elapsed), 60)
            duration = f'{mins}m {secs}s' if mins else f'{secs}s'
            s.update(
                label=f'Analysis complete — {duration}', state='complete', expanded=True)

        st.session_state['search_term_id'] = term_id
        st.session_state['results'] = load_results(term_id, engines)
        return

    # Full pipeline -- run in thread, poll queue for updates
    start_time = time.time()
    q = queue.Queue()

    thread = threading.Thread(
        target=run_full_pipeline,
        args=(term, engines, pages, force_rerun, q),
        daemon=True,
    )
    thread.start()

    with st.status('Pipeline running...', expanded=True) as s:
        log_placeholder = st.empty()
        messages = []
        final_term_id = None

        while True:
            try:
                item = q.get(timeout=0.5)
                if item is None:
                    s.update(label='✗ Pipeline failed — check logs',
                             state='error', expanded=True)
                    break
                elif isinstance(item, tuple) and item[0] == 'DONE':
                    final_term_id = item[1]
                    elapsed = time.time() - start_time
                    mins, secs = divmod(int(elapsed), 60)
                    duration = f'{mins}m {secs}s' if mins else f'{secs}s'
                    messages.append(
                        (f'Data ingestion complete — {duration}', '#16a34a'))
                    render_log(log_placeholder, messages)
                    s.update(
                        label=f'Data ingestion complete — {duration}', state='complete', expanded=True)
                    break
                else:
                    # Handle plain string or (msg, color) tuple
                    if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], str) and item[1].startswith('#'):
                        msg_text, msg_color = item
                        messages.append((msg_text, msg_color))
                    else:
                        msg_text = item
                        msg_color = None
                        messages.append((msg_text, None))

                    # Single render per message -- JS handles word-by-word reveal
                    messages[-1] = (msg_text, msg_color)
                    render_log(log_placeholder, messages, animate_last=True)
                    # Wait briefly so the JS reveal doesn't get clobbered by the
                    # next message, but cap it so long status lines don't freeze
                    # the UI for several seconds.
                    word_count = len(msg_text.split())
                    time.sleep(min(word_count * 0.04 + 0.05, 0.5))
            except queue.Empty:
                # Normal -- no new status yet. Exit only if the worker died.
                if not thread.is_alive():
                    break

    thread.join(timeout=5)

    if final_term_id:
        st.session_state['search_term_id'] = final_term_id
        st.session_state['results'] = load_results(final_term_id, engines)


# Auto-trigger search after clicking a "Recent Searches" button -- the click
# sets `pending_search=True` and reruns. We pick it up here and fire the
# search exactly once, then clear the flag.
if st.session_state.get('pending_search') and not st.session_state.get('running'):
    st.session_state['pending_search'] = False
    if search_input and search_input.strip():
        st.session_state['running'] = True
        try:
            do_search(search_input, selected_engines, pages, force_rerun=False)
        finally:
            st.session_state['running'] = False
            invalidate_search_caches()

if search_btn and not st.session_state.get('running'):
    if not search_input or not search_input.strip():
        st.warning('Please enter a search term.')
    else:
        st.session_state['running'] = True
        try:
            do_search(search_input, selected_engines, pages, force_rerun=False)
        finally:
            st.session_state['running'] = False
            invalidate_search_caches()

if rerun_btn and not st.session_state.get('running'):
    if not search_input or not search_input.strip():
        st.warning('Please enter a search term to rerun.')
    else:
        st.session_state['running'] = True
        try:
            do_search(search_input, selected_engines, pages, force_rerun=True)
        finally:
            st.session_state['running'] = False
            invalidate_search_caches()

# ---------------------------------------------------------------------------
# Results display
# ---------------------------------------------------------------------------

results = st.session_state.get('results', [])

# Show notice when displaying cached results
if st.session_state.get('showed_existing') and results:
    st.markdown('''
    <div style="background:rgba(45,58,140,0.08); border:1px solid var(--nexus-accent-border);
                border-radius:8px; padding:10px 16px; margin-bottom:12px;">
        <span style="color:var(--nexus-accent); font-size:0.9rem; font-weight:600;">
            Showing cached results from database.
        </span>
    </div>
    ''', unsafe_allow_html=True)

if results:
    st.markdown('---')

    total = len(results)
    term_display = st.session_state.get('last_search', '')
    st.markdown(
        f'<div style="font-size:1.1rem;font-weight:700;margin-bottom:16px;"><b>{total} results</b> for <i>"{term_display}"</i></div>', unsafe_allow_html=True)

    st.markdown('<br>', unsafe_allow_html=True)

    for i, row in enumerate(results, 1):
        url = row['url']
        # DB returns Decimal -- cast to float so :.2f formatting works
        score = float(row.get('relevance_score') or 0)
        engine_count = row.get('engine_count') or 0

        # Engine count bar (max 4 engines)
        filled = '█' * engine_count
        empty = '░' * (len(ALL_ENGINES) - engine_count)
        engine_bar = filled + empty

        st.markdown(f'''
        <div class="result-card">
            <div class="result-rank">#{i:02d} &nbsp;|&nbsp; engines: {engine_bar} ({engine_count}/{len(ALL_ENGINES)}) &nbsp;|&nbsp; score: <span style="color:var(--nexus-accent);font-size:1.05rem;font-weight:800;">{score:.2f}</span></div>
            <a class="result-url" href="{url}" target="_blank">{url}</a>
        </div>
        ''', unsafe_allow_html=True)

elif st.session_state.get('last_search'):
    st.info('No results found. Try running the pipeline first.')
