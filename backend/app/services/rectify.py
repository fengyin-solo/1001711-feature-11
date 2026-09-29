"""整改闭环业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "rectify"
REQUIRED_FIELDS = ["整改单号", "关联隐患", "整改措施"]
STATUS_ORDER = ["待下发", "整改中", "待验收", "已闭环"]
ACTION_RULES = {"下发整改": "整改中", "提交验收": "待验收", "确认闭环": "已闭环"}
NEGATIVE_ACTIONS = []


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
            return None, f"整改单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于整改闭环可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["整改状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if action == "确认闭环":
            entry["abnormal"] = False
            # 点检异常来源的整改事项闭环后，台账与运营概览同步回收，
            # 并回写点检记录的异常项数；全部闭环时点检记录同步收尾。
            spot_code = str(entry.get("关联点检单") or "").strip()
            if spot_code:
                from app.services.spotcheck import SpotcheckService

                SpotcheckService().sync_rectify_closed(spot_code)
                return entry, f"整改单已{action}，点检单 {spot_code} 的待整改量已回收"
        return entry, f"整改单已{action}"
