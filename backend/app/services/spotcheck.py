"""点检记录业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.services.rectify import RectifyService
from app.store import store

MODULE = "spotcheck"
REQUIRED_FIELDS = ["点检单号", "关联计划", "点检设备"]
OPTIONAL_FIELDS = ["点检人员", "点检日期", "点检结论", "异常项数"]
STATUS_ORDER = ["待点检", "点检中", "已提交", "已退回"]
ACTION_RULES = {"开始点检": "点检中", "提交结果": "已提交", "退回重检": "已退回"}
ACTION_SOURCES = {
    "开始点检": {"待点检"},
    "提交结果": {"点检中"},
    "退回重检": {"点检中"},
}
VOID_PLAN_STATUS = "已作废"


class SpotcheckService:
    def __init__(self) -> None:
        self.rectify_service = RectifyService()

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
            rows = [row for row in rows if keyword in str(row.get("点检单号", ""))]
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
        for field in OPTIONAL_FIELDS:
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["点检状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"点检记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于点检记录可执行范围"
        if self._plan_is_void(entry):
            return None, "关联点检计划已作废，记录仅允许查看，不能变更状态"
        if action == "提交结果" and entry.get("status") == "已提交":
            return entry, "点检结果已提交，重复提交未重复生成整改事项"
        if entry.get("status") not in ACTION_SOURCES[action]:
            return None, f"当前点检状态为「{entry.get('status')}」，不能执行「{action}」"

        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        generated_count = 0
        if action == "提交结果":
            abnormal_count, message = self._prepare_submission(entry, values)
            if message:
                return None, message
        else:
            abnormal_count = 0

        entry["status"] = target
        entry["点检状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = False

        if action == "提交结果":
            entry["abnormal"] = abnormal_count > 0
            if abnormal_count:
                generated = self.rectify_service.create_from_spotcheck(entry, abnormal_count)
                generated_count = len(generated)

        if action == "提交结果":
            if generated_count:
                return entry, f"点检结果已提交，已生成 {generated_count} 项待整改事项"
            return entry, "点检结果已提交"
        return entry, f"点检记录已{action}"

    def _prepare_submission(
        self,
        entry: dict[str, Any],
        values: dict[str, Any],
    ) -> tuple[int, str]:
        conclusion = str(
            values.get("点检结论")
            if values.get("点检结论") is not None
            else entry.get("点检结论")
            or ""
        ).strip()
        raw_count = (
            values.get("异常项数")
            if values.get("异常项数") is not None
            else entry.get("异常项数")
        )
        entry["点检结论"] = conclusion
        entry["异常项数"] = "" if raw_count is None else str(raw_count).strip()

        if conclusion != "异常":
            entry["异常项数"] = "0"
            return 0, ""
        if not str(raw_count or "").strip():
            return 0, "点检结论为异常，但异常项数为空：结论与异常项数冲突，不能提交"

        try:
            abnormal_count = int(str(raw_count).strip())
        except (TypeError, ValueError):
            return 0, "点检结论为异常时，异常项数必须为正整数"
        if abnormal_count <= 0:
            return 0, "点检结论为异常时，异常项数必须大于 0"
        entry["异常项数"] = str(abnormal_count)
        return abnormal_count, ""

    def _plan_is_void(self, entry: dict[str, Any]) -> bool:
        plan_no = str(entry.get("关联计划") or "").strip()
        if not plan_no:
            return False
        for plan in store.rows("plan"):
            plan_no_match = (
                str(plan.get("计划编号") or "").strip() == plan_no
                or str(plan.get("id") or "").strip() == plan_no
            )
            if plan_no_match:
                return str(plan.get("status") or "").strip() == VOID_PLAN_STATUS
        return False
