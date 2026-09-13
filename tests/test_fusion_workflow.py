import json
from dataclasses import replace
from pathlib import Path

import pytest
import skillforge as mini_pkg
import skillforge.runtime as runtime_mod
from skillforge import FakeModelClient, MiniAgent, SessionStore, WorkspaceContext
from skillforge.audit import AuditSubagent, audit_code_change
from skillforge.evidence import EvidenceStore, log_brief, log_failure_detail, log_run
from skillforge.skills import PromotionGate, SkillCard, SkillCandidate, SkillCompiler, SkillDistiller, SkillMatcher, SkillStore
from skillforge.workflow import (
    CompletionGate,
    FreshnessGuard,
    HandoffArtifact,
    StaticValidator,
    TaskPacket,
    TaskPacketCompiler,
    TaskPacketSkillConstraint,
    WORKFLOW_IR_SCHEMA_VERSION,
    WorkflowKernel,
    WorkflowKernelState,
    WorkflowIR,
    WorkflowArtifactStore,
    workflow_template,
)


def build_workflow_workspace(tmp_path):
    (tmp_path / "README.md").write_text("workflow fixture\n", encoding="utf-8")
    return WorkspaceContext.build(tmp_path)


def build_workflow_agent(tmp_path, outputs, **kwargs):
    workspace = build_workflow_workspace(tmp_path)
    store = SessionStore(tmp_path / ".skillforge" / "sessions")
    approval_policy = kwargs.pop("approval_policy", "auto")
    return MiniAgent(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=store,
        approval_policy=approval_policy,
        **kwargs,
    )


def load_evidence_index(run_dir):
    return json.loads((Path(run_dir) / "evidence" / "index.json").read_text(encoding="utf-8"))


def test_workflow_templates_validate_policies_and_budget():
    repo_audit = workflow_template("repo_audit")
    code_change = workflow_template("code_change")
    test_fix = workflow_template("test_fix")

    assert repo_audit.write_policy == "read_only"
    assert "run_shell" not in repo_audit.allowed_tools
    assert "log_run" not in repo_audit.allowed_tools
    assert not any(tool in repo_audit.allowed_tools for tool in {"write_file", "patch_file"})
    assert code_change.completion_requirements == ("diff", "verification", "audit", "handoff")
    assert test_fix.log_policy == "raw_logs_to_evidence_only"

    StaticValidator().validate(repo_audit)
    StaticValidator().validate(code_change)
    StaticValidator().validate(test_fix)


def test_workflow_ir_schema_is_versioned_and_serializable():
    workflow = workflow_template("code_change")

    artifact = workflow.to_artifact()

    assert artifact["schema_version"] == WORKFLOW_IR_SCHEMA_VERSION
    assert artifact["artifact_type"] == "workflow_ir"
    assert artifact["name"] == "code_change"
    assert artifact["phases"][-1] == "handoff"
    assert artifact["allowed_tools"][-1] == "log_failure_detail"


