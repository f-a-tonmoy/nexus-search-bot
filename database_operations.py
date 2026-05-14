import mysql.connector
from mysql.connector import Error
from urllib.parse import urlparse, urlencode, parse_qs


def get_db_connection():
    try:
        connection = mysql.connector.connect(
            host='localhost',
            user='root',
            password='00000',
            database='my_custom_bot'
        )
        return connection
    except Error as e:
        print(f'Database connection failed: {e}')
        return None


def insert_search_term(connection, term):
    cursor = connection.cursor()
    try:
        cursor.execute('SELECT id FROM search_terms WHERE term = %s', (term,))
        row = cursor.fetchone()
        if row:
            print(f'Search term already exists (id={row[0]}): {term}')
            return row[0]
        cursor.execute('INSERT INTO search_terms (term) VALUES (%s)', (term,))
        connection.commit()
        print(f'Inserted search term (id={cursor.lastrowid}): {term}')
        return cursor.lastrowid
    except Error as e:
        connection.rollback()
        print(f'Failed to insert search term: {e}')
        return None
    finally:
        cursor.close()


def insert_raw_urls(connection, search_term_id, engine_name, page_no, urls):
    cursor = connection.cursor()
    inserted = []
    try:
        for url in urls:
            cursor.execute(
                '''INSERT INTO raw_urls (search_term_id, search_engine, page_no, url)
                   VALUES (%s, %s, %s, %s)''',
                (search_term_id, engine_name, page_no, url)
            )
            inserted.append((url, cursor.lastrowid))
        connection.commit()
        print(f'Inserted {len(inserted)} raw URLs [{engine_name} p{page_no}]')
        return inserted
    except Error as e:
        connection.rollback()
        print(f'Failed to insert raw URLs: {e}')
        return []
    finally:
        cursor.close()


TRACKING_PARAMS = {
    'msclkid', 'msockid', 'gclid', 'fbclid',
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'ad_group', 'pn_mapping', 'ref', 'referrer',
    'mc_cid', 'mc_eid', 'igshid', 'trk', 'trkInfo',
    '_hsenc', '_hsmi', 'hsCtaTracking',
}


def _normalize_url(url):
    try:
        parsed = urlparse(url)

        # Lowercase scheme + host. Strip leading "www." so the same page is
        # stored once regardless of whether an engine returned the www form.
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        if netloc.startswith('www.'):
            netloc = netloc[4:]

        path = parsed.path.rstrip('/')

        # Strip tracking query params, keep the rest
        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=True)
            clean_params = {k: v for k, v in params.items(
            ) if k.lower() not in TRACKING_PARAMS}
            query = urlencode(clean_params, doseq=True) if clean_params else ''
        else:
            query = ''

        normalized = f'{scheme}://{netloc}{path}'
        if query:
            normalized += f'?{query}'
        return normalized
    except Exception:
        return url


