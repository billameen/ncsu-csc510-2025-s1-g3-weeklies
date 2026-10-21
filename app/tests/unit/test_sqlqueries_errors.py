from sqlQueries import create_connection, close_connection, execute_query, fetch_all, fetch_one


def test_execute_query_returns_none_on_sql_error(tmp_path):
    dbp = tmp_path / "bad.sqlite"
    conn = create_connection(dbp.as_posix())
    try:
        # Intentionally execute invalid SQL to trigger the error path
        cur = execute_query(conn, "THIS IS NOT VALID SQL")
        assert cur is None
    finally:
        close_connection(conn)


def test_fetch_all_and_fetch_one_handle_error_gracefully(tmp_path):
    dbp = tmp_path / "bad2.sqlite"
    conn = create_connection(dbp.as_posix())
    try:
        # Table does not exist; should cause execute_query to return None
        rows = fetch_all(conn, 'SELECT * FROM "DoesNotExist"')
        assert rows == []

        row = fetch_one(conn, 'SELECT * FROM "DoesNotExist"')
        assert row is None
    finally:
        close_connection(conn)
