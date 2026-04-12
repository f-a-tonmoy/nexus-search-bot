import re
import os
import time
import random
import base64

from dotenv import load_dotenv
from groq import Groq

import undetected_chromedriver as uc

import requests
import concurrent.futures
from urllib.parse import urlparse

from database_operations import (
    get_db_connection,
    insert_search_term,
    insert_raw_urls,
    insert_clean_urls,
)

BASE_DIR = r'e:\CCNY\DSE I2400 - Data Engineering\Project 1\Custom Bot'
BRAVE_PATH = r'C:\Program Files\BraveSoftware\Brave-Browser-Nightly\Application\brave.exe'

SEARCH_ENGINES = {
    'Google': 'https://www.google.com/search?q=',
    'Bing': 'https://www.bing.com/search?q=',
    'Yahoo': 'https://search.yahoo.com/search?p=',
    'DuckDuckGo': 'https://duckduckgo.com/?q='
}

AD_DOMAINS = {
    'googleadservices.com',
    'doubleclick.net',
    'googlesyndication.com',
    'ads.yahoo.com',
    'bing.com/aclick',
    'adf.ly',
    'adclick.g.doubleclick.net',
    'pagead2.googlesyndication.com',
    'tpc.googlesyndication.com',
}


def load_client():
    load_dotenv()
    api_key = None
    with open(os.path.join(BASE_DIR, 'groq.txt'), 'r') as f:
        api_key = f.read().strip()

    print(f'[CLIENT] Groq API key loaded: {"Yes" if api_key else "No"}')
    client = Groq(api_key=api_key)
    print('[CLIENT] Groq client initialized successfully')
    return client


def driver_setup():
    options = uc.ChromeOptions()
    options.binary_location = BRAVE_PATH

    options.add_argument('--headless=new')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')

    profile_path = os.path.join(os.getcwd(), 'chrome_profile')
    options.add_argument(f'--user-data-dir={profile_path}')

    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ]
    options.add_argument(f'--user-agent={random.choice(user_agents)}')

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
            url += f'&first={(page_no - 1) * 5 + 1}&FORM=PERE'
        elif engine_name == 'Yahoo':
            url += f'&b={(page_no - 1) * 10 + 1}'

    return url


def handle_duckduckgo_pagination(driver, page_no):
    print(f'  [DDG] Scrolling to load page {page_no}...')
    for _ in range(page_no - 1):
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        time.sleep(3)
        try:
            driver.execute_script(
                'var btn = document.getElementById(\'more-results\') || '
                'document.querySelector(\'.result--more__btn\'); if(btn) btn.click();'
            )
            time.sleep(3)
        except Exception:
            pass


def resize_window_to_full_height(driver):
    web_page_height = driver.execute_script('''
        return Math.max(
            document.body.scrollHeight,
            document.body.offsetHeight,
            document.documentElement.clientHeight,
            document.documentElement.scrollHeight,
            document.documentElement.offsetHeight
        );
    ''')
    print(f'  [BROWSER] Page height: {web_page_height}px -- resizing window')
    driver.set_window_size(1920, web_page_height)
    time.sleep(random.uniform(2, 4))


def capture_screenshot(driver, engine_name, page_no):
    filename = f'screenshot_{engine_name.lower()}_{page_no}.png'
    filepath = os.path.join(BASE_DIR, 'screenshots', filename)
    driver.save_screenshot(filepath)
    print(f'  [SCREENSHOT] Saved: {filename}')
    return filepath


def take_screenshot(search_term, engine_name, page_no=1):
    if engine_name not in SEARCH_ENGINES:
        print(f'  [SCREENSHOT] Unsupported engine: {engine_name}')
        return None

    print(f'  [BROWSER] Opening {engine_name} page {page_no}...')
    driver = driver_setup()

    try:
        url = get_search_url(search_term, engine_name, page_no)
        print(f'  [BROWSER] Navigating to: {url}')
        driver.get(url)

        wait = random.uniform(5, 8)
        print(f'  [BROWSER] Waiting {wait:.1f}s for page to load...')
        time.sleep(wait)

        if engine_name == 'DuckDuckGo' and page_no > 1:
            handle_duckduckgo_pagination(driver, page_no)

        resize_window_to_full_height(driver)
        filepath = capture_screenshot(driver, engine_name, page_no)

    finally:
        driver.quit()
        print(f'  [BROWSER] Driver closed')

    return filepath


