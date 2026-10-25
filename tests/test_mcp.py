import asyncio

from mcp import Client

from finapi.mcp_server import mcp

TOOLS = {"get_quotes", "get_price_history", "get_company_profile", "analyze_stock"}


def call(name, args):
    async def run():
        async with Client(mcp) as client:
            return await client.call_tool(name, args)
    return asyncio.run(run())


def _text(result):
    return " ".join(getattr(c, "text", "") for c in result.content)


def test_lists_the_four_tools():
    async def run():
        async with Client(mcp) as client:
            return await client.list_tools()
    tools = asyncio.run(run()).tools
    assert {t.name for t in tools} == TOOLS
    assert all(t.description for t in tools)


def test_analyze_stock_ok(market):
    result = call("analyze_stock", {"symbol": "aapl", "period": "1y"})
    assert not result.is_error, _text(result)
    assert "rsi_14" in result.structured_content


def test_quotes_accepts_list(market):
    result = call("get_quotes", {"symbols": ["AAPL", "MSFT"]})
    assert not result.is_error
    assert [q["symbol"] for q in result.structured_content["quotes"]] == ["AAPL", "MSFT"]


def test_unknown_symbol_is_tool_error_with_message(market):
    result = call("get_company_profile", {"symbol": "NOPE"})
    assert result.is_error and "NOPE" in _text(result)


def test_invalid_input_message_reaches_model(market):
    result = call("get_price_history", {"symbol": "AAPL", "max_points": 1})
    assert result.is_error and "max_points must be between" in _text(result)


def test_provider_failure_is_tool_error(market):
    market.error = ConnectionError("boom")
    result = call("get_price_history", {"symbol": "AAPL"})
    assert result.is_error and "boom" in _text(result)


def test_schema_enums_come_from_core():
    import typing

    from finapi import core, mcp_server
    assert typing.get_args(mcp_server.Period) == tuple(core.PERIODS)
    assert typing.get_args(mcp_server.Interval) == core.INTERVALS


def test_http_transport_port_is_configurable(monkeypatch):
    from finapi import mcp_server
    seen = {}
    monkeypatch.setattr(mcp_server.mcp, "run", lambda **kw: seen.update(kw))
    mcp_server.main(["--transport", "streamable-http", "--port", "9001"])
    assert seen == {"transport": "streamable-http", "host": "127.0.0.1", "port": 9001}
    seen.clear()
    mcp_server.main([])
    assert seen == {"transport": "stdio"}