def test_workflow_ir_artifact_store_writes_under_skillforge_and_loads_validated_round_trip(tmp_path):
    store = WorkflowArtifactStore(tmp_path / ".skillforge" / "workflows")

    written_path = store.write(workflow_template("repo_audit"))
    loaded = store.load("repo_audit")

    assert written_path == tmp_path / ".skillforge" / "workflows" / "repo_audit.json"
    assert written_path.exists()
    payload = json.loads(written_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == WORKFLOW_IR_SCHEMA_VERSION
    assert payload["write_policy"] == "read_only"
    assert loaded == workflow_template("repo_audit")


def test_workflow_ir_artifact_store_rejects_schema_mismatch(tmp_path):
    store = WorkflowArtifactStore(tmp_path / ".skillforge" / "workflows")
    artifact_path = store.workflow_path("test_fix")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(
            {
                **workflow_template("test_fix").to_artifact(),
                "schema_version": "legacy-v0",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        store.load("test_fix")
    except ValueError as exc:
        assert "schema_version" in str(exc)
    else:
        raise AssertionError("expected schema mismatch to raise ValueError")


def test_static_validator_rejects_write_enabled_workflows_missing_completion_evidence_requirements():
    validator = StaticValidator()
    code_change = workflow_template("code_change")

    for requirements, expected in (
        (("diff", "audit", "handoff"), "verification"),
        (("verification", "audit", "handoff"), "diff"),
    ):
        try:
            validator.validate(replace(code_change, completion_requirements=requirements))
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError(f"expected missing {expected} requirement to fail validation")


def test_static_validator_rejects_invalid_log_policy_and_write_policy():
    validator = StaticValidator()
    code_change = workflow_template("code_change")

    try:
        validator.validate(replace(code_change, write_policy="full_access"))
    except ValueError as exc:
        assert "write policy" in str(exc)
    else:
        raise AssertionError("expected invalid write policy to fail validation")

    try:
        validator.validate(replace(code_change, log_policy="inline_prompt"))
    except ValueError as exc:
        assert "raw logs" in str(exc)
    else:
        raise AssertionError("expected invalid log policy to fail validation")

    payload = code_change.to_dict()
    del payload["log_policy"]
    try:
        WorkflowIR.from_dict(payload)
    except ValueError as exc:
        assert "log_policy" in str(exc)
    else:
        raise AssertionError("expected missing log_policy to fail schema validation")


def test_static_validator_rejects_read_only_write_tools_and_protected_path_risk():
    validator = StaticValidator()
    repo_audit = workflow_template("repo_audit")
    code_change = workflow_template("code_change")

    try:
        validator.validate(replace(repo_audit, allowed_tools=repo_audit.allowed_tools + ("write_file",)))
    except ValueError as exc:
        assert "risky tools" in str(exc)
        assert "write_file" in str(exc)
    else:
        raise AssertionError("expected read-only workflow with write tool to fail validation")

    try:
        validator.validate(replace(repo_audit, allowed_tools=repo_audit.allowed_tools + ("run_shell",)))
    except ValueError as exc:
        assert "run_shell" in str(exc)
    else:
        raise AssertionError("expected read-only workflow with shell access to fail validation")

    try:
        validator.validate(replace(code_change, completion_requirements=("diff", "verification", "handoff")))
    except ValueError as exc:
        assert "protected path" in str(exc)
    else:
        raise AssertionError("expected missing audit requirement to fail validation")


def test_repo_audit_task_packet_does_not_expose_shell_execution():
    workflow = workflow_template("repo_audit")
    kernel = WorkflowKernel(workflow)
    kernel.transition("investigate")
    kernel.transition("audit")

    packet = TaskPacketCompiler().compile(
        user_intent="audit the repository",
        workflow=workflow,
        kernel=kernel,
    )

    assert "run_shell" not in packet.allowed_tools
    assert "log_run" not in packet.allowed_tools
    assert "write_file" not in packet.allowed_tools
    assert "patch_file" not in packet.allowed_tools


def test_repo_audit_cannot_use_log_run_to_write_workspace(tmp_path):
    agent = build_workflow_agent(tmp_path, [], workflow="repo_audit")
    agent.workflow_kernel.transition("investigate")

    result = agent.run_tool(
        "log_run",
        {
            "command": "python3 -c \"from pathlib import Path; Path('escape.txt').write_text('written')\"",
            "timeout": 5,
        },
    )

    assert "error: tool log_run is not allowed in workflow repo_audit phase investigate" in result
    assert not (tmp_path / "escape.txt").exists()


def test_task_packet_schema_is_serializable_and_round_trips_current_kernel_state(tmp_path):
    store = SkillStore(tmp_path / ".skillforge" / "skills")
    store.save_active(
        SkillCard(
            skill_id="pytest-failure-triage",
            title="Pytest failure triage",
            triggers=("pytest",),
            workflow_tags=("test_fix",),
            file_patterns=("tests/*.py",),
            steps=("Run pytest through log_run.", "Inspect the first failure before editing."),
            verification=("Re-run the narrowest failing target.",),
        )
    )
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")
    raw_log_path = evidence.write_raw_log("secret raw log")
    raw = evidence.add(
        "log",
        {
            "raw_log_path": str(raw_log_path),
            "status": "failed",
            "parsed_summary": "1 failed, 3 passed",
            "failure_count": 1,
            "failures": ["tests/test_app.py: assert 1 == 2"],
        },
        raw=True,
    )
    evidence.add("diff", {"summary": "patched config precedence"})

    workflow = workflow_template("test_fix")
    kernel = WorkflowKernel(workflow)
    kernel.transition("investigate")
    kernel.record_round(2)
    kernel.record_tool(3)

    packet = TaskPacketCompiler(skill_store=store).compile(
        user_intent="fix failing pytest",
        workflow=workflow,
        kernel=kernel,
        evidence_store=evidence,
        paths=("tests/test_app.py",),
    )

    payload = packet.to_dict()
    assert json.loads(json.dumps(payload))["workflow"] == "test_fix"
    assert payload["phase"] == "investigate"
    assert payload["workflow_state"]["name"] == "test_fix"
    assert payload["workflow_state"]["phases"] == list(workflow.phases)
    assert payload["kernel_state"]["phase"] == "investigate"
    assert payload["kernel_state"]["rounds_used"] == 2
    assert payload["kernel_state"]["tools_used"] == 3
    assert raw.evidence_id in payload["evidence_refs"]
    assert payload["evidence_briefs"][0]["brief"] == "patched config precedence"
    assert payload["evidence_briefs"][1]["brief"] == "1 failed, 3 passed"
    assert "secret raw log" not in payload["prompt_context"]
    assert payload["active_skill_ids"] == ["pytest-failure-triage"]
    assert payload["active_skill_constraints"] == [
        {
            "skill_id": "pytest-failure-triage",
            "steps": ["Run pytest through log_run.", "Inspect the first failure before editing."],
            "verification": ["Re-run the narrowest failing target."],
        }
    ]

    restored = TaskPacket.from_dict(payload)
    assert restored == packet


def test_task_packet_from_dict_rejects_tools_outside_current_phase_policy():
    workflow = workflow_template("code_change")
    kernel = WorkflowKernel(workflow)
    kernel.transition("plan_compile")
    packet = TaskPacketCompiler().compile(
        user_intent="change the config loader",
        workflow=workflow,
        kernel=kernel,
    )

    payload = packet.to_dict()
    payload["allowed_tools"].append("patch_file")

    try:
        TaskPacket.from_dict(payload)
    except ValueError as exc:
        assert "phase tool policy" in str(exc)
        assert "patch_file" in str(exc)
    else:
        raise AssertionError("expected packet with tampered phase tools to fail validation")


def test_task_packet_from_dict_rejects_workflow_and_kernel_state_drift():
    workflow = workflow_template("test_fix")
    kernel = WorkflowKernel(workflow)
    kernel.transition("investigate")
    packet = TaskPacketCompiler().compile(
        user_intent="fix failing pytest",
        workflow=workflow,
        kernel=kernel,
    )

    payload = packet.to_dict()
    payload["workflow_state"]["phase_history"] = ["intake"]

    try:
        TaskPacket.from_dict(payload)
    except ValueError as exc:
        assert "workflow_state" in str(exc)
        assert "kernel_state" in str(exc)
    else:
        raise AssertionError("expected packet with drifted workflow state to fail validation")


def test_task_packet_compiler_restricts_allowed_tools_by_current_phase():
    workflow = workflow_template("code_change")
    kernel = WorkflowKernel(workflow)
    compiler = TaskPacketCompiler()

    intake_packet = compiler.compile(
        user_intent="change the config loader",
        workflow=workflow,
        kernel=kernel,
    )
    assert intake_packet.phase == "intake"
    assert set(intake_packet.allowed_tools) == {"list_files", "read_file", "search"}

    kernel.transition("plan_compile")
    plan_packet = compiler.compile(
        user_intent="change the config loader",
        workflow=workflow,
        kernel=kernel,
    )
    assert plan_packet.phase == "plan_compile"
    assert "delegate" in plan_packet.allowed_tools
    assert "patch_file" not in plan_packet.allowed_tools
    assert "run_shell" not in plan_packet.allowed_tools

    kernel.transition("implement")
    implement_packet = compiler.compile(
        user_intent="change the config loader",
        workflow=workflow,
        kernel=kernel,
    )
    assert "patch_file" in implement_packet.allowed_tools
    assert "write_file" in implement_packet.allowed_tools
    assert "run_shell" in implement_packet.allowed_tools

    kernel.transition("verify")
    verify_packet = compiler.compile(
        user_intent="change the config loader",
        workflow=workflow,
        kernel=kernel,
    )
    assert verify_packet.phase == "verify"
    assert "run_shell" in verify_packet.allowed_tools
    assert "log_run" in verify_packet.allowed_tools
    assert "patch_file" not in verify_packet.allowed_tools
    assert "write_file" not in verify_packet.allowed_tools


def test_workflow_kernel_advances_all_templates_in_declared_phase_order():
    for workflow_name in ("repo_audit", "code_change", "test_fix"):
        workflow = workflow_template(workflow_name)
        kernel = WorkflowKernel(workflow)

        assert kernel.state.phase == workflow.phases[0]
        assert kernel.state.status == "active"

        for phase in workflow.phases[1:]:
            kernel.transition(phase)

        assert kernel.state.phase == "handoff"
        assert kernel.state.phase_history == workflow.phases
        assert kernel.state.status == "handoff"


def test_workflow_kernel_rejects_illegal_phase_transition():
    kernel = WorkflowKernel(workflow_template("code_change"))

    try:
        kernel.transition("implement")
    except ValueError as exc:
        assert "illegal phase transition" in str(exc)
        assert "plan_compile" in str(exc)
    else:
        raise AssertionError("expected illegal workflow transition to fail fast")


def test_workflow_kernel_round_budget_exceeded_forces_handoff_and_round_trips_state():
    workflow = workflow_template("code_change")
    kernel = WorkflowKernel(workflow)

    kernel.record_round(workflow.round_budget)
    assert kernel.state.status == "active"
    kernel.record_round()

    assert kernel.state.phase == "handoff"
    assert kernel.state.status == "handoff"
    assert kernel.state.stop_reason == "round_budget_exceeded"
    assert kernel.state.rounds_used == workflow.round_budget + 1
    assert kernel.state.phase_history[-1] == "handoff"

    restored = WorkflowKernelState.from_dict(kernel.state.to_dict(), workflow)
    assert restored == kernel.state


def test_workflow_kernel_tool_budget_exceeded_in_handoff_becomes_blocked():
    workflow = workflow_template("test_fix")
    kernel = WorkflowKernel(workflow)

    for phase in workflow.phases[1:]:
        kernel.transition(phase)

    assert kernel.state.status == "handoff"

    kernel.record_tool(workflow.tool_budget + 1)

    assert kernel.state.phase == "handoff"
    assert kernel.state.status == "blocked"
    assert kernel.state.stop_reason == "tool_budget_exceeded"
    assert kernel.state.tools_used == workflow.tool_budget + 1


def test_task_packet_compiler_excludes_raw_logs_and_includes_active_skills(tmp_path):
    store = SkillStore(tmp_path / ".skillforge" / "skills")
    store.save_active(
        SkillCard(
            skill_id="pytest-failure-triage",
            title="Pytest failure triage",
            triggers=("pytest",),
            workflow_tags=("test_fix",),
            file_patterns=("tests/*.py",),
            steps=("Run pytest through log_run.",),
            verification=("Check log_failure_detail.",),
        )
    )
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")
    raw_log_path = evidence.write_raw_log("this raw log must stay out")
    raw = evidence.add(
        "log",
        {
            "raw_log_path": str(raw_log_path),
            "status": "failed",
            "parsed_summary": "1 failed",
            "failure_count": 1,
            "failures": ["tests/test_app.py: assert 1 == 2"],
        },
        raw=True,
    )
    kernel = WorkflowKernel(workflow_template("test_fix"))
    kernel.transition("investigate")

    packet = TaskPacketCompiler(skill_store=store).compile(
        user_intent="fix failing pytest",
        workflow=workflow_template("test_fix"),
        kernel=kernel,
        evidence_store=evidence,
        paths=("tests/test_app.py",),
    )

    assert packet.workflow == "test_fix"
    assert raw.evidence_id in packet.evidence_refs
    assert "this raw log must stay out" not in packet.prompt_context
    assert "pytest-failure-triage" in packet.active_skill_ids
    assert packet.active_skill_constraints[0].skill_id == "pytest-failure-triage"


def test_task_packet_compiler_rejects_raw_log_records_with_prompt_facing_secret_fields(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")
    raw_log_path = evidence.write_raw_log("SECRET_RAW_LOG")

    with pytest.raises(ValueError, match="raw log evidence must not include prompt-facing fields"):
        evidence.add("log", {"summary": "SECRET_RAW_LOG", "raw_log_path": str(raw_log_path)}, raw=True)


def test_cli_build_agent_accepts_workflow_flag(tmp_path):
    args = mini_pkg.build_arg_parser().parse_args(
        [
            "--cwd",
            str(tmp_path),
            "--provider",
            "fake",
            "--workflow",
            "repo_audit",
        ]
    )

    agent = mini_pkg.build_agent(args)

    assert agent.workflow.name == "repo_audit"
    assert agent.workflow_kernel.state.phase == "intake"


def test_workflow_run_tool_rejects_tools_outside_current_task_packet_phase(tmp_path):
    agent = build_workflow_agent(tmp_path, [], workflow="repo_audit")

    result = agent.run_tool("run_shell", {"command": "pwd", "timeout": 5})

    assert "not allowed in workflow repo_audit phase intake" in result


def test_agent_loop_uses_task_packet_context_and_restricted_tools_each_round(tmp_path):
    (tmp_path / "notes.txt").write_text("audit me\n", encoding="utf-8")
    agent = build_workflow_agent(
        tmp_path,
        [
            '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
            "<final>Intake complete.</final>",
            '<tool>{"name":"read_file","args":{"path":"notes.txt","start":1,"end":20}}</tool>',
            "<final>Investigation complete.</final>",
            "<final>Audit summary ready.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="repo_audit",
    )

    answer = agent.ask("Audit the repository and summarize risks.")

    assert answer == "Handoff complete."
    assert len(agent.model_client.prompts) == 6
    assert "Workflow task packet:" in agent.model_client.prompts[0]
    assert "Phase: intake" in agent.model_client.prompts[0]
    assert "- log_run" not in agent.model_client.prompts[0]
    assert "- run_shell" not in agent.model_client.prompts[0]
    assert "- write_file" not in agent.model_client.prompts[0]
    assert "Phase: investigate" in agent.model_client.prompts[2]
    assert "- log_run" not in agent.model_client.prompts[2]
    assert "Phase: audit" in agent.model_client.prompts[4]
    assert "Phase: handoff" in agent.model_client.prompts[5]


def test_fake_workflow_e2e_writes_trace_and_artifacts_with_task_packet_metadata(tmp_path):
    agent = build_workflow_agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Investigation complete.</final>",
            "<final>Audit summary ready.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="repo_audit",
    )

    assert agent.ask("Audit the repository and hand off findings.") == "Handoff complete."

    run_dir = agent.current_run_dir
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    trace_events = [json.loads(line) for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()]

    assert report["prompt_metadata"]["workflow_name"] == "repo_audit"
    assert report["prompt_metadata"]["workflow_phase"] == "handoff"
    assert report["prompt_metadata"]["workflow_allowed_tools"] == ["read_file", "search", "log_brief"]
    assert any(event["event"] == "workflow_phase_transition" for event in trace_events)
    assert any(event["event"] == "workflow_task_packet_compiled" for event in trace_events)


def test_repo_audit_runtime_persists_workflow_and_tool_evidence(tmp_path):
    (tmp_path / "notes.txt").write_text("audit me\n", encoding="utf-8")
    agent = build_workflow_agent(
        tmp_path,
        [
            '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
            "<final>Intake complete.</final>",
            '<tool>{"name":"read_file","args":{"path":"notes.txt","start":1,"end":20}}</tool>',
            "<final>Investigation complete.</final>",
            "<final>Audit summary ready.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="repo_audit",
    )

    assert agent.ask("Audit the repository and summarize risks.") == "Handoff complete."

    index_payload = load_evidence_index(agent.current_run_dir)
    records = index_payload["records"]
    record_types = [item["type"] for item in records]

    assert "workflow" in record_types
    assert "tool" in record_types

    evidence_store = agent.current_evidence_store()
    restored = evidence_store.records()
    workflow_records = [record for record in restored if record.record_type == "workflow"]
    tool_records = [record for record in restored if record.record_type == "tool"]

    assert workflow_records
    assert any(record.payload["event"] == "workflow_phase_transition" for record in workflow_records)
    assert [record.payload["tool_name"] for record in tool_records] == ["list_files", "read_file"]


def test_test_fix_runtime_persists_log_record_alongside_workflow_and_tool_evidence(tmp_path):
    test_file = tmp_path / "test_pass.py"
    test_file.write_text(
        "def test_ok():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    agent = build_workflow_agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            f'<tool>{{"name":"log_run","args":{{"command":"python3 -m pytest {test_file}","timeout":5}}}}</tool>',
            "<final>Investigation complete.</final>",
            "<final>Implement complete.</final>",
            "<final>Verify complete.</final>",
            "<final>Audit complete.</final>",
            "<final>Skill distill complete.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="test_fix",
    )

    assert agent.ask("Run pytest, inspect evidence, and hand off.") == "error: audit failed; missing diff evidence; missing verification evidence"

    index_payload = load_evidence_index(agent.current_run_dir)
    records = index_payload["records"]
    record_types = [item["type"] for item in records]

    assert "workflow" in record_types
    assert "tool" in record_types
    assert "log" in record_types

    evidence_store = agent.current_evidence_store()
    restored = evidence_store.records()
    log_records = [record for record in restored if record.record_type == "log"]
    assert len(log_records) == 1
    assert log_records[0].raw is True
    assert log_records[0].payload["parsed_summary"] == "1 passed"


def test_cli_fake_provider_test_fix_e2e_records_verified_handoff_and_quarantined_candidate(tmp_path, capsys, monkeypatch):
    app_file = tmp_path / "app.py"
    app_file.write_text("VALUE = 1\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_app.py"
    test_file.write_text(
        "from app import VALUE\n\n"
        "def test_value():\n"
        "    assert VALUE == 2\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "SKILLFORGE_FAKE_OUTPUTS",
        json.dumps(
            [
                "<final>Intake complete.</final>",
                f'<tool>{{"name":"log_run","args":{{"command":"python3 -m pytest {test_file.relative_to(tmp_path).as_posix()}","timeout":30}}}}</tool>',
                "<final>Investigation complete.</final>",
                '<tool name="patch_file" path="app.py"><old_text>VALUE = 1\n</old_text><new_text>VALUE = 2\n</new_text></tool>',
                "<final>Implement complete.</final>",
                f'<tool>{{"name":"log_run","args":{{"command":"python3 -m pytest {test_file.relative_to(tmp_path).as_posix()}","timeout":30}}}}</tool>',
                "<final>Verify complete.</final>",
                "<final>Audit complete.</final>",
                "<final>Skill distill complete.</final>",
                "<final>Handoff complete.</final>",
            ]
        ),
    )

    exit_code = mini_pkg.main(
        [
            "--cwd",
            str(tmp_path),
            "--provider",
            "fake",
            "--approval",
            "auto",
            "--workflow",
            "test_fix",
            "Fix",
            "the",
            "failing",
            "pytest",
            "workflow",
            "and",
            "handoff",
            "the",
            "verified",
            "result.",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Handoff complete." in captured.out
    assert app_file.read_text(encoding="utf-8") == "VALUE = 2\n"

    run_dirs = [path for path in (tmp_path / ".skillforge" / "runs").iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "completed"
    assert report["prompt_metadata"]["workflow_name"] == "test_fix"
    assert report["prompt_metadata"]["workflow_phase"] == "handoff"

    records = EvidenceStore(run_dir).records()
    log_records = [record for record in records if record.record_type == "log"]
    assert [record.payload["status"] for record in log_records] == ["failed", "passed"]
    verification_records = [record for record in records if record.record_type == "verification"]
    assert len(verification_records) == 1
    assert verification_records[0].payload["status"] == "passed"
    assert verification_records[0].payload["command"] == "python3 -m pytest tests/test_app.py"
    audit_records = [record for record in records if record.record_type == "audit"]
    assert len(audit_records) == 1
    assert audit_records[0].payload["status"] == "pass"
    handoff_records = [record for record in records if record.record_type == "handoff"]
    assert len(handoff_records) == 1
    assert handoff_records[0].payload["summary"] == "Handoff complete."
    skill_records = [record for record in records if record.record_type == "skill"]
    assert len(skill_records) == 1
    assert skill_records[0].payload["slot"] == "candidate"

    store = SkillStore(tmp_path / ".skillforge" / "skills")
    candidates = store.list_candidates()
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.candidate_id == skill_records[0].payload["candidate_id"]
    assert candidate.status == "quarantine"
    assert candidate.workflow_tags == ("test_fix",)
    assert candidate.triggers == ("pytest",)
    assert candidate.verification == ("Re-run python3 -m pytest tests/test_app.py.",)
    assert store.list_active() == []
    freshness_payload = store.load_candidate_freshness(candidate.candidate_id)
    assert freshness_payload["root"] == str(tmp_path.resolve())
    assert [item["path"] for item in freshness_payload["files"]] == [str(app_file.resolve())]


def test_workflow_delegate_child_inherits_locked_task_packet_and_rejects_forbidden_tools(tmp_path):
    agent = build_workflow_agent(
        tmp_path,
        [
            '<tool>{"name":"log_run","args":{"command":"pwd","timeout":5}}</tool>',
            "<final>Child stopped after the rejection.</final>",
        ],
        workflow="code_change",
    )
    agent.workflow_kernel.transition("plan_compile")

    result = agent.run_tool("delegate", {"task": "inspect README only", "max_steps": 2})

    assert "delegate_result" in result
    assert len(agent.model_client.prompts) == 2
    child_prompt = agent.model_client.prompts[-1]
    assert "Phase: implement" not in "\n".join(agent.model_client.prompts)
    assert "Workflow task packet:" in child_prompt
    assert "Phase: plan_compile" in child_prompt
    assert "- delegate" in child_prompt
    assert "- run_shell" not in child_prompt
    assert "- write_file" not in child_prompt
    assert "- patch_file" not in child_prompt
    assert "- log_run" not in child_prompt
    run_dirs = sorted((tmp_path / ".skillforge" / "runs").iterdir(), key=lambda path: path.stat().st_mtime)
    child_trace = [json.loads(line) for line in (run_dirs[-1] / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    tool_events = [event for event in child_trace if event["event"] == "tool_executed"]
    assert tool_events
    assert tool_events[0]["name"] == "log_run"
    assert tool_events[0]["tool_error_code"] == "workflow_tool_not_allowed"
    assert tool_events[0]["security_event_type"] == "workflow_tool_not_allowed"


def test_workflow_delegate_child_keeps_locked_task_packet_when_read_only_blocks_log_run(tmp_path):
    test_file = tmp_path / "test_pass.py"
    test_file.write_text(
        "def test_ok():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    agent = build_workflow_agent(
        tmp_path,
        [
            f'<tool>{{"name":"log_run","args":{{"command":"python3 -m pytest {test_file}","timeout":5}}}}</tool>',
            "<final>Child implement summary.</final>",
        ],
        workflow="code_change",
    )
    agent.workflow_kernel.transition("plan_compile")
    agent.workflow_kernel.transition("implement")

    result = agent.run_tool("delegate", {"task": "collect verification context", "max_steps": 2})

    assert "delegate_result" in result
    assert len(agent.model_client.prompts) == 2
    second_prompt = agent.model_client.prompts[-1]
    assert "Workflow task packet:" in second_prompt
    assert "Phase: implement" in second_prompt
    assert "Budgets used: rounds 1/12, tools 1/40" in second_prompt
    assert "Evidence briefs:" in second_prompt
    assert "- none" in second_prompt
    assert "Phase: verify" not in second_prompt
    run_dirs = sorted((tmp_path / ".skillforge" / "runs").iterdir(), key=lambda path: path.stat().st_mtime)
    child_trace = [json.loads(line) for line in (run_dirs[-1] / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    tool_events = [event for event in child_trace if event["event"] == "tool_executed"]
    assert tool_events[0]["name"] == "log_run"
    assert tool_events[0]["tool_error_code"] == "approval_denied"
    assert tool_events[0]["security_event_type"] == "read_only_block"


def test_log_tools_store_raw_logs_and_return_failure_detail(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    test_file = repo / "test_sample.py"
    test_file.write_text(
        "def test_failure():\n"
        "    assert 1 == 2\n",
        encoding="utf-8",
    )
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")

    run_record = log_run(evidence, ["/usr/bin/env", "python3", "-m", "pytest", str(test_file)], cwd=repo)
    brief = log_brief(evidence, run_record.evidence_id, max_chars=120)
    detail = log_failure_detail(evidence, run_record.evidence_id, 0)

    assert run_record.payload["returncode"] != 0
    assert Path(run_record.payload["raw_log_path"]).exists()
    assert "1 failed" in brief
    assert "test_sample.py" in detail
    assert "assert 1 == 2" in detail


def test_log_run_falls_back_for_non_pytest_commands_and_never_marks_pass(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")

    record = log_run(evidence, ["/bin/echo", "hello"], cwd=tmp_path)

    assert record.raw is True
    assert record.payload["status"] == "unparsed"
    assert record.payload["returncode"] == 0
    assert record.payload["failure_count"] == 0
    assert record.payload["failures"] == []
    assert Path(record.payload["raw_log_path"]).read_text(encoding="utf-8").strip() == "hello"
    assert log_brief(evidence, record.evidence_id, max_chars=40) == "unparsed"


def test_log_run_falls_back_for_unparseable_pytest_output_and_failure_detail_stays_closed(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")

    record = log_run(
        evidence,
        ["/usr/bin/env", "python3", "-m", "pytest", "--version"],
        cwd=tmp_path,
    )

    assert record.raw is True
    assert record.payload["status"] == "unparsed"
    assert record.payload["returncode"] == 0
    assert record.payload["failure_count"] == 0
    assert record.payload["failures"] == []
    assert "pytest " in Path(record.payload["raw_log_path"]).read_text(encoding="utf-8")
    assert log_brief(evidence, record.evidence_id, max_chars=40) == "unparsed"
    with pytest.raises(ValueError, match="failure detail"):
        log_failure_detail(evidence, record.evidence_id, 0)


def test_log_failure_detail_fails_fast_when_failure_is_missing(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")
    raw_log_path = evidence.write_raw_log("no failures here")
    record = evidence.add(
        "log",
        {
            "raw_log_path": str(raw_log_path),
            "status": "passed",
            "parsed_summary": "1 passed",
            "failure_count": 0,
            "failures": [],
        },
        raw=True,
    )

    with pytest.raises(ValueError, match="failure detail"):
        log_failure_detail(evidence, record.evidence_id, 0)


def test_completion_gate_requires_diff_verification_audit_and_handoff(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")
    gate = CompletionGate(workflow_template("code_change"))

    evidence.add("diff", {"summary": "changed app.py"})
    evidence.add("verification", {"status": "passed", "command": "pytest"})
    evidence.add("audit", {"status": "pass"})
    assert not gate.can_complete(evidence.records())

    evidence.add("handoff", {"next": "none"})
    assert gate.can_complete(evidence.records())


def test_completion_gate_distinguishes_workflow_requirements_and_rejects_unparsed_log_as_verification(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")
    raw_log_path = evidence.write_raw_log("pytest 8.4.0")
    evidence.add(
        "log",
        {
            "raw_log_path": str(raw_log_path),
            "status": "unparsed",
            "returncode": 0,
            "failure_count": 0,
            "failures": [],
        },
        raw=True,
    )
    evidence.add("diff", {"summary": "changed app.py"})
    evidence.add("audit", {"status": "pass"})
    evidence.add("handoff", {"next": "none"})

    result = CompletionGate(workflow_template("code_change")).evaluate(evidence.records())
    assert not result.allowed
    assert result.missing == ("verification",)
    assert result.invalid == ()

    repo_evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-2")
    repo_evidence.add("audit", {"status": "pass"})
    repo_evidence.add("handoff", {"next": "done"})
    repo_result = CompletionGate(workflow_template("repo_audit")).evaluate(repo_evidence.records())
    assert repo_result.allowed
    assert repo_result.missing == ()
    assert repo_result.invalid == ()


def test_code_change_workflow_cannot_complete_handoff_without_required_evidence(tmp_path):
    agent = build_workflow_agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Plan compile complete.</final>",
            "<final>Implement complete.</final>",
            "<final>Verify complete.</final>",
            "<final>Audit complete.</final>",
            "<final>Skill distill complete.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="code_change",
    )

    answer = agent.ask("Make the requested code change and hand off the result.")

    assert answer == "error: audit failed; missing diff evidence; missing verification evidence"
    report = json.loads((agent.current_run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "stopped"
    assert report["stop_reason"] == "audit_failed"
    assert report["task_state"]["status"] == "stopped"
    assert report["task_state"]["stop_reason"] == "audit_failed"
    assert report["prompt_metadata"]["workflow_phase"] == "audit"
    assert agent.workflow_kernel.state.phase == "audit"
    assert agent.workflow_kernel.state.status == "blocked"


def test_code_change_runtime_produces_completion_evidence_and_can_finish(tmp_path):
    app_file = tmp_path / "app.py"
    app_file.write_text("VALUE = 1\n", encoding="utf-8")
    test_file = tmp_path / "test_app.py"
    test_file.write_text(
        "from app import VALUE\n\n"
        "def test_value():\n"
        "    assert VALUE == 2\n",
        encoding="utf-8",
    )
    agent = build_workflow_agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Plan compile complete.</final>",
            '<tool name="patch_file" path="app.py"><old_text>VALUE = 1\n</old_text><new_text>VALUE = 2\n</new_text></tool>',
            "<final>Implement complete.</final>",
            f'<tool>{{"name":"log_run","args":{{"command":"python3 -m pytest {test_file.name}","timeout":30}}}}</tool>',
            "<final>Verify complete.</final>",
            "<final>Audit complete.</final>",
            "<final>Skill distill complete.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="code_change",
    )

    answer = agent.ask("Update the constant and verify the targeted pytest file.")

    assert answer == "Handoff complete."
    evidence_store = agent.current_evidence_store()
    records = evidence_store.records()
    by_type = {record.record_type: record for record in records}
    assert by_type["diff"].payload["paths"] == ["app.py"]
    assert by_type["verification"].payload["status"] == "passed"
    assert by_type["audit"].payload["status"] == "pass"
    assert by_type["handoff"].payload["summary"] == "Handoff complete."


def test_code_change_audit_fail_blocks_before_skill_distill_and_handoff(tmp_path):
    app_file = tmp_path / "app.py"
    app_file.write_text("VALUE = 1\n", encoding="utf-8")
    test_file = tmp_path / "test_app.py"
    test_file.write_text(
        "from app import VALUE\n\n"
        "def test_value():\n"
        "    assert VALUE == 2\n",
        encoding="utf-8",
    )
    agent = build_workflow_agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Plan compile complete.</final>",
            '<tool name="patch_file" path="app.py"><old_text>VALUE = 1\n</old_text><new_text>VALUE = 2\n</new_text></tool>',
            "<final>Implement complete.</final>",
            f'<tool>{{"name":"log_run","args":{{"command":"python3 -m pytest {test_file.name}","timeout":30}}}}</tool>',
            "<final>Verify complete.</final>",
            '<final>{"status":"fail","concerns":["missing regression coverage"],"summary":"Audit failed."}</final>',
        ],
        workflow="code_change",
    )

    answer = agent.ask("Update the constant, verify it, and stop if audit fails.")

    assert answer == "error: audit failed; missing regression coverage"
    report = json.loads((agent.current_run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "stopped"
    assert report["stop_reason"] == "audit_failed"
    assert report["prompt_metadata"]["workflow_phase"] == "audit"
    assert agent.workflow_kernel.state.phase == "audit"
    assert agent.workflow_kernel.state.status == "blocked"
    records = agent.current_evidence_store().records()
    audit_record = [record for record in records if record.record_type == "audit"][-1]
    assert audit_record.payload["status"] == "fail"
    assert audit_record.payload["concerns"] == ["missing regression coverage"]
    assert "skill_distill" not in audit_record.payload.get("next_phase", "")
    assert "handoff" not in {record.record_type for record in records}


def test_code_change_audit_concerns_can_continue_to_handoff(tmp_path):
    app_file = tmp_path / "app.py"
    app_file.write_text("VALUE = 1\n", encoding="utf-8")
    test_file = tmp_path / "test_app.py"
    test_file.write_text(
        "from app import VALUE\n\n"
        "def test_value():\n"
        "    assert VALUE == 2\n",
        encoding="utf-8",
    )
    agent = build_workflow_agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Plan compile complete.</final>",
            '<tool name="patch_file" path="app.py"><old_text>VALUE = 1\n</old_text><new_text>VALUE = 2\n</new_text></tool>',
            "<final>Implement complete.</final>",
            f'<tool>{{"name":"log_run","args":{{"command":"python3 -m pytest {test_file.name}","timeout":30}}}}</tool>',
            "<final>Verify complete.</final>",
            '<final>{"status":"concerns","concerns":["consider a broader regression sweep"],"action":"continue","summary":"Audit noted concerns."}</final>',
            "<final>Skill distill complete.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="code_change",
    )

    answer = agent.ask("Update the constant, keep audit concerns as evidence, and continue.")

    assert answer == "Handoff complete."
    assert agent.workflow_kernel.state.phase == "handoff"
    records = agent.current_evidence_store().records()
    audit_record = [record for record in records if record.record_type == "audit"][-1]
    assert audit_record.payload["status"] == "concerns"
    assert audit_record.payload["concerns"] == ["consider a broader regression sweep"]
    assert audit_record.payload["next_phase"] == "skill_distill"
    assert any(record.record_type == "handoff" for record in records)


def test_code_change_audit_concerns_without_recorded_items_blocks_before_handoff(tmp_path):
    app_file = tmp_path / "app.py"
    app_file.write_text("VALUE = 1\n", encoding="utf-8")
    test_file = tmp_path / "test_app.py"
    test_file.write_text(
        "from app import VALUE\n\n"
        "def test_value():\n"
        "    assert VALUE == 2\n",
        encoding="utf-8",
    )
    agent = build_workflow_agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Plan compile complete.</final>",
            '<tool name="patch_file" path="app.py"><old_text>VALUE = 1\n</old_text><new_text>VALUE = 2\n</new_text></tool>',
            "<final>Implement complete.</final>",
            f'<tool>{{"name":"log_run","args":{{"command":"python3 -m pytest {test_file.name}","timeout":30}}}}</tool>',
            "<final>Verify complete.</final>",
            '<final>{"status":"concerns","summary":"Audit said concerns without details."}</final>',
        ],
        workflow="code_change",
    )

    answer = agent.ask("Update the constant, but block if audit claims concerns without recording any.")

    assert answer == "error: audit failed; audit status=concerns requires at least one recorded concern"
    assert agent.workflow_kernel.state.phase == "audit"
    assert agent.workflow_kernel.state.status == "blocked"
    records = agent.current_evidence_store().records()
    audit_record = [record for record in records if record.record_type == "audit"][-1]
    assert audit_record.payload["status"] == "fail"
    assert audit_record.payload["concerns"] == ["audit status=concerns requires at least one recorded concern"]
    assert not any(record.record_type == "handoff" for record in records)


def test_code_change_audit_concerns_can_return_to_implement_before_passing(tmp_path):
    app_file = tmp_path / "app.py"
    app_file.write_text("VALUE = 1\n", encoding="utf-8")
    test_file = tmp_path / "test_app.py"
    test_file.write_text(
        "from app import VALUE\n\n"
        "def test_value():\n"
        "    assert VALUE == 2\n",
        encoding="utf-8",
    )
    agent = build_workflow_agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Plan compile complete.</final>",
            '<tool name="patch_file" path="app.py"><old_text>VALUE = 1\n</old_text><new_text>VALUE = 2\n</new_text></tool>',
            "<final>Implement complete.</final>",
            f'<tool>{{"name":"log_run","args":{{"command":"python3 -m pytest {test_file.name}","timeout":30}}}}</tool>',
            "<final>Verify complete.</final>",
            '<final>{"status":"concerns","concerns":["capture the audit note and revise once"],"action":"return_to_implement","summary":"Audit wants another implementation pass."}</final>',
            "<final>Implement complete after audit feedback.</final>",
            f'<tool>{{"name":"log_run","args":{{"command":"python3 -m pytest {test_file.name}","timeout":30}}}}</tool>',
            "<final>Verify complete after audit feedback.</final>",
            "<final>Audit pass after revision.</final>",
            "<final>Skill distill complete.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="code_change",
    )

    answer = agent.ask("Update the constant, loop back on audit concerns once, then hand off.")

    assert answer == "Handoff complete."
    assert agent.workflow_kernel.state.phase == "handoff"
    records = agent.current_evidence_store().records()
    audit_records = [record for record in records if record.record_type == "audit"]
    assert len(audit_records) == 2
    assert audit_records[0].payload["status"] == "concerns"
    assert audit_records[0].payload["next_phase"] == "implement"
    assert audit_records[1].payload["status"] == "pass"
    workflow_records = [record for record in records if record.record_type == "workflow"]
    transitions = [record.payload for record in workflow_records if record.payload.get("event") == "workflow_phase_transition"]
    assert any(
        payload.get("from_phase") == "audit" and payload.get("to_phase") == "implement"
        for payload in transitions
    )
    assert any(record.record_type == "handoff" for record in records)


def test_test_fix_verify_phase_unparsed_log_does_not_create_verification_pass(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("before\n", encoding="utf-8")
    agent = build_workflow_agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Investigation complete.</final>",
            '<tool name="patch_file" path="notes.txt"><old_text>before\n</old_text><new_text>after\n</new_text></tool>',
            "<final>Implement complete.</final>",
            '<tool>{"name":"log_run","args":{"command":"python3 -m pytest --version","timeout":30}}</tool>',
            "<final>Verify complete.</final>",
            "<final>Audit complete.</final>",
            "<final>Skill distill complete.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="test_fix",
    )

    answer = agent.ask("Patch the file, run an unparseable pytest command, and hand off.")

    assert answer == "error: audit failed; missing verification evidence"
    records = agent.current_evidence_store().records()
    assert "verification" not in {record.record_type for record in records}
    assert not any(record.record_type == "handoff" for record in records)


def test_deterministic_auditor_and_read_only_boundary(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")
    evidence.add("diff", {"paths": ["app.py"]})
    evidence.add("verification", {"status": "passed", "command": "pytest"})

    report = audit_code_change(evidence.records())
    assert report.status == "pass"
    assert report.evidence_refs

    subagent = AuditSubagent()
    assert subagent.is_tool_allowed("read_file")
    assert not subagent.is_tool_allowed("write_file")


def test_audit_subagent_whitelist_stays_read_only():
    subagent = AuditSubagent()

    assert subagent.allowed_tools == frozenset({"list_files", "read_file", "search", "log_brief", "log_failure_detail"})
    for tool_name in ("write_file", "patch_file", "run_shell", "log_run", "promote", "delegate"):
        assert not subagent.is_tool_allowed(tool_name)


def test_audit_delegate_child_prompt_uses_audit_whitelist_only(tmp_path):
    agent = build_workflow_agent(
        tmp_path,
        ["<final>Audit child summary.</final>"],
        workflow="code_change",
    )
    agent.workflow_kernel.transition("plan_compile")
    agent.workflow_kernel.transition("implement")
    agent.workflow_kernel.transition("verify")
    agent.workflow_kernel.transition("audit")

    result = agent.run_tool("delegate", {"task": "audit the collected evidence", "max_steps": 1})

    assert "delegate_result" in result
    child_prompt = agent.model_client.prompts[-1]
    assert "Phase: audit" in child_prompt
    for tool_name in AuditSubagent.allowed_tools:
        assert f"- {tool_name}" in child_prompt
    for tool_name in ("delegate", "write_file", "patch_file", "run_shell", "log_run", "promote"):
        assert f"- {tool_name}" not in child_prompt


@pytest.mark.parametrize(
    ("tool_name", "tool_args", "forbidden_path"),
    [
        ("write_file", {"path": "audit-blocked.txt", "content": "nope\n"}, "audit-blocked.txt"),
        (
            "patch_file",
            {"path": "README.md", "old_text": "workflow fixture\n", "new_text": "mutated by audit\n"},
            "README.md",
        ),
        ("run_shell", {"command": "printf 'audit-shell' > audit-shell.txt", "timeout": 5}, "audit-shell.txt"),
        ("log_run", {"command": "python3 -c \"from pathlib import Path; Path('audit-log.txt').write_text('nope')\"", "timeout": 5}, "audit-log.txt"),
    ],
)
def test_audit_delegate_child_rejects_forbidden_workspace_mutations(tmp_path, tool_name, tool_args, forbidden_path):
    agent = build_workflow_agent(
        tmp_path,
        [
            f'<tool>{{"name":"{tool_name}","args":{json.dumps(tool_args, ensure_ascii=True)}}}</tool>',
            "<final>Audit child stopped after rejection.</final>",
        ],
        workflow="code_change",
    )
    agent.workflow_kernel.transition("plan_compile")
    agent.workflow_kernel.transition("implement")
    agent.workflow_kernel.transition("verify")
    agent.workflow_kernel.transition("audit")

    result = agent.run_tool("delegate", {"task": "audit only; do not mutate the workspace", "max_steps": 2})

    assert "delegate_result" in result
    assert not (tmp_path / forbidden_path).exists() or (tmp_path / forbidden_path).read_text(encoding="utf-8") == "workflow fixture\n"
    run_dirs = sorted((tmp_path / ".skillforge" / "runs").iterdir(), key=lambda path: path.stat().st_mtime)
    child_trace = [json.loads(line) for line in (run_dirs[-1] / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    tool_events = [event for event in child_trace if event["event"] == "tool_executed"]
    assert tool_events
    assert tool_events[0]["name"] == tool_name
    assert tool_events[0]["tool_error_code"] == "workflow_tool_not_allowed"
    assert tool_events[0]["security_event_type"] == "workflow_tool_not_allowed"


def test_skill_candidate_quarantine_manual_promote_and_task_packet_reuse(tmp_path):
    store = SkillStore(tmp_path / ".skillforge" / "skills")
    candidate = SkillCandidate(
        candidate_id="cand-pytest",
        title="Pytest failure triage",
        triggers=("pytest",),
        workflow_tags=("test_fix",),
        file_patterns=("tests/*.py",),
        steps=("Run log_run on pytest.",),
        verification=("Use log_failure_detail before editing.",),
        evidence_refs=("ev-1",),
    )

    store.save_candidate(candidate)
    assert candidate.candidate_id in [item.candidate_id for item in store.list_candidates()]
    assert store.list_active() == []

    active = store.promote(candidate.candidate_id, skill_id="pytest-failure-triage")
    assert active.skill_id == "pytest-failure-triage"
    assert store.list_candidates() == []
    assert SkillMatcher(store).match("pytest failed", workflow="test_fix", paths=["tests/test_app.py"])[0].skill_id == active.skill_id

    packet = SkillCompiler(store).compile_for_task("pytest failed", workflow="test_fix", paths=["tests/test_app.py"])
    assert packet["active_skill_ids"] == ["pytest-failure-triage"]


def test_skill_reuse_e2e_promoted_active_skill_enters_next_task_packet(tmp_path):
    fixture = _build_cli_verified_candidate_fixture(tmp_path)
    store = fixture["store"]
    candidate = fixture["candidate"]
    gate = PromotionGate(store)

    promoted = gate.promote(
        candidate.candidate_id,
        skill_id="pytest-failure-triage",
        evidence_records=fixture["records"],
        freshness_guard=fixture["freshness_guard"],
    )

    kernel = WorkflowKernel(workflow_template("test_fix"))
    kernel.transition("investigate")
    packet = TaskPacketCompiler(skill_store=store).compile(
        user_intent="fix the failing pytest and inspect the first failure before editing",
        workflow=workflow_template("test_fix"),
        kernel=kernel,
        evidence_store=EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-next"),
        paths=("tests/test_app.py", "skillforge/runtime.py"),
    )

    assert promoted.skill_id == "pytest-failure-triage"
    assert packet.active_skill_ids == ("pytest-failure-triage",)
    assert packet.active_skill_constraints == (
        TaskPacketSkillConstraint(
            skill_id="pytest-failure-triage",
            steps=tuple(candidate.steps),
            verification=tuple(candidate.verification),
        ),
    )
    assert "Run pytest through log_run." in packet.prompt_context
    assert "Inspect the failure detail before editing." in packet.prompt_context
    assert "Re-run python3 -m pytest tests/test_app.py." in packet.prompt_context
    assert fixture["raw_log_text"] not in packet.prompt_context


def test_task_packet_compiler_blocks_matching_active_skill_with_forbidden_prompt_content(tmp_path):
    store = SkillStore(tmp_path / ".skillforge" / "skills")
    store.save_active(
        SkillCard(
            skill_id="pytest-failure-triage",
            title="Pytest failure triage",
            triggers=("pytest",),
            workflow_tags=("test_fix",),
            file_patterns=("tests/*.py",),
            steps=(
                "Inspect /Users/demo/private/project/tests/test_app.py before editing.",
                "Read .skillforge/runs/run-1/evidence/log/log-abcdef123456.txt for the raw failure.",
            ),
            verification=("Re-run with sk-live-secret-abc after the edit.",),
        )
    )
    kernel = WorkflowKernel(workflow_template("test_fix"))
    kernel.transition("investigate")

    with pytest.raises(ValueError, match="active skill .*forbidden prompt content"):
        TaskPacketCompiler(skill_store=store).compile(
            user_intent="fix failing pytest",
            workflow=workflow_template("test_fix"),
            kernel=kernel,
            paths=("tests/test_app.py",),
        )


def test_active_skill_stats_record_single_use_and_success_for_multi_phase_workflow(tmp_path, monkeypatch):
    store = SkillStore(tmp_path / ".skillforge" / "skills")
    store.save_active(
        SkillCard(
            skill_id="repo-audit-triage",
            title="Repo audit triage",
            triggers=("audit",),
            workflow_tags=("repo_audit",),
            file_patterns=(),
            steps=("List files before summarizing risk.",),
            verification=("Confirm risks in the handoff.",),
        )
    )
    monkeypatch.setattr(runtime_mod, "now", lambda: "2026-06-28T12:00:00+00:00")
    agent = build_workflow_agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Investigation complete.</final>",
            "<final>Audit summary ready.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="repo_audit",
    )

    assert agent.ask("Audit the repository and summarize risks.") == "Handoff complete."

    updated = store.get_active("repo-audit-triage")
    assert updated.uses == 1
    assert updated.successes == 1
    assert updated.failures == 0
    assert updated.last_used == "2026-06-28T12:00:00+00:00"


def test_active_skill_stats_record_failure_when_workflow_run_stops(tmp_path, monkeypatch):
    store = SkillStore(tmp_path / ".skillforge" / "skills")
    store.save_active(
        SkillCard(
            skill_id="repo-audit-triage",
            title="Repo audit triage",
            triggers=("audit",),
            workflow_tags=("repo_audit",),
            file_patterns=(),
            steps=("List files before summarizing risk.",),
            verification=("Confirm risks in the handoff.",),
        )
    )
    monkeypatch.setattr(runtime_mod, "now", lambda: "2026-06-28T13:00:00+00:00")
    agent = build_workflow_agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Investigation complete.</final>",
            '<final>{"status":"fail","concerns":["missing risk summary"],"summary":"Audit failed."}</final>',
        ],
        workflow="repo_audit",
    )

    assert agent.ask("Audit the repository and summarize risks.") == "error: audit failed; missing risk summary"

    updated = store.get_active("repo-audit-triage")
    assert updated.uses == 1
    assert updated.successes == 0
    assert updated.failures == 1
    assert updated.last_used == "2026-06-28T13:00:00+00:00"


def _build_cli_verified_candidate_fixture(tmp_path):
    workspace_paths = []
    for relative_path, content in (
        ("skillforge/runtime.py", "def apply_fix():\n    return 'ok'\n"),
        ("tests/test_app.py", "def test_example():\n    assert True\n"),
    ):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        workspace_paths.append(path)

    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")
    raw_log_path = evidence.write_raw_log(
        "============================= test session starts =============================\n"
        + "AssertionError: expected deterministic reproduction\n" * 40
    )
    log_record = evidence.add(
        "log",
        {
            "command": ["python3", "-m", "pytest", "tests/test_app.py"],
            "cwd": str(tmp_path),
            "returncode": 0,
            "status": "passed",
            "parsed_summary": "1 passed",
            "raw_log_path": str(raw_log_path),
            "failure_count": 0,
            "failures": [],
        },
        raw=True,
    )
    evidence.add(
        "workflow",
        {
            "event": "workflow_run_started",
            "summary": "test_fix started",
            "workflow": "test_fix",
            "phase": "verify",
            "status": "active",
            "run_id": "run-1",
            "task_id": "task-1",
        },
    )
    evidence.add(
        "diff",
        {
            "summary": "patched runtime and pytest fixture",
            "paths": [str(path.relative_to(tmp_path)) for path in workspace_paths],
            "diff_summary": ["updated assertion handling"],
        },
    )
    evidence.add(
        "verification",
        {
            "summary": "1 passed",
            "status": "passed",
            "command": "python3 -m pytest tests/test_app.py",
            "log_evidence_id": log_record.evidence_id,
        },
    )
    evidence.add(
        "audit",
        {
            "status": "pass",
            "summary": "audit pass",
            "concerns": [],
            "next_phase": "skill_distill",
        },
    )
    evidence.add(
        "handoff",
        {
            "summary": "handoff complete",
            "next_phase": "done",
            "evidence_refs": [log_record.evidence_id],
        },
    )

    store = SkillStore(tmp_path / ".skillforge" / "skills")
    candidate = SkillDistiller(store).distill(evidence.records(), workflow=workflow_template("test_fix"))
    freshness_paths = PromotionGate(store).required_freshness_paths(candidate, evidence_records=evidence.records())
    freshness_guard = FreshnessGuard.capture(tmp_path, [tmp_path / path for path in freshness_paths])
    return {
        "store": store,
        "candidate": candidate,
        "records": tuple(evidence.records()),
        "freshness_guard": freshness_guard,
        "workspace_paths": tuple(workspace_paths),
        "raw_log_text": raw_log_path.read_text(encoding="utf-8"),
    }


def test_skillforge_skills_cli_lists_and_shows_quarantine_and_active_without_raw_logs(tmp_path, capsys):
    fixture = _build_cli_verified_candidate_fixture(tmp_path)
    store = fixture["store"]
    active = store.promote(fixture["candidate"].candidate_id, skill_id="cli-active")

    store.save_candidate(
        SkillCandidate(
            candidate_id="cand-extra",
            title="Candidate extra",
            triggers=("pytest",),
            workflow_tags=("test_fix",),
            file_patterns=("tests/*.py",),
            steps=("Use log_run.",),
            verification=("Use log_failure_detail.",),
            evidence_refs=("ev-extra",),
        )
    )

    assert mini_pkg.main(["skills", "list", "--cwd", str(tmp_path)]) == 0
    list_output = capsys.readouterr().out
    assert "candidate\tcand-extra\tCandidate extra\tquarantine" in list_output
    assert f"active\t{active.skill_id}\t{active.title}" in list_output
    assert "AssertionError: expected deterministic reproduction" not in list_output

    assert mini_pkg.main(["skills", "show", "cand-extra", "--cwd", str(tmp_path)]) == 0
    candidate_payload = json.loads(capsys.readouterr().out)
    assert candidate_payload["candidate_id"] == "cand-extra"
    assert candidate_payload["status"] == "quarantine"
    assert "raw_log_path" not in json.dumps(candidate_payload)

    assert mini_pkg.main(["skills", "show", active.skill_id, "--cwd", str(tmp_path)]) == 0
    active_payload = json.loads(capsys.readouterr().out)
    assert active_payload["skill_id"] == active.skill_id
    assert active_payload["title"] == active.title


def test_skillforge_skills_cli_promote_runs_promotion_gate_and_blocks_stale_workspace(tmp_path):
    fixture = _build_cli_verified_candidate_fixture(tmp_path)
    candidate = fixture["candidate"]
    store = fixture["store"]

    touched_file = fixture["workspace_paths"][0]
    touched_file.write_text("def apply_fix():\n    return 'stale'\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="promotion gate blocked; freshness: workspace freshness is stale for:"):
        mini_pkg.main(["skills", "promote", candidate.candidate_id, "--cwd", str(tmp_path), "--skill-id", "cli-promoted"])

    assert [item.candidate_id for item in store.list_candidates()] == [candidate.candidate_id]
    assert store.list_active() == []
    assert store.list_archive() == []


def test_skillforge_skills_cli_promote_blocks_tampered_freshness_sidecar(tmp_path):
    fixture = _build_cli_verified_candidate_fixture(tmp_path)
    candidate = fixture["candidate"]
    store = fixture["store"]

    touched_file = fixture["workspace_paths"][0]
    touched_file.write_text("def apply_fix():\n    return 'stale'\n", encoding="utf-8")
    store.candidate_freshness_path(candidate.candidate_id).write_text(
        json.dumps({"root": str(tmp_path.resolve()), "files": []}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="promotion gate blocked; freshness: stored freshness scope does not match candidate evidence scope"):
        mini_pkg.main(["skills", "promote", candidate.candidate_id, "--cwd", str(tmp_path), "--skill-id", "cli-promoted"])

    assert [item.candidate_id for item in store.list_candidates()] == [candidate.candidate_id]
    assert store.list_active() == []
    assert store.list_archive() == []


def test_skillforge_skills_cli_promotes_verified_quarantined_candidate(tmp_path, capsys):
    fixture = _build_cli_verified_candidate_fixture(tmp_path)
    store = fixture["store"]
    candidate = fixture["candidate"]

    assert mini_pkg.main(["skills", "promote", candidate.candidate_id, "--cwd", str(tmp_path), "--skill-id", "cli-promoted"]) == 0
    assert "promoted\tcli-promoted" in capsys.readouterr().out
    assert [card.skill_id for card in store.list_active()] == ["cli-promoted"]
    assert [item.status for item in store.list_archive()] == ["promoted"]


def test_skillforge_skills_cli_reject_archives_candidate_as_rejected(tmp_path, capsys):
    store = SkillStore(tmp_path / ".skillforge" / "skills")
    candidate = SkillCandidate(
        candidate_id="cand-reject",
        title="Reject me",
        triggers=("pytest",),
        workflow_tags=("test_fix",),
        file_patterns=("tests/*.py",),
        steps=("Use log_run.",),
        verification=("Use log_failure_detail.",),
        evidence_refs=("ev-reject",),
    )
    store.save_candidate(candidate)

    assert mini_pkg.main(["skills", "reject", candidate.candidate_id, "--cwd", str(tmp_path)]) == 0
    assert "rejected\tcand-reject" in capsys.readouterr().out
    assert store.list_candidates() == []
    archived = store.list_archive()
    assert [item.candidate_id for item in archived] == ["cand-reject"]
    assert [item.status for item in archived] == ["rejected"]


def test_handoff_artifact_and_freshness_guard(tmp_path):
    target = tmp_path / "app.py"
    target.write_text("print('v1')\n", encoding="utf-8")
    guard = FreshnessGuard.capture(tmp_path, [target])

    handoff = HandoffArtifact(
        completed=("verification passed",),
        open_items=(),
        risks=(),
        next_phase="done",
        evidence_refs=("ev-1",),
    )
    payload = handoff.to_dict()
    assert payload["next_phase"] == "done"
    assert payload["evidence_refs"] == ["ev-1"]
    assert guard.check()["status"] == "fresh"

    target.write_text("print('v2')\n", encoding="utf-8")
    assert guard.check()["status"] == "stale"