def extract_links(filepath, client):
    print(f'  [VLM] Reading screenshot: {os.path.basename(filepath)}')

    with open(filepath, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode('utf-8')

    print(f'  [VLM] Image encoded ({len(img_b64) // 1024}KB) -- sending to Groq...')

    prompt = (
        'Identify the search results in this image. Extract the main website domain or URL for each result. '
        'Format each strictly as a clean URL starting with https://. Do not include trailing punctuation, '
        'colons, or breadcrumb arrows. If the image shows a CAPTCHA page, ignore it and return nothing. '
        'If there is a cookie request modal or popup, ignore it and only extract the underlying search result URLs. '
        'Do not include sponsored results or advertisement links.'
    )

    messages = [
        {
            'role': 'user',
            'content': [
                {
                    'type': 'image_url',
                    'image_url': {'url': f'data:image/png;base64,{img_b64}'}
                },
                {
                    'type': 'text',
                    'text': prompt
                }
            ]
        }
    ]

    try:
        response = client.chat.completions.create(
            model='meta-llama/llama-4-scout-17b-16e-instruct',
            messages=messages,
            max_tokens=500
        )

        raw_text = response.choices[0].message.content
        print(f'  [VLM] Raw response received ({len(raw_text)} chars)')

        urls = re.findall(r'https?://[a-zA-Z0-9.\-/?=&#_]+', raw_text)
        unique_urls = list(set([url.rstrip('.-') for url in urls]))

        print(f'  [VLM] Extracted {len(unique_urls)} unique URLs')
        for u in unique_urls:
            print(f'    - {u}')
        return unique_urls

    except Exception as e:
        print(f'  [VLM] Extraction failed: {e}')
        return []


def is_ad_url(url):
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith('www.'):
            netloc = netloc[4:]
        return any(ad in netloc for ad in AD_DOMAINS)
    except Exception:
        return False


def filter_ads(urls):
    filtered = [u for u in urls if not is_ad_url(u)]
    removed = len(urls) - len(filtered)
    if removed:
        print(f'  [FILTER] Removed {removed} ad URLs')
    else:
        print(f'  [FILTER] No ad URLs detected')
    return filtered


def process_single_url(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    try:
        if not url.startswith('http'):
            url = 'https://' + url

        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith('www.'):
            netloc = netloc[4:]

        path = parsed.path
        if path.endswith('/'):
            path = path[:-1]

        clean_url = f'https://{netloc}{path}'
        if parsed.query:
            clean_url += f'?{parsed.query}'

        response = requests.head(clean_url, headers=headers, timeout=5, allow_redirects=True)

        if response.status_code < 404 or response.status_code == 405:
            return clean_url

    except Exception:
        pass

    return None


def clean_and_validate_urls(raw_urls):
    print(f'\n[CLEAN] Starting dedup + ad filter on {len(raw_urls)} URLs...')
    raw_urls = filter_ads(list(set(raw_urls)))
    print(f'[CLEAN] {len(raw_urls)} URLs after dedup + ad filter')

    print(f'[CLEAN] Validating {len(raw_urls)} URLs concurrently...')
    valid_urls = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        results = executor.map(process_single_url, raw_urls)
        for result in results:
            if result:
                valid_urls.append(result)

    print(f'[CLEAN] {len(valid_urls)} URLs passed validation')
    return valid_urls


def run_pipeline(search_term, pages=2):
    print(f'\n{"="*60}')
    print(f'[PIPELINE] Starting for: "{search_term}"')
    print(f'{"="*60}')

    print('\n[PIPELINE] Connecting to database...')
    conn = get_db_connection()
    if not conn:
        print('[PIPELINE] ERROR: Could not connect to database. Aborting.')
        return None, []
    print('[PIPELINE] Database connected')

    print('\n[PIPELINE] Loading Groq client...')
    client = load_client()

    print('\n[PIPELINE] Inserting search term into DB...')
    search_term_id = insert_search_term(conn, search_term)
    if not search_term_id:
        print('[PIPELINE] ERROR: Failed to insert search term. Aborting.')
        return None, []
    print(f'[PIPELINE] Search term saved (id={search_term_id})')

    all_raw_urls = []
    raw_url_id_map = {}
    total_engines = len(SEARCH_ENGINES)

    for engine_idx, engine in enumerate(SEARCH_ENGINES, 1):
        print(f'\n[PIPELINE] Engine {engine_idx}/{total_engines}: {engine}')

        for page in range(1, pages + 1):
            print(f'\n  --- {engine} | Page {page}/{pages} ---')

            filepath = take_screenshot(search_term, engine, page_no=page)
            if not filepath:
                print(f'  [PIPELINE] Screenshot failed, skipping')
                continue

            urls = extract_links(filepath, client)
            if not urls:
                print(f'  [PIPELINE] No URLs extracted, skipping DB insert')
                continue

            inserted = insert_raw_urls(conn, search_term_id, engine, page, urls)

            for url, raw_id in inserted:
                raw_url_id_map[url] = raw_id
                all_raw_urls.append(url)

            print(f'  [PIPELINE] Running total raw URLs: {len(all_raw_urls)}')

    print(f'\n[PIPELINE] All engines done. Total raw URLs: {len(all_raw_urls)}')

    clean_urls = clean_and_validate_urls(all_raw_urls)

    print(f'\n[PIPELINE] Inserting {len(clean_urls)} clean URLs into DB...')
    insert_clean_urls(conn, search_term_id, raw_url_id_map, clean_urls)

    conn.close()
    print('[PIPELINE] DB connection closed')

    print(f'\n{"="*60}')
    print(f'[PIPELINE] DONE')
    print(f'  Search term id : {search_term_id}')
    print(f'  Clean URLs saved: {len(clean_urls)}')
    print(f'{"="*60}')

    return search_term_id, clean_urls


if __name__ == '__main__':
    search_term = 'Childhood cancer treatment best hospitals USA'
    # search_term = input('Enter your search term: ').strip().lower()

    term_id, urls = run_pipeline(search_term.strip().lower(), pages=2)

    print(f'\nFinal URL list:')
    for url in urls:
        print(f'  {url}')