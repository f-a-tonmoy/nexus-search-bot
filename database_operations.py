import mysql.connector
from mysql.connector import Error


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
    from urllib.parse import urlparse, urlencode, parse_qs
    try:
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')

        # Strip tracking query params, keep the rest
        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=True)
            clean_params = {k: v for k, v in params.items() if k.lower() not in TRACKING_PARAMS}
            query = urlencode(clean_params, doseq=True) if clean_params else ''
        else:
            query = ''

        normalized = f'{parsed.scheme}://{parsed.netloc}{path}'
        if query:
            normalized += f'?{query}'
        return normalized
    except Exception:
        return url


def insert_clean_urls(connection, search_term_id, raw_url_id_map, clean_urls):
    """
    raw_url_id_map: dict of {url: [(raw_url_id, engine_name), ...]}
    """
    cursor = connection.cursor()
    inserted_ids = []
    normalized_map = {_normalize_url(raw_url): entries for raw_url, entries in raw_url_id_map.items()}

    try:
        for url in clean_urls:
            normalized = _normalize_url(url)
            entries = normalized_map.get(normalized)

            if entries is None:
                for norm_raw, e in normalized_map.items():
                    if normalized in norm_raw or norm_raw in normalized:
                        entries = e
                        break

            if entries is None:
                print(f'  [DB] Warning: no raw_url match for {url}, skipping.')
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


def insert_url_frequency(connection, search_term_id, clean_url_id, term_occurrences, source_engine_count):
    cursor = connection.cursor()
    try:
        cursor.execute(
            '''INSERT INTO url_frequency
                   (clean_url_id, search_term_id, term_occurrences, source_engine_count)
               VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                   term_occurrences = VALUES(term_occurrences),
                   source_engine_count = VALUES(source_engine_count)''',
            (clean_url_id, search_term_id, term_occurrences, source_engine_count)
        )
        connection.commit()
        return cursor.lastrowid
    except Error as e:
        connection.rollback()
        print(f'Failed to insert frequency for clean_url_id={clean_url_id}: {e}')
        return None
    finally:
        cursor.close()


def insert_search_history(connection, search_term):
    """Record every pipeline run in search_history."""
    cursor = connection.cursor()
    try:
        cursor.execute(
            'INSERT INTO search_history (search_term) VALUES (%s)',
            (search_term,)
        )
        connection.commit()
    except Error as e:
        connection.rollback()
        print(f'Failed to insert search history: {e}')
    finally:
        cursor.close()


def get_recent_searches(connection, limit=3):
    """Return the most recent distinct search terms."""
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            '''SELECT search_term, MAX(searched_at) AS searched_at
               FROM search_history
               GROUP BY search_term
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
    Returns rows ordered by engine_count DESC, term_occurrences DESC.
    """
    cursor = connection.cursor(dictionary=True)
    try:
        if engines:
            placeholders = ','.join(['%s'] * len(engines))
            query = f'''
                SELECT cu.id, cu.url,
                       COALESCE(uf.term_occurrences, 0) AS term_occurrences,
                       COUNT(DISTINCT cue.search_engine) AS engine_count
                FROM clean_urls cu
                LEFT JOIN url_frequency uf
                    ON cu.id = uf.clean_url_id AND uf.search_term_id = %s
                JOIN clean_url_engines cue
                    ON cu.id = cue.clean_url_id AND cue.search_term_id = %s
                    AND cue.search_engine IN ({placeholders})
                WHERE cu.search_term_id = %s
                AND cu.id = (
                    SELECT MIN(cu2.id) FROM clean_urls cu2
                    WHERE cu2.search_term_id = cu.search_term_id
                    AND cu2.url = cu.url
                )
                GROUP BY cu.id, cu.url, uf.term_occurrences
                ORDER BY engine_count DESC, term_occurrences DESC
            '''
            params = [search_term_id, search_term_id] + engines + [search_term_id]
        else:
            query = '''
                SELECT cu.id, cu.url,
                       COALESCE(uf.term_occurrences, 0) AS term_occurrences,
                       COUNT(DISTINCT cue.search_engine) AS engine_count
                FROM clean_urls cu
                LEFT JOIN url_frequency uf
                    ON cu.id = uf.clean_url_id AND uf.search_term_id = %s
                LEFT JOIN clean_url_engines cue
                    ON cu.id = cue.clean_url_id AND cue.search_term_id = %s
                WHERE cu.search_term_id = %s
                AND cu.id = (
                    SELECT MIN(cu2.id) FROM clean_urls cu2
                    WHERE cu2.search_term_id = cu.search_term_id
                    AND cu2.url = cu.url
                )
                GROUP BY cu.id, cu.url, uf.term_occurrences
                ORDER BY engine_count DESC, term_occurrences DESC
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
        cursor.execute(
            '''SELECT cu.id, cu.url, uf.term_occurrences, uf.source_engine_count,
                      COUNT(DISTINCT cue.search_engine) AS engine_count
               FROM clean_urls cu
               LEFT JOIN url_frequency uf
                   ON cu.id = uf.clean_url_id AND uf.search_term_id = %s
               LEFT JOIN clean_url_engines cue
                   ON cu.id = cue.clean_url_id AND cue.search_term_id = %s
               WHERE cu.search_term_id = %s
               AND cu.id = (
                   SELECT MIN(cu2.id) FROM clean_urls cu2
                   WHERE cu2.search_term_id = cu.search_term_id
                   AND cu2.url = cu.url
               )
               GROUP BY cu.id, cu.url, uf.term_occurrences, uf.source_engine_count
               ORDER BY engine_count DESC, uf.term_occurrences DESC''',
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
