#NEXUS — Multi-Engine Search Intelligence

NEXUS is a web search aggregation and relevance ranking engine. It scrapes Google, Bing, Yahoo, and DuckDuckGo simultaneously, validates and deduplicates the results, scores each URL by keyword relevance using phrase-weighted frequency analysis, and surfaces the most relevant results through a Streamlit GUI.

---

## How It Works

NEXUS runs a three-stage ETL pipeline:

**1. Extract - Web Scraping**
Four search engines are scraped in parallel using `undetected_chromedriver` with Brave Browser. Each engine gets its own isolated browser session and DB connection. URLs are extracted via DOM selectors, unwrapped from redirect wrappers, and filtered for noise (ads, social media, search engine internals).

**2. Transform - Validation and Deduplication**
Raw URLs go through concurrent HEAD/GET validation to confirm reachability. Redirects are followed to their canonical form (`response.url`), and tracking parameters (`utm_*`, `msclkid`, `gclid`) are stripped before storage. This ensures URLs from different engines that redirect to the same page are correctly deduplicated.

Multi-engine attribution is tracked via a dedicated `clean_url_engines` table -- if Google and DuckDuckGo both return the same URL, it's stored once in `clean_urls` but attributed to both engines. This powers the engine count signal used in ranking.

**3. Load + Score - Frequency Analysis**
Each validated URL is fetched and its visible text extracted using BeautifulSoup (scripts, styles, nav, footer stripped). A phrase-weighted scoring model counts both individual keyword matches and multi-word phrase matches:

- Individual keywords: 1x weight
- Bigrams (e.g. `childhood cancer`): 2x weight
- Trigrams (e.g. `childhood cancer treatment`): 3x weight

Weights scale linearly with phrase length -- a trigram match is three times as specific as a single keyword match.

This rewards pages that discuss the topic in context rather than pages that happen to contain the individual words independently. Scores and engine counts are written to `url_frequency` and results are ranked by `term_occurrences DESC, engine_count DESC`.

---

## Architecture

```
User Input (Search Term)
        │
        ▼
┌───────────────────────────────────────┐
│         Parallel Scraping             │
│  Google  Bing  Yahoo  DuckDuckGo      │
│  (each in isolated browser + thread)  │
└───────────────┬───────────────────────┘
                │ raw URLs
                ▼
┌───────────────────────────────────────┐
│       URL Validation Pipeline         │
│  - Concurrent HEAD/GET requests       │
│  - Redirect following (canonical URL) │
│  - Tracking param stripping           │
│  - Deduplication via unique constraint│
└───────────────┬───────────────────────┘
                │ clean URLs + engine attribution
                ▼
┌───────────────────────────────────────┐
│     MySQL Database (my_custom_bot)    │
│  search_terms  raw_urls  clean_urls   │
│  clean_url_engines  url_frequency     │
│  search_history                       │
└───────────────┬───────────────────────┘
                │
                ▼
┌───────────────────────────────────────┐
│    Keyword Frequency Analyzer         │
│  - BeautifulSoup text extraction      │
│  - Phrase-weighted scoring model      │
│  - Concurrent (10 threads)            │
└───────────────┬───────────────────────┘
                │ ranked results
                ▼
┌───────────────────────────────────────┐
│         NEXUS Streamlit GUI           │
│  - Live pipeline status log           │
│  - Engine filter + page selector      │
│  - Recent search history              │
│  - Results ranked by relevance        │
└───────────────────────────────────────┘
```

---

## Project Structure

```
nexus-search-bot/
├── app.py                      # Streamlit GUI (NEXUS)
├── web_search_scraper.py       # Parallel multi-engine scraping pipeline
├── term_frequency_analyzer.py  # Phrase-weighted keyword frequency scorer
├── database_operations.py      # All MySQL DB operations
├── clear_database.py           # Utility to wipe all tables
├── requirements.txt
├── nexus.sql                   # Schema export
├── .gitignore
├── .streamlit/
│   └── config.toml             # Theme configuration
├── misc/
│   ├── data_ingestion.py       # Early prototype (superseded)
│   └── pipeline.ipynb          # Notebook prototype (superseded)
├── logs/                       # Auto-generated run logs (gitignored)
├── screenshots/                # Auto-generated screenshots (gitignored)
└── chrome_profile/             # Browser profile (gitignored)
```

---

## Database Schema

| Table | Description |
|---|---|
| `search_terms` | Stores unique search queries |
| `raw_urls` | All URLs scraped per engine per page |
| `clean_urls` | Validated, deduplicated canonical URLs |
| `clean_url_engines` | Tracks which engines returned each clean URL |
| `url_frequency` | Phrase-weighted keyword frequency score per URL |
| `search_history` | Log of every pipeline run with timestamp |

---

## Prerequisites

- Python 3.10+
- MySQL 8.0+
- Brave Browser or any Chromium-based browser

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Create the database
```sql
CREATE DATABASE my_custom_bot;
```
Then import the schema:
```bash
mysql -u root -p my_custom_bot < nexus.sql
```

### 3. Configure database credentials
In `database_operations.py`, update if needed:
```python
host='localhost'
user='root'
password='00000'
database='my_custom_bot'
```

### 4. Configure browser path
In `web_search_scraper.py`, update `BRAVE_PATH` to point to your Chromium-based browser executable.

---

## Running the App

```bash
streamlit run app.py
```

---

## CLI Usage

Scrape and analyze a search term directly:
```bash
python web_search_scraper.py
```

Run frequency analysis only on existing DB data:
```bash
python term_frequency_analyzer.py
```

Clear all data:
```bash
python clear_database.py
```

---

## Key Design Decisions

- **Parallel scraping** - all engines run simultaneously in separate threads, each with its own browser session and DB connection, protected by a global driver init lock to avoid chromedriver binary conflicts on Windows
- **Canonical URL via redirect** - `response.url` after following redirects is used as the canonical form, ensuring www vs non-www variants of the same page deduplicate correctly
- **`clean_url_engines` table** - decouples engine attribution from URL storage, enabling accurate multi-engine count even when different engines return slightly different URL variants that resolve to the same canonical URL
- **Phrase-weighted scoring** - weights scale linearly with phrase length: 1x for individual keywords, 2x for bigrams, 3x for trigrams. This rewards pages that discuss the topic in context rather than pages that happen to contain the individual words independently
- **Tracking param stripping** - `utm_*`, `msclkid`, `gclid` and other ad tracking parameters are removed before validation, preventing the same page from appearing multiple times with different tracking IDs

---

## Dependencies

| Package | Purpose |
|---|---|
| `streamlit` | GUI framework |
| `mysql-connector-python` | MySQL connection |
| `undetected-chromedriver` | Anti-bot browser automation |
| `selenium` | DOM interaction and URL extraction |
| `requests` | Concurrent URL validation |
| `beautifulsoup4` | Page text extraction for frequency analysis |