def insert_clean_urls(connection, search_term_id, raw_url_id_map, clean_urls):
    """
    raw_url_id_map: dict of {url: [(raw_url_id, engine_name), ...]}
    clean_urls: iterable of canonical URLs or (original_url, canonical_url) pairs
    """
    cursor = connection.cursor()
    inserted_ids = []
    normalized_map = {_normalize_url(
        raw_url): entries for raw_url, entries in raw_url_id_map.items()}

    try:
        for item in clean_urls:
            if isinstance(item, tuple) and len(item) == 2:
                original_url, url = item
            else:
                original_url = item
                url = item

            normalized_original = _normalize_url(original_url)
            normalized = _normalize_url(url)
            entries = normalized_map.get(normalized_original)

            if entries is None:
                entries = normalized_map.get(normalized)

            # Substring fallback removed -- it could mis-link `/page1` to `/page12`.
            # If neither the original nor canonical URL has a normalized match,
            # we don't trust an approximate one.

            if entries is None:
                print(
                    f'  [DB] Warning: no raw_url match for '
                    f'{original_url} -> {url}, skipping.'
                )
                continue

            first_raw_url_id = entries[0][0]

            cursor.execute(
                '''INSERT IGNORE INTO clean_urls (raw_url_id, search_term_id, url)
                   VALUES (%s, %s, %s)''',
                (first_raw_url_id, search_term_id, url)
            )

            if cursor.lastrowid:
                clean_url_id = cursor.lastrowid
            else:
                cursor.execute(
                    'SELECT id FROM clean_urls WHERE search_term_id = %s AND url = %s',
                    (search_term_id, url)
                )
                row = cursor.fetchone()
                clean_url_id = row[0] if row else None

            if clean_url_id:
                inserted_ids.append(clean_url_id)
                for _, engine_name in entries:
                    cursor.execute(
                        '''INSERT IGNORE INTO clean_url_engines
                               (clean_url_id, search_term_id, search_engine)
                           VALUES (%s, %s, %s)''',
                        (clean_url_id, search_term_id, engine_name)
                    )

        connection.commit()
        print(f'  [DB] Inserted {len(inserted_ids)} clean URLs')
        return inserted_ids

    except Error as e:
        connection.rollback()
        print(f'  [DB] Failed to insert clean URLs: {e}')
        return []
    finally:
        cursor.close()


def insert_url_frequency(connection, search_term_id, clean_url_id, relevance_score):
    cursor = connection.cursor()
    try:
        cursor.execute(
            '''INSERT INTO url_frequency
                   (clean_url_id, search_term_id, relevance_score)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE
                   relevance_score = VALUES(relevance_score)''',
            (clean_url_id, search_term_id, relevance_score)
        )
        connection.commit()
        return cursor.lastrowid
    except Error as e:
        connection.rollback()
        print(
            f'Failed to insert frequency for clean_url_id={clean_url_id}: {e}')
        return None
    finally:
        cursor.close()


def insert_search_history(connection, search_term_id):
    """Record every pipeline run in search_history."""
    cursor = connection.cursor()
    try:
        cursor.execute(
            'INSERT INTO search_history (search_term_id) VALUES (%s)',
            (search_term_id,)
        )
        connection.commit()
    except Error as e:
        connection.rollback()
        print(f'Failed to insert search history: {e}')
    finally:
        cursor.close()


def clear_data_for_search_term(connection, search_term_id):
    """Delete all run data for a search term while keeping the term itself."""
    cursor = connection.cursor()
    try:
        tables = [
            'url_frequency',
            'clean_url_engines',
            'clean_urls',
            'raw_urls',
            'search_history',
        ]
        deleted_counts = {}

        for table in tables:
            cursor.execute(
                f'DELETE FROM {table} WHERE search_term_id = %s',
                (search_term_id,)
            )
            deleted_counts[table] = cursor.rowcount

        connection.commit()
        return deleted_counts
    except Error as e:
        connection.rollback()
        print(f'Failed to clear data for search_term_id={search_term_id}: {e}')
        return None
    finally:
        cursor.close()


def get_recent_searches(connection, limit=3):
    """Return the most recent distinct search terms via join with search_terms."""
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            '''SELECT st.term AS search_term, MAX(sh.searched_at) AS searched_at
               FROM search_history sh
               JOIN search_terms st ON sh.search_term_id = st.id
               GROUP BY sh.search_term_id, st.term
               ORDER BY searched_at DESC
               LIMIT %s''',
            (limit,)
        )
        return cursor.fetchall()
    except Error as e:
        print(f'Failed to fetch recent searches: {e}')
        return []
    finally:
        cursor.close()


def get_all_search_terms(connection):
    """Return all search terms in DB -- used for autofill."""
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute('SELECT id, term FROM search_terms ORDER BY term')
        return cursor.fetchall()
    except Error as e:
        print(f'Failed to fetch search terms: {e}')
        return []
    finally:
        cursor.close()


