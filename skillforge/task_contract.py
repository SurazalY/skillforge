"""TaskContract：用户目标与授权边界，不能被摘要改写。

B-05 会消费本对象的 revision 与验收种类；本模块不实现 CompletionGate。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import uuid


WRITE_MODE_SCOPE = "scope"
WRITE_MODE_STRICT_PATCH = "strict_patch"
VALID_WRITE_MODES = frozenset({WRITE_MODE_SCOPE, WRITE_MODE_STRICT_PATCH})

# 验收种类给 B-05 的 CompletionGate 使用；B-04 只记录，不改完成门。
VALID_ACCEPTANCE_KINDS = frozenset({"tests", "docs", "build", "config", "manual", "unspecified"})


def _normalize_tuple(values, *, field_name, allow_empty=True):
    if values is None:
        return ()
    if isinstance(values, str):
        values = (values,)
    if not isinstance(values, (list, tuple)):
        raise TypeError(f"{field_name} must be a list or tuple of strings")
    out = []
    for item in values:
        text = str(item).strip().replace("\\", "/")
        if not text:
            raise ValueError(f"{field_name} must not contain empty entries")
        out.append(text)
    if not out and not allow_empty:
        raise ValueError(f"{field_name} must not be empty")
    return tuple(out)


@dataclass(frozen=True)
class TaskContract:
    """一次 Run 的任务合同。

    字段：
    - goal: 用户目标（描述性，不单独构成授权）
    - allowed_paths: 相对工作区的可改范围；"." 表示仓库内
    - forbidden: 明确禁止路径或能力名
    - acceptance_kinds: 验收种类（tests/docs/build/...）
    - revision: 合同版本；用户追加约束时递增，摘要不能改它
    - write_mode: scope（默认范围授权）或 strict_patch（精确逐补丁）
    - verification_cwd / verification_actions: 已获准验证的工作目录与动作前缀
    - capabilities: 额外能力（network/install/publish/...）；默认空
    """

    goal: str
    allowed_paths: tuple[str, ...] = (".",)
    forbidden: tuple[str, ...] = ()
    acceptance_kinds: tuple[str, ...] = ("unspecified",)
    revision: int = 1
    contract_id: str = field(default_factory=lambda: "tc_" + uuid.uuid4().hex[:12])
    write_mode: str = WRITE_MODE_SCOPE
    verification_cwd: str = "."
    verification_actions: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    source: str = "user"

    def __post_init__(self):
        object.__setattr__(self, "goal", str(self.goal or ""))
        object.__setattr__(self, "allowed_paths", _normalize_tuple(self.allowed_paths, field_name="allowed_paths", allow_empty=False))
        object.__setattr__(self, "forbidden", _normalize_tuple(self.forbidden, field_name="forbidden"))
        kinds = _normalize_tuple(self.acceptance_kinds, field_name="acceptance_kinds", allow_empty=False)
        for kind in kinds:
            if kind not in VALID_ACCEPTANCE_KINDS:
                raise ValueError(f"unknown acceptance kind: {kind}")
        object.__setattr__(self, "acceptance_kinds", kinds)
        object.__setattr__(self, "revision", int(self.revision))
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        mode = str(self.write_mode or WRITE_MODE_SCOPE)
        if mode not in VALID_WRITE_MODES:
            raise ValueError(f"unknown write_mode: {mode}")
        object.__setattr__(self, "write_mode", mode)
        object.__setattr__(self, "verification_cwd", str(self.verification_cwd or ".").replace("\\", "/"))
        object.__setattr__(self, "verification_actions", _normalize_tuple(self.verification_actions, field_name="verification_actions"))
        object.__setattr__(self, "capabilities", _normalize_tuple(self.capabilities, field_name="capabilities"))
        src = str(self.source or "user")
        if src not in {"user", "default"}:
            # Skill / 日志 / 子 Agent 不能成为合同来源。
            raise ValueError("TaskContract source must be user or default")
        object.__setattr__(self, "source", src)

    @classmethod
    def default_workspace(cls, goal="", **kwargs):
        """默认范围：仓库内读取 + 普通写入（scope）。不含 process/publish。"""
        kwargs.setdefault("source", "default")
        return cls(goal=goal, **kwargs)

    @classmethod
    def from_user_request(cls, goal, **kwargs):
        kwargs.setdefault("source", "user")
        kwargs.setdefault("write_mode", WRITE_MODE_SCOPE)
        return cls(goal=goal, **kwargs)

    def summary(self):
        """给人看的摘要。调用方不得用返回值改授权。"""
        return (
            f"contract_id={self.contract_id} revision={self.revision} "
            f"write_mode={self.write_mode} goal={self.goal!r}"
        )

    @property
    def objective(self):
        """B-05 名称：用户目标。与 goal 同一字段，摘要不能改授权。"""
        return self.goal

    @property
    def authorized_scope(self):
        """B-05 名称：可改/可读范围。"""
        return self.allowed_paths

    @property
    def acceptance_requirements(self):
        """B-05 名称：验收种类。不要另造第二套种类。"""
        return self.acceptance_kinds

    @property
    def task_revision(self):
        """B-05 名称：合同版本。"""
        return self.revision

    def b05_view(self):
        """B-05 CompletionGate 应消费的稳定视图。不含授权扩张通道。"""
        return {
            "objective": self.goal,
            "authorized_scope": list(self.allowed_paths),
            "forbidden": list(self.forbidden),
            "acceptance_requirements": list(self.acceptance_kinds),
            "task_revision": self.revision,
            "contract_id": self.contract_id,
            "write_mode": self.write_mode,
            "verification_cwd": self.verification_cwd,
            "verification_actions": list(self.verification_actions),
            "capabilities": list(self.capabilities),
            "source": self.source,
        }

    def with_goal(self, goal):
        """只更新目标文本，不升 revision、不改范围。"""
        return replace(self, goal=str(goal or ""))

    def revise(self, **changes):
        """用户追加约束：新对象、revision+1。禁止从摘要偷偷改。"""
        if "revision" in changes:
            raise ValueError("revision is assigned by revise(); do not set it directly")
        if "source" in changes and changes["source"] not in {"user", "default"}:
            raise ValueError("revise() cannot adopt an untrusted source")
        changes = dict(changes)
        changes["revision"] = self.revision + 1
        changes.setdefault("source", "user")
        return replace(self, **changes)

    def to_dict(self):
        payload = {
            "contract_id": self.contract_id,
            "goal": self.goal,
            "allowed_paths": list(self.allowed_paths),
            "forbidden": list(self.forbidden),
            "acceptance_kinds": list(self.acceptance_kinds),
            "revision": self.revision,
            "write_mode": self.write_mode,
            "verification_cwd": self.verification_cwd,
            "verification_actions": list(self.verification_actions),
            "capabilities": list(self.capabilities),
            "source": self.source,
        }
        payload.update(self.b05_view())
        return payload

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        return cls(
            goal=data.get("goal") or data.get("objective") or "",
            allowed_paths=tuple(data.get("allowed_paths") or data.get("authorized_scope") or (".",)),
            forbidden=tuple(data.get("forbidden") or ()),
            acceptance_kinds=tuple(data.get("acceptance_kinds") or data.get("acceptance_requirements") or ("unspecified",)),
            revision=int(data.get("revision") or data.get("task_revision") or 1),
            contract_id=str(data.get("contract_id") or "tc_" + uuid.uuid4().hex[:12]),
            write_mode=str(data.get("write_mode") or WRITE_MODE_SCOPE),
            verification_cwd=str(data.get("verification_cwd") or "."),
            verification_actions=tuple(data.get("verification_actions") or ()),
            capabilities=tuple(data.get("capabilities") or ()),
            source=str(data.get("source") or "user"),
        )
