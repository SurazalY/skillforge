"""工具策略、范围授权与精确审批。

范围授权决定可做什么；写入预条件（文件哈希）另见 patch_plan。
Skill / 日志 / 子 Agent 文本不能扩大本模块中的授权。
"""

from __future__ import annotations

from dataclasses import dataclass
import uuid

from .store import canonical_hash
from .task_contract import WRITE_MODE_STRICT_PATCH


EFFECT_READ = "read"
EFFECT_WRITE = "workspace_write"
EFFECT_PROCESS = "process"
EFFECT_DELEGATE = "delegate"
EFFECT_EXTERNAL = "external_side_effect"

# 本轮不自主执行的外部副作用。
EXTERNAL_CAPABILITIES = frozenset({"publish", "push", "message", "network_exfil"})
# 未获准前需另授权的能力。
RESTRICTED_CAPABILITIES = frozenset({"network", "install", "destructive", "publish", "push", "message"})
# 已授权读取含工件回查。网关放行，不改 CompletionGate / TaskPacket 白名单。
AUTHORIZED_ARTIFACT_READ_TOOLS = frozenset({"artifact_read", "artifact_search"})
PUBLISH_MARKERS = ("git push", "npm publish", "twine upload", "gh release")
INSTALL_MARKERS = ("pip install", "npm install", "pip3 install")

DECISION_ALLOW = "allow"
DECISION_DENY = "deny"
DECISION_NEED_TICKET = "need_precise_ticket"
DECISION_ASK = "ask_user"

DENY_READ_ONLY = "read_only"
DENY_SCOPE = "out_of_scope"
DENY_FORBIDDEN = "forbidden"
DENY_CAPABILITY = "capability_not_granted"
DENY_POLICY_NEVER = "approval_never"
DENY_TICKET = "ticket_mismatch"
DENY_UNTRUSTED = "untrusted_source_cannot_grant"


TOOL_EFFECTS = {
    "list_files": EFFECT_READ,
    "read_file": EFFECT_READ,
    "search": EFFECT_READ,
    "artifact_read": EFFECT_READ,
    "artifact_search": EFFECT_READ,
    "log_brief": EFFECT_READ,
    "log_failure_detail": EFFECT_READ,
    "write_file": EFFECT_WRITE,
    "patch_file": EFFECT_WRITE,
    "run_shell": EFFECT_PROCESS,
    "log_run": EFFECT_PROCESS,
    "delegate": EFFECT_DELEGATE,
}


def tool_effect(name):
    return TOOL_EFFECTS.get(str(name), EFFECT_EXTERNAL)


def posix_relpath(path_text):
    text = str(path_text or ".").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    if text in {"", "."}:
        return "."
    return text


def path_in_scope(rel_path, allowed_paths, forbidden):
    rel = posix_relpath(rel_path)
    for item in forbidden:
        item = posix_relpath(item)
        if item in {"", "."}:
            continue
        if rel == item or rel.startswith(item + "/"):
            return False
    if not allowed_paths:
        return False
    for item in allowed_paths:
        item = posix_relpath(item)
        if item in {".", "*"}:
            return True
        if rel == item or rel.startswith(item + "/"):
            return True
    return False


def spec_hash(*, name, args, revision):
    return canonical_hash(
        {
            "name": str(name),
            "args": args or {},
            "revision": int(revision),
        }
    )


@dataclass(frozen=True)
class AuthDecision:
    action: str
    reason: str = ""
    effect: str = ""
    spec_hash: str = ""
    require_ticket: bool = False

    @property
    def allowed(self):
        return self.action == DECISION_ALLOW


def looks_like_publish(command):
    lowered = " ".join(str(command or "").lower().split())
    return any(marker in lowered for marker in PUBLISH_MARKERS)


def looks_like_install_or_network(command):
    lowered = " ".join(str(command or "").lower().split())
    if any(marker in lowered for marker in INSTALL_MARKERS):
        return True
    tokens = lowered.split()
    return "curl" in tokens or "wget" in tokens


def command_matches_verification(command, actions):
    command = " ".join(str(command or "").split())
    if not command or not actions:
        return False
    lowered = command.lower()
    for action in actions:
        prefix = " ".join(str(action).split()).lower()
        if not prefix:
            continue
        if lowered == prefix or lowered.startswith(prefix + " "):
            return True
        tokens = lowered.split()
        prefix_tokens = prefix.split()
        if tokens[: len(prefix_tokens)] == prefix_tokens:
            return True
    return False


