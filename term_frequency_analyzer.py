import os
import re
import logging
from datetime import datetime

import requests
import concurrent.futures
from bs4 import BeautifulSoup

import math

from database_operations import (
    get_db_connection,
    get_clean_urls_for_term,
    insert_url_frequency,
)

BASE_DIR = r'e:\CCNY\DSE I2400 - Data Engineering\Project 1\Custom Bot'
LOGS_DIR = os.path.join(BASE_DIR, 'logs')

STOP_WORDS = {
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
    'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
    'would', 'could', 'should', 'may', 'might', 'shall', 'can', 'not',
    'no', 'nor', 'so', 'yet', 'both', 'either', 'neither', 'that', 'this',
    'these', 'those', 'it', 'its', 'we', 'you', 'he', 'she', 'they',
    'their', 'our', 'your', 'my', 'his', 'her', 'which', 'who', 'whom',
    'what', 'how', 'when', 'where', 'why', 'most', 'more', 'very',
    'just', 'also', 'about', 'than', 'then', 'each', 'other', 'such',
    'into', 'over', 'after', 'before', 'between', 'through', 'during',
    'including', 'across', 'among', 'within',
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logger():
    os.makedirs(LOGS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = os.path.join(LOGS_DIR, f'frequency_{timestamp}.log')

    logger = logging.getLogger('frequency')
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_path, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('%(message)s'))

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info(f'Log file: {log_path}')
    return logger


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

def extract_keywords(search_term):
    """Extract individual keywords after removing stop words."""
    words = re.findall(r'[a-z]+', search_term.lower())
    keywords = [w for w in words if w not in STOP_WORDS and len(w) > 2]
    return keywords


def extract_phrases(search_term):
    """
    Extract meaningful 2-3 word phrases from the search term.
    These are counted with a higher weight than individual keywords.
    Example: 'childhood cancer treatment best hospitals usa'
    → ['childhood cancer', 'cancer treatment', 'childhood cancer treatment']
    """
    words = re.findall(r'[a-z]+', search_term.lower())
    meaningful = [w for w in words if w not in STOP_WORDS and len(w) > 2]

    phrases = []
    # Bigrams
    for i in range(len(meaningful) - 1):
        phrases.append(f'{meaningful[i]} {meaningful[i+1]}')
    # Trigrams
    for i in range(len(meaningful) - 2):
        phrases.append(f'{meaningful[i]} {meaningful[i+1]} {meaningful[i+2]}')

    return phrases


# ---------------------------------------------------------------------------
# Page scraping
# ---------------------------------------------------------------------------

def fetch_page_text(url, timeout=10):
    # Full browser User-Agent + standard accept headers so sites with
    # anti-bot heuristics don't refuse the page content fetch.
    headers = {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/120.0.0.0 Safari/537.36'),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if response.status_code >= 400:
            return None, f'HTTP {response.status_code}'

        soup = BeautifulSoup(response.text, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'meta', 'noscript']):
            tag.decompose()

        text = soup.get_text(separator=' ')
        text = re.sub(r'\s+', ' ', text).strip().lower()
        return text, None

    except Exception as e:
        return None, str(e)


def _word_pattern(term):
    """Build a whole-word regex for `term` that also matches the plural form.
    Examples:
      'cancer'    -> \\bcancers?\\b           (matches 'cancer' or 'cancers')
      'hospitals' -> \\bhospitals?\\b         (matches 'hospital' or 'hospitals')
      'data engineering' -> \\bdata engineerings?\\b
    The trailing-s heuristic is applied only to the LAST word so that bigrams
    and trigrams pluralize correctly ('childhood cancer' -> 'childhood cancers').
    Words ending in 's' that are <= 3 chars (e.g. 'us', 'is', 'gas') keep their
    final 's' literal to avoid false matches.
    """
    parts = [re.escape(p) for p in term.split()]
    if not parts:
        return r'(?!)'  # never matches
    last = parts[-1]
    if last.endswith('s') and len(last) > 3:
        # Likely already plural -- make the trailing s optional
        parts[-1] = last[:-1] + 's?'
    else:
        # Allow optional plural-s suffix
        parts[-1] = last + 's?'
    return rf'\b{" ".join(parts)}\b'


def _count_whole_word(text, term):
    """Count whole-word occurrences of `term` (and its plural form) in `text`.
    Uses word boundaries so 'data' won't match inside 'metadata' / 'database',
    and accepts both singular and plural forms of the final word."""
    return len(re.findall(_word_pattern(term), text))


def score_page(text, keywords, phrases):
    """
    Score a page using individual keywords and phrases, normalized by page length.
    Weights scale linearly with phrase length:
      - Individual keywords (1-gram): 1x
      - Bigrams:                      2x
      - Trigrams:                     3x

    Raw score is divided by log(word_count) to normalize for page length.
    This prevents long pages (e.g. faculty profiles, CVs) from dominating
    purely due to higher word count.

    Matches are word-boundary anchored and plural-aware -- 'cancer' matches
    both 'cancer' and 'cancers', but won't match inside 'metadata'.

    Returns a float rounded to 2 decimal places.
    """

    kw_score = sum(_count_whole_word(text, kw) for kw in keywords)

    phrase_score = 0
    for ph in phrases:
        weight = len(ph.split())
        phrase_score += _count_whole_word(text, ph) * weight

    raw_score = kw_score + phrase_score

    # Normalize by log of page word count (minimum 1 to avoid division by zero)
    page_word_count = max(len(text.split()), 1)
    normalized = raw_score / math.log(page_word_count + 1)

    # Keep 2 decimal places so weak-but-real signal isn't rounded to 0
    return round(normalized, 2)


# ---------------------------------------------------------------------------
# Per-URL processing
# ---------------------------------------------------------------------------

def process_url(args):
    url, clean_url_id, search_term_id, keywords, phrases = args
    text, error = fetch_page_text(url)
    if text is None:
        return clean_url_id, search_term_id, url, 0, error
    score = score_page(text, keywords, phrases)
    return clean_url_id, search_term_id, url, score, None


# ---------------------------------------------------------------------------
# Core frequency runner -- callable from GUI or CLI
# ---------------------------------------------------------------------------

def run_frequency(search_term_id, search_term, log=None, status_callback=None, force_rerun=False):
    """
    Run keyword frequency analysis for a search term.

    Args:
        search_term_id: DB id of the search term
        search_term: the search term string
        log: optional logger instance (created if None)
        status_callback: optional callable(str) for GUI status updates
        force_rerun: if True, clears existing frequency data and reruns
                     if False and data exists, uses existing data (no prompt)
    
    Returns True if analysis was run, False if existing data was used.
    """
    def status(msg):
        if status_callback:
            status_callback(msg)

    if log is None:
        log = setup_logger()

    log.info(f'{"="*60}')
    log.info(f'FREQUENCY START: term_id={search_term_id} "{search_term}"')
    log.info(f'{"="*60}')

    keywords = extract_keywords(search_term)
    phrases = extract_phrases(search_term)
    log.info(f'Keywords ({len(keywords)}): {keywords}')
    log.info(f'Phrases  ({len(phrases)}): {phrases}')

    conn = get_db_connection()
    if not conn:
        log.error('Could not connect to database. Aborting.')
        return False

    # Check if frequency data already exists
    cursor = conn.cursor()
    cursor.execute(
        'SELECT COUNT(*) FROM url_frequency WHERE search_term_id = %s',
        (search_term_id,)
    )
    existing_count = cursor.fetchone()[0]
    cursor.close()

    if existing_count > 0 and not force_rerun:
        log.info(f'Frequency data already exists ({existing_count} records). Using existing data.')
        rows = get_clean_urls_for_term(conn, search_term_id)
        log.info(f'Existing results ({len(rows)} URLs):')
        for row in rows:
            engines = row.get('engine_count') or 0
            score = float(row.get('relevance_score') or 0)
            log.debug(f'  engines={engines} score={score:>6.2f} {row["url"]}')
        conn.close()
        return False

    if existing_count > 0 and force_rerun:
        log.info(f'Clearing {existing_count} existing frequency records...')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM url_frequency WHERE search_term_id = %s', (search_term_id,))
        conn.commit()
        cursor.close()

    rows = get_clean_urls_for_term(conn, search_term_id)
    if not rows:
        log.info('No clean URLs found for this search term.')
        conn.close()
        return False

    log.info(f'Processing {len(rows)} clean URLs...')
    status(f'{len(rows)} unique URLs after deduplication. Scoring...')

    args_list = [
        (row['url'], row['id'], search_term_id, keywords, phrases)
        for row in rows
    ]

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_url, args): args for args in args_list}
        for future in concurrent.futures.as_completed(futures):
            clean_url_id, term_id, url, score, error = future.result()
            if error:
                log.debug(f'  FAILED [{error}] {url}')
            else:
                log.debug(f'  score={score:>6.2f} {url}')
            results.append((clean_url_id, term_id, url, score, error))

    log.info('Writing frequency data to DB...')
    inserted = 0
    for clean_url_id, term_id, url, score, error in results:
        log.debug(f'  score={score} {url}')
        insert_url_frequency(conn, term_id, clean_url_id, score)
        inserted += 1

    conn.close()
    status(f'Frequency analysis done. {inserted} URLs scored.')

    log.info(f'{"="*60}')
    log.info(f'FREQUENCY DONE')
    log.info(f'  URLs processed : {len(results)}')
    log.info(f'  Records written: {inserted}')
    log.info(f'{"="*60}')

    return True


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    log = setup_logger()

    # Use one connection for all metadata queries -- run_frequency manages
    # its own connection internally, so we close this one before invoking it.
    conn = get_db_connection()
    if not conn:
        log.error('Could not connect to DB.')
        exit(1)

    try:
        cursor = conn.cursor(dictionary=True)

        # List all terms
        cursor.execute('SELECT id, term FROM search_terms ORDER BY id DESC')
        terms = cursor.fetchall()
        if not terms:
            log.error('No search terms found in DB.')
            exit(1)

        print('\nAvailable search terms:')
        for t in terms:
            print(f"  [{t['id']}] {t['term']}")

        choice = input('\nEnter search term id to process (or "all"): ').strip().lower()

        # Pick selection (still on the same connection)
        if choice == 'all':
            selected = terms
        else:
            cursor.execute(
                'SELECT id, term FROM search_terms WHERE id = %s', (choice,))
            selected = cursor.fetchall()

        # Per-term existing-data counts in one query
        existing_counts = {}
        if selected:
            ids = tuple(t['id'] for t in selected)
            placeholders = ','.join(['%s'] * len(ids))
            cursor.execute(
                f'''SELECT search_term_id, COUNT(*) AS n
                    FROM url_frequency
                    WHERE search_term_id IN ({placeholders})
                    GROUP BY search_term_id''',
                ids,
            )
            existing_counts = {row['search_term_id']: row['n']
                               for row in cursor.fetchall()}

        cursor.close()
    finally:
        conn.close()

    # Now drive run_frequency for each selected term
    for t in selected:
        count = existing_counts.get(t['id'], 0)
        force = False
        if count > 0:
            ans = input(
                f'\nFrequency data exists for "{t["term"]}" '
                f'({count} records). Rerun? (y/n): '
            ).strip().lower()
            force = (ans == 'y')

        run_frequency(t['id'], t['term'], log, force_rerun=force)
