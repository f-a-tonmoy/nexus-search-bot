from database_operations import get_db_connection


def clear_database():
    conn = get_db_connection()
    if not conn:
        print('Could not connect to database.')
        return

    confirm = input('This will delete ALL data. Type "yes" to confirm: ').strip().lower()
    if confirm != 'yes':
        print('Aborted.')
        conn.close()
        return

    cursor = conn.cursor()
    try:
        tables = [
            'url_frequency',
            'clean_url_engines',
            'clean_urls',
            'raw_urls',
            'search_terms',
        ]

        for table in tables:
            cursor.execute(f'DELETE FROM {table}')
            cursor.execute(f'ALTER TABLE {table} AUTO_INCREMENT = 1')
            print(f'Cleared: {table}')

        conn.commit()
        print('\nDatabase cleared successfully.')

    except Exception as e:
        conn.rollback()
        print(f'Error: {e}')
    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    clear_database()
