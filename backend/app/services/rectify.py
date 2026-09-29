"""整改闭环业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "rectify"
REQUIRED_FIELDS = ["整改单号", "关联隐患", "整改措施"]
OPTIONAL_FIELDS = ["历史点检单号", "责任单位", "整改期限", "完成日期", "验收人员", "整改状态"]
STATUS_ORDER = ["待下发", "整改中", "待验收", "已闭环"]
ACTION_RULES = {"下发整改": "整改中", "提交验收": "待验收", "确认闭环": "已闭环"}
SPOTCHECK_MODULE = "spotcheck"


class RectifyService:
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
            rows = [row for row in rows if keyword in str(row.get("整改单号", ""))]
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
        entry = {"id": self._next_id(rows)}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in OPTIONAL_FIELDS:
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["整改状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def create_from_spotcheck(
        self,
        spotcheck: dict[str, Any],
        abnormal_count: int,
    ) -> list[dict[str, Any]]:
        """按点检异常项数生成整改事项，并保留历史点检单号用于追溯。"""
        rows = store.rows(MODULE)
        source_id = int(spotcheck.get("id", 0))
        source_no = str(spotcheck.get("点检单号") or "").strip()
        existing = [
            row
            for row in rows
            if row.get("source_module") == SPOTCHECK_MODULE
            and int(row.get("source_id", 0)) == source_id
        ]
        if existing:
            return existing

        created: list[dict[str, Any]] = []

        for item_index in range(1, abnormal_count + 1):
            entry = {
                "id": self._next_id(rows),
                "status": "待下发",
                "pending": True,
                "abnormal": True,
                "整改单号": f"RECT-SPOT-{source_id:04d}-{item_index:02d}",
                "关联隐患": f"点检异常 {source_no}（第{item_index}项）",
                "历史点检单号": source_no,
                "整改措施": f"整改点检单 {source_no} 的第 {item_index} 项异常",
                "责任单位": "",
                "整改期限": "",
                "完成日期": "",
                "验收人员": "",
                "整改状态": "待下发",
                "source_module": SPOTCHECK_MODULE,
                "source_id": source_id,
                "source_no": source_no,
                "source_item_index": item_index,
            }
            rows.append(entry)
            created.append(entry)
        return created

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"整改单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于整改闭环可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        should_sync_spotcheck = (
            action == "确认闭环" and entry.get("status") != STATUS_ORDER[-1]
        )
        entry["status"] = target
        entry["整改状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = (
            entry.get("source_module") == SPOTCHECK_MODULE
            and target != STATUS_ORDER[-1]
        )

        message = f"整改单已{action}"
        if should_sync_spotcheck:
            remaining = self._sync_spotcheck_source(entry)
            if remaining is not None:
                message += f"，点检单剩余异常 {remaining} 项"
        return entry, message

    def _next_id(self, rows: list[dict[str, Any]]) -> int:
        return max((int(row.get("id", 0)) for row in rows), default=0) + 1

    def _sync_spotcheck_source(self, rectify: dict[str, Any]) -> int | None:
        if rectify.get("source_module") != SPOTCHECK_MODULE:
            return None

        source_id = int(rectify.get("source_id", 0))
        source = store.find(SPOTCHECK_MODULE, source_id)
        if source is None:
            return None

        linked_rows = [
            row
            for row in store.rows(MODULE)
            if row.get("source_module") == SPOTCHECK_MODULE
            and int(row.get("source_id", 0)) == source_id
        ]
        remaining = sum(1 for row in linked_rows if row.get("status") != STATUS_ORDER[-1])
        source["异常项数"] = str(remaining)
        source["abnormal"] = remaining > 0
        source["status"] = "已提交"
        source["点检状态"] = "已提交"
        source["pending"] = False
        return remaining
