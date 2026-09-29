"""点检计划业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "plan"
REQUIRED_FIELDS = ["计划编号", "点检对象", "点检周期"]
STATUS_ORDER = ["待编制", "待审批", "已批复", "已作废"]
ACTION_RULES = {"提交审批": "待审批", "确认批复": "已批复", "作废计划": "已作废"}
ACTION_SOURCES = {
    "提交审批": {"待编制"},
    "确认批复": {"待审批"},
    "作废计划": {"待编制", "待审批", "已批复"},
}
NEGATIVE_ACTIONS = ["作废计划"]
VOID_PLAN_STATUS = "已作废"


class PlanService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("计划编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"点检计划 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于点检计划可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if entry.get("status") == VOID_PLAN_STATUS:
            return None, "点检计划已作废，只能查看，不能变更状态"
        if entry.get("status") not in ACTION_SOURCES[action]:
            return None, f"当前计划状态为「{entry.get('status')}」，不能执行「{action}」"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"点检计划已{action}"
