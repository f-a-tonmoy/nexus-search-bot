# NEXUS — Multi-Engine Web Search Intelligence Bot
**DSE I2400 — Project 1 | CUNY MS Data Science, City College of New York**

NEXUS is a full-stack data ingestion engine that scrapes multiple search engines, deduplicates and validates URLs, counts keyword frequency across result pages, and ranks them through a Streamlit GUI.

---

## Project Structure

```
nexus-search-bot/
├── app.py                      # Streamlit GUI (NEXUS)
├── web_search_scraper.py       # Multi-engine scraping pipeline
├── term_frequency_analyzer.py  # Keyword frequency counter
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

## Prerequisites

- Python 3.10+
- MySQL 8.0+
- Brave Browser (Nightly) installed at:
  `C:\Program Files\BraveSoftware\Brave-Browser-Nightly\Application\brave.exe`

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Create the database
In MySQL, create the database:
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

---

## Running the App

```bash
streamlit run app.py
```

---

## Running the Pipeline (CLI)

To scrape and analyze a search term directly:
```bash
python web_search_scraper.py
```
Picks a random term from the 5 predefined search terms and runs the full pipeline.

To run frequency analysis only:
```bash
python term_frequency_analyzer.py
```
Prompts you to select a term from the DB and optionally rerun.

To clear all data:
```bash
python clear_database.py
```

---

## Database Schema

| Table | Description |
|---|---|
| `search_terms` | Stores unique search queries |
| `raw_urls` | All URLs scraped per engine per page |
| `clean_urls` | Validated, deduplicated canonical URLs |
| `clean_url_engines` | Tracks which engines returned each clean URL |
| `url_frequency` | Keyword frequency score per URL per search term |
| `search_history` | Log of every pipeline run with timestamp |

---

## Search Terms

```
1. childhood cancer morbidity rate ethnicity or race
2. childhood cancer early diagnosis methods
3. childhood cancer immunotherapy success rate
4. childhood cancer treatment best hospitals usa
5. childhood cancer treatment best hospitals europe asia latin countries
```

---

## Pipeline Overview

```
Search Term Input
      │
      ▼
Web Scraping (Google, Bing, Yahoo, DuckDuckGo)
      │  undetected_chromedriver + Brave Browser
      │  DOM extraction, ad filtering, screenshot capture
      ▼
URL Validation
      │  Concurrent HEAD/GET requests
      │  Redirect following → canonical URL
      │  Tracking param stripping (utm_*, msclkid, gclid)
      ▼
Database Storage
      │  raw_urls → clean_urls → clean_url_engines
      ▼
Keyword Frequency Analysis
      │  BeautifulSoup page text extraction
      │  Concurrent processing (10 threads)
      ▼
Ranked Results (GUI)
      │  ORDER BY term_occurrences DESC, engine_count DESC
      ▼
NEXUS Streamlit GUI
```

---

## Key Design Decisions

- **One browser per engine** — driver stays open across all pages per engine, reducing Chrome startup overhead
- **Canonical URL via redirect** — `response.url` after following redirects used as canonical form, ensuring cross-engine deduplication works correctly
- **`clean_url_engines` table** — tracks multi-engine attribution per URL accurately via FK, enabling reliable `source_engine_count`
- **Tracking param stripping** — `utm_*`, `msclkid`, `gclid` removed before validation to prevent duplicate URLs from ad tracking
- **`raw_url_id_map` as list** — stores all `(raw_id, engine)` pairs per URL to capture multi-engine provenance before deduplication

---

## Dependencies

| Package | Purpose |
|---|---|
| `streamlit` | GUI framework |
| `mysql-connector-python` | MySQL connection |
| `undetected-chromedriver` | Anti-bot browser automation |
| `selenium` | DOM interaction |
| `requests` | URL validation |
| `beautifulsoup4` | Page text extraction |
