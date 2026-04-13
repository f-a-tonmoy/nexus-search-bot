import os
import re
import logging
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
import concurrent.futures

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
    'what', 'how', 'when', 'where', 'why', 'best', 'most', 'more', 'very',
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
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
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


def count_keywords(text, keywords, phrases):
    """
    Score a page using individual keywords and phrases.
    Weights scale linearly with phrase length:
      - Individual keywords (1-gram): 1x
      - Bigrams:                      2x
      - Trigrams:                     3x
    """
    kw_score = sum(text.count(kw) for kw in keywords)

    phrase_score = 0
    for ph in phrases:
        word_count = len(ph.split())
        weight = word_count  # 2 for bigram, 3 for trigram
        phrase_score += text.count(ph) * weight

    return kw_score + phrase_score


# ---------------------------------------------------------------------------
# Source engine count
# ---------------------------------------------------------------------------

def get_source_engine_count(conn, clean_url_id, search_term_id):
    cursor = conn.cursor()
    try:
        cursor.execute(
            '''SELECT COUNT(DISTINCT search_engine)
               FROM clean_url_engines
               WHERE clean_url_id = %s AND search_term_id = %s''',
            (clean_url_id, search_term_id)
        )
        row = cursor.fetchone()
        return row[0] if row else 0
    except Exception:
        return 0
    finally:
        cursor.close()


# ---------------------------------------------------------------------------
# Per-URL processing
# ---------------------------------------------------------------------------

def process_url(args):
    url, clean_url_id, search_term_id, keywords, phrases = args
    text, error = fetch_page_text(url)
    if text is None:
        return clean_url_id, search_term_id, url, 0, error
    total = count_keywords(text, keywords, phrases)
    return clean_url_id, search_term_id, url, total, None


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
            engines = row.get('engine_count') or row.get('source_engine_count') or 0
            score = row.get('term_occurrences') or 0
            log.debug(f'  engines={engines} score={score:>4} {row["url"]}')
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
    status(f'Counting keyword frequencies for {len(rows)} URLs...')

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
                log.debug(f'  score={score:>4} {url}')
            results.append((clean_url_id, term_id, url, score, error))

    log.info('Writing frequency data to DB...')
    inserted = 0
    for clean_url_id, term_id, url, score, error in results:
        engine_count = get_source_engine_count(conn, clean_url_id, term_id)
        log.debug(f'  engines={engine_count} score={score} {url}')
        insert_url_frequency(conn, term_id, clean_url_id, score, engine_count)
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

    conn = get_db_connection()
    if not conn:
        log.error('Could not connect to DB.')
        exit(1)

    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT id, term FROM search_terms ORDER BY id DESC')
    terms = cursor.fetchall()
    cursor.close()
    conn.close()

    if not terms:
        log.error('No search terms found in DB.')
        exit(1)

    print('\nAvailable search terms:')
    for t in terms:
        print(f"  [{t['id']}] {t['term']}")

    choice = input('\nEnter search term id to process (or "all"): ').strip().lower()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if choice == 'all':
        cursor.execute('SELECT id, term FROM search_terms')
        selected = cursor.fetchall()
    else:
        cursor.execute('SELECT id, term FROM search_terms WHERE id = %s', (choice,))
        selected = cursor.fetchall()

    cursor.close()
    conn.close()

    for t in selected:
        # CLI mode -- ask user if existing data should be reused
        conn2 = get_db_connection()
        cursor2 = conn2.cursor()
        cursor2.execute('SELECT COUNT(*) FROM url_frequency WHERE search_term_id = %s', (t['id'],))
        count = cursor2.fetchone()[0]
        cursor2.close()
        conn2.close()

        force = False
        if count > 0:
            ans = input(f'\nFrequency data exists for "{t["term"]}" ({count} records). Rerun? (y/n): ').strip().lower()
            force = (ans == 'y')

        run_frequency(t['id'], t['term'], log, force_rerun=force)
