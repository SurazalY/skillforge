"""Agent 运行时核心逻辑。

SkillForge 就是包在模型外面的控制循环：负责组 prompt、解析模型输出、
校验并执行工具、写 trace、更新工作记忆，以及在合适的时候停下来。
"""

import json
import os
import re
import textwrap
import uuid
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import memory as memorylib
from .audit import audit_code_change
from .context_manager import ContextManager
from .evidence import EvidenceStore
from .run_store import RunStore
from .skills import SkillDistiller, SkillStore
from .task_state import STOP_REASON_AUDIT_FAILED, STOP_REASON_COMPLETION_GATE_BLOCKED, STOP_REASON_SKILL_DISTILL_FAILED, TaskState
from . import tools as toolkit
from .workflow import (
    CompletionGate,
    HandoffArtifact,
    TaskPacket,
    TaskPacketCompiler,
    WorkflowKernel,
    _phase_allowed_tools,
    _render_task_packet_prompt_context,
    workflow_template,
)
from .workspace import IGNORED_PATH_NAMES, MAX_HISTORY, WorkspaceContext, clip, now

SENSITIVE_ENV_NAME_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD")
REDACTED_VALUE = "<redacted>"
DEFAULT_SHELL_ENV_ALLOWLIST = ("HOME", "LANG", "LC_ALL", "LC_CTYPE", "LOGNAME", "PATH", "PWD", "SHELL", "TERM", "TMPDIR", "TMP", "TEMP", "USER")
DEFAULT_FEATURE_FLAGS = {
    "memory": True,
    "relevant_memory": True,
    "context_reduction": True,
    "prompt_cache": True,
}
CHECKPOINT_SCHEMA_VERSION = "phase1-v1"
CHECKPOINT_NONE_STATUS = "no-checkpoint"
CHECKPOINT_FULL_VALID_STATUS = "full-valid"
CHECKPOINT_PARTIAL_STALE_STATUS = "partial-stale"
CHECKPOINT_WORKSPACE_MISMATCH_STATUS = "workspace-mismatch"
CHECKPOINT_SCHEMA_MISMATCH_STATUS = "schema-mismatch"
DURABLE_MEMORY_INTENT_PATTERN = re.compile(r"(?i)\b(capture|remember|save|store|persist|note)\b")
DURABLE_MEMORY_INTENT_ZH_PATTERN = re.compile(r"(记住|保存|记录|沉淀|长期记忆|持久记忆)")
DURABLE_MEMORY_LINE_PATTERNS = (
    ("project-conventions", re.compile(r"(?i)^Project convention:\s*(.+)$")),
    ("key-decisions", re.compile(r"(?i)^Decision:\s*(.+)$")),
    ("dependency-facts", re.compile(r"(?i)^Dependency:\s*(.+)$")),
    ("user-preferences", re.compile(r"(?i)^Preference:\s*(.+)$")),
    ("project-conventions", re.compile(r"^项目约定：\s*(.+)$")),
    ("key-decisions", re.compile(r"^决策：\s*(.+)$")),
    ("dependency-facts", re.compile(r"^依赖：\s*(.+)$")),
    ("user-preferences", re.compile(r"^偏好：\s*(.+)$")),
)
SECRET_SHAPED_TEXT_PATTERN = re.compile(r"(?i)(\b(api[_ -]?key|token|secret|password)\b|sk-[A-Za-z0-9_-]{6,})")
EVIDENCE_ID_PATTERN = re.compile(r"^evidence_id:\s*(\S+)\s*$", re.MULTILINE)


@dataclass
class PromptPrefix:
    # prefix 除了文本本身，还带一小份元数据，
    # 这样 runtime 才能明确判断 prefix 是否可以复用。
    text: str
    hash: str
    workspace_fingerprint: str
    tool_signature: str
    built_at: str


class SessionStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, session_id):
        return self.root / f"{session_id}.json"

    def save(self, session):
        path = self.path(session["id"])
        path.write_text(json.dumps(session, indent=2), encoding="utf-8")
        return path

    def load(self, session_id):
        return json.loads(self.path(session_id).read_text(encoding="utf-8"))

    def latest(self):
        files = sorted(self.root.glob("*.json"), key=lambda path: path.stat().st_mtime)
        return files[-1].stem if files else None


