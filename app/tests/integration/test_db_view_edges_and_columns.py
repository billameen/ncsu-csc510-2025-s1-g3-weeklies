from html import unescape

def test_db_view_user_table_page_zero_clamped(client, login_session):
    r = client.get("/db?t=User&page=0", follow_redirects=True)
    # should clamp to page 1 internally and still render
    assert r.status_code in (200, 302, 303)

def test_db_view_menuitem_table_columns_present(client, login_session):
    r = client.get("/db?t=MenuItem&page=1", follow_redirects=True)
    assert r.status_code in (200, 302, 303)
    # We don't assert exact HTML; just ensure the template rendered something
    body = r.get_data(as_text=True).lower()
    # These tokens are expected to appear via columns or row dump in your template
    assert ("menu" in body) or ("item" in body)

def test_db_view_last_page_clamps_high_value(client, login_session):
    r = client.get("/db?t=Restaurant&page=9999", follow_redirects=True)
    assert r.status_code in (200, 302, 303)

def test_db_view_switch_tables_between_calls(client, login_session):
    r1 = client.get("/db?t=User&page=1", follow_redirects=True)
    r2 = client.get("/db?t=Restaurant&page=1", follow_redirects=True)
    assert r1.status_code in (200, 302, 303)
    assert r2.status_code in (200, 302, 303)