def get_results_for_term(connection, search_term_id, engines=None):
    """
    Fetch ranked URLs for a search term.
    Optionally filter by a list of engine names.
    Returns rows ordered by relevance_score DESC, engine_count DESC.
    """
    cursor = connection.cursor(dictionary=True)
    try:
        # No per-row dedup subquery -- the UNIQUE (search_term_id, url(512))
        # constraint on clean_urls already prevents duplicates per term.
        if engines:
            placeholders = ','.join(['%s'] * len(engines))
            query = f'''
                SELECT cu.id, cu.url,
                       COALESCE(uf.relevance_score, 0) AS relevance_score,
                       COUNT(DISTINCT cue.search_engine) AS engine_count
                FROM clean_urls cu
                LEFT JOIN url_frequency uf
                    ON cu.id = uf.clean_url_id AND uf.search_term_id = %s
                JOIN clean_url_engines cue
                    ON cu.id = cue.clean_url_id AND cue.search_term_id = %s
                    AND cue.search_engine IN ({placeholders})
                WHERE cu.search_term_id = %s
                GROUP BY cu.id, cu.url, uf.relevance_score
                ORDER BY relevance_score DESC, engine_count DESC
            '''
            params = [search_term_id, search_term_id] + \
                engines + [search_term_id]
        else:
            query = '''
                SELECT cu.id, cu.url,
                       COALESCE(uf.relevance_score, 0) AS relevance_score,
                       COUNT(DISTINCT cue.search_engine) AS engine_count
                FROM clean_urls cu
                LEFT JOIN url_frequency uf
                    ON cu.id = uf.clean_url_id AND uf.search_term_id = %s
                LEFT JOIN clean_url_engines cue
                    ON cu.id = cue.clean_url_id AND cue.search_term_id = %s
                WHERE cu.search_term_id = %s
                GROUP BY cu.id, cu.url, uf.relevance_score
                ORDER BY relevance_score DESC, engine_count DESC
            '''
            params = [search_term_id, search_term_id, search_term_id]

        cursor.execute(query, params)
        return cursor.fetchall()
    except Error as e:
        print(f'Failed to fetch results: {e}')
        return []
    finally:
        cursor.close()


def get_clean_urls_for_term(connection, search_term_id):
    """Used by term_frequency_analyzer -- returns all clean URLs for scoring."""
    cursor = connection.cursor(dictionary=True)
    try:
        # UNIQUE (search_term_id, url(512)) on clean_urls already prevents
        # per-term duplicates -- no need for the MIN(id) dedup subquery.
        cursor.execute(
            '''SELECT cu.id, cu.url, uf.relevance_score,
                      COUNT(DISTINCT cue.search_engine) AS engine_count
               FROM clean_urls cu
               LEFT JOIN url_frequency uf
                   ON cu.id = uf.clean_url_id AND uf.search_term_id = %s
               LEFT JOIN clean_url_engines cue
                   ON cu.id = cue.clean_url_id AND cue.search_term_id = %s
               WHERE cu.search_term_id = %s
               GROUP BY cu.id, cu.url, uf.relevance_score
               ORDER BY relevance_score DESC, engine_count DESC''',
            (search_term_id, search_term_id, search_term_id)
        )
        return cursor.fetchall()
    except Error as e:
        print(f'Failed to fetch clean URLs: {e}')
        return []
    finally:
        cursor.close()


def has_frequency_data(connection, search_term_id):
    """Check if frequency data exists for a search term."""
    cursor = connection.cursor()
    try:
        cursor.execute(
            'SELECT COUNT(*) FROM url_frequency WHERE search_term_id = %s',
            (search_term_id,)
        )
        return cursor.fetchone()[0] > 0
    except Error:
        return False
    finally:
        cursor.close()


def get_search_term_id(connection, term):
    """Return the id of a search term if it exists, else None."""
    cursor = connection.cursor()
    try:
        cursor.execute('SELECT id FROM search_terms WHERE term = %s', (term,))
        row = cursor.fetchone()
        return row[0] if row else None
    except Error:
        return None
    finally:
        cursor.close()
