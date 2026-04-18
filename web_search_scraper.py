import re
import os
import time
import random
import logging
import threading
from datetime import datetime
from urllib.parse import urlparse, unquote

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

import requests
import concurrent.futures
from urllib.parse import urlparse, urlencode, parse_qs

import tempfile
import base64

from database_operations import (
    get_db_connection,
    insert_search_term,
    insert_raw_urls,
    insert_clean_urls,
    insert_search_history,
)

BASE_DIR = r'e:\CCNY\DSE I2400 - Data Engineering\Project 1\Custom Bot'
BRAVE_PATH = r'C:\Program Files\BraveSoftware\Brave-Browser-Nightly\Application\brave.exe'
LOGS_DIR = os.path.join(BASE_DIR, 'logs')

SEARCH_ENGINES = {
    'Google':     'https://www.google.com/search?q=',
    'Bing':       'https://www.bing.com/search?form=QBLH&q=',
    'Yahoo':      'https://search.yahoo.com/search?p=',
    'DuckDuckGo': 'https://duckduckgo.com/?q=',
}

DOM_SELECTORS = {
    'Google':     'div.g a[jsname="UWckNb"], a[jsname="UWckNb"], a[ping]',
    'Bing':       'li.b_algo h2 a, li.b_algo .b_title a',
    'Yahoo':      'div.algo-sr a[href], div.compTitle a[href]',
    'DuckDuckGo': 'a[data-testid="result-title-a"], h2.EKtkFWMYpwzMKOYr a',
}

ENGINE_DELAYS = {
    'Google':     (2, 5),
    'Bing':       (5, 15),
    'Yahoo':      (2, 5),
    'DuckDuckGo': (2, 5),
}

# Noise path patterns to exclude regardless of domain
EXCLUDED_PATHS = {
    '/give', '/donate', '/donation', '/support/donate',
    '/profiles/', '/profile/', '/faculty/', '/staff/',
    '/people/', '/person/', '/author/', '/authors/',
    '/team/', '/about/team', '/biography/', '/bio/',
    '/member/', '/members/', '/directory/',
}

EXCLUDED_DOMAINS = {
    'googleadservices.com', 'doubleclick.net', 'googlesyndication.com',
    'pagead2.googlesyndication.com', 'tpc.googlesyndication.com',
    'ads.yahoo.com', 'adf.ly', 'google.com', 'bing.com', 'yahoo.com',
    'duckduckgo.com', 'accounts.google.com', 'maps.google.com',
    'translate.google.com', 'webcache.googleusercontent.com',
    'support.google.com', 'youtube.com', 'youtu.be',
}


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logger():
    os.makedirs(LOGS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = os.path.join(LOGS_DIR, f'run_{timestamp}.log')

    logger = logging.getLogger('scraper')
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_path, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('%(message)s'))

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info(f'Log file: {log_path}')
    return logger


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------

DRIVER_INIT_LOCK = threading.Lock()


def driver_setup():
    options = uc.ChromeOptions()
    options.binary_location = BRAVE_PATH

    options.add_argument('--headless=new')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')

    # Use a unique profile per driver instance to avoid profile lock conflicts
    profile_path = tempfile.mkdtemp(prefix='chrome_profile_')
    options.add_argument(f'--user-data-dir={profile_path}')

    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ]
    options.add_argument(f'--user-agent={random.choice(user_agents)}')

    with DRIVER_INIT_LOCK:
        return uc.Chrome(
            options=options,
            browser_executable_path=BRAVE_PATH,
            version_main=146
        )


def get_search_url(search_term, engine_name, page_no=1):
    safe_term = search_term.replace(' ', '+')
    url = f'{SEARCH_ENGINES[engine_name]}{safe_term}'

    if page_no > 1:
        if engine_name == 'Google':
            url += f'&start={(page_no - 1) * 10}'
        elif engine_name == 'Bing':
            url += f'&first={(page_no - 1) * 10 + 1}&FORM=PERE'
        elif engine_name == 'Yahoo':
            url += f'&b={(page_no - 1) * 10 + 1}'

    return url


def handle_duckduckgo_pagination(driver, page_no, log):
    log.debug(f'DDG: scrolling to load page {page_no}')
    for _ in range(page_no - 1):
        driver.execute_script(
            'window.scrollTo(0, document.body.scrollHeight);')
        time.sleep(3)
        try:
            driver.execute_script(
                'var btn = document.getElementById("more-results") || '
                'document.querySelector(".result--more__btn"); if(btn) btn.click();'
            )
            time.sleep(3)
        except Exception:
            pass


