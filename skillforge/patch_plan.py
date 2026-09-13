"""PatchPlan、文件前态哈希与同目录原子替换。

多文件不是原子提交：部分 APPLYING / NEEDS_REVIEW 只要求可定位。
完整崩溃协调属于 C，本模块不假装已恢复。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
import uuid
from pathlib import Path


PLAN_PREPARED = "PREPARED"
PLAN_APPLYING = "APPLYING"
PLAN_APPLIED = "APPLIED"
PLAN_NEEDS_REVIEW = "NEEDS_REVIEW"

HUNK_PENDING = "PENDING"
HUNK_APPLYING = "APPLYING"
HUNK_APPLIED = "APPLIED"
HUNK_STALE = "STALE"
HUNK_FAILED = "FAILED"
HUNK_NEEDS_REVIEW = "NEEDS_REVIEW"

MISSING_HASH = "missing"


class StaleInputError(ValueError):
    """前态哈希变化：旧补丁失效，不撤销任务范围授权。"""


class MatchCountError(ValueError):
    """old_text 不是恰好一次。"""


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def file_content_hash(path):
    path = Path(path)
    if not path.is_file():
        return MISSING_HASH
    return sha256_bytes(path.read_bytes())


def atomic_replace_text(path, content, encoding="utf-8"):
    """同目录临时文件 + fsync + os.replace。不跨越卷。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.sf-{uuid.uuid4().hex}.tmp"
    try:
        with open(tmp, "w", encoding=encoding) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


@dataclass
class PatchHunk:
    path: str
    expected_content_hash: str
    old_text: str = ""
    new_text: str = ""
    content: str | None = None
    after_content_hash: str = ""
    status: str = HUNK_PENDING
    error: str = ""
    op: str = "patch"

    def to_dict(self):
        return {
            "path": self.path,
            "expected_content_hash": self.expected_content_hash,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "content": self.content,
            "after_content_hash": self.after_content_hash,
            "status": self.status,
            "error": self.error,
            "op": self.op,
        }

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        return cls(
            path=str(data.get("path") or ""),
            expected_content_hash=str(data.get("expected_content_hash") or ""),
            old_text=str(data.get("old_text") or ""),
            new_text=str(data.get("new_text") or ""),
            content=data.get("content"),
            after_content_hash=str(data.get("after_content_hash") or ""),
            status=str(data.get("status") or HUNK_PENDING),
            error=str(data.get("error") or ""),
            op=str(data.get("op") or "patch"),
        )


@dataclass
class PatchPlan:
    plan_id: str = field(default_factory=lambda: "plan_" + uuid.uuid4().hex[:12])
    contract_revision: int = 1
    hunks: list = field(default_factory=list)
    status: str = PLAN_PREPARED
    spec_hash: str = ""

    def to_dict(self):
        return {
            "plan_id": self.plan_id,
            "contract_revision": self.contract_revision,
            "hunks": [hunk.to_dict() for hunk in self.hunks],
            "status": self.status,
            "spec_hash": self.spec_hash,
        }

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        return cls(
            plan_id=str(data.get("plan_id") or "plan_" + uuid.uuid4().hex[:12]),
            contract_revision=int(data.get("contract_revision") or 1),
            hunks=[PatchHunk.from_dict(item) for item in (data.get("hunks") or [])],
            status=str(data.get("status") or PLAN_PREPARED),
            spec_hash=str(data.get("spec_hash") or ""),
        )

    def locatable_status(self):
        """部分应用时每个 hunk 可定位；不声称多文件原子提交。"""
        return {
            "plan_id": self.plan_id,
            "status": self.status,
            "atomic_multi_file": False,
            "hunks": [
                {
                    "path": hunk.path,
                    "status": hunk.status,
                    "expected_content_hash": hunk.expected_content_hash,
                    "after_content_hash": hunk.after_content_hash,
                    "error": hunk.error,
                }
                for hunk in self.hunks
            ],
        }


def prepare_plan(hunks, *, contract_revision=1, spec_hash=""):
    plan = PatchPlan(
        contract_revision=int(contract_revision),
        hunks=list(hunks),
        status=PLAN_PREPARED,
        spec_hash=spec_hash,
    )
    for hunk in plan.hunks:
        hunk.status = HUNK_PENDING
    return plan


def apply_hunk_on_disk(agent, hunk):
    """执行前再读文件核哈希；0/2 次匹配失败。不持有 DB 事务。"""
    path = agent.path(hunk.path)
    actual = file_content_hash(path)
    expected = str(hunk.expected_content_hash or "").strip()
    if expected and actual != expected:
        hunk.status = HUNK_STALE
        hunk.error = f"STALE_INPUT: expected {expected}, found {actual}"
        raise StaleInputError(hunk.error)
    if hunk.op == "write" or hunk.content is not None:
        content = str(hunk.content)
        atomic_replace_text(path, content)
        hunk.after_content_hash = file_content_hash(path)
        hunk.status = HUNK_APPLIED
        return f"wrote {path.relative_to(agent.root).as_posix()} ({len(content)} chars)"
    if not path.is_file():
        hunk.status = HUNK_FAILED
        hunk.error = "path is not a file"
        raise ValueError(hunk.error)
    old_text = str(hunk.old_text or "")
    if not old_text:
        hunk.status = HUNK_FAILED
        hunk.error = "old_text must not be empty"
        raise ValueError(hunk.error)
    text = path.read_text(encoding="utf-8")
    count = text.count(old_text)
    if count != 1:
        hunk.status = HUNK_FAILED
        hunk.error = f"old_text must occur exactly once, found {count}"
        raise MatchCountError(hunk.error)
    new_content = text.replace(old_text, str(hunk.new_text), 1)
    atomic_replace_text(path, new_content)
    hunk.after_content_hash = file_content_hash(path)
    hunk.status = HUNK_APPLIED
    return f"patched {path.relative_to(agent.root).as_posix()}"


def apply_plan(agent, plan):
    """逐 hunk 应用。中途失败标 NEEDS_REVIEW，已落地 hunk 保持 APPLIED。"""
    if plan.status not in {PLAN_PREPARED, PLAN_NEEDS_REVIEW, PLAN_APPLYING}:
        return plan
    plan.status = PLAN_APPLYING
    for hunk in plan.hunks:
        if hunk.status == HUNK_APPLIED:
            continue
        hunk.status = HUNK_APPLYING
        try:
            apply_hunk_on_disk(agent, hunk)
        except StaleInputError:
            hunk.status = HUNK_STALE
            plan.status = PLAN_NEEDS_REVIEW
            return plan
        except Exception as exc:
            hunk.status = HUNK_FAILED if hunk.status != HUNK_STALE else hunk.status
            hunk.error = hunk.error or str(exc)
            plan.status = PLAN_NEEDS_REVIEW
            return plan
    if all(hunk.status == HUNK_APPLIED for hunk in plan.hunks):
        plan.status = PLAN_APPLIED
    else:
        plan.status = PLAN_NEEDS_REVIEW
    return plan