class SkillForge:
    def __init__(
        self,
        model_client,
        workspace,
        session_store,
        session=None,
        run_store=None,
        approval_policy="ask",
        max_steps=6,
        max_new_tokens=512,
        depth=0,
        max_depth=1,
        read_only=False,
        shell_env_allowlist=None,
        secret_env_names=None,
        feature_flags=None,
        workflow=None,
        workflow_state=None,
        delegated_task_packet=None,
        workflow_phase_locked=False,
        delegated_tool_whitelist=None,
    ):
        self.model_client = model_client
        self.workspace = workspace
        self.root = Path(workspace.repo_root)
        self.session_store = session_store
        self.approval_policy = approval_policy
        self.max_steps = max_steps
        self.max_new_tokens = max_new_tokens
        self.depth = depth
        self.max_depth = max_depth
        self.read_only = read_only
        self.shell_env_allowlist = tuple(shell_env_allowlist or DEFAULT_SHELL_ENV_ALLOWLIST)
        self.secret_env_names = {str(name).upper() for name in (secret_env_names or ())}
        self.feature_flags = dict(DEFAULT_FEATURE_FLAGS)
        if feature_flags:
            self.feature_flags.update({str(key): bool(value) for key, value in feature_flags.items()})
        self.run_store = run_store or RunStore(Path(workspace.repo_root) / ".skillforge" / "runs")
        self.session = session or {
            "id": datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6],
            "created_at": now(),
            "workspace_root": workspace.repo_root,
            "history": [],
            "memory": memorylib.default_memory_state(),
        }
        self._ensure_session_shape()
        self.workflow = None
        self.workflow_kernel = None
        self.task_packet_compiler = None
        self.active_task_packet = None
        self.inherited_task_packet = None
        self.workflow_phase_locked = bool(workflow_phase_locked)
        self.delegated_tool_whitelist = tuple(str(name) for name in (delegated_tool_whitelist or ()) if str(name).strip())
        self.skill_store = None
        self.evidence_store = None
        self._configure_workflow(
            workflow or self.session.get("workflow"),
            workflow_state=workflow_state,
            delegated_task_packet=delegated_task_packet,
        )
        self.memory = memorylib.LayeredMemory(
            self.session.setdefault("memory", memorylib.default_memory_state()),
            workspace_root=self.root,
        )
        self.session["memory"] = self.memory.to_dict()
        self.tools = self.build_tools()
        self.prefix_state = self.build_prefix()
        self.prefix = self.prefix_state.text
        self.context_manager = ContextManager(self)
        self.resume_state = self.evaluate_resume_state()
        self.session_path = self.session_store.save(self.session)
        self.current_task_state = None
        self.current_run_dir = None
        self.last_prompt_metadata = {}
        self.last_completion_metadata = {}
        self.last_durable_promotions = []
        self.last_durable_rejections = []
        self.last_durable_superseded = []
        self._last_tool_result_metadata = {}
        self._last_prefix_refresh = {
            "workspace_changed": False,
            "prefix_changed": False,
        }
        self._used_active_skill_ids = set()

    @classmethod
    def from_session(cls, model_client, workspace, session_store, session_id, **kwargs):
        return cls(
            model_client=model_client,
            workspace=workspace,
            session_store=session_store,
            session=session_store.load(session_id),
            **kwargs,
        )

    def _ensure_session_shape(self):
        self.session.setdefault("history", [])
        self.session.setdefault("memory", memorylib.default_memory_state())
        checkpoints = self.session.setdefault("checkpoints", {})
        if not isinstance(checkpoints, dict):
            checkpoints = {}
            self.session["checkpoints"] = checkpoints
        checkpoints.setdefault("current_id", "")
        checkpoints.setdefault("items", {})
        runtime_identity = self.session.setdefault("runtime_identity", {})
        if not isinstance(runtime_identity, dict):
            self.session["runtime_identity"] = {}
        resume_state = self.session.setdefault("resume_state", {})
        if not isinstance(resume_state, dict):
            self.session["resume_state"] = {}

    def current_runtime_identity(self):
        return {
            "session_id": self.session.get("id", ""),
            "cwd": str(self.root),
            "model": str(getattr(self.model_client, "model", "")),
            "model_client": self.model_client.__class__.__name__,
            "approval_policy": self.approval_policy,
            "read_only": bool(self.read_only),
            "max_steps": int(self.max_steps),
            "max_new_tokens": int(self.max_new_tokens),
            "feature_flags": dict(self.feature_flags),
            "shell_env_allowlist": list(self.shell_env_allowlist),
            "workspace_fingerprint": getattr(getattr(self, "prefix_state", None), "workspace_fingerprint", self.workspace.fingerprint()),
            "tool_signature": self.tool_signature(),
        }

    def checkpoint_state(self):
        self._ensure_session_shape()
        return self.session["checkpoints"]

    def current_checkpoint(self):
        state = self.checkpoint_state()
        checkpoint_id = str(state.get("current_id", "")).strip()
        if not checkpoint_id:
            return None
        return state.get("items", {}).get(checkpoint_id)

    def invalidate_stale_memory(self):
        invalidated = self.memory.invalidate_stale_file_summaries()
        self.session["memory"] = self.memory.to_dict()
        return invalidated

    def evaluate_resume_state(self):
        previous_resume_state = dict(self.session.get("resume_state", {}) or {})
        invalidated = self.invalidate_stale_memory()
        checkpoint = self.current_checkpoint()
        status = CHECKPOINT_NONE_STATUS
        stale_paths = list(invalidated)
        mismatch_fields = []
        if checkpoint:
            if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
                status = CHECKPOINT_SCHEMA_MISMATCH_STATUS
            else:
                for item in checkpoint.get("key_files", []):
                    path = str(item.get("path", "")).strip()
                    if not path:
                        continue
                    expected = item.get("freshness")
                    current = memorylib.file_freshness(path, self.root)
                    if expected != current and path not in stale_paths:
                        stale_paths.append(path)
                saved_identity = dict(checkpoint.get("runtime_identity", {}) or self.session.get("runtime_identity", {}) or {})
                current_identity = self.current_runtime_identity()
                identity_keys = (
                    "cwd",
                    "model",
                    "model_client",
                    "approval_policy",
                    "read_only",
                    "max_steps",
                    "max_new_tokens",
                    "feature_flags",
                    "shell_env_allowlist",
                    "workspace_fingerprint",
                    "tool_signature",
                )
                for key in identity_keys:
                    if key not in saved_identity:
                        continue
                    if saved_identity.get(key) != current_identity.get(key):
                        mismatch_fields.append(key)
                mismatch_fields.sort()
                if stale_paths:
                    status = CHECKPOINT_PARTIAL_STALE_STATUS
                elif mismatch_fields:
                    status = CHECKPOINT_WORKSPACE_MISMATCH_STATUS
                else:
                    status = CHECKPOINT_FULL_VALID_STATUS

        resume_state = {
            "status": status,
            "stale_paths": stale_paths,
            "runtime_identity_mismatch_fields": mismatch_fields,
            "stale_summary_invalidations": max(
                len(invalidated),
                int(previous_resume_state.get("stale_summary_invalidations", 0))
                if status == CHECKPOINT_PARTIAL_STALE_STATUS
                else 0,
            ),
        }
        self.session["resume_state"] = resume_state
        self.session["runtime_identity"] = self.current_runtime_identity()
        return resume_state

    def render_checkpoint_text(self):
        checkpoint = self.current_checkpoint()
        if not checkpoint:
            return ""
        lines = [
            "Task checkpoint:",
            f"- Resume status: {self.resume_state.get('status', CHECKPOINT_NONE_STATUS)}",
            f"- Current goal: {checkpoint.get('current_goal', '-') or '-'}",
            f"- Current blocker: {checkpoint.get('current_blocker', '-') or '-'}",
            f"- Next step: {checkpoint.get('next_step', '-') or '-'}",
        ]
        key_files = [str(item.get("path", "")).strip() for item in checkpoint.get("key_files", []) if str(item.get("path", "")).strip()]
        lines.append(f"- Key files: {', '.join(key_files) or '-'}")
        if checkpoint.get("completed"):
            lines.append("- Completed: " + " | ".join(str(item) for item in checkpoint.get("completed", [])))
        if checkpoint.get("excluded"):
            lines.append("- Excluded: " + " | ".join(str(item) for item in checkpoint.get("excluded", [])))
        if self.resume_state.get("stale_paths"):
            lines.append("- Stale paths: " + ", ".join(self.resume_state["stale_paths"]))
        summary = str(checkpoint.get("summary", "")).strip()
        if summary:
            lines.append(f"- Summary: {summary}")
        return "\n".join(lines)

    @staticmethod
    def remember(bucket, item, limit):
        if not item:
            return
        if item in bucket:
            bucket.remove(item)
        bucket.append(item)
        del bucket[:-limit]

    def build_tools(self):
        return toolkit.build_tool_registry(self)

    def tool_signature(self):
        return self._tool_signature_for_names(tuple(self.tools))

    def prompt_tool_signature(self):
        return self._tool_signature_for_names(self.prompt_tool_names())

    def _tool_signature_for_names(self, names):
        payload = []
        for name in sorted(names):
            tool = self.tools[name]
            payload.append(
                {
                    "name": name,
                    "schema": tool["schema"],
                    "risky": tool["risky"],
                    "description": tool["description"],
                }
            )
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def prompt_tool_names(self):
        if not self.workflow or not self.workflow_kernel:
            return tuple(self.tools)
        allowed = set(self.current_allowed_tool_names())
        return tuple(name for name in self.tools if name in allowed)

    def current_allowed_tool_names(self):
        if self.active_task_packet is not None:
            allowed_tools = self.active_task_packet.allowed_tools
            if self.delegated_tool_whitelist:
                whitelist = set(self.delegated_tool_whitelist)
                return tuple(name for name in allowed_tools if name in whitelist)
            return allowed_tools
        if not self.workflow or not self.workflow_kernel:
            return tuple(self.tools)
        return tuple(name for name in _phase_allowed_tools(self.workflow, self.workflow_kernel.state.phase) if name in self.tools)

    def build_prefix(self):
        tool_lines = []
        for name in self.prompt_tool_names():
            tool = self.tools[name]
            fields = ", ".join(f"{key}: {value}" for key, value in tool["schema"].items())
            risk = "approval required" if tool["risky"] else "safe"
            tool_lines.append(f"- {name}({fields}) [{risk}] {tool['description']}")
        tool_text = "\n".join(tool_lines)
        examples = "\n".join(
            [toolkit.tool_example(name) for name in self.prompt_tool_names() if toolkit.tool_example(name)] + ["<final>Done.</final>"]
        )
        # prefix 可以理解成 agent 的“工作手册”：
        # 它是谁、工具怎么调用、当前仓库是什么状态，都写在这里。
        text = textwrap.dedent(
            f"""\
            You are skillforge, a small local coding agent working inside a local repository.

            Rules:
            - Use tools instead of guessing about the workspace.
            - Return exactly one <tool>...</tool> or one <final>...</final>.
            - Tool calls must look like:
              <tool>{{"name":"tool_name","args":{{...}}}}</tool>
            - For write_file and patch_file with multi-line text, prefer XML style:
              <tool name="write_file" path="file.py"><content>...</content></tool>
            - Final answers must look like:
              <final>your answer</final>
            - Never invent tool results.
            - Keep answers concise and concrete.
            - If the user asks you to create or update a specific file and the path is clear, use write_file or patch_file instead of repeatedly listing files.
            - Before writing tests for existing code, read the implementation first.
            - When writing tests, match the current implementation unless the user explicitly asked you to change the code.
            - New files should be complete and runnable, including obvious imports.
            - Do not repeat the same tool call with the same arguments if it did not help. Choose a different tool or return a final answer.
            - Required tool arguments must not be empty. Do not call read_file, write_file, patch_file, run_shell, or delegate with args={{}}.

            Tools:
            {tool_text}

            Valid response examples:
            {examples}

            {self.workspace.text()}
            """
        ).strip()
        return PromptPrefix(
            text=text,
            hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            workspace_fingerprint=self.workspace.fingerprint(),
            tool_signature=self.prompt_tool_signature(),
            built_at=now(),
        )

    def _apply_prefix_state(self, prefix_state):
        self.prefix_state = prefix_state
        self.prefix = prefix_state.text

    def refresh_prefix(self, force=False):
        previous_hash = getattr(getattr(self, "prefix_state", None), "hash", None)
        previous_workspace_fingerprint = getattr(getattr(self, "prefix_state", None), "workspace_fingerprint", None)

        # 工作区事实相对稳定，所以这里按整体刷新；
        # 只有这些事实真的变化了，才重建完整 prefix。
        refreshed_workspace = WorkspaceContext.build(self.root)
        refreshed_workspace_fingerprint = refreshed_workspace.fingerprint()
        workspace_changed = force or refreshed_workspace_fingerprint != previous_workspace_fingerprint
        if workspace_changed:
            self.workspace = refreshed_workspace

        prefix_state = self.build_prefix() if workspace_changed or force or previous_hash is None else self.prefix_state
        prefix_changed = force or previous_hash != prefix_state.hash
        if prefix_changed:
            self._apply_prefix_state(prefix_state)

        self._last_prefix_refresh = {
            "workspace_changed": workspace_changed,
            "prefix_changed": prefix_changed,
        }
        return dict(self._last_prefix_refresh)

    def memory_text(self):
        return self.memory.render_memory_text()

    def history_text(self):
        history = self.session["history"]
        if not history:
            return "- empty"

        lines = []
        seen_reads = set()
        recent_start = max(0, len(history) - 6)
        for index, item in enumerate(history):
            recent = index >= recent_start
            if item["role"] == "tool" and item["name"] == "read_file" and not recent:
                path = str(item["args"].get("path", ""))
                if path in seen_reads:
                    continue
                seen_reads.add(path)

            if item["role"] == "tool":
                limit = 900 if recent else 180
                lines.append(f"[tool:{item['name']}] {json.dumps(item['args'], sort_keys=True)}")
                lines.append(clip(item["content"], limit))
            else:
                limit = 900 if recent else 220
                lines.append(f"[{item['role']}] {clip(item['content'], limit)}")

        return clip("\n".join(lines), MAX_HISTORY)

    def feature_enabled(self, name):
        return bool(self.feature_flags.get(str(name), False))

    def prompt(self, user_message):
        prompt, _ = self._build_prompt_and_metadata(user_message)
        return prompt

    def record(self, item):
        self.session["history"].append(item)
        self.session_path = self.session_store.save(self.session)

    @staticmethod
    def looks_sensitive_env_name(name):
        upper = str(name).upper()
        return any(upper == marker or upper.endswith(marker) or upper.endswith(f"_{marker}") for marker in SENSITIVE_ENV_NAME_MARKERS)

    def is_secret_env_name(self, name):
        upper = str(name).upper()
        return upper in self.secret_env_names or self.looks_sensitive_env_name(upper)

    def configured_secret_env_items(self):
        items = [
            (name, value)
            for name, value in os.environ.items()
            if str(name).upper() in self.secret_env_names and value
        ]
        items.sort(key=lambda item: item[0])
        return items

    def detected_secret_env_items(self):
        items = [
            (name, value)
            for name, value in os.environ.items()
            if self.is_secret_env_name(name) and value
        ]
        items.sort(key=lambda item: item[0])
        return items

    def secret_env_summary(self):
        names = [name for name, _ in self.configured_secret_env_items()]
        return {
            "secret_env_count": len(names),
            "secret_env_names": names,
        }

    def detected_secret_env_summary(self):
        names = [name for name, _ in self.detected_secret_env_items()]
        return {
            "secret_env_count": len(names),
            "secret_env_names": names,
        }

    def redact_text(self, text):
        text = str(text)
        for _, value in sorted(self.detected_secret_env_items(), key=lambda item: len(item[1]), reverse=True):
            text = text.replace(value, REDACTED_VALUE)
        return text

    def redact_artifact(self, value, key=None):
        if key and self.is_secret_env_name(key):
            return REDACTED_VALUE
        if isinstance(value, dict):
            return {
                str(item_key): self.redact_artifact(item_value, key=item_key)
                for item_key, item_value in value.items()
            }
        if isinstance(value, list):
            return [self.redact_artifact(item, key=key) for item in value]
        if isinstance(value, tuple):
            return [self.redact_artifact(item, key=key) for item in value]
        if isinstance(value, str):
            redacted = self.redact_text(value)
            return redacted
        return value

    def shell_env(self):
        env = {
            name: os.environ[name]
            for name in self.shell_env_allowlist
            if name in os.environ
        }
        env["PWD"] = str(self.root)
        if "PATH" not in env and os.environ.get("PATH"):
            env["PATH"] = os.environ["PATH"]
        return env

    def prompt_metadata(self, user_message, prompt):
        _, metadata = self._build_prompt_and_metadata(user_message)
        return metadata

    def _build_prompt_and_metadata(self, user_message):
        task_packet = None
        force_refresh = False
        if self.workflow and self.workflow_kernel:
            task_packet = self._compile_workflow_task_packet(user_message)
            force_refresh = getattr(getattr(self, "prefix_state", None), "tool_signature", "") != self.prompt_tool_signature()
        refresh = self.refresh_prefix(force=force_refresh)
        self.resume_state = self.evaluate_resume_state()
        prompt, metadata = self.context_manager.build(user_message)
        # 这里把“这轮 prompt 是怎么拼出来的”连同缓存相关状态一起记下来，
        # 后面 trace/report 才能解释清楚：为什么这一轮 prefix 变了、缓存有没有命中。
        metadata.update(
            {
                "prefix_chars": len(self.prefix),
                "workspace_chars": len(self.workspace.text()),
                "memory_chars": len(self.memory_text()),
                "history_chars": len(self.history_text()),
                "request_chars": len(user_message),
                "tool_count": len(self.tools),
                "workspace_docs": len(self.workspace.project_docs),
                "recent_commits": len(self.workspace.recent_commits),
                "prefix_hash": self.prefix_state.hash,
                "prompt_cache_key": self.prefix_state.hash,
                "workspace_fingerprint": self.prefix_state.workspace_fingerprint,
                "tool_signature": self.prefix_state.tool_signature,
                "workspace_changed": refresh["workspace_changed"],
                "prefix_changed": refresh["prefix_changed"],
                "prompt_cache_supported": bool(getattr(self.model_client, "supports_prompt_cache", False)),
                "resume_status": self.resume_state.get("status", CHECKPOINT_NONE_STATUS),
                "stale_summary_invalidations": int(self.resume_state.get("stale_summary_invalidations", 0)),
                "stale_paths": list(self.resume_state.get("stale_paths", [])),
                "runtime_identity_mismatch_fields": list(self.resume_state.get("runtime_identity_mismatch_fields", [])),
            }
        )
        if task_packet is not None:
            metadata.update(
                {
                    "workflow_name": task_packet.workflow,
                    "workflow_phase": task_packet.phase,
                    "workflow_status": task_packet.kernel_state.status,
                    "workflow_allowed_tools": list(self.prompt_tool_names()),
                    "workflow_evidence_refs": list(task_packet.evidence_refs),
                    "workflow_active_skill_ids": list(task_packet.active_skill_ids),
                }
            )
        metadata.update(self.detected_secret_env_summary())
        return prompt, metadata

    def _configure_workflow(self, workflow_name, workflow_state=None, delegated_task_packet=None):
        if isinstance(delegated_task_packet, dict):
            delegated_task_packet = TaskPacket.from_dict(delegated_task_packet)
        if delegated_task_packet is not None:
            workflow_name = delegated_task_packet.workflow
        workflow_name = str(workflow_name or "").strip()
        if not workflow_name:
            self.session.pop("workflow", None)
            return
        self.workflow = workflow_template(workflow_name)
        if delegated_task_packet is not None:
            if delegated_task_packet.workflow != self.workflow.name:
                raise ValueError(
                    f"delegated task packet workflow mismatch: expected {self.workflow.name}, got {delegated_task_packet.workflow}"
                )
            self.workflow_kernel = WorkflowKernel(self.workflow, state=delegated_task_packet.kernel_state)
            self.inherited_task_packet = delegated_task_packet
            self.active_task_packet = delegated_task_packet
        elif workflow_state is not None:
            self.workflow_kernel = WorkflowKernel(self.workflow, state=workflow_state)
        else:
            self.workflow_kernel = WorkflowKernel(self.workflow)
        self.skill_store = SkillStore(self.root / ".skillforge" / "skills")
        self.task_packet_compiler = TaskPacketCompiler(skill_store=self.skill_store)
        self.session["workflow"] = self.workflow.name

    def _reset_workflow_run(self):
        if not self.workflow:
            return
        self._used_active_skill_ids = set()
        if self.workflow_phase_locked and self.inherited_task_packet is not None:
            self.workflow_kernel = WorkflowKernel(self.workflow, state=self.inherited_task_packet.kernel_state)
            self.active_task_packet = self.inherited_task_packet
            self.evidence_store = None
            return
        self.workflow_kernel = WorkflowKernel(self.workflow)
        self.active_task_packet = None
        self.evidence_store = None

    def current_evidence_store(self):
        if self.current_run_dir is None:
            return None
        run_root = Path(self.current_run_dir)
        if self.evidence_store is None or self.evidence_store.run_root != run_root:
            self.evidence_store = EvidenceStore(run_root)
        return self.evidence_store

    def record_runtime_evidence(self, record_type, payload, raw=False):
        store = self.current_evidence_store()
        if store is None or self.current_task_state is None:
            raise RuntimeError("runtime evidence requires an active run")
        return store.add(record_type, self.redact_artifact(payload), raw=raw)

    def _workflow_evidence_payload(self, event, summary, **metadata):
        payload = {
            "event": str(event),
            "summary": clip(str(summary), 160),
            "workflow": self.workflow.name if self.workflow else "",
            "phase": self.workflow_kernel.state.phase if self.workflow_kernel else "",
            "status": self.workflow_kernel.state.status if self.workflow_kernel else "",
            "run_id": self.current_task_state.run_id if self.current_task_state else "",
            "task_id": self.current_task_state.task_id if self.current_task_state else "",
        }
        payload.update(metadata)
        return payload

    @staticmethod
    def _compact_evidence_value(value):
        if isinstance(value, dict):
            return {str(key): SkillForge._compact_evidence_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [SkillForge._compact_evidence_value(item) for item in value]
        if isinstance(value, tuple):
            return [SkillForge._compact_evidence_value(item) for item in value]
        if isinstance(value, str):
            return clip(value, 200)
        return value

    def _tool_evidence_payload(self, name, args, result, metadata):
        tool_status = str(metadata.get("tool_status", "")).strip() or "unknown"
        payload = {
            "summary": f"{name} {tool_status}",
            "tool_name": str(name),
            "status": tool_status,
            "tool_error_code": str(metadata.get("tool_error_code", "")).strip(),
            "risk_level": str(metadata.get("risk_level", "")).strip(),
            "read_only": bool(metadata.get("read_only", False)),
            "args": self._compact_evidence_value(self.redact_artifact(args)),
            "affected_paths": list(metadata.get("affected_paths", [])),
            "workspace_changed": bool(metadata.get("workspace_changed", False)),
            "diff_summary": list(metadata.get("diff_summary", [])),
            "run_id": self.current_task_state.run_id if self.current_task_state else "",
            "task_id": self.current_task_state.task_id if self.current_task_state else "",
            "workflow": self.workflow.name if self.workflow else "",
            "phase": self.workflow_kernel.state.phase if self.workflow_kernel else "",
            "related_evidence_ids": EVIDENCE_ID_PATTERN.findall(str(result or "")),
        }
        return payload

    def _record_tool_evidence(self, name, args, result):
        metadata = dict(self._last_tool_result_metadata or {})
        tool_record = self.record_runtime_evidence(
            "tool",
            self._tool_evidence_payload(name, args, result, metadata),
        )
        self._record_completion_evidence_from_tool(name, args, result, metadata, tool_record.evidence_id)

    def _record_completion_evidence_from_tool(self, name, args, result, metadata, tool_evidence_id):
        if not self.workflow or not self.workflow_kernel:
            return
        affected_paths = [str(path).strip() for path in metadata.get("affected_paths", []) if str(path).strip()]
        diff_summary = [str(item).strip() for item in metadata.get("diff_summary", []) if str(item).strip()]
        if metadata.get("workspace_changed") and affected_paths:
            self.record_runtime_evidence(
                "diff",
                {
                    "summary": f"{name} changed {', '.join(affected_paths)}",
                    "tool_name": str(name),
                    "phase": self.workflow_kernel.state.phase,
                    "paths": affected_paths,
                    "diff_summary": diff_summary,
                    "tool_evidence_id": tool_evidence_id,
                },
            )
        if self.workflow_kernel.state.phase != "verify" or name != "log_run":
            return
        related_evidence_ids = EVIDENCE_ID_PATTERN.findall(str(result or ""))
        if not related_evidence_ids:
            return
        log_record = self.current_evidence_store().get(related_evidence_ids[-1])
        verification_status = str(log_record.payload.get("status", "")).strip()
        if verification_status == "unparsed":
            return
        self.record_runtime_evidence(
            "verification",
            {
                "summary": str(log_record.payload.get("parsed_summary") or verification_status),
                "status": verification_status,
                "phase": self.workflow_kernel.state.phase,
                "command": " ".join(str(part) for part in log_record.payload.get("command", [])),
                "returncode": log_record.payload.get("returncode"),
                "log_evidence_id": log_record.evidence_id,
                "tool_evidence_id": tool_evidence_id,
            },
        )

    def _workflow_paths(self):
        memory = self.memory.to_dict().get("working", {})
        return tuple(str(path) for path in memory.get("recent_files", []) if str(path).strip())

    def _compile_workflow_task_packet(self, user_message):
        if not self.workflow or not self.workflow_kernel or not self.task_packet_compiler:
            return None
        packet = self.task_packet_compiler.compile(
            user_intent=str(user_message),
            workflow=self.workflow,
            kernel=self.workflow_kernel,
            evidence_store=self.current_evidence_store(),
            paths=self._workflow_paths(),
        )
        if self.workflow_phase_locked and self.inherited_task_packet is not None:
            packet = self._merge_locked_task_packet(packet)
        self.active_task_packet = packet
        self._record_active_skill_use(packet)
        return self.active_task_packet

    def _record_active_skill_use(self, packet):
        if packet is None or self.skill_store is None or self.current_task_state is None:
            return
        new_skill_ids = [skill_id for skill_id in packet.active_skill_ids if skill_id not in self._used_active_skill_ids]
        if not new_skill_ids:
            return
        used_at = now()
        for skill_id in new_skill_ids:
            self.skill_store.record_active_use(skill_id, used_at=used_at)
            self._used_active_skill_ids.add(skill_id)

    def _record_active_skill_outcome(self, *, succeeded):
        if self.skill_store is None or not self._used_active_skill_ids:
            return
        for skill_id in sorted(self._used_active_skill_ids):
            self.skill_store.record_active_result(skill_id, succeeded=succeeded)

    def _merge_locked_task_packet(self, packet):
        inherited = self.inherited_task_packet
        if inherited is None:
            return packet

        def merge_briefs(left, right):
            merged = {}
            for item in left + right:
                merged[item.evidence_id] = item
            return tuple(merged[item_id] for item_id in merged)

        def merge_skill_constraints(left, right):
            merged = {}
            for item in left + right:
                merged[item.skill_id] = item
            return tuple(merged[skill_id] for skill_id in merged)

        evidence_briefs = merge_briefs(inherited.evidence_briefs, packet.evidence_briefs)
        evidence_refs = tuple(item.evidence_id for item in evidence_briefs)
        active_skill_constraints = merge_skill_constraints(inherited.active_skill_constraints, packet.active_skill_constraints)
        active_skill_ids = tuple(item.skill_id for item in active_skill_constraints)
        prompt_context = _render_task_packet_prompt_context(
            user_intent=packet.user_intent,
            workflow_state=packet.workflow_state,
            kernel_state=packet.kernel_state,
            allowed_tools=packet.allowed_tools,
            evidence_briefs=evidence_briefs,
            active_skill_constraints=active_skill_constraints,
        )
        return TaskPacket(
            schema_version=packet.schema_version,
            user_intent=packet.user_intent,
            workflow=packet.workflow,
            phase=packet.phase,
            workflow_state=packet.workflow_state,
            kernel_state=packet.kernel_state,
            allowed_tools=packet.allowed_tools,
            evidence_refs=evidence_refs,
            evidence_briefs=evidence_briefs,
            active_skill_ids=active_skill_ids,
            active_skill_constraints=active_skill_constraints,
            prompt_context=prompt_context,
        )

    def render_workflow_prompt_context(self):
        if self.active_task_packet is None:
            return ""
        if not self.delegated_tool_whitelist:
            return self.active_task_packet.prompt_context
        return _render_task_packet_prompt_context(
            user_intent=self.active_task_packet.user_intent,
            workflow_state=self.active_task_packet.workflow_state,
            kernel_state=self.active_task_packet.kernel_state,
            allowed_tools=self.current_allowed_tool_names(),
            evidence_briefs=self.active_task_packet.evidence_briefs,
            active_skill_constraints=self.active_task_packet.active_skill_constraints,
        )

    def _emit_workflow_task_packet_trace(self, task_state):
        if self.active_task_packet is None:
            return
        self.emit_trace(
            task_state,
            "workflow_task_packet_compiled",
            {
                "workflow": self.active_task_packet.workflow,
                "phase": self.active_task_packet.phase,
                "allowed_tools": list(self.current_allowed_tool_names()),
                "active_skill_ids": list(self.active_task_packet.active_skill_ids),
                "evidence_refs": list(self.active_task_packet.evidence_refs),
            },
        )

    def _advance_workflow_phase(self, task_state, phase_summary):
        if not self.workflow or not self.workflow_kernel:
            return False
        current_phase = self.workflow_kernel.state.phase
        if current_phase == "audit":
            return self._handle_audit_phase_completion(task_state, phase_summary)
        self._record_phase_completion_evidence(current_phase, phase_summary)
        current_index = self.workflow.phases.index(current_phase)
        if current_index + 1 >= len(self.workflow.phases):
            return False
        next_phase = self.workflow.phases[current_index + 1]
        self.workflow_kernel.transition(next_phase)
        self.active_task_packet = None
        self.record_runtime_evidence(
            "workflow",
            self._workflow_evidence_payload(
                "workflow_phase_transition",
                f"{self.workflow.name}:{current_phase}->{next_phase}",
                from_phase=current_phase,
                to_phase=next_phase,
                phase_summary=clip(phase_summary, 300),
            ),
        )
        self.emit_trace(
            task_state,
            "workflow_phase_transition",
            {
                "workflow": self.workflow.name,
                "from_phase": current_phase,
                "to_phase": next_phase,
                "status": self.workflow_kernel.state.status,
                "phase_summary": clip(phase_summary, 300),
            },
        )
        return True

    def _emit_workflow_transition(self, task_state, current_phase, next_phase, phase_summary):
        self.active_task_packet = None
        self.record_runtime_evidence(
            "workflow",
            self._workflow_evidence_payload(
                "workflow_phase_transition",
                f"{self.workflow.name}:{current_phase}->{next_phase}",
                from_phase=current_phase,
                to_phase=next_phase,
                phase_summary=clip(phase_summary, 300),
            ),
        )
        self.emit_trace(
            task_state,
            "workflow_phase_transition",
            {
                "workflow": self.workflow.name,
                "from_phase": current_phase,
                "to_phase": next_phase,
                "status": self.workflow_kernel.state.status,
                "phase_summary": clip(phase_summary, 300),
            },
        )

    def _handle_audit_phase_completion(self, task_state, phase_summary):
        audit_payload = self._resolve_audit_feedback(phase_summary)
        self.record_runtime_evidence("audit", audit_payload)
        current_phase = self.workflow_kernel.state.phase
        if audit_payload["status"] == "fail":
            return self._audit_failure(task_state, audit_payload)
        next_phase = audit_payload.get("next_phase", "")
        if not next_phase:
            return False
        self.workflow_kernel.transition(next_phase)
        self._emit_workflow_transition(task_state, current_phase, next_phase, phase_summary)
        return True

    def _record_skill_candidate_after_handoff(self, task_state):
        if self.skill_store is None:
            return self._skill_distill_failure(task_state, "skill store is not configured")
        try:
            candidate = SkillDistiller(self.skill_store).distill(
                self.current_evidence_store().records(),
                workflow=self.workflow,
            )
        except Exception as exc:
            return self._skill_distill_failure(task_state, str(exc))
        freshness_path = self.skill_store.candidate_freshness_path(candidate.candidate_id)
        self.record_runtime_evidence(
            "skill",
            {
                "slot": "candidate",
                "candidate_id": candidate.candidate_id,
                "summary": clip(f"quarantined {candidate.title}", 300),
                "workflow": self.workflow.name if self.workflow else "",
                "phase": self.workflow_kernel.state.phase if self.workflow_kernel else "",
                "active": False,
                "skill_candidate": candidate.to_dict(),
                "freshness_path": str(freshness_path) if freshness_path.exists() else "",
            },
        )
        self.emit_trace(
            task_state,
            "skill_candidate_distilled",
            {
                "candidate_id": candidate.candidate_id,
                "workflow": self.workflow.name if self.workflow else "",
                "phase": self.workflow_kernel.state.phase if self.workflow_kernel else "",
                "freshness_path": str(freshness_path) if freshness_path.exists() else "",
            },
        )
        return None

    def _skill_distill_failure(self, task_state, reason):
        reason = clip(str(reason or "unknown distill error"), 300)
        final = f"error: skill distill failed; {reason}"
        task_state.stop(STOP_REASON_SKILL_DISTILL_FAILED, final_answer=final)
        self._record_active_skill_outcome(succeeded=False)
        self.run_store.write_task_state(task_state)
        if self.workflow_kernel:
            self.workflow_kernel.block(STOP_REASON_SKILL_DISTILL_FAILED)
        self.active_task_packet = None
        self.record_runtime_evidence(
            "workflow",
            self._workflow_evidence_payload(
                "workflow_skill_distill_failed",
                final,
                stop_reason=task_state.stop_reason,
            ),
        )
        checkpoint = self.create_checkpoint(
            task_state,
            task_state.user_request,
            trigger=STOP_REASON_SKILL_DISTILL_FAILED,
        )
        self.run_store.write_task_state(task_state)
        self.emit_trace(
            task_state,
            "checkpoint_created",
            {
                "checkpoint_id": checkpoint["checkpoint_id"],
                "trigger": STOP_REASON_SKILL_DISTILL_FAILED,
            },
        )
        self.emit_trace(
            task_state,
            "run_finished",
            {
                "status": task_state.status,
                "stop_reason": task_state.stop_reason,
                "final_answer": final,
            },
        )
        self.run_store.write_report(task_state, self.redact_artifact(self.build_report(task_state)))
        return final

    def _parse_audit_feedback(self, phase_summary):
        text = str(phase_summary or "").strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _default_next_phase(self, current_phase):
        if not self.workflow:
            return ""
        current_index = self.workflow.phases.index(current_phase)
        if current_index + 1 >= len(self.workflow.phases):
            return ""
        return self.workflow.phases[current_index + 1]

    def _resolve_audit_feedback(self, phase_summary):
        current_phase = self.workflow_kernel.state.phase if self.workflow_kernel else "audit"
        summary_text = clip(str(phase_summary or ""), 300)
        structured = self._parse_audit_feedback(phase_summary)
        explicit_status = str(structured.get("status", "")).strip().lower()
        concerns = []
        checks = []
        evidence_refs = []
        if self.workflow and self.workflow.write_policy == "workspace_writes_allowed":
            report = audit_code_change(self.current_evidence_store().records())
            concerns.extend(report.concerns)
            checks.extend(check.to_dict() for check in report.checks)
            evidence_refs.extend(report.evidence_refs)
            if report.status == "fail":
                explicit_status = "fail"
        explicit_concerns = structured.get("concerns", ())
        if isinstance(explicit_concerns, (list, tuple)):
            for item in explicit_concerns:
                text = str(item).strip()
                if text:
                    concerns.append(text)
        elif isinstance(explicit_concerns, str) and explicit_concerns.strip():
            concerns.append(explicit_concerns.strip())
        concerns = list(dict.fromkeys(concerns))
        if explicit_status not in {"pass", "passed", "concerns", "fail"}:
            explicit_status = "concerns" if concerns else "pass"
        if explicit_status == "concerns" and not concerns:
            explicit_status = "fail"
            concerns = ["audit status=concerns requires at least one recorded concern"]
        next_phase = ""
        action = str(structured.get("action", "")).strip().lower()
        if explicit_status == "fail":
            next_phase = ""
        elif explicit_status == "concerns" and action == "return_to_implement":
            next_phase = "implement"
        else:
            next_phase = self._default_next_phase(current_phase)
        return {
            "status": explicit_status,
            "summary": clip(str(structured.get("summary") or summary_text), 300),
            "concerns": concerns,
            "checks": checks,
            "evidence_refs": list(dict.fromkeys(evidence_refs)),
            "workflow": self.workflow.name if self.workflow else "",
            "phase": current_phase,
            "action": action,
            "next_phase": next_phase,
        }

    def _audit_failure(self, task_state, audit_payload):
        concerns = [str(item).strip() for item in audit_payload.get("concerns", []) if str(item).strip()]
        final = "error: audit failed"
        if concerns:
            final += "; " + "; ".join(concerns)
        task_state.stop(STOP_REASON_AUDIT_FAILED, final_answer=final)
        self._record_active_skill_outcome(succeeded=False)
        self.run_store.write_task_state(task_state)
        self.workflow_kernel.block(STOP_REASON_AUDIT_FAILED)
        self.active_task_packet = None
        self.record_runtime_evidence(
            "workflow",
            self._workflow_evidence_payload(
                "workflow_audit_failed",
                final,
                concerns=concerns,
                evidence_refs=list(audit_payload.get("evidence_refs", [])),
                stop_reason=task_state.stop_reason,
            ),
        )
        checkpoint = self.create_checkpoint(task_state, task_state.user_request, trigger=STOP_REASON_AUDIT_FAILED)
        self.run_store.write_task_state(task_state)
        self.emit_trace(
            task_state,
            "checkpoint_created",
            {
                "checkpoint_id": checkpoint["checkpoint_id"],
                "trigger": STOP_REASON_AUDIT_FAILED,
            },
        )
        self.emit_trace(
            task_state,
            "run_finished",
            {
                "status": task_state.status,
                "stop_reason": task_state.stop_reason,
                "final_answer": final,
            },
        )
        self.run_store.write_report(task_state, self.redact_artifact(self.build_report(task_state)))
        return final

    def _record_phase_completion_evidence(self, phase, phase_summary):
        if not self.workflow:
            return
        phase = str(phase or "").strip()
        summary = clip(str(phase_summary or ""), 300)
        if phase == "audit":
            return

    def _record_handoff_evidence(self, final):
        if not self.workflow or not self.workflow_kernel:
            return None
        store = self.current_evidence_store()
        evidence_refs = tuple(record.evidence_id for record in store.records())
        artifact = HandoffArtifact(
            completed=(clip(str(final or ""), 300),),
            open_items=(),
            risks=(),
            next_phase="done",
            evidence_refs=evidence_refs,
        )
        payload = artifact.to_dict()
        payload.update(
            {
                "summary": clip(str(final or ""), 300),
                "workflow": self.workflow.name,
                "phase": self.workflow_kernel.state.phase,
            }
        )
        return self.record_runtime_evidence("handoff", payload)

    def _completion_gate_failure(self, task_state, user_message, gate_result):
        final = gate_result.failure_message()
        task_state.stop(STOP_REASON_COMPLETION_GATE_BLOCKED, final_answer=final)
        self._record_active_skill_outcome(succeeded=False)
        self.run_store.write_task_state(task_state)
        if self.workflow_kernel:
            self.workflow_kernel.block(STOP_REASON_COMPLETION_GATE_BLOCKED)
            self.record_runtime_evidence(
                "workflow",
                self._workflow_evidence_payload(
                    "workflow_completion_gate_blocked",
                    final,
                    missing=list(gate_result.missing),
                    invalid=list(gate_result.invalid),
                    evidence_refs=list(gate_result.evidence_refs),
                    stop_reason=task_state.stop_reason,
                ),
            )
        checkpoint = self.create_checkpoint(task_state, user_message, trigger=STOP_REASON_COMPLETION_GATE_BLOCKED)
        self.run_store.write_task_state(task_state)
        self.emit_trace(
            task_state,
            "checkpoint_created",
            {
                "checkpoint_id": checkpoint["checkpoint_id"],
                "trigger": STOP_REASON_COMPLETION_GATE_BLOCKED,
            },
        )
        self.emit_trace(
            task_state,
            "run_finished",
            {
                "status": task_state.status,
                "stop_reason": task_state.stop_reason,
                "final_answer": final,
            },
        )
        self.run_store.write_report(task_state, self.redact_artifact(self.build_report(task_state)))
        return final

    def emit_trace(self, task_state, event, payload=None):
        payload = self.redact_artifact(payload or {})
        payload["event"] = event
        payload["created_at"] = now()
        # trace 是运行中的逐事件时间线，适合回答“这一轮 agent 到底做了什么”。
        self.run_store.append_trace(task_state, payload)
        return payload

    def capture_workspace_snapshot(self):
        snapshot = {}
        for path in self.root.rglob("*"):
            try:
                relative_parts = path.relative_to(self.root).parts
            except ValueError:
                continue
            if any(part in IGNORED_PATH_NAMES for part in relative_parts):
                continue
            if not path.is_file():
                continue
            try:
                snapshot[path.relative_to(self.root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            except Exception:
                continue
        return snapshot

    @staticmethod
    def diff_workspace_snapshots(before, after):
        changed_paths = []
        summaries = []
        all_paths = sorted(set(before) | set(after))
        for path in all_paths:
            if before.get(path) == after.get(path):
                continue
            changed_paths.append(path)
            if path not in before:
                summaries.append(f"created:{path}")
            elif path not in after:
                summaries.append(f"deleted:{path}")
            else:
                summaries.append(f"modified:{path}")
        return changed_paths, summaries

    def create_checkpoint(self, task_state, user_message, trigger):
        state = self.checkpoint_state()
        current = self.current_checkpoint()
        checkpoint_id = "ckpt_" + uuid.uuid4().hex[:8]
        key_files = []
        freshness = {}
        for path in self.memory.to_dict()["working"]["recent_files"]:
            file_freshness = memorylib.file_freshness(path, self.root)
            freshness[path] = file_freshness
            key_files.append({"path": path, "freshness": file_freshness})
        checkpoint = {
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": current.get("checkpoint_id", "") if current else "",
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "created_at": now(),
            "current_goal": str(user_message),
            "completed": [task_state.final_answer] if task_state.final_answer else [],
            "excluded": [],
            "current_blocker": "" if str(task_state.stop_reason or "") in ("", "final_answer_returned") else str(task_state.stop_reason),
            "next_step": self.infer_next_step(task_state),
            "key_files": key_files,
            "freshness": freshness,
            "summary": f"{trigger}: {clip(str(user_message), 120)}",
            "runtime_identity": self.current_runtime_identity(),
        }
        state["items"][checkpoint_id] = checkpoint
        state["current_id"] = checkpoint_id
        task_state.checkpoint_id = checkpoint_id
        self.session["runtime_identity"] = checkpoint["runtime_identity"]
        self.session_path = self.session_store.save(self.session)
        return checkpoint

    def infer_next_step(self, task_state):
        if task_state.status == "completed":
            return "No next step recorded."
        if task_state.stop_reason == "step_limit_reached":
            return "Resume from the latest checkpoint and continue the task."
        if task_state.last_tool:
            return f"Decide the next action after {task_state.last_tool}."
        return "Continue the task from the latest checkpoint."

    def update_memory_after_tool(self, name, args, result):
        """把少量高价值工具结果沉淀到 working memory。

        为什么存在：
        并不是每个工具结果都值得长期带进下一轮 prompt。完整结果已经进了
        `history`，这里只挑少量“下一轮大概率还会用到”的事实做提纯，
        例如最近读写过哪些文件、某个文件读出来的短摘要。

        输入 / 输出：
        - 输入：工具名 `name`、参数 `args`、执行结果 `result`
        - 输出：无显式返回值，副作用是更新 `self.memory`

        在 agent 链路里的位置：
        它发生在 `run_tool()` 真正执行完工具之后、下一轮 prompt 组装之前。
        也就是说：工具结果先进入完整历史，再由这个函数择优沉淀成轻量记忆。
        """
        if not self.feature_enabled("memory"):
            return
        path = args.get("path")
        if not path:
            return

        canonical_path = self.memory.canonical_path(path)
        # 不是所有工具结果都进入工作记忆。
        # 读文件会生成摘要；写文件/patch 会让旧摘要失效，因为它们可能过期了。
        if name in {"read_file", "write_file", "patch_file"}:
            self.memory.remember_file(canonical_path)
        if name == "read_file":
            summary = memorylib.summarize_read_result(result)
            self.memory.set_file_summary(canonical_path, summary)
            self.memory.append_note(summary, tags=(canonical_path,), source=canonical_path)
        elif name in {"write_file", "patch_file"}:
            self.memory.invalidate_file_summary(canonical_path)

    def note_tool(self, name, args, result):
        self.update_memory_after_tool(name, args, result)

    def record_process_note_for_tool(self, name, metadata):
        status = str(metadata.get("tool_status", "")).strip()
        if status not in {"partial_success", "error", "rejected"}:
            return
        affected_paths = [str(path).strip() for path in metadata.get("affected_paths", []) if str(path).strip()]
        path_text = ", ".join(affected_paths) or "workspace"
        if status == "partial_success":
            text = f"{name} partial_success on {path_text}; inspect diff before retry"
        elif status == "error":
            text = f"{name} error on {path_text}; check the failure before retry"
        else:
            text = f"{name} rejected; choose a different action before retry"
        tags = ["process", status, *affected_paths]
        self.memory.append_note(text, tags=tuple(tags), source=name, kind="process")
        self.session["memory"] = self.memory.to_dict()

    def reject_durable_reason(self, note_text):
        text = str(note_text or "").strip()
        lowered = text.lower()
        if not text:
            return "empty"
        if REDACTED_VALUE in text or SECRET_SHAPED_TEXT_PATTERN.search(text):
            return "secret_shaped"
        checkpoint_like_prefixes = (
            "current goal",
            "current blocker",
            "next step",
            "current phase",
            "key files",
            "freshness",
            "当前目标",
            "当前卡点",
            "下一步",
            "当前阶段",
            "关键文件",
            "已完成",
            "已排除",
        )
        if any(lowered.startswith(prefix) for prefix in checkpoint_like_prefixes):
            return "transient_task_state"
        if re.search(r"(?i)\b(stdout|stderr|traceback|exit_code)\b", text) or len(text) > 220:
            return "noisy_output"
        return ""

    def extract_durable_promotions(self, user_message, final_answer):
        user_text = str(user_message or "")
        if not (DURABLE_MEMORY_INTENT_PATTERN.search(user_text) or DURABLE_MEMORY_INTENT_ZH_PATTERN.search(user_text)):
            return [], []
        promotions = []
        rejections = []
        for line in str(final_answer or "").splitlines():
            text = line.strip()
            if not text or REDACTED_VALUE in text:
                continue
            for topic, pattern in DURABLE_MEMORY_LINE_PATTERNS:
                match = pattern.match(text)
                if not match:
                    continue
                note_text = match.group(1).strip()
                if note_text:
                    reason = self.reject_durable_reason(note_text)
                    if reason:
                        rejections.append(f"{topic}:{reason}")
                        break
                    promotions.append((topic, note_text))
                break
        return promotions, rejections

    def promote_durable_memory(self, user_message, final_answer):
        promotions, rejections = self.extract_durable_promotions(user_message, final_answer)
        promoted, superseded = self.memory.promote_durable(promotions)
        self.session["memory"] = self.memory.to_dict()
        self.last_durable_promotions = promoted
        self.last_durable_rejections = rejections
        self.last_durable_superseded = superseded
        return promoted, rejections, superseded

    def ask(self, user_message):
        """执行一次完整的 agent 回合，直到产出最终答案或命中停止条件。

        为什么存在：
        `ask()` 是整个 runtime 的总调度器。它把“用户提一个请求”扩展成一条
        可持续推进的控制循环：记录会话、组 prompt、调用模型、执行工具、
        写 trace/report、更新状态，直到模型给出最终答案或系统主动停下。

        输入 / 输出：
        - 输入：`user_message`，即用户这一次的任务描述
        - 输出：字符串形式的最终回答；如果中途达到步数上限或重试上限，
          返回的是一条停止原因说明

        在 agent 链路里的位置：
        它是 CLI 和底层工具/模型之间的核心桥梁。CLI 收到用户输入后基本只做
        一件事：调用 `agent.ask()`。而 `ask()` 内部再去驱动 `ContextManager`
        组 prompt、`model_client.complete()` 调模型、`run_tool()` 执行动作。
        如果新人想理解 skillforge 是怎么“从一句话跑成一个 agent 流程”的，
        这里就是最关键的入口。
        """
        run_started_at = time.monotonic()
        self.memory.set_task_summary(user_message)
        self.record({"role": "user", "content": user_message, "created_at": now()})
        self._reset_workflow_run()
        self._used_active_skill_ids = set()

        task_state = TaskState.create(run_id=self.new_run_id(), task_id=self.new_task_id(), user_request=user_message)
        task_state.resume_status = self.resume_state.get("status", CHECKPOINT_NONE_STATUS)
        self.current_task_state = task_state
        self.current_run_dir = self.run_store.start_run(task_state)
        if self.workflow and self.workflow_kernel:
            self.record_runtime_evidence(
                "workflow",
                self._workflow_evidence_payload(
                    "workflow_run_started",
                    f"{self.workflow.name}:{self.workflow_kernel.state.phase} started",
                ),
            )
        self.emit_trace(
            task_state,
            "run_started",
            {
                "task_id": task_state.task_id,
                "user_request": clip(user_message, 300),
            },
        )

        tool_steps = 0
        attempts = 0
        max_attempts = max(self.max_steps * 3, self.max_steps + 4)

        # 这是 agent 的主循环，可以按“感知 -> 决策 -> 行动 -> 记录”来理解：
        # 1. 感知：重新组 prompt，把当前状态整理给模型看
        # 2. 决策：让模型返回一个工具调用，或一个最终答案
        # 3. 行动：如果是工具调用，就执行工具
        # 4. 记录：把结果写回 history / task_state / trace / memory
        # 然后进入下一轮，直到停机条件满足
        while tool_steps < self.max_steps and attempts < max_attempts:
            attempts += 1
            task_state.record_attempt()
            self.run_store.write_task_state(task_state)
            prompt_started_at = time.monotonic()
            prompt, prompt_metadata = self._build_prompt_and_metadata(user_message)
            if self.workflow:
                self._emit_workflow_task_packet_trace(task_state)
            self.emit_trace(
                task_state,
                "prompt_built",
                {
                    "prompt_metadata": prompt_metadata,
                    "duration_ms": int((time.monotonic() - prompt_started_at) * 1000),
                },
            )
            if prompt_metadata.get("resume_status") == CHECKPOINT_PARTIAL_STALE_STATUS:
                checkpoint = self.create_checkpoint(task_state, user_message, trigger="freshness_mismatch")
                self.run_store.write_task_state(task_state)
                self.emit_trace(
                    task_state,
                    "checkpoint_created",
                    {
                        "checkpoint_id": checkpoint["checkpoint_id"],
                        "trigger": "freshness_mismatch",
                    },
                )
            elif prompt_metadata.get("resume_status") == CHECKPOINT_WORKSPACE_MISMATCH_STATUS:
                self.emit_trace(
                    task_state,
                    "runtime_identity_mismatch",
                    {
                        "fields": list(prompt_metadata.get("runtime_identity_mismatch_fields", [])),
                    },
                )
                checkpoint = self.create_checkpoint(task_state, user_message, trigger="workspace_mismatch")
                self.run_store.write_task_state(task_state)
                self.emit_trace(
                    task_state,
                    "checkpoint_created",
                    {
                        "checkpoint_id": checkpoint["checkpoint_id"],
                        "trigger": "workspace_mismatch",
                    },
                )
            if prompt_metadata.get("budget_reductions"):
                checkpoint = self.create_checkpoint(task_state, user_message, trigger="context_reduction")
                self.run_store.write_task_state(task_state)
                self.emit_trace(
                    task_state,
                    "checkpoint_created",
                    {
                        "checkpoint_id": checkpoint["checkpoint_id"],
                        "trigger": "context_reduction",
                    },
                )
            self.emit_trace(
                task_state,
                "model_requested",
                {
                    "attempts": task_state.attempts,
                    "tool_steps": task_state.tool_steps,
                    "prompt_cache_key": prompt_metadata.get("prompt_cache_key"),
                },
            )
            prompt_cache_key = None
            prompt_cache_retention = None
            if getattr(self.model_client, "supports_prompt_cache", False):
                # 只有后端明确支持时，才把稳定前缀的 hash 作为 cache key 发出去。
                prompt_cache_key = prompt_metadata.get("prompt_cache_key")
                prompt_cache_retention = "in_memory"
            model_started_at = time.monotonic()
            raw = self.model_client.complete(
                prompt,
                self.max_new_tokens,
                prompt_cache_key=prompt_cache_key,
                prompt_cache_retention=prompt_cache_retention,
            )
            if self.workflow and self.workflow_kernel:
                self.workflow_kernel.record_round()
            completion_metadata = dict(getattr(self.model_client, "last_completion_metadata", {}) or {})
            if completion_metadata:
                # 把后端返回的 usage/cache 统计并回 prompt_metadata，
                # 方便统一写入 report 和 trace。
                prompt_metadata.update(completion_metadata)
            self.last_completion_metadata = completion_metadata
            self.last_prompt_metadata = prompt_metadata
            kind, payload = self.parse(raw)
            self.emit_trace(
                task_state,
                "model_parsed",
                {
                    "kind": kind,
                    "completion_metadata": completion_metadata,
                    "duration_ms": int((time.monotonic() - model_started_at) * 1000),
                },
            )

            if kind == "tool":
                tool_steps += 1
                name = payload.get("name", "")
                args = payload.get("args", {})
                task_state.record_tool(name)
                if self.workflow and self.workflow_kernel:
                    self.workflow_kernel.record_tool()
                tool_started_at = time.monotonic()
                result = self.run_tool(name, args)
                self._record_tool_evidence(name, args, result)
                self.record(
                    {
                        "role": "tool",
                        "name": name,
                        "args": args,
                        "content": result,
                        "created_at": now(),
                    }
                )
                self.run_store.write_task_state(task_state)
                self.emit_trace(
                    task_state,
                    "tool_executed",
                    {
                        "name": name,
                        "args": args,
                        "result": clip(result, 500),
                        "duration_ms": int((time.monotonic() - tool_started_at) * 1000),
                        **dict(self._last_tool_result_metadata or {}),
                    },
                )
                checkpoint = self.create_checkpoint(task_state, user_message, trigger="tool_executed")
                self.run_store.write_task_state(task_state)
                self.emit_trace(
                    task_state,
                    "checkpoint_created",
                    {
                        "checkpoint_id": checkpoint["checkpoint_id"],
                        "trigger": "tool_executed",
                    },
                )
                continue

            if kind == "retry":
                self.record({"role": "assistant", "content": payload, "created_at": now()})
                self.run_store.write_task_state(task_state)
                continue

            final = (payload or raw).strip()
            if (
                self.workflow
                and self.workflow_kernel
                and self.workflow_kernel.state.phase != "handoff"
                and not self.workflow_phase_locked
            ):
                self.record({"role": "assistant", "content": final, "created_at": now()})
                self.run_store.write_task_state(task_state)
                phase_result = self._advance_workflow_phase(task_state, final)
                if isinstance(phase_result, str):
                    return phase_result
                continue
            if (
                self.workflow
                and self.workflow_kernel
                and self.workflow.write_policy == "workspace_writes_allowed"
                and self.workflow_kernel.state.phase == "handoff"
            ):
                self._record_handoff_evidence(final)
                gate_result = CompletionGate(self.workflow).evaluate(self.current_evidence_store().records())
                if not gate_result.allowed:
                    self.record({"role": "assistant", "content": final, "created_at": now()})
                    return self._completion_gate_failure(task_state, user_message, gate_result)
                if "skill_distill" in self.workflow.phases:
                    skill_result = self._record_skill_candidate_after_handoff(task_state)
                    if isinstance(skill_result, str):
                        self.record({"role": "assistant", "content": final, "created_at": now()})
                        return skill_result
            self.record({"role": "assistant", "content": final, "created_at": now()})
            task_state.finish_success(final)
            self._record_active_skill_outcome(succeeded=True)
            self.promote_durable_memory(user_message, final)
            checkpoint = self.create_checkpoint(task_state, user_message, trigger="run_finished")
            self.run_store.write_task_state(task_state)
            if self.workflow and self.workflow_kernel:
                self.record_runtime_evidence(
                    "workflow",
                    self._workflow_evidence_payload(
                        "workflow_run_finished",
                        f"{self.workflow.name}:{self.workflow_kernel.state.phase} finished",
                        stop_reason=task_state.stop_reason,
                    ),
                )
            self.emit_trace(
                task_state,
                "checkpoint_created",
                {
                    "checkpoint_id": checkpoint["checkpoint_id"],
                    "trigger": "run_finished",
                },
            )
            self.emit_trace(
                task_state,
                "run_finished",
                {
                    "status": task_state.status,
                    "stop_reason": task_state.stop_reason,
                    "final_answer": final,
                    "run_duration_ms": int((time.monotonic() - run_started_at) * 1000),
                },
            )
            self.run_store.write_report(task_state, self.redact_artifact(self.build_report(task_state)))
            return final

        if attempts >= max_attempts and tool_steps < self.max_steps:
            final = "Stopped after too many malformed model responses without a valid tool call or final answer."
            task_state.stop_retry_limit(final)
        else:
            final = "Stopped after reaching the step limit without a final answer."
            task_state.stop_step_limit(final)
        self.record({"role": "assistant", "content": final, "created_at": now()})
        self._record_active_skill_outcome(succeeded=False)
        self.promote_durable_memory(user_message, final)
        self.run_store.write_task_state(task_state)
        checkpoint = self.create_checkpoint(task_state, user_message, trigger=task_state.stop_reason or "run_stopped")
        if self.workflow and self.workflow_kernel:
            self.record_runtime_evidence(
                "workflow",
                self._workflow_evidence_payload(
                    "workflow_run_finished",
                    f"{self.workflow.name}:{self.workflow_kernel.state.phase} finished",
                    stop_reason=task_state.stop_reason,
                ),
            )
        self.emit_trace(
            task_state,
            "checkpoint_created",
            {
                "checkpoint_id": checkpoint["checkpoint_id"],
                "trigger": task_state.stop_reason or "run_stopped",
            },
        )
        self.emit_trace(
            task_state,
            "run_finished",
            {
                "status": task_state.status,
                "stop_reason": task_state.stop_reason,
                "final_answer": final,
                "run_duration_ms": int((time.monotonic() - run_started_at) * 1000),
            },
        )
        self.run_store.write_report(task_state, self.redact_artifact(self.build_report(task_state)))
        return final

    def run_tool(self, name, args):
        """执行一次工具调用，并在执行前后套上完整护栏。

        为什么存在：
        在 agent 系统里，真正危险的不是“模型会不会想调用工具”，而是
        “平台有没有在执行前把边界守住”。这个函数就是工具层的总闸口：
        所有工具调用都必须先经过它，不能让模型直接碰到底层函数。

        输入 / 输出：
        - 输入：工具名 `name`，参数字典 `args`
        - 输出：字符串结果。无论是成功结果还是错误信息，都会统一返回文本，
          这样模型下一轮都能继续消费这份反馈。

        在 agent 链路里的位置：
        它位于 `ask()` 的“模型决定要调用工具”之后，是控制循环里真正把模型
        意图落到外部世界的一步。因此这里串起了几乎所有安全与可控设计：
        工具是否存在、参数是否合法、是否重复、是否需要审批、执行结果是否裁剪、
        是否需要回写记忆。
        """
        # 工具执行不是“直接调函数”，而是一条带护栏的流水线：
        # 工具是否存在 -> 参数是否合法 -> 是否重复调用 -> 是否通过审批
        # -> 真正执行 -> 更新记忆。
        tool = self.tools.get(name)
        if tool is None:
            self._last_tool_result_metadata = {
                "tool_status": "rejected",
                "tool_error_code": "unknown_tool",
                "security_event_type": "",
                "risk_level": "high",
                "read_only": False,
                "affected_paths": [],
                "workspace_changed": False,
                "diff_summary": [],
            }
            return f"error: unknown tool '{name}'"
        if self.workflow and self.workflow_kernel:
            packet = self.active_task_packet or self._compile_workflow_task_packet(
                self.current_task_state.user_request if self.current_task_state else self.memory.to_dict()["working"].get("task_summary", "") or "workflow task"
            )
            allowed_tools = self.current_allowed_tool_names() if packet is not None else ()
            if packet is not None and name not in allowed_tools:
                self._last_tool_result_metadata = {
                    "tool_status": "rejected",
                    "tool_error_code": "workflow_tool_not_allowed",
                    "security_event_type": "workflow_tool_not_allowed",
                    "risk_level": "high" if tool["risky"] else "low",
                    "read_only": not tool["risky"],
                    "affected_paths": [],
                    "workspace_changed": False,
                    "diff_summary": [],
                }
                return f"error: tool {name} is not allowed in workflow {packet.workflow} phase {packet.phase}"
        try:
            self.validate_tool(name, args)
        except Exception as exc:
            example = self.tool_example(name)
            message = f"error: invalid arguments for {name}: {exc}"
            if example:
                message += f"\nexample: {example}"
            security_event_type = "path_escape" if "path escapes workspace" in str(exc) else ""
            self._last_tool_result_metadata = {
                "tool_status": "rejected",
                "tool_error_code": "invalid_arguments",
                "security_event_type": security_event_type,
                "risk_level": "high" if tool["risky"] else "low",
                "read_only": not tool["risky"],
                "affected_paths": [],
                "workspace_changed": False,
                "diff_summary": [],
            }
            return message
        if self.repeated_tool_call(name, args):
            self._last_tool_result_metadata = {
                "tool_status": "rejected",
                "tool_error_code": "repeated_identical_call",
                "security_event_type": "",
                "risk_level": "high" if tool["risky"] else "low",
                "read_only": not tool["risky"],
                "affected_paths": [],
                "workspace_changed": False,
                "diff_summary": [],
            }
            return f"error: repeated identical tool call for {name}; choose a different tool or return a final answer"
        if tool["risky"] and not self.approve(name, args):
            self._last_tool_result_metadata = {
                "tool_status": "rejected",
                "tool_error_code": "approval_denied",
                "security_event_type": "read_only_block" if self.read_only else "approval_denied",
                "risk_level": "high",
                "read_only": False,
                "affected_paths": [],
                "workspace_changed": False,
                "diff_summary": [],
            }
            return f"error: approval denied for {name}"
        before_snapshot = self.capture_workspace_snapshot() if tool["risky"] else {}
        after_snapshot = before_snapshot
        try:
            result = clip(tool["run"](args))
            after_snapshot = self.capture_workspace_snapshot() if tool["risky"] else before_snapshot
            affected_paths, diff_summary = self.diff_workspace_snapshots(before_snapshot, after_snapshot)
            workspace_changed = bool(affected_paths)
            tool_status = "ok"
            tool_error_code = ""
            if name == "run_shell":
                match = re.search(r"exit_code:\s*(-?\d+)", result)
                exit_code = int(match.group(1)) if match else 0
                if exit_code != 0 and workspace_changed:
                    tool_status = "partial_success"
                    tool_error_code = "tool_partial_success"
                elif exit_code != 0:
                    tool_status = "error"
                    tool_error_code = "tool_failed"
            self.update_memory_after_tool(name, args, result)
            self._last_tool_result_metadata = {
                "tool_status": tool_status,
                "tool_error_code": tool_error_code,
                "security_event_type": "",
                "risk_level": "high" if tool["risky"] else "low",
                "read_only": not tool["risky"],
                "affected_paths": affected_paths,
                "workspace_changed": workspace_changed,
                "workspace_fingerprint": self.workspace.fingerprint(),
                "diff_summary": diff_summary,
            }
            self.record_process_note_for_tool(name, self._last_tool_result_metadata)
            return result
        except Exception as exc:
            after_snapshot = self.capture_workspace_snapshot() if tool["risky"] else before_snapshot
            affected_paths, diff_summary = self.diff_workspace_snapshots(before_snapshot, after_snapshot)
            workspace_changed = bool(affected_paths)
            security_event_type = "path_escape" if "path escapes workspace" in str(exc) else ""
            self._last_tool_result_metadata = {
                "tool_status": "partial_success" if workspace_changed else "error",
                "tool_error_code": "tool_partial_success" if workspace_changed else "tool_failed",
                "security_event_type": security_event_type,
                "risk_level": "high" if tool["risky"] else "low",
                "read_only": not tool["risky"],
                "affected_paths": affected_paths,
                "workspace_changed": workspace_changed,
                "workspace_fingerprint": self.workspace.fingerprint(),
                "diff_summary": diff_summary,
            }
            self.record_process_note_for_tool(name, self._last_tool_result_metadata)
            return f"error: tool {name} failed: {exc}"

    def repeated_tool_call(self, name, args):
        # agent 很常见的一种坏循环，是在没有新信息的情况下反复发起同一调用。
        # 这里提前挡掉最简单的这种循环。
        tool_events = [item for item in self.session["history"] if item["role"] == "tool"]
        if len(tool_events) < 2:
            return False
        recent = tool_events[-2:]
        return all(item["name"] == name and item["args"] == args for item in recent)

    @staticmethod
    def new_task_id():
        return "task_" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]

    @staticmethod
    def new_run_id():
        return "run_" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]

    def build_report(self, task_state):
        # report 是一次运行的最终摘要；
        # 和 trace 的区别在于，trace 关注过程，report 关注结果与关键指标。
        return {
            "run_id": task_state.run_id,
            "task_id": task_state.task_id,
            "status": task_state.status,
            "stop_reason": task_state.stop_reason,
            "final_answer": task_state.final_answer,
            "tool_steps": task_state.tool_steps,
            "attempts": task_state.attempts,
            "checkpoint_id": task_state.checkpoint_id,
            "resume_status": task_state.resume_status,
            "task_state": task_state.to_dict(),
            "prompt_metadata": self.last_prompt_metadata,
            "durable_promotions": list(self.last_durable_promotions),
            "durable_rejections": list(self.last_durable_rejections),
            "durable_superseded": list(self.last_durable_superseded),
            "redacted_env": self.detected_secret_env_summary(),
        }

    def tool_example(self, name):
        return toolkit.tool_example(name)

    def validate_tool(self, name, args):
        """把通用工具校验和 runtime 级额外约束串起来。"""
        toolkit.validate_tool(self, name, args)
        if name == "delegate":
            if self.depth >= self.max_depth:
                raise ValueError("delegate depth exceeded")

    def tool_list_files(self, args):
        return toolkit.tool_list_files(self, args)

    def tool_read_file(self, args):
        return toolkit.tool_read_file(self, args)

    def tool_search(self, args):
        return toolkit.tool_search(self, args)

    def tool_run_shell(self, args):
        return toolkit.tool_run_shell(self, args)

    def tool_write_file(self, args):
        return toolkit.tool_write_file(self, args)

    def tool_patch_file(self, args):
        return toolkit.tool_patch_file(self, args)

    def tool_delegate(self, args):
        return toolkit.tool_delegate(self, args)

    def approve(self, name, args):
        if self.read_only:
            return False
        if self.approval_policy == "auto":
            return True
        if self.approval_policy == "never":
            return False
        try:
            answer = input(f"approve {name} {json.dumps(args, ensure_ascii=True)}? [y/N] ")
        except EOFError:
            return False
        return answer.strip().lower() in {"y", "yes"}

    @staticmethod
    def parse(raw):
        """把模型原始输出解析成 runtime 可执行的动作或最终答案。

        为什么存在：
        模型输出首先是自然语言文本，而 runtime 需要的是结构化决策：
        “这是工具调用”还是“这是最终答案”。如果没有这层解析，后面的工具校验、
        审批和执行链路就没法可靠工作。

        输入 / 输出：
        - 输入：模型返回的原始文本 `raw`
        - 输出：`(kind, payload)`，其中 `kind` 可能是 `tool`、`final`、`retry`

        在 agent 链路里的位置：
        它位于 `model_client.complete()` 之后、`run_tool()` 之前，是模型输出
        进入平台控制流的第一道结构化关口。
        """
        raw = str(raw)
        # 这里支持两种工具格式：
        # 1. <tool>...</tool> 里包 JSON，适合简短调用
        # 2. XML 风格属性/子标签，适合写文件这类多行内容
        if "<tool>" in raw and ("<final>" not in raw or raw.find("<tool>") < raw.find("<final>")):
            body = SkillForge.extract(raw, "tool")
            try:
                payload = json.loads(body)
            except Exception:
                return "retry", SkillForge.retry_notice("model returned malformed tool JSON")
            if not isinstance(payload, dict):
                return "retry", SkillForge.retry_notice("tool payload must be a JSON object")
            if not str(payload.get("name", "")).strip():
                return "retry", SkillForge.retry_notice("tool payload is missing a tool name")
            args = payload.get("args", {})
            if args is None:
                payload["args"] = {}
            elif not isinstance(args, dict):
                return "retry", SkillForge.retry_notice()
            return "tool", payload
        if "<tool" in raw and ("<final>" not in raw or raw.find("<tool") < raw.find("<final>")):
            payload = SkillForge.parse_xml_tool(raw)
            if payload is not None:
                return "tool", payload
            return "retry", SkillForge.retry_notice()
        if "<final>" in raw:
            final = SkillForge.extract(raw, "final").strip()
            if final:
                return "final", final
            return "retry", SkillForge.retry_notice("model returned an empty <final> answer")
        raw = raw.strip()
        if raw:
            return "final", raw
        return "retry", SkillForge.retry_notice("model returned an empty response")

    @staticmethod
    def retry_notice(problem=None):
        prefix = "Runtime notice"
        if problem:
            prefix += f": {problem}"
        else:
            prefix += ": model returned malformed tool output"
        return (
            f"{prefix}. Reply with a valid <tool> call or a non-empty <final> answer. "
            'For multi-line files, prefer <tool name="write_file" path="file.py"><content>...</content></tool>.'
        )

    @staticmethod
    def parse_xml_tool(raw):
        match = re.search(r"<tool(?P<attrs>[^>]*)>(?P<body>.*?)</tool>", raw, re.S)
        if not match:
            return None
        attrs = SkillForge.parse_attrs(match.group("attrs"))
        name = str(attrs.pop("name", "")).strip()
        if not name:
            return None

        body = match.group("body")
        args = dict(attrs)
        for key in ("content", "old_text", "new_text", "command", "task", "pattern", "path"):
            if f"<{key}>" in body:
                args[key] = SkillForge.extract_raw(body, key)

        body_text = body.strip("\n")
        if name == "write_file" and "content" not in args and body_text:
            args["content"] = body_text
        if name == "delegate" and "task" not in args and body_text:
            args["task"] = body_text.strip()
        return {"name": name, "args": args}

    @staticmethod
    def parse_attrs(text):
        attrs = {}
        for match in re.finditer(r"""([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""", text):
            attrs[match.group(1)] = match.group(2) if match.group(2) is not None else match.group(3)
        return attrs

    @staticmethod
    def extract(text, tag):
        start_tag = f"<{tag}>"
        end_tag = f"</{tag}>"
        start = text.find(start_tag)
        if start == -1:
            return text
        start += len(start_tag)
        end = text.find(end_tag, start)
        if end == -1:
            return text[start:].strip()
        return text[start:end].strip()

    @staticmethod
    def extract_raw(text, tag):
        start_tag = f"<{tag}>"
        end_tag = f"</{tag}>"
        start = text.find(start_tag)
        if start == -1:
            return text
        start += len(start_tag)
        end = text.find(end_tag, start)
        if end == -1:
            return text[start:]
        return text[start:end]

    def reset(self):
        self.session["history"] = []
        self.session["memory"].clear()
        self.session["memory"].update(memorylib.default_memory_state())
        self.memory = memorylib.LayeredMemory(self.session["memory"], workspace_root=self.root)
        self.session_store.save(self.session)

    def path(self, raw_path):
        path = Path(raw_path)
        path = path if path.is_absolute() else self.root / path
        resolved = path.resolve()
        # 所有文件类工具都被锚定在 workspace root 之下。
        # 这样既能防住 "../" 逃逸，也能防住符号链接解析后跳出仓库。
        if os.path.commonpath([str(self.root), str(resolved)]) != str(self.root):
            raise ValueError(f"path escapes workspace: {raw_path}")
        return resolved


MiniAgent = SkillForge