def is_captcha_page(driver, engine_name=None, log=None):
    try:
        src = driver.page_source.lower()
        title = driver.title.lower()
        signals = ['captcha', 'unusual traffic',
                   'not a robot', 'verify you are human', 'blocked']
        for signal in signals:
            # Bing embeds "blocked" in JS/CSS on normal pages -- check title only
            if engine_name == 'Bing':
                matched = signal in title
            else:
                matched = signal in src or signal in title
            if matched:
                if log:
                    where = 'title' if signal in title else 'page source'
                    log.debug(
                        f'CAPTCHA signal matched: "{signal}" found in {where}')
                return True
        return False
    except Exception:
        return False


def resize_and_screenshot(driver, engine_name, page_no, log):
    height = driver.execute_script('''
        return Math.max(
            document.body.scrollHeight, document.body.offsetHeight,
            document.documentElement.clientHeight,
            document.documentElement.scrollHeight,
            document.documentElement.offsetHeight
        );
    ''')
    log.debug(f'Page height: {height}px -- resizing for screenshot')
    driver.set_window_size(1920, height)
    time.sleep(1)

    filename = f'screenshot_{engine_name.lower()}_{page_no}.png'
    filepath = os.path.join(BASE_DIR, 'screenshots', filename)
    driver.save_screenshot(filepath)
    log.debug(f'Screenshot saved: {filename}')

    driver.set_window_size(1920, 1080)
    return filepath


# ---------------------------------------------------------------------------
# URL extraction
# ---------------------------------------------------------------------------

def unwrap_redirect(href, engine_name):
    if not href:
        return None

    if 'google.com/url' in href and 'q=' in href:
        match = re.search(r'[?&]q=(https?://[^&]+)', href)
        if match:
            return unquote(match.group(1))

    if 'bing.com/ck' in href or 'bing.com/aclick' in href:
        match = re.search(r'[?&]u=a1(.*?)(?:&|$)', href)
        if match:
            try:

                decoded = base64.b64decode(match.group(
                    1) + '==').decode('utf-8', errors='ignore')
                url_match = re.search(r'https?://[^\s"]+', decoded)
                if url_match:
                    return url_match.group(0)
            except Exception:
                pass
        return None

    if 'yahoo.com' in href and 'RU=' in href:
        match = re.search(r'RU=(https?://[^/&]+[^&]*)', href)
        if match:
            return unquote(match.group(1))

    return href


def is_noise_url(url):
    try:
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')
        # Check exact prefix match
        if any(path.startswith(p) for p in EXCLUDED_PATHS):
            return True
        # Check if any excluded segment appears anywhere in path
        if any(p in path for p in EXCLUDED_PATHS):
            return True
    except Exception:
        pass
    return False


def extract_links_from_dom(driver, engine_name, log):
    selector = DOM_SELECTORS[engine_name]
    log.debug(f'DOM selector: {selector}')

    try:
        elements = driver.find_elements(By.CSS_SELECTOR, selector)
        log.debug(f'Found {len(elements)} raw link elements')
    except Exception as e:
        log.warning(f'Selector failed: {e}')
        return []

    urls = []
    for el in elements:
        try:
            href = el.get_attribute('href')
            if not href or not href.startswith('http'):
                continue

            real_url = unwrap_redirect(href, engine_name)
            if not real_url or not real_url.startswith('http'):
                continue

            parsed = urlparse(real_url)
            netloc = parsed.netloc.lower()
            if netloc.startswith('www.'):
                netloc = netloc[4:]

            if any(excl in netloc for excl in EXCLUDED_DOMAINS):
                continue

            if is_noise_url(real_url):
                log.debug(f'Noise URL skipped: {real_url}')
                continue

            urls.append(real_url)
        except Exception:
            continue

    unique_urls = list(dict.fromkeys(urls))
    log.debug(f'{len(unique_urls)} unique organic URLs extracted')
    for u in unique_urls:
        log.debug(f'  - {u}')

    return unique_urls


# ---------------------------------------------------------------------------
# Main scrape function -- one driver per engine, reused across all pages
# ---------------------------------------------------------------------------

