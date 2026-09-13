import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import tempfile

from .verification import (
    RESULT_PASS,
    evaluate_verification_payload,
)


WORKFLOW_IR_SCHEMA_VERSION = "workflow-ir-v1"
WORKFLOW_IR_ARTIFACT_TYPE = "workflow_ir"
VALID_COMPLETION_REQUIREMENTS = {"diff", "verification", "audit", "handoff"}
VALID_LOG_POLICIES = {"raw_logs_to_evidence_only"}
VALID_WRITE_POLICIES = {"read_only", "workspace_writes_allowed"}
WRITE_TOOL_NAMES = frozenset({"write_file", "patch_file"})
WORKSPACE_EXECUTION_TOOL_NAMES = frozenset({"run_shell", "log_run"})
READ_ONLY_FORBIDDEN_TOOL_NAMES = WORKSPACE_EXECUTION_TOOL_NAMES | WRITE_TOOL_NAMES
LOG_TOOL_NAMES = frozenset({"log_run", "log_brief", "log_failure_detail"})
VALID_KERNEL_STATUSES = frozenset({"active", "handoff", "blocked"})
AUDIT_ACCEPTED_STATUSES = frozenset({"pass", "passed", "concerns"})
TASK_PACKET_SCHEMA_VERSION = "task-packet-v1"


def _require_non_empty_string(value, field_name):
    if not isinstance(value, str) or not value:
        raise ValueError(f"workflow schema field '{field_name}' must be a non-empty string")
    return value


def _require_positive_int(value, field_name):
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"workflow schema field '{field_name}' must be a positive integer")
    return value


def _require_non_negative_int(value, field_name):
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"workflow state field '{field_name}' must be a non-negative integer")
    return value


def _require_string_tuple(value, field_name):
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"workflow schema field '{field_name}' must be a non-empty list of strings")
    normalized = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError(f"workflow schema field '{field_name}' must contain non-empty strings")
        normalized.append(item)
    return tuple(normalized)


def _require_string_tuple_allow_empty(value, field_name):
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"workflow schema field '{field_name}' must be a list of strings")
    normalized = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError(f"workflow schema field '{field_name}' must contain non-empty strings")
        normalized.append(item)
    return tuple(normalized)


def _phase_transition_allowed(workflow, current_phase, next_phase, *, allow_forced_handoff=False):
    current_index = workflow.phases.index(current_phase)
    if current_index + 1 < len(workflow.phases) and workflow.phases[current_index + 1] == next_phase:
        return True
    if allow_forced_handoff and next_phase == "handoff" and "handoff" in workflow.phases:
        return True
    return (
        workflow.write_policy == "workspace_writes_allowed"
        and current_phase == "audit"
        and next_phase == "implement"
        and "implement" in workflow.phases
    )


def _validate_phase_history(workflow, phase_history):
    if phase_history[0] != workflow.phases[0]:
        raise ValueError("workflow kernel state must start from the workflow intake phase")
    for current_phase, next_phase in zip(phase_history, phase_history[1:]):
        if not _phase_transition_allowed(workflow, current_phase, next_phase, allow_forced_handoff=True):
            raise ValueError("workflow kernel state phase_history must follow workflow order")


