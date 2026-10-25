import pytest
from fastapi.testclient import TestClient

from finapi.rest import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("url, key", [
    ("/v1/quotes?symbols=AAPL,MSFT", "quotes"),
    ("/v1/history/AAPL?period=3mo&max_points=20", "bars"),
    ("/v1/company/AAPL", "sector"),
    ("/v1/analysis/AAPL?period=1y", "rsi_14"),
])
def test_routes_ok(market, url, key):
    res = client.get(url)
    assert res.status_code == 200, res.text
    assert key in res.json()


def _error(res, status, type_):
    assert res.status_code == status, res.text
    body = res.json()["error"]
    assert body["type"] == type_ and body["message"]
    return body["message"]


def test_bad_symbol_400(market):
    _error(client.get("/v1/company/A;B"), 400, "invalid_input")


def test_end_before_start_is_400_not_500(market):
    msg = _error(client.get("/v1/analysis/AAPL?start_date=2024-03-01&end_date=2024-01-01"),
                 400, "invalid_input")
    assert "before" in msg


def test_unknown_symbol_404(market):
    _error(client.get("/v1/company/NOPE"), 404, "not_found")


def test_provider_failure_502(market):
    market.error = ConnectionError("boom")
    _error(client.get("/v1/history/AAPL"), 502, "upstream_error")


def test_request_validation_uses_error_shape(market):
    _error(client.get("/v1/history/AAPL?max_points=abc"), 400, "invalid_input")
    _error(client.get("/v1/history/AAPL?max_points=1"), 400, "invalid_input")


def test_operation_ids_match_tool_names():
    ops = {op["operationId"] for path in app.openapi()["paths"].values() for op in path.values()}
    assert {"get_quotes", "get_price_history", "get_company_profile", "analyze_stock"} <= ops