def scrape_engine(search_term, engine_name, pages, log, status_callback=None):
    """
    Opens one browser session per engine and scrapes all pages.
    Returns list of (page_no, filepath, urls) tuples.
    """
    def status(msg):
        if status_callback:
            status_callback(msg)

    if engine_name not in SEARCH_ENGINES:
        log.warning(f'Unsupported engine: {engine_name}')
        return []

    log.debug(f'Opening {engine_name} -- will scrape {pages} page(s)')
    driver = driver_setup()
    results = []

    try:
        for page_no in range(1, pages + 1):
            status(f'Searching {engine_name}... (page {page_no}/{pages})')
            log.info(f'  {engine_name} | Page {page_no}/{pages}')
            log.debug(f'--- {engine_name} page {page_no} start ---')

            url = get_search_url(search_term, engine_name, page_no)
            log.debug(f'Navigating to: {url}')
            driver.get(url)

            wait = random.uniform(
                8, 12) if engine_name == 'Bing' else random.uniform(5, 8)
            log.debug(f'Waiting {wait:.1f}s for page to load')
            time.sleep(wait)

            if engine_name == 'Bing':
                log.debug(f'Bing title: {driver.title}')
                log.debug(f'Bing URL: {driver.current_url}')

            if engine_name == 'DuckDuckGo' and page_no > 1:
                handle_duckduckgo_pagination(driver, page_no, log)

            if is_captcha_page(driver, engine_name, log):
                log.warning(f'CAPTCHA on {engine_name} p{page_no} -- skipping')
                status(
                    f'CAPTCHA detected on {engine_name} page {page_no} -- skipping')
                continue

            filepath = resize_and_screenshot(driver, engine_name, page_no, log)
            urls = extract_links_from_dom(driver, engine_name, log)

            if not urls:
                log.warning(
                    f'No URLs extracted from {engine_name} p{page_no} -- possible soft CAPTCHA or empty page')
                status(
                    f'No results from {engine_name} page {page_no} -- possible CAPTCHA or block')
                results.append((page_no, filepath, []))
                continue

            results.append((page_no, filepath, urls))

            if page_no < pages:
                lo, hi = ENGINE_DELAYS[engine_name]
                delay = random.uniform(lo, hi)
                log.debug(f'Inter-page delay: {delay:.1f}s')
                time.sleep(delay)

    finally:
        driver.quit()
        log.debug(f'{engine_name} driver closed')

    return results


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

TRACKING_PARAMS = {
    'msclkid', 'msockid', 'gclid', 'fbclid',
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'ad_group', 'pn_mapping', 'ref', 'referrer',
    'mc_cid', 'mc_eid', 'igshid', 'trk', 'trkInfo',
    '_hsenc', '_hsmi', 'hsCtaTracking',
}


def strip_tracking_params(url):
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return url
        params = parse_qs(parsed.query, keep_blank_values=True)
        clean = {k: v for k, v in params.items() if k.lower()
                 not in TRACKING_PARAMS}
        query = urlencode(clean, doseq=True) if clean else ''
        result = f'{parsed.scheme}://{parsed.netloc}{parsed.path}'
        if query:
            result += f'?{query}'
        return result
    except Exception:
        return url


def process_single_url(url):
    url = strip_tracking_params(url)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')
        clean_url = f'{parsed.scheme}://{parsed.netloc}{path}'
        if parsed.query:
            clean_url += f'?{parsed.query}'

        response = requests.head(
            clean_url, headers=headers, timeout=5, allow_redirects=True)

        if response.status_code < 404 or response.status_code == 405:
            # Use the final URL after redirects as the canonical form
            canonical = response.url.rstrip('/')
            return canonical, None

        # Some sites (e.g. Newsweek) block HEAD -- retry with GET
        if response.status_code == 406:
            response = requests.get(
                clean_url, headers=headers, timeout=5, allow_redirects=True, stream=True)
            response.close()
            if response.status_code < 404 or response.status_code == 405:
                canonical = response.url.rstrip('/')
                return canonical, None

        return None, f'HTTP {response.status_code}'
    except Exception as e:
        return None, str(e)


