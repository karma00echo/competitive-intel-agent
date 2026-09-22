import pytest

from competitive_intel.web.intelligence import (
    CommandCenterPresenter, SignalPresenter, parse_analyst_command, public_url,
)


@pytest.mark.parametrize("kind", ["ADDED", "MODIFIED", "REMOVED", "UNKNOWN"])
def test_signal_projection(kind):
    row = dict(id=1, competitor_id=2, name="Acme", run_id=3,
        fact_key="price.plus", old_value={"amount":10,"currency":"USD"},
        new_value={"amount":12,"currency":"USD"}, change_type=kind,
        evidence_text="x"*900, created_at="2026-01-01", verification_status="CONFIRMED",
        source_url="https://user:password@example.com/pricing?api_key=secret#private",
        raw_html="PRIVATE HTML", password="PRIVATE PASSWORD")
    item = SignalPresenter.present(row)
    assert item["category"] == "Pricing"
    assert item["change_type"] == ("UNCOMPARABLE" if kind == "UNKNOWN" else kind)
    assert len(item["evidence_excerpt"]) == 500
    assert item["source_url"] == "https://example.com/pricing"
    assert "PRIVATE" not in str(item) and "secret" not in str(item)


@pytest.mark.parametrize("text,action", [
    ("分析 Notion","analyze"), ("重新分析 飞书","analyze"),
    ("查看 Notion 最新报告","report"), ("查看 Notion 最近变化","signals"),
    ("打开运行 12","run"), ("为什么本次没有提取事实","capability"),
    ("最近有哪些变化","signals"), ("查看最近 signals","signals"),
    ("查看 Notion 来源","sources"), ("查看 Notion 当前价格","pricing"),
    ("预测三年后市场格局","unsupported"),
    ("帮我分析 Notion 这个产品。", "analyze"),
    ("Notion", "analyze"), ("飞书", "analyze"),
    ("查看 Linear 最近发生了哪些变化。", "signals"),
    ("比较 Notion 和 Asana 的定价及功能。", "unsupported"),
    ("随便聊聊", "unsupported"),
])
def test_analyst_grammar(text, action):
    assert parse_analyst_command(text)["action"] == action


def test_untrusted_urls_are_not_navigable():
    for url in ["javascript:alert(1)", "//example.com", "https://[", "data:text/html,x"]:
        assert public_url(url) is None


def test_attention_is_deterministic_not_a_model_opinion():
    row = dict(competitor_id=1,name="Acme",official_domain=None,last_checked=None,
        started_at=None,run_id=2,run_status="COMPLETED",has_warnings=True,
        verified_source_count=0,pending_source_count=1,unknown_count=1,
        missing_report=True,signal_count=3,report_id=None)
    result = CommandCenterPresenter.card(row)
    assert len(result["warnings"]) == 5
    assert result["status"] == "Needs attention"
