def test_security_headers_adds_csp(app_context, flask_app):
    client = flask_app.test_client()
    resp = client.get('/health')
    # Most middleware adds CSP even to health; if not, this will indicate config drift.
    assert resp.status_code in (200, 404)
    assert 'Content-Security-Policy' in resp.headers
