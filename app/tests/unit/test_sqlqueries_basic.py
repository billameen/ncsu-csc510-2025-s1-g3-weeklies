# tests/unit/test_sqlqueries_basic.py
from sqlQueries import (
    create_connection,
    close_connection,
    execute_query,
    fetch_one,
    fetch_all,
)


def test_sql_create_and_close(tmp_path):
    dbp = tmp_path / "mini.sqlite"
    con = create_connection(dbp.as_posix())
    assert con is not None
    close_connection(con)


def test_sql_execute_and_fetch(tmp_path):
    dbp = tmp_path / "mini.sqlite"
    con = create_connection(dbp.as_posix())
    try:
        execute_query(con, 'CREATE TABLE T(a INTEGER, b TEXT)')
        execute_query(con, 'INSERT INTO T(a,b) VALUES (?,?)', (1, "x"))
        execute_query(con, 'INSERT INTO T(a,b) VALUES (?,?)', (2, "y"))

        rows = fetch_all(con, 'SELECT * FROM T ORDER BY a')
        assert rows == [(1, "x"), (2, "y")]

        row1 = fetch_one(con, 'SELECT b FROM T WHERE a=?', (2,))
        assert row1 == ("y",)
    finally:
        close_connection(con)
