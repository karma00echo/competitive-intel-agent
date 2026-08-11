"""Deterministic presentation models for the local Agent workspace."""

from __future__ import annotations

from collections import Counter
from typing import Any


STATE_LABELS = {
    "INITIALIZING": "初始化",
    "PROFILE_LOOKUP": "查询竞品档案",
    "MODE_SELECTION": "选择运行模式",
    "SOURCE_DISCOVERY": "发现来源",
    "SOURCE_VALIDATION": "验证来源",
    "PAGE_FETCHING": "抓取页面",
    "SNAPSHOT_PERSISTENCE": "保存快照",
    "FACT_EXTRACTION": "提取事实",
    "FACT_PERSISTENCE": "保存事实",
    "HISTORY_LOOKUP": "查找历史基线",
    "FACT_COMPARISON": "比较事实",
    "CHANGE_PERSISTENCE": "保存变化",
    "REPORT_GENERATION": "生成报告",
    "REPORT_PERSISTENCE": "保存报告",
    "RUN_SUMMARY": "汇总结果",
    "COMPLETED": "已完成",
    "COMPLETED_WITH_WARNINGS": "带警告完成",
    "FAILED": "失败",
}

TOOL_LABELS = {
    "get_competitor_profile": "查询竞品档案",
    "discover_competitor_sources": "发现官方来源",
    "refresh_verified_sources": "抓取已验证来源",
    "extract_competitor_facts": "提取结构化事实",
    "get_previous_fact_baseline": "查询历史基线",
    "compare_competitor_facts": "比较历史事实",
    "generate_competitor_report": "生成分析报告",
    "finalize_run_summary": "汇总运行结果",
    "skip_fact_extraction": "跳过事实提取",
}

STATE_PROGRESS = {
    "INITIALIZING": 5,
    "PROFILE_LOOKUP": 10,
    "MODE_SELECTION": 15,
    "SOURCE_DISCOVERY": 25,
    "SOURCE_VALIDATION": 35,
    "PAGE_FETCHING": 45,
    "SNAPSHOT_PERSISTENCE": 55,
    "FACT_EXTRACTION": 65,
    "FACT_PERSISTENCE": 70,
    "HISTORY_LOOKUP": 75,
    "FACT_COMPARISON": 82,
    "CHANGE_PERSISTENCE": 86,
    "REPORT_GENERATION": 90,
    "REPORT_PERSISTENCE": 95,
    "RUN_SUMMARY": 98,
    "COMPLETED": 100,
    "COMPLETED_WITH_WARNINGS": 100,
    "FAILED": 100,
}

TERMINAL_STATES = {"COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"}


def progress_for_events(events: list[dict[str, Any]], current_state: str) -> int:
    """Return a monotonic state-derived percentage without estimating time."""
    values = [
        STATE_PROGRESS.get(str(event.get("stage", "")), 0) for event in events
    ]
    values.append(STATE_PROGRESS.get(current_state, 5))
    return max(values, default=5)


def tool_view(call: dict[str, Any]) -> dict[str, Any]:
    return {
        **call,
        "display_name": TOOL_LABELS.get(call["tool_name"], call["tool_name"]),
        "provider": _tool_provider(call),
    }


def build_message_stream(
    *,
    run: dict[str, Any],
    events: list[dict[str, Any]],
    calls: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    changes: list[dict[str, Any]],
    report: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build chat-like messages solely from persisted, auditable run data."""
    messages: list[dict[str, Any]] = [
        {
            "type": "USER_REQUEST",
            "title": "用户请求",
            "text": f"分析 {run['competitor']}",
        },
        {
            "type": "AGENT_PLAN",
            "title": "受控执行计划",
            "text": (
                "查询竞品档案并判断运行模式；发现或读取已验证来源；"
                "抓取页面；按当前能力提取、比较事实并生成报告。"
            ),
        },
    ]
    if run.get("run_mode"):
        messages.append(
            {
                "type": "MODE_SELECTED",
                "title": "运行模式",
                "text": "首次建档" if run["run_mode"] == "BASELINE" else "变化追踪",
            }
        )
    if sources or _called(calls, "discover_competitor_sources"):
        statuses = Counter(item.get("verification_status") for item in sources)
        messages.append(
            {
                "type": "SOURCE_DISCOVERY_RESULT",
                "title": "来源发现",
                "text": (
                    f"已验证 {statuses['VERIFIED']}，待确认 "
                    f"{statuses['PENDING_CONFIRMATION']}，已拒绝 {statuses['REJECTED']}。"
                ),
                "card": "sources",
            }
        )
    if _called(calls, "refresh_verified_sources"):
        messages.append(
            {
                "type": "FETCH_RESULT",
                "title": "页面抓取",
                "text": (
                    f"成功 {run.get('page_fetch_success_count', 0)}，失败 "
                    f"{run.get('page_fetch_failure_count', 0)}，"
                    f"保存快照 {run.get('snapshot_count', 0)}。"
                ),
                "card": "fetch",
            }
        )
    extraction_status = run.get("fact_extraction_status")
    if extraction_status == "SKIPPED":
        messages.append(
            {
                "type": "WARNING",
                "title": "事实提取已跳过",
                "text": run.get("fact_extraction_reason")
                or "真实事实提取 Provider 尚未接入。",
            }
        )
    elif facts or _called(calls, "extract_competitor_facts"):
        messages.append(
            {
                "type": "FACT_EXTRACTION_RESULT",
                "title": "结构化事实",
                "text": f"本次可展示 {len(facts)} 条有证据事实。",
                "card": "facts",
            }
        )
    if changes or _called(calls, "compare_competitor_facts"):
        counts = Counter(item.get("change_type") for item in changes)
        messages.append(
            {
                "type": "CHANGE_RESULT",
                "title": "事实变化",
                "text": (
                    f"新增 {counts['ADDED']}，修改 {counts['MODIFIED']}，"
                    f"移除 {counts['REMOVED']}，不可比较 {counts['UNCOMPARABLE']}。"
                ),
                "card": "changes",
            }
        )
    if report:
        messages.append(
            {
                "type": "REPORT_RESULT",
                "title": "正式报告",
                "text": report.get("executive_summary") or "报告已生成。",
                "card": "report",
            }
        )
    for warning in run.get("warnings", []):
        messages.append({"type": "WARNING", "title": "运行警告", "text": str(warning)})
    for error in run.get("errors", []):
        messages.append({"type": "ERROR", "title": "运行错误", "text": str(error)})
    final_state = run.get("final_state")
    if final_state in TERMINAL_STATES:
        messages.append(
            {
                "type": "FINAL_SUMMARY",
                "title": STATE_LABELS[final_state],
                "text": _final_text(run),
            }
        )
    return messages


def _called(calls: list[dict[str, Any]], name: str) -> bool:
    return any(call.get("tool_name") == name for call in calls)


def _tool_provider(call: dict[str, Any]) -> str:
    payload = call.get("input")
    if isinstance(payload, dict):
        for key in ("provider", "search_provider", "fact_provider", "agent_provider"):
            if payload.get(key):
                return str(payload[key])
    return "internal"


def _final_text(run: dict[str, Any]) -> str:
    state = run.get("final_state")
    if state == "FAILED":
        return "运行失败；请在执行轨迹中查看已记录错误。"
    if state == "COMPLETED_WITH_WARNINGS":
        return "受控流程已结束，但存在明确限制或待核实事项。"
    return "受控流程已完成，结果和证据已保存。"