@dataclass(frozen=True)
class WorkflowIR:
    name: str
    phases: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    write_policy: str
    log_policy: str
    completion_requirements: tuple[str, ...]
    round_budget: int
    tool_budget: int

    def to_dict(self):
        return asdict(self)

    def to_artifact(self):
        return {
            "schema_version": WORKFLOW_IR_SCHEMA_VERSION,
            "artifact_type": WORKFLOW_IR_ARTIFACT_TYPE,
            **self.to_dict(),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("workflow schema must be a JSON object")
        required_fields = {
            "name",
            "phases",
            "allowed_tools",
            "write_policy",
            "log_policy",
            "completion_requirements",
            "round_budget",
            "tool_budget",
        }
        missing = sorted(required_fields - set(data))
        if missing:
            raise ValueError(f"workflow schema missing required fields: {missing}")
        unexpected = sorted(set(data) - required_fields)
        if unexpected:
            raise ValueError(f"workflow schema has unexpected fields: {unexpected}")
        workflow = cls(
            name=_require_non_empty_string(data["name"], "name"),
            phases=_require_string_tuple(data["phases"], "phases"),
            allowed_tools=_require_string_tuple(data["allowed_tools"], "allowed_tools"),
            write_policy=_require_non_empty_string(data["write_policy"], "write_policy"),
            log_policy=_require_non_empty_string(data["log_policy"], "log_policy"),
            completion_requirements=_require_string_tuple(data["completion_requirements"], "completion_requirements"),
            round_budget=_require_positive_int(data["round_budget"], "round_budget"),
            tool_budget=_require_positive_int(data["tool_budget"], "tool_budget"),
        )
        StaticValidator().validate(workflow)
        return workflow

    @classmethod
    def from_artifact(cls, data):
        if not isinstance(data, dict):
            raise ValueError("workflow artifact must be a JSON object")
        schema_version = data.get("schema_version")
        if schema_version != WORKFLOW_IR_SCHEMA_VERSION:
            raise ValueError(
                f"workflow artifact schema_version mismatch: expected {WORKFLOW_IR_SCHEMA_VERSION}, got {schema_version!r}"
            )
        artifact_type = data.get("artifact_type")
        if artifact_type != WORKFLOW_IR_ARTIFACT_TYPE:
            raise ValueError(
                f"workflow artifact_type mismatch: expected {WORKFLOW_IR_ARTIFACT_TYPE}, got {artifact_type!r}"
            )
        workflow_payload = {
            key: value
            for key, value in data.items()
            if key not in {"schema_version", "artifact_type"}
        }
        return cls.from_dict(workflow_payload)


WORKFLOW_TEMPLATES = {
    "repo_audit": WorkflowIR(
        name="repo_audit",
        phases=("intake", "investigate", "audit", "handoff"),
        allowed_tools=("list_files", "read_file", "search", "log_brief", "log_failure_detail"),
        write_policy="read_only",
        log_policy="raw_logs_to_evidence_only",
        completion_requirements=("audit", "handoff"),
        round_budget=8,
        tool_budget=20,
    ),
    "code_change": WorkflowIR(
        name="code_change",
        phases=("intake", "plan_compile", "implement", "verify", "audit", "skill_distill", "handoff"),
        allowed_tools=(
            "list_files",
            "read_file",
            "search",
            "run_shell",
            "write_file",
            "patch_file",
            "delegate",
            "log_run",
            "log_brief",
            "log_failure_detail",
        ),
        write_policy="workspace_writes_allowed",
        log_policy="raw_logs_to_evidence_only",
        completion_requirements=("diff", "verification", "audit", "handoff"),
        round_budget=12,
        tool_budget=40,
    ),
    "test_fix": WorkflowIR(
        name="test_fix",
        phases=("intake", "investigate", "implement", "verify", "audit", "skill_distill", "handoff"),
        allowed_tools=(
            "list_files",
            "read_file",
            "search",
            "run_shell",
            "write_file",
            "patch_file",
            "log_run",
            "log_brief",
            "log_failure_detail",
        ),
        write_policy="workspace_writes_allowed",
        log_policy="raw_logs_to_evidence_only",
        completion_requirements=("diff", "verification", "audit", "handoff"),
        round_budget=10,
        tool_budget=32,
    ),
}


def workflow_template(name):
    try:
        return WORKFLOW_TEMPLATES[name]
    except KeyError as exc:
        raise ValueError(f"unknown workflow template: {name}") from exc


class WorkflowArtifactStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def workflow_path(self, name):
        return self.root / f"{name}.json"

    def write(self, workflow):
        validated = StaticValidator().validate(workflow)
        path = self.workflow_path(validated.name)
        self._write_json_atomic(path, validated.to_artifact())
        return path

    def write_template(self, name):
        return self.write(workflow_template(name))

    def load(self, name):
        path = self.workflow_path(name)
        payload = json.loads(path.read_text(encoding="utf-8"))
        workflow = WorkflowIR.from_artifact(payload)
        if workflow.name != name:
            raise ValueError(f"workflow artifact name mismatch: expected {name}, got {workflow.name}")
        return workflow

    def _write_json_atomic(self, path, payload):
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=str(path.parent),
            prefix=path.name + ".",
            suffix=".tmp",
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp_name = handle.name
        Path(temp_name).replace(path)


class StaticValidator:
    def validate(self, workflow):
        if workflow.name not in WORKFLOW_TEMPLATES:
            raise ValueError(f"unknown workflow: {workflow.name}")
        if not workflow.phases:
            raise ValueError("workflow phases are required")
        if workflow.round_budget <= 0 or workflow.tool_budget <= 0:
            raise ValueError("workflow budgets must be positive")
        if workflow.log_policy not in VALID_LOG_POLICIES:
            raise ValueError("raw logs must stay in evidence only")
        if workflow.write_policy not in VALID_WRITE_POLICIES:
            raise ValueError(f"unknown write policy: {workflow.write_policy}")
        allowed_tools = set(workflow.allowed_tools)
        completion_requirements = set(workflow.completion_requirements)
        if len(workflow.allowed_tools) != len(allowed_tools):
            raise ValueError("workflow allowed_tools must not contain duplicates")
        if len(workflow.completion_requirements) != len(completion_requirements):
            raise ValueError("workflow completion_requirements must not contain duplicates")
        if workflow.write_policy == "read_only":
            present = READ_ONLY_FORBIDDEN_TOOL_NAMES & allowed_tools
            if present:
                raise ValueError(f"read-only workflow allows risky tools: {sorted(present)}")
        if allowed_tools & LOG_TOOL_NAMES and workflow.log_policy != "raw_logs_to_evidence_only":
            raise ValueError("raw logs must stay in evidence only")
        for requirement in workflow.completion_requirements:
            if requirement not in VALID_COMPLETION_REQUIREMENTS:
                raise ValueError(f"unknown completion requirement: {requirement}")
        phase_by_requirement = {
            "verification": "verify",
            "audit": "audit",
            "handoff": "handoff",
        }
        for requirement, phase in phase_by_requirement.items():
            if requirement in completion_requirements and phase not in workflow.phases:
                raise ValueError(f"workflow requires {requirement} evidence but has no {phase} phase")
        if workflow.write_policy == "workspace_writes_allowed":
            missing = [
                requirement
                for requirement in ("diff", "verification", "audit", "handoff")
                if requirement not in completion_requirements
            ]
            if missing:
                if "audit" in missing:
                    raise ValueError(
                        "write-enabled workflow must require audit evidence to catch protected path risk before handoff"
                    )
                raise ValueError(
                    f"write-enabled workflow missing completion requirements: {missing}"
                )
        elif workflow.write_policy == "read_only":
            missing = [
                requirement
                for requirement in ("audit", "handoff")
                if requirement not in completion_requirements
            ]
            if missing:
                raise ValueError(f"read-only workflow missing completion requirements: {missing}")
        return workflow


@dataclass(frozen=True)
class WorkflowKernelState:
    workflow: str
    phase: str
    phase_history: tuple[str, ...]
    rounds_used: int
    tools_used: int
    status: str
    stop_reason: str | None = None

    def to_dict(self):
        return {
            "workflow": self.workflow,
            "phase": self.phase,
            "phase_history": list(self.phase_history),
            "rounds_used": self.rounds_used,
            "tools_used": self.tools_used,
            "status": self.status,
            "stop_reason": self.stop_reason,
        }

    @classmethod
    def from_dict(cls, data, workflow):
        if not isinstance(data, dict):
            raise ValueError("workflow kernel state must be a JSON object")
        required_fields = {
            "workflow",
            "phase",
            "phase_history",
            "rounds_used",
            "tools_used",
            "status",
            "stop_reason",
        }
        missing = sorted(required_fields - set(data))
        if missing:
            raise ValueError(f"workflow kernel state missing required fields: {missing}")
        unexpected = sorted(set(data) - required_fields)
        if unexpected:
            raise ValueError(f"workflow kernel state has unexpected fields: {unexpected}")

        StaticValidator().validate(workflow)
        workflow_name = _require_non_empty_string(data["workflow"], "workflow")
        if workflow_name != workflow.name:
            raise ValueError(f"workflow kernel state mismatch: expected {workflow.name}, got {workflow_name}")
        phase = _require_non_empty_string(data["phase"], "phase")
        if phase not in workflow.phases:
            raise ValueError(f"workflow kernel state phase {phase!r} is not in workflow {workflow.name}")
        phase_history = _require_string_tuple(data["phase_history"], "phase_history")
        if phase_history[-1] != phase:
            raise ValueError("workflow kernel state phase_history must end at current phase")
        _validate_phase_history(workflow, phase_history)
        status = _require_non_empty_string(data["status"], "status")
        if status not in VALID_KERNEL_STATUSES:
            raise ValueError(f"unknown workflow kernel status: {status}")
        stop_reason = data["stop_reason"]
        if stop_reason is not None and not isinstance(stop_reason, str):
            raise ValueError("workflow kernel state stop_reason must be a string or null")
        return cls(
            workflow=workflow_name,
            phase=phase,
            phase_history=phase_history,
            rounds_used=_require_non_negative_int(data["rounds_used"], "rounds_used"),
            tools_used=_require_non_negative_int(data["tools_used"], "tools_used"),
            status=status,
            stop_reason=stop_reason,
        )


class WorkflowKernel:
    def __init__(self, workflow, state=None):
        self.workflow = StaticValidator().validate(workflow)
        if state is None:
            state = WorkflowKernelState(
                workflow=self.workflow.name,
                phase=self.workflow.phases[0],
                phase_history=(self.workflow.phases[0],),
                rounds_used=0,
                tools_used=0,
                status="active",
                stop_reason=None,
            )
        elif isinstance(state, dict):
            state = WorkflowKernelState.from_dict(state, self.workflow)
        elif not isinstance(state, WorkflowKernelState):
            raise TypeError("workflow kernel state must be a WorkflowKernelState or dict")
        self._state = WorkflowKernelState.from_dict(state.to_dict(), self.workflow)

    @property
    def state(self):
        return self._state

    def to_dict(self):
        return self._state.to_dict()

    def transition(self, next_phase):
        next_phase = _require_non_empty_string(next_phase, "next_phase")
        if self._state.status != "active":
            raise ValueError(f"cannot transition workflow in {self._state.status} state")
        current_phase = self._state.phase
        if not _phase_transition_allowed(self.workflow, current_phase, next_phase):
            current_index = self.workflow.phases.index(current_phase)
            expected = self.workflow.phases[current_index + 1] if current_index + 1 < len(self.workflow.phases) else "<terminal>"
            raise ValueError(
                f"illegal phase transition for workflow {self.workflow.name}: "
                f"{current_phase} -> {next_phase}; expected {expected}"
            )
        status = "handoff" if next_phase == "handoff" else "active"
        self._state = WorkflowKernelState(
            workflow=self._state.workflow,
            phase=next_phase,
            phase_history=self._state.phase_history + (next_phase,),
            rounds_used=self._state.rounds_used,
            tools_used=self._state.tools_used,
            status=status,
            stop_reason=self._state.stop_reason,
        )
        return self._state

    def record_round(self, count=1):
        count = _require_positive_int(count, "count")
        return self._consume_budget("rounds_used", count, self.workflow.round_budget, "round_budget_exceeded")

    def record_tool(self, count=1):
        count = _require_positive_int(count, "count")
        return self._consume_budget("tools_used", count, self.workflow.tool_budget, "tool_budget_exceeded")

    def block(self, stop_reason):
        stop_reason = _require_non_empty_string(stop_reason, "stop_reason")
        self._state = WorkflowKernelState(
            workflow=self._state.workflow,
            phase=self._state.phase,
            phase_history=self._state.phase_history,
            rounds_used=self._state.rounds_used,
            tools_used=self._state.tools_used,
            status="blocked",
            stop_reason=stop_reason,
        )
        return self._state

    def _consume_budget(self, field_name, count, budget, stop_reason):
        if self._state.status == "blocked":
            raise ValueError("cannot consume budget for a blocked workflow")
        rounds_used = self._state.rounds_used
        tools_used = self._state.tools_used
        if field_name == "rounds_used":
            rounds_used += count
            new_value = rounds_used
        elif field_name == "tools_used":
            tools_used += count
            new_value = tools_used
        else:
            raise ValueError(f"unknown budget field: {field_name}")

        status = self._state.status
        phase = self._state.phase
        phase_history = self._state.phase_history
        if new_value > budget:
            phase, phase_history, status = self._force_terminal_stop()
        self._state = WorkflowKernelState(
            workflow=self._state.workflow,
            phase=phase,
            phase_history=phase_history,
            rounds_used=rounds_used,
            tools_used=tools_used,
            status=status,
            stop_reason=stop_reason if new_value > budget else self._state.stop_reason,
        )
        return self._state

    def _force_terminal_stop(self):
        if self._state.phase == "handoff":
            return "handoff", self._state.phase_history, "blocked"
        if "handoff" not in self.workflow.phases:
            return self._state.phase, self._state.phase_history, "blocked"
        if self._state.phase_history[-1] == "handoff":
            return "handoff", self._state.phase_history, "blocked"
        return "handoff", self._state.phase_history + ("handoff",), "handoff"


@dataclass(frozen=True)
class TaskPacketWorkflowState:
    name: str
    phases: tuple[str, ...]
    write_policy: str
    log_policy: str
    completion_requirements: tuple[str, ...]
    round_budget: int
    tool_budget: int
    current_phase: str
    status: str
    phase_history: tuple[str, ...]

    def to_dict(self):
        return {
            "name": self.name,
            "phases": list(self.phases),
            "write_policy": self.write_policy,
            "log_policy": self.log_policy,
            "completion_requirements": list(self.completion_requirements),
            "round_budget": self.round_budget,
            "tool_budget": self.tool_budget,
            "current_phase": self.current_phase,
            "status": self.status,
            "phase_history": list(self.phase_history),
        }

    def to_workflow_ir(self):
        return WorkflowIR(
            name=self.name,
            phases=self.phases,
            allowed_tools=workflow_template(self.name).allowed_tools,
            write_policy=self.write_policy,
            log_policy=self.log_policy,
            completion_requirements=self.completion_requirements,
            round_budget=self.round_budget,
            tool_budget=self.tool_budget,
        )

    @classmethod
    def from_workflow(cls, workflow, kernel_state):
        return cls(
            name=workflow.name,
            phases=workflow.phases,
            write_policy=workflow.write_policy,
            log_policy=workflow.log_policy,
            completion_requirements=workflow.completion_requirements,
            round_budget=workflow.round_budget,
            tool_budget=workflow.tool_budget,
            current_phase=kernel_state.phase,
            status=kernel_state.status,
            phase_history=kernel_state.phase_history,
        )

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("task packet workflow_state must be a JSON object")
        required_fields = {
            "name",
            "phases",
            "write_policy",
            "log_policy",
            "completion_requirements",
            "round_budget",
            "tool_budget",
            "current_phase",
            "status",
            "phase_history",
        }
        missing = sorted(required_fields - set(data))
        if missing:
            raise ValueError(f"task packet workflow_state missing required fields: {missing}")
        unexpected = sorted(set(data) - required_fields)
        if unexpected:
            raise ValueError(f"task packet workflow_state has unexpected fields: {unexpected}")
        state = cls(
            name=_require_non_empty_string(data["name"], "name"),
            phases=_require_string_tuple(data["phases"], "phases"),
            write_policy=_require_non_empty_string(data["write_policy"], "write_policy"),
            log_policy=_require_non_empty_string(data["log_policy"], "log_policy"),
            completion_requirements=_require_string_tuple(data["completion_requirements"], "completion_requirements"),
            round_budget=_require_positive_int(data["round_budget"], "round_budget"),
            tool_budget=_require_positive_int(data["tool_budget"], "tool_budget"),
            current_phase=_require_non_empty_string(data["current_phase"], "current_phase"),
            status=_require_non_empty_string(data["status"], "status"),
            phase_history=_require_string_tuple(data["phase_history"], "phase_history"),
        )
        workflow = state.to_workflow_ir()
        StaticValidator().validate(workflow)
        if state.current_phase not in workflow.phases:
            raise ValueError(f"task packet workflow_state phase {state.current_phase!r} is not in workflow {state.name}")
        if state.status not in VALID_KERNEL_STATUSES:
            raise ValueError(f"unknown task packet workflow_state status: {state.status}")
        return state


@dataclass(frozen=True)
class TaskPacketEvidenceBrief:
    evidence_id: str
    record_type: str
    brief: str

    def to_dict(self):
        return {
            "evidence_id": self.evidence_id,
            "record_type": self.record_type,
            "brief": self.brief,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("task packet evidence_brief must be a JSON object")
        required_fields = {"evidence_id", "record_type", "brief"}
        missing = sorted(required_fields - set(data))
        if missing:
            raise ValueError(f"task packet evidence_brief missing required fields: {missing}")
        unexpected = sorted(set(data) - required_fields)
        if unexpected:
            raise ValueError(f"task packet evidence_brief has unexpected fields: {unexpected}")
        return cls(
            evidence_id=_require_non_empty_string(data["evidence_id"], "evidence_id"),
            record_type=_require_non_empty_string(data["record_type"], "record_type"),
            brief=_require_non_empty_string(data["brief"], "brief"),
        )


@dataclass(frozen=True)
class TaskPacketSkillConstraint:
    skill_id: str
    steps: tuple[str, ...]
    verification: tuple[str, ...]

    def to_dict(self):
        return {
            "skill_id": self.skill_id,
            "steps": list(self.steps),
            "verification": list(self.verification),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("task packet active_skill_constraint must be a JSON object")
        required_fields = {"skill_id", "steps", "verification"}
        missing = sorted(required_fields - set(data))
        if missing:
            raise ValueError(f"task packet active_skill_constraint missing required fields: {missing}")
        unexpected = sorted(set(data) - required_fields)
        if unexpected:
            raise ValueError(f"task packet active_skill_constraint has unexpected fields: {unexpected}")
        return cls(
            skill_id=_require_non_empty_string(data["skill_id"], "skill_id"),
            steps=_require_string_tuple(data["steps"], "steps"),
            verification=_require_string_tuple(data["verification"], "verification"),
        )


@dataclass(frozen=True)
class TaskPacket:
    schema_version: str
    user_intent: str
    workflow: str
    phase: str
    workflow_state: TaskPacketWorkflowState
    kernel_state: WorkflowKernelState
    allowed_tools: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    evidence_briefs: tuple[TaskPacketEvidenceBrief, ...]
    active_skill_ids: tuple[str, ...]
    active_skill_constraints: tuple[TaskPacketSkillConstraint, ...]
    prompt_context: str

    def to_dict(self):
        return {
            "schema_version": self.schema_version,
            "user_intent": self.user_intent,
            "workflow": self.workflow,
            "phase": self.phase,
            "workflow_state": self.workflow_state.to_dict(),
            "kernel_state": self.kernel_state.to_dict(),
            "allowed_tools": list(self.allowed_tools),
            "evidence_refs": list(self.evidence_refs),
            "evidence_briefs": [item.to_dict() for item in self.evidence_briefs],
            "active_skill_ids": list(self.active_skill_ids),
            "active_skill_constraints": [item.to_dict() for item in self.active_skill_constraints],
            "prompt_context": self.prompt_context,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("task packet must be a JSON object")
        required_fields = {
            "schema_version",
            "user_intent",
            "workflow",
            "phase",
            "workflow_state",
            "kernel_state",
            "allowed_tools",
            "evidence_refs",
            "evidence_briefs",
            "active_skill_ids",
            "active_skill_constraints",
            "prompt_context",
        }
        missing = sorted(required_fields - set(data))
        if missing:
            raise ValueError(f"task packet missing required fields: {missing}")
        unexpected = sorted(set(data) - required_fields)
        if unexpected:
            raise ValueError(f"task packet has unexpected fields: {unexpected}")
        schema_version = _require_non_empty_string(data["schema_version"], "schema_version")
        if schema_version != TASK_PACKET_SCHEMA_VERSION:
            raise ValueError(
                f"task packet schema_version mismatch: expected {TASK_PACKET_SCHEMA_VERSION}, got {schema_version!r}"
            )
        workflow_state = TaskPacketWorkflowState.from_dict(data["workflow_state"])
        workflow = workflow_state.to_workflow_ir()
        kernel_state = WorkflowKernelState.from_dict(data["kernel_state"], workflow)
        workflow_name = _require_non_empty_string(data["workflow"], "workflow")
        if workflow_name != workflow.name:
            raise ValueError("task packet workflow must match workflow_state name")
        phase = _require_non_empty_string(data["phase"], "phase")
        if phase != kernel_state.phase:
            raise ValueError("task packet phase must match kernel_state phase")
        if phase != workflow_state.current_phase:
            raise ValueError("task packet phase must match workflow_state current_phase")
        _validate_task_packet_state_alignment(workflow_state, kernel_state)
        allowed_tools = _require_string_tuple(data["allowed_tools"], "allowed_tools")
        expected_allowed_tools = _phase_allowed_tools(workflow, phase)
        if allowed_tools != expected_allowed_tools:
            raise ValueError(
                "task packet allowed_tools must match current phase tool policy: "
                f"expected {list(expected_allowed_tools)}, got {list(allowed_tools)}"
            )
        evidence_refs = _require_string_tuple_allow_empty(data["evidence_refs"], "evidence_refs")
        evidence_briefs = tuple(TaskPacketEvidenceBrief.from_dict(item) for item in data["evidence_briefs"])
        active_skill_ids = _require_string_tuple_allow_empty(data["active_skill_ids"], "active_skill_ids")
        active_skill_constraints = tuple(TaskPacketSkillConstraint.from_dict(item) for item in data["active_skill_constraints"])
        constraint_ids = tuple(item.skill_id for item in active_skill_constraints)
        if constraint_ids != active_skill_ids:
            raise ValueError("task packet active_skill_constraints must align with active_skill_ids")
        for evidence_brief in evidence_briefs:
            if evidence_brief.evidence_id not in evidence_refs:
                raise ValueError("task packet evidence_briefs must reference evidence_refs entries")
        for tool_name in allowed_tools:
            if tool_name not in workflow.allowed_tools:
                raise ValueError(f"task packet allowed tool {tool_name!r} is not in workflow {workflow.name}")
        return cls(
            schema_version=schema_version,
            user_intent=_require_non_empty_string(data["user_intent"], "user_intent"),
            workflow=workflow_name,
            phase=phase,
            workflow_state=workflow_state,
            kernel_state=kernel_state,
            allowed_tools=allowed_tools,
            evidence_refs=evidence_refs,
            evidence_briefs=evidence_briefs,
            active_skill_ids=active_skill_ids,
            active_skill_constraints=active_skill_constraints,
            prompt_context=_require_non_empty_string(data["prompt_context"], "prompt_context"),
        )


class TaskPacketCompiler:
    def __init__(self, skill_store=None):
        self.skill_store = skill_store

    def compile(self, user_intent, workflow, kernel=None, evidence_store=None, paths=()):
        StaticValidator().validate(workflow)
        kernel_state = _coerce_kernel_state(workflow, kernel)
        workflow_state = TaskPacketWorkflowState.from_workflow(workflow, kernel_state)
        allowed_tools = _phase_allowed_tools(workflow, kernel_state.phase)
        records = _sorted_evidence_records(evidence_store.records() if evidence_store is not None else [])
        evidence_refs = tuple(record.evidence_id for record in records)
        active_skill_ids = ()
        active_skill_constraints = ()
        if self.skill_store is not None:
            from .skills import SkillCompiler

            compiled_skills = SkillCompiler(self.skill_store).compile_for_task(
                user_intent,
                workflow=workflow.name,
                paths=paths,
            )
            active_skill_ids = tuple(compiled_skills["active_skill_ids"])
            active_skill_constraints = tuple(
                TaskPacketSkillConstraint(
                    skill_id=item["skill_id"],
                    steps=tuple(item["steps"]),
                    verification=tuple(item["verification"]),
                )
                for item in compiled_skills["skill_constraints"]
            )
        evidence_briefs = tuple(
            TaskPacketEvidenceBrief(
                evidence_id=record.evidence_id,
                record_type=record.record_type,
                brief=_evidence_brief(record),
            )
            for record in records
        )
        prompt_context = _render_task_packet_prompt_context(
            user_intent=user_intent,
            workflow_state=workflow_state,
            kernel_state=kernel_state,
            allowed_tools=allowed_tools,
            evidence_briefs=evidence_briefs,
            active_skill_constraints=active_skill_constraints,
        )
        return TaskPacket(
            schema_version=TASK_PACKET_SCHEMA_VERSION,
            user_intent=user_intent,
            workflow=workflow.name,
            phase=kernel_state.phase,
            workflow_state=workflow_state,
            kernel_state=kernel_state,
            allowed_tools=allowed_tools,
            evidence_refs=evidence_refs,
            evidence_briefs=evidence_briefs,
            active_skill_ids=active_skill_ids,
            active_skill_constraints=active_skill_constraints,
            prompt_context=prompt_context,
        )


PHASE_ALLOWED_TOOL_NAMES = {
    "repo_audit": {
        "intake": ("list_files", "read_file", "search"),
        "investigate": ("list_files", "read_file", "search", "log_brief", "log_failure_detail"),
        "audit": ("list_files", "read_file", "search", "log_brief", "log_failure_detail"),
        "handoff": ("read_file", "search", "log_brief"),
    },
    "code_change": {
        "intake": ("list_files", "read_file", "search"),
        "plan_compile": ("list_files", "read_file", "search", "delegate"),
        "implement": (
            "list_files",
            "read_file",
            "search",
            "run_shell",
            "write_file",
            "patch_file",
            "delegate",
            "log_run",
            "log_brief",
            "log_failure_detail",
        ),
        "verify": ("list_files", "read_file", "search", "run_shell", "log_run", "log_brief", "log_failure_detail"),
        "audit": ("list_files", "read_file", "search", "delegate", "log_brief", "log_failure_detail"),
        "skill_distill": ("read_file", "search", "log_brief", "log_failure_detail"),
        "handoff": ("read_file", "search", "log_brief"),
    },
    "test_fix": {
        "intake": ("list_files", "read_file", "search", "log_brief", "log_failure_detail"),
        "investigate": ("list_files", "read_file", "search", "run_shell", "log_run", "log_brief", "log_failure_detail"),
        "implement": (
            "list_files",
            "read_file",
            "search",
            "run_shell",
            "write_file",
            "patch_file",
            "log_run",
            "log_brief",
            "log_failure_detail",
        ),
        "verify": ("list_files", "read_file", "search", "run_shell", "log_run", "log_brief", "log_failure_detail"),
        "audit": ("list_files", "read_file", "search", "log_brief", "log_failure_detail"),
        "skill_distill": ("read_file", "search", "log_brief", "log_failure_detail"),
        "handoff": ("read_file", "search", "log_brief"),
    },
}


def _coerce_kernel_state(workflow, kernel):
    if kernel is None:
        return WorkflowKernel(workflow).state
    if isinstance(kernel, WorkflowKernel):
        if kernel.workflow.name != workflow.name:
            raise ValueError(f"workflow kernel mismatch: expected {workflow.name}, got {kernel.workflow.name}")
        return kernel.state
    if isinstance(kernel, WorkflowKernelState):
        return WorkflowKernelState.from_dict(kernel.to_dict(), workflow)
    if isinstance(kernel, dict):
        return WorkflowKernelState.from_dict(kernel, workflow)
    raise TypeError("task packet compiler kernel must be a WorkflowKernel, WorkflowKernelState, dict, or None")


def _phase_allowed_tools(workflow, phase):
    try:
        phase_tools = PHASE_ALLOWED_TOOL_NAMES[workflow.name][phase]
    except KeyError as exc:
        raise ValueError(f"missing task packet tool policy for workflow {workflow.name} phase {phase}") from exc
    invalid = [tool_name for tool_name in phase_tools if tool_name not in workflow.allowed_tools]
    if invalid:
        raise ValueError(f"task packet tool policy exposes tools outside workflow {workflow.name}: {invalid}")
    return tuple(phase_tools)


def _validate_task_packet_state_alignment(workflow_state, kernel_state):
    mismatches = []
    if workflow_state.current_phase != kernel_state.phase:
        mismatches.append(f"phase: workflow_state={workflow_state.current_phase!r}, kernel_state={kernel_state.phase!r}")
    if workflow_state.status != kernel_state.status:
        mismatches.append(f"status: workflow_state={workflow_state.status!r}, kernel_state={kernel_state.status!r}")
    if workflow_state.phase_history != kernel_state.phase_history:
        mismatches.append(
            f"phase_history: workflow_state={list(workflow_state.phase_history)!r}, "
            f"kernel_state={list(kernel_state.phase_history)!r}"
        )
    if workflow_state.name != kernel_state.workflow:
        mismatches.append(f"workflow: workflow_state={workflow_state.name!r}, kernel_state={kernel_state.workflow!r}")
    if mismatches:
        raise ValueError(
            "task packet workflow_state must align with kernel_state current status: " + "; ".join(mismatches)
        )


def _sorted_evidence_records(records):
    return sorted(records, key=lambda record: (record.raw, record.record_type, record.evidence_id))


def _evidence_brief(record):
    payload = dict(record.payload)
    if record.raw:
        for field_name in ("parsed_summary", "status"):
            value = payload.get(field_name)
            if value:
                return str(value)
        return record.record_type
    for field_name in ("summary", "brief", "status", "command"):
        value = payload.get(field_name)
        if isinstance(value, (list, tuple)):
            value = " ".join(str(item) for item in value)
        if value:
            return str(value)
    return record.record_type


def _render_task_packet_prompt_context(
    *,
    user_intent,
    workflow_state,
    kernel_state,
    allowed_tools,
    evidence_briefs,
    active_skill_constraints,
):
    lines = [
        f"User intent: {user_intent}",
        f"Workflow: {workflow_state.name}",
        f"Phase: {kernel_state.phase}",
        f"Workflow status: {kernel_state.status}",
        f"Phase history: {', '.join(kernel_state.phase_history)}",
        f"Budgets used: rounds {kernel_state.rounds_used}/{workflow_state.round_budget}, tools {kernel_state.tools_used}/{workflow_state.tool_budget}",
        "Allowed tools:",
        *([f"- {tool_name}" for tool_name in allowed_tools] or ["- none"]),
        "Evidence briefs:",
        *([f"- {item.evidence_id} ({item.record_type}): {item.brief}" for item in evidence_briefs] or ["- none"]),
        "Active skills:",
    ]
    if active_skill_constraints:
        for item in active_skill_constraints:
            lines.append(f"- {item.skill_id}")
            lines.extend(f"  step: {step}" for step in item.steps)
            lines.extend(f"  verify: {check}" for check in item.verification)
    else:
        lines.append("- none")
    return "\n".join(lines)


class CompletionGate:
    def __init__(self, workflow):
        self.workflow = workflow

    def evaluate(self, records, task_contract=None, current_manifest=None):
        records = tuple(records)
        by_type = {record.record_type: record for record in records}
        missing = []
        invalid = []
        contract_view = task_contract.b05_view() if task_contract is not None else None
        for requirement in self.workflow.completion_requirements:
            record = by_type.get(requirement)
            if record is None:
                missing.append(requirement)
                continue
            if requirement == "verification":
                if contract_view is None:
                    status = str(record.payload.get("status", "")).strip()
                    if status not in {"passed", "pass"}:
                        invalid.append(f"verification evidence status={status or 'missing'}")
                else:
                    result, reasons = evaluate_verification_payload(
                        record.payload,
                        contract_view,
                        current_manifest=current_manifest,
                        records=records,
                        verification_record=record,
                    )
                    if result != RESULT_PASS:
                        detail = "; ".join(reasons) if reasons else result
                        invalid.append(f"verification evidence result={result}: {detail}")
            if requirement == "audit":
                status = str(record.payload.get("status", "")).strip()
                if status not in AUDIT_ACCEPTED_STATUSES:
                    invalid.append(f"audit evidence status={status or 'missing'}")
                if status == "concerns":
                    concerns = record.payload.get("concerns")
                    if not isinstance(concerns, list) or not any(str(item).strip() for item in concerns):
                        invalid.append("audit evidence concerns status requires at least one recorded concern")
        return CompletionGateResult(
            allowed=not missing and not invalid,
            missing=tuple(missing),
            invalid=tuple(invalid),
            evidence_refs=tuple(record.evidence_id for record in records),
        )

    def can_complete(self, records, task_contract=None, current_manifest=None):
        return self.evaluate(records, task_contract=task_contract, current_manifest=current_manifest).allowed


@dataclass(frozen=True)
class CompletionGateResult:
    allowed: bool
    missing: tuple[str, ...]
    invalid: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def failure_message(self):
        issues = []
        if self.missing:
            issues.append(f"missing {', '.join(self.missing)} evidence")
        issues.extend(self.invalid)
        return "error: completion gate blocked; " + "; ".join(issues)


@dataclass(frozen=True)
class HandoffArtifact:
    completed: tuple[str, ...]
    open_items: tuple[str, ...]
    risks: tuple[str, ...]
    next_phase: str
    evidence_refs: tuple[str, ...]

    def to_dict(self):
        return {
            "completed": list(self.completed),
            "open_items": list(self.open_items),
            "risks": list(self.risks),
            "next_phase": self.next_phase,
            "evidence_refs": list(self.evidence_refs),
        }


def _file_fingerprint(path):
    path = Path(path)
    if not path.exists():
        return {"path": str(path), "exists": False, "sha256": ""}
    return {
        "path": str(path),
        "exists": True,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


@dataclass(frozen=True)
class FreshnessGuard:
    root: str
    files: tuple[dict, ...]

    @classmethod
    def capture(cls, root, files):
        return cls(str(Path(root).resolve()), tuple(_file_fingerprint(path) for path in files))

    def check(self):
        stale = []
        for item in self.files:
            current = _file_fingerprint(item["path"])
            if current != item:
                stale.append(item["path"])
        return {"status": "stale" if stale else "fresh", "stale_paths": stale}

    def write(self, path):
        Path(path).write_text(json.dumps({"root": self.root, "files": list(self.files)}, indent=2), encoding="utf-8")
