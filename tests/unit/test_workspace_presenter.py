from __future__ import annotations

from competitive_intel.web.workspace import (
    STATE_LABELS,
    TOOL_LABELS,
    build_message_stream,
    progress_for_events,
    tool_view,
)


def _run(**overrides):
    return {
        "competitor": "Notion",
        "run_mode": "BASELINE",
        "final_state": "COMPLETED",
        "current_state": "COMPLETED",
        "warnings": [],
        "errors": [],
        "page_fetch_success_count": 2,
        "page_fetch_failure_count": 0,
        "snapshot_count": 2,
        "fact_extraction_status": "COMPLETED",
        **overrides,
    }


def test_state_and_tool_names_have_readable_chinese_labels() -> None:
    assert STATE_LABELS["SOURCE_DISCOVERY"] == "发现来源"
    assert STATE_LABELS["COMPLETED_WITH_WARNINGS"] == "带警告完成"
    assert TOOL_LABELS["refresh_verified_sources"] == "抓取已验证来源"
    assert TOOL_LABELS["skip_fact_extraction"] == "跳过事实提取"


def test_progress_is_state_derived_and_monotonic_for_event_prefixes() -> None:
    states = [
        "INITIALIZING",
        "PROFILE_LOOKUP",
        "MODE_SELECTION",
        "SOURCE_DISCOVERY",
        "PAGE_FETCHING",
        "FACT_EXTRACTION",
        "REPORT_GENERATION",
        "COMPLETED",
    ]
    values = [
        progress_for_events(
            [{"stage": stage} for stage in states[:index + 1]], states[index]
        )
        for index in range(len(states))
    ]
    assert values == sorted(values)
    assert values[-1] == 100


def test_baseline_message_stream_uses_only_supplied_run_data() -> None:
    messages = build_message_stream(
        run=_run(),
        events=[],
        calls=[
            {"tool_name": "discover_competitor_sources"},
            {"tool_name": "refresh_verified_sources"},
            {"tool_name": "extract_competitor_facts"},
        ],
        sources=[
            {"verification_status": "VERIFIED"},
            {"verification_status": "PENDING_CONFIRMATION"},
        ],
        facts=[{"fact_key": "price.plus"}],
        changes=[],
        report={"executive_summary": "Baseline report"},
    )
    types = [message["type"] for message in messages]
    assert types[:3] == ["USER_REQUEST", "AGENT_PLAN", "MODE_SELECTED"]
    assert "SOURCE_DISCOVERY_RESULT" in types
    assert "FETCH_RESULT" in types
    assert "FACT_EXTRACTION_RESULT" in types
    assert "REPORT_RESULT" in types
    assert types[-1] == "FINAL_SUMMARY"
    assert messages[0]["text"] == "分析 Notion"


def test_refresh_warning_and_failed_messages_are_honest() -> None:
    skipped = build_message_stream(
        run=_run(
            run_mode="REFRESH",
            final_state="COMPLETED_WITH_WARNINGS",
            current_state="COMPLETED_WITH_WARNINGS",
            fact_extraction_status="SKIPPED",
            fact_extraction_reason="Real provider unavailable.",
            warnings=["Fact extraction skipped."],
        ),
        events=[],
        calls=[],
        sources=[],
        facts=[],
        changes=[{"change_type": "MODIFIED"}],
        report=None,
    )
    assert any(
        message["type"] == "WARNING"
        and "Real provider unavailable." in message["text"]
        for message in skipped
    )
    assert skipped[-1]["title"] == "带警告完成"

    failed = build_message_stream(
        run=_run(
            final_state="FAILED",
            current_state="FAILED",
            errors=["Fetch failed."],
        ),
        events=[],
        calls=[],
        sources=[],
        facts=[],
        changes=[],
        report=None,
    )
    assert failed[-1]["title"] == "失败"
    assert "运行失败" in failed[-1]["text"]


def test_tool_view_maps_name_and_provider_without_expanding_payload() -> None:
    result = tool_view(
        {
            "tool_name": "discover_competitor_sources",
            "input": {"search_provider": "fixture"},
            "output": {"count": 4},
        }
    )
    assert result["display_name"] == "发现官方来源"
    assert result["provider"] == "fixture"