def validate_urls(raw_urls, log):
    log.debug(f'Deduplicating {len(raw_urls)} URLs')
    raw_urls = list(dict.fromkeys(raw_urls))
    log.debug(f'{len(raw_urls)} after dedup')
    log.debug('Validating URLs concurrently...')

    valid_urls = []
    rejected = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(
            process_single_url, url): url for url in raw_urls}
        for future in concurrent.futures.as_completed(futures):
            original_url = futures[future]
            result, reason = future.result()
            if result:
                valid_urls.append(result)
            else:
                rejected.append((original_url, reason))

    log.debug(f'{len(valid_urls)} URLs passed validation')
    if rejected:
        log.debug(f'{len(rejected)} URLs failed validation:')
        for url, reason in rejected:
            log.debug(f'  REJECTED [{reason}] {url}')

    return valid_urls


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(search_term, pages=3, engines=None, status_callback=None):
    """
    Full scraping pipeline.

    Args:
        search_term: search query string
        pages: number of pages to scrape per engine (1-5)
        engines: list of engine names to use, e.g. ['Google', 'DuckDuckGo']
                 defaults to all engines if None
        status_callback: optional callable(str) for GUI status updates
    """
    def status(msg):
        if status_callback:
            status_callback(msg)

    log = setup_logger()
    pipeline_start = time.time()

    # Determine which engines to use
    active_engines = engines if engines else list(SEARCH_ENGINES.keys())

    # Clear screenshots folder before each run
    screenshots_dir = os.path.join(BASE_DIR, 'screenshots')
    os.makedirs(screenshots_dir, exist_ok=True)
    for f in os.listdir(screenshots_dir):
        if f.endswith('.png'):
            os.remove(os.path.join(screenshots_dir, f))
    log.debug('Screenshots folder cleared')

    log.info(f'{"="*60}')
    log.info(f'PIPELINE START: "{search_term}"')
    log.info(f'Engines: {active_engines} | Pages: {pages}')
    log.info(f'{"="*60}')

    log.debug('Connecting to database...')
    conn = get_db_connection()
    if not conn:
        log.error('Could not connect to database. Aborting.')
        return None, []
    log.debug('Database connected')

    search_term_id = insert_search_term(conn, search_term)
    if not search_term_id:
        log.error('Failed to insert search term. Aborting.')
        return None, []
    log.debug(f'Search term saved (id={search_term_id})')

    all_raw_urls = []
    raw_url_id_map = {}
    map_lock = threading.Lock()
    startup_lock = threading.Lock()
    total_engines = len(active_engines)

    def scrape_and_store(engine, startup_delay=0):
        time.sleep(startup_delay)
        thread_conn = get_db_connection()
        if not thread_conn:
            log.error(f'  {engine}: could not connect to DB')
            return
        try:
            status(f'Opening {engine}...')
            engine_results = scrape_engine(
                search_term, engine, pages, log, status_callback=status_callback)
            for page_no, filepath, urls in engine_results:
                if not urls:
                    log.info(f'  {engine} p{page_no}: 0 URLs extracted')
                else:
                    inserted = insert_raw_urls(
                        thread_conn, search_term_id, engine, page_no, urls)
                    with map_lock:
                        for url, raw_id in inserted:
                            if url not in raw_url_id_map:
                                raw_url_id_map[url] = []
                            raw_url_id_map[url].append((raw_id, engine))
                            all_raw_urls.append(url)
                    log.info(f'  {engine} p{page_no}: {len(urls)} URLs')
                    status(
                        f'Found {len(urls)} URLs from {engine} page {page_no}')
        finally:
            thread_conn.close()

    if total_engines == 1:
        status(f'Starting {active_engines[0]}...')
    else:
        status(f'Launching {total_engines} engines in parallel...')
    with concurrent.futures.ThreadPoolExecutor(max_workers=total_engines) as executor:
        futures = {
            executor.submit(scrape_and_store, engine): engine
            for engine in active_engines
        }
        for future in concurrent.futures.as_completed(futures):
            engine = futures[future]
            try:
                future.result()
            except Exception as e:
                log.error(f'  {engine} failed: {e}')

    log.info(f'All engines done. Total raw URLs: {len(all_raw_urls)}')
    status(
        f'All engines scraped. {len(all_raw_urls)} total raw URLs collected.')
    status(f'Validating {len(all_raw_urls)} raw URLs for reachability...')

    clean_urls = validate_urls(all_raw_urls, log)
    status(f'{len(clean_urls)} reachable URLs confirmed.')

    log.debug(f'Inserting {len(clean_urls)} clean URLs into DB...')
    insert_clean_urls(conn, search_term_id, raw_url_id_map, clean_urls)

    insert_search_history(conn, search_term_id)

    conn.close()
    log.debug('DB connection closed')

    elapsed = time.time() - pipeline_start
    mins, secs = divmod(int(elapsed), 60)

    log.info(f'{"="*60}')
    log.info(f'PIPELINE DONE')
    log.info(f'  Search term id : {search_term_id}')
    log.info(f'  Clean URLs saved: {len(clean_urls)}')
    log.info(f'  Total duration : {mins}m {secs}s')
    log.info(f'{"="*60}')

    status(f'Done! {len(clean_urls)} URLs saved to database')
    return search_term_id, clean_urls


SEARCH_TERMS = [
    'childhood cancer morbidity rate ethnicity or race',
    'childhood cancer early diagnosis methods',
    'childhood cancer immunotherapy success rate',
    'childhood cancer treatment best hospitals usa',
    'childhood cancer treatment best hospitals europe asia latin countries',
]

if __name__ == '__main__':
    search_term = random.choice(SEARCH_TERMS).strip().lower()
    print(f'Selected search term: "{search_term}"')
    term_id, urls = run_pipeline(search_term, pages=3)
