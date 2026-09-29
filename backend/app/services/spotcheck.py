"""点检记录业务规则：状态流转、异常上报、整改闭环联动与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "spotcheck"
PLAN_MODULE = "plan"
RECTIFY_MODULE = "rectify"
REQUIRED_FIELDS = ["点检单号", "关联计划", "点检设备"]
STATUS_ORDER = ["待点检", "点检中", "已提交", "已退回"]
ACTION_RULES = {"开始点检": "点检中", "提交结果": "已提交", "退回重检": "已退回"}
NEGATIVE_ACTIONS = []

# 各动作允许的来源状态：越权流转直接拦下。
ACTION_SOURCE_STATUS = {
    "开始点检": {"待点检"},
    "提交结果": {"点检中", "已退回"},
    "退回重检": {"点检中", "已提交"},
}

ABNORMAL_RESULT = "异常"
NORMAL_RESULTS = {"正常", "合格", "无异常"}
PLAN_VOID_STATUS = "已作废"

# 整改闭环台账各状态：只有未闭环的整改事项计入待整改量。
RECTIFY_OPEN_STATUSES = ["待下发", "整改中", "待验收"]


def _parse_abnormal_count(raw: Any) -> int | None:
    """把异常项数解析成非负整数；空值或无法解析时返回 None，交由调用方判定冲突。"""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _next_rectify_code(next_id: int) -> str:
    """按整改台账现有单号顺延生成 RECT-XXXX，保证历史单号不重号。"""
    return f"RECT-{next_id:04d}"


class SpotcheckService:
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
        page_rows = [dict(row) for row in rows[start:start + size]]
        for row in page_rows:
            self._decorate_row(row)
        return page_rows, total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        view = dict(entry)
        self._decorate_row(view)
        return view

    def _decorate_row(self, row: dict[str, Any]) -> None:
        """附带关联计划状态与待整改量，供列表、详情与前端按钮控制使用。"""
        plan = self._find_plan(str(row.get("关联计划") or ""))
        row["关联计划状态"] = plan.get("status") if plan else None
        row["计划已作废"] = bool(plan and plan.get("status") == PLAN_VOID_STATUS)
        row["待整改数"] = self._open_rectify_count(str(row.get("点检单号") or ""))

    def _find_plan(self, plan_ref: str) -> dict[str, Any] | None:
        if not plan_ref:
            return None
        for plan in store.rows(PLAN_MODULE):
            if str(plan.get("计划编号") or "") == plan_ref:
                return plan
        return None

    def _open_rectify_count(self, spot_code: str) -> int:
        return sum(
            1
            for item in store.rows(RECTIFY_MODULE)
            if str(item.get("关联点检单") or "") == spot_code
            and item.get("status") in RECTIFY_OPEN_STATUSES
        )

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["点检状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["点检结论"] = None
        entry["异常项数"] = None
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str, list[dict[str, Any]]]:
        """执行动作，返回（记录, 提示语, 本次新生成的整改事项）。失败时记录为 None。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"点检记录 {entry_id} 不存在或已归档", []
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于点检记录可执行范围", []

        # 关联计划已作废：记录冻结为只读，任何状态变更都不允许。
        plan = self._find_plan(str(entry.get("关联计划") or ""))
        if plan and plan.get("status") == PLAN_VOID_STATUS:
            return None, "关联的点检计划已作废，该点检记录不允许变更状态，只能查看", []

        current = str(entry.get("status") or "")

        # 同一张点检单重复提交只走一次：已提交的记录再次提交直接回显既有结果，
        # 不重复流转、不重复建账（刷新或从详情返回看到的都是同一结果）。
        if action == "提交结果" and current == "已提交":
            return entry, self._already_submitted_message(entry), []

        allowed = ACTION_SOURCE_STATUS.get(action, set())
        if allowed and current not in allowed:
            return None, f"点检记录当前为「{current}」，不允许执行「{action}」", []

        if action == "提交结果":
            return self._submit(entry, values or {})

        target = ACTION_RULES[action]
        entry["status"] = target
        entry["点检状态"] = target
        entry["pending"] = target != "已提交"
        return entry, f"点检记录已{action}", []

    def _already_submitted_message(self, entry: dict[str, Any]) -> str:
        open_count = self._open_rectify_count(str(entry.get("点检单号") or ""))
        message = "该点检单已提交过，无需重复提交"
        if open_count:
            message += f"；台账中仍有 {open_count} 项待整改事项"
        elif entry.get("点检结论") == ABNORMAL_RESULT:
            message += "；关联整改事项已全部闭环"
        return message

    def _submit(
        self,
        entry: dict[str, Any],
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str, list[dict[str, Any]]]:
        # 历史点检单号是上报与建台账的根，不能缺失。
        spot_code = str(entry.get("点检单号") or "").strip()
        if not spot_code:
            return None, "点检单号缺失，无法上报异常并生成整改事项", []

        result = str(values.get("点检结论") or entry.get("点检结论") or "").strip()
        if result not in NORMAL_RESULTS and result != ABNORMAL_RESULT:
            return None, "点检结论需明确为「正常」或「异常」，请补全后再提交", []

        abnormal_count = _parse_abnormal_count(values.get("异常项数", entry.get("异常项数")))
        if result == ABNORMAL_RESULT:
            if abnormal_count is None:
                return (
                    None,
                    "点检结论为异常，但异常项数为空：结论与异常项数冲突，请填写异常项数后再提交",
                    [],
                )
            if abnormal_count <= 0:
                return (
                    None,
                    f"点检结论为异常，但异常项数为 {abnormal_count}：结论与异常项数冲突，异常项数必须大于 0",
                    [],
                )

        existing = [
            item
            for item in store.rows(RECTIFY_MODULE)
            if str(item.get("关联点检单") or "") == spot_code
        ]

        created: list[dict[str, Any]] = []
        if result == ABNORMAL_RESULT:
            entry["异常项数"] = abnormal_count
            if not existing:
                created = self._create_rectify_items(entry, abnormal_count)
            entry["abnormal"] = True
        else:
            entry["异常项数"] = 0
            entry["abnormal"] = False
        entry["点检结论"] = result
        entry["status"] = "已提交"
        entry["点检状态"] = "已提交"
        entry["pending"] = True

        if result == ABNORMAL_RESULT:
            if created:
                message = f"点检结论为异常，已按 {abnormal_count} 个异常项生成 {len(created)} 条待整改事项，记录状态流转为已提交"
            else:
                message = "点检结论为异常；该点检单此前已生成整改事项，本次不重复建账，记录状态为已提交"
        else:
            message = "点检结论为正常，记录状态已流转为已提交，无需整改"
        return entry, message, created

    def _create_rectify_items(
        self,
        entry: dict[str, Any],
        abnormal_count: int,
    ) -> list[dict[str, Any]]:
        """按异常项数逐条落到整改闭环台账，均计入运营概览待整改量。"""
        rows = store.rows(RECTIFY_MODULE)
        created: list[dict[str, Any]] = []
        spot_code = str(entry.get("点检单号") or "")
        equipment = str(entry.get("点检设备") or "")
        next_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        for index in range(1, abnormal_count + 1):
            item_id = next_id
            next_id += 1
            item = {
                "id": item_id,
                "整改单号": _next_rectify_code(item_id),
                "关联隐患": f"点检异常 {spot_code}-{index}",
                "整改措施": f"处理点检单 {spot_code} 第 {index} 项异常",
                "责任单位": "待指派",
                "整改期限": None,
                "完成日期": None,
                "验收人员": None,
                "整改状态": "待下发",
                "关联点检单": spot_code,
                "来源点检设备": equipment,
                "来源异常项": index,
                "status": "待下发",
                "pending": True,
                "abnormal": True,
            }
            rows.append(item)
            created.append(item)
        return created

    def sync_rectify_closed(self, spot_code: str) -> None:
        """整改闭环回收后，同步点检记录的异常项数；全部闭环时记录正式收尾。"""
        entry = next(
            (row for row in store.rows(MODULE) if str(row.get("点检单号") or "") == spot_code),
            None,
        )
        if entry is None:
            return
        open_count = self._open_rectify_count(spot_code)
        entry["异常项数"] = open_count
        if open_count == 0:
            entry["pending"] = False