class AuthorizationGate:
    """同一策略里的两种依据：任务范围授权 vs 精确票据。"""

    def __init__(self, agent):
        self.agent = agent

    @property
    def contract(self):
        return self.agent.task_contract

    def ignore_untrusted_claims(self, text):
        """Skill/日志/子 Agent 输出不得扩大授权。本方法是显式无操作。"""
        _ = text
        return self.contract

    def decide(self, name, args, *, rel_path=None, ticket=None):
        effect = tool_effect(name)
        contract = self.contract
        args = args or {}
        hashed = spec_hash(name=name, args=args, revision=contract.revision)
        policy = str(self.agent.approval_policy or "ask")

        if name in set(contract.forbidden):
            return AuthDecision(DECISION_DENY, DENY_FORBIDDEN, effect, hashed)

        if effect == EFFECT_READ:
            if rel_path is not None and not path_in_scope(rel_path, contract.allowed_paths, contract.forbidden):
                return AuthDecision(DECISION_DENY, DENY_SCOPE, effect, hashed)
            return AuthDecision(DECISION_ALLOW, "read_in_scope", effect, hashed)

        if effect == EFFECT_DELEGATE:
            # 子 Agent 只读，不能把父级授权扩大。
            return AuthDecision(DECISION_ALLOW, "delegate_read_only", effect, hashed)

        if effect == EFFECT_EXTERNAL or name in EXTERNAL_CAPABILITIES:
            # 本轮无已实现的推送/发布/发消息能力；授权字段也不能把未实现动作放行。
            return AuthDecision(DECISION_DENY, DENY_CAPABILITY, effect, hashed)

        if self.agent.read_only:
            return AuthDecision(DECISION_DENY, DENY_READ_ONLY, effect, hashed)

        if effect == EFFECT_WRITE:
            if rel_path is not None and not path_in_scope(rel_path, contract.allowed_paths, contract.forbidden):
                return AuthDecision(DECISION_DENY, DENY_SCOPE, effect, hashed)
            if "destructive" in contract.forbidden:
                return AuthDecision(DECISION_DENY, DENY_FORBIDDEN, effect, hashed)
            if contract.write_mode == WRITE_MODE_STRICT_PATCH:
                return self._precise_or_deny(ticket, hashed, effect)
            if policy == "never":
                return AuthDecision(DECISION_DENY, DENY_POLICY_NEVER, effect, hashed)
            # scope 默认：任务范围内普通补丁自动执行。
            if policy in {"auto", "ask", "scope"}:
                return AuthDecision(DECISION_ALLOW, "scope_write", effect, hashed)
            return AuthDecision(DECISION_ASK, "ask_write", effect, hashed)

        if effect == EFFECT_PROCESS:
            if policy == "never":
                return AuthDecision(DECISION_DENY, DENY_POLICY_NEVER, effect, hashed)
            command = str(args.get("command") or "")
            if looks_like_publish(command):
                return AuthDecision(DECISION_DENY, DENY_CAPABILITY, effect, hashed)
            cwd_ok = posix_relpath(contract.verification_cwd) in {".", posix_relpath(args.get("cwd") or ".")}
            if command_matches_verification(command, contract.verification_actions) and cwd_ok:
                return AuthDecision(DECISION_ALLOW, "declared_verification", effect, hashed)
            if looks_like_install_or_network(command):
                if "install" not in contract.capabilities and "network" not in contract.capabilities:
                    return AuthDecision(DECISION_DENY, DENY_CAPABILITY, effect, hashed)
            # 会话 auto 是用户显式选择，不等于把范围授权做成永远 auto。
            if policy == "auto":
                return AuthDecision(DECISION_ALLOW, "session_auto_process", effect, hashed)
            if policy in {"ask", "scope"}:
                return AuthDecision(DECISION_ASK, "ask_process", effect, hashed)
            return AuthDecision(DECISION_DENY, DENY_CAPABILITY, effect, hashed)

        return AuthDecision(DECISION_DENY, DENY_CAPABILITY, effect, hashed)

    def _precise_or_deny(self, ticket, hashed, effect):
        if not ticket:
            return AuthDecision(DECISION_NEED_TICKET, "precise_ticket_required", effect, hashed, require_ticket=True)
        if str(ticket.get("spec_hash") or "") != hashed:
            return AuthDecision(DECISION_DENY, DENY_TICKET, effect, hashed, require_ticket=True)
        if str(ticket.get("state") or "") != "approved":
            return AuthDecision(DECISION_DENY, DENY_TICKET, effect, hashed, require_ticket=True)
        if str(ticket.get("policy_revision") or "") != str(self.contract.revision):
            return AuthDecision(DECISION_DENY, DENY_TICKET, effect, hashed, require_ticket=True)
        return AuthDecision(DECISION_ALLOW, "precise_ticket", effect, hashed, require_ticket=True)

    def issue_precise_ticket(self, name, args, *, call_id=None):
        store = self.agent.artifact_store()
        hashed = spec_hash(name=name, args=args or {}, revision=self.contract.revision)
        approval_id = "appr_" + uuid.uuid4().hex[:16]
        record = {
            "approval_id": approval_id,
            "call_id": call_id,
            "spec_hash": hashed,
            "policy_revision": str(self.contract.revision),
            "state": "approved",
        }
        if store is not None and hasattr(store, "remember_approval"):
            saved = store.remember_approval(**record)
            return saved
        self.agent._local_approvals = getattr(self.agent, "_local_approvals", {})
        saved = {
            "id": approval_id,
            "call_id": call_id,
            "spec_hash": hashed,
            "policy_revision": str(self.contract.revision),
            "state": "approved",
        }
        self.agent._local_approvals[approval_id] = saved
        return saved

    def load_ticket(self, approval_id):
        if not approval_id:
            return None
        store = self.agent.artifact_store()
        if store is not None and hasattr(store, "get_approval"):
            found = store.get_approval(approval_id)
            if found is not None:
                return found
        return getattr(self.agent, "_local_approvals", {}).get(approval_id)

    def capability_granted(self, name):
        return name in self.contract.capabilities
