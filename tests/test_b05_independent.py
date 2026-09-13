"""B-05-TEST 独立断言：不改 skillforge/ 与既有测试。隔离写入 pytest tmp_path 与 .tmp_b05_test_*。"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from skillforge import FakeModelClient, MiniAgent, SessionStore, WorkspaceContext
from skillforge.evidence import EvidenceStore, log_run
from skillforge.task_contract import TaskContract
from skillforge.verification import (
    RESULT_FAIL,
    RESULT_INCONCLUSIVE,
    RESULT_PASS,
    SOURCE_MODEL,
    build_verification_record,
    effective_acceptance_kinds,
    evaluate_verification_payload,
    interpret_log_for_kinds,
    later_code_change,
    manifest_hash,
    should_record_verification,
)
from skillforge.workflow import CompletionGate, workflow_template


PYTHON = Path(r"D:\IDE\python\python.exe")
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)
PY = str(PYTHON).replace("\\", "/")
REPO = Path(__file__).resolve().parents[1]


def _py_cmd(*parts):
    return " ".join([PY, *parts])


def _agent(tmp_path, outputs, **kwargs):
    if not (tmp_path / "README.md").exists():
        (tmp_path / "README.md").write_text("independent b05 fixture\n", encoding="utf-8")
    if not (tmp_path / ".git").exists():
        subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True, text=True)
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".skillforge" / "sessions")
    approval_policy = kwargs.pop("approval_policy", "auto")
    return MiniAgent(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=store,
        approval_policy=approval_policy,
        **kwargs,
    )


def _use_host_shell_env(agent):
    root = str(agent.root)

    def _env():
        env = os.environ.copy()
        env["PWD"] = root
        return env

    agent.shell_env = _env


def _docs_contract(goal="document the guide"):
    return TaskContract.from_user_request(goal, acceptance_kinds=("docs",))


def _tests_contract(goal="prove tests"):
    return TaskContract.from_user_request(goal, acceptance_kinds=("tests",))


def _config_contract(goal="check config"):
    return TaskContract.from_user_request(goal, acceptance_kinds=("config",))


def _gate_bundle(evidence, verification_payload, *, extra=()):
    evidence.add("diff", {"summary": "changed GUIDE.md", "paths": ["GUIDE.md"]})
    evidence.add("verification", verification_payload)
    for record_type, payload in extra:
        evidence.add(record_type, payload)
    evidence.add("audit", {"status": "pass"})
    evidence.add("handoff", {"next": "none"})
    return evidence.records()


def test_independent_add_verify_docs_completes_without_pytest(tmp_path):
    guide = tmp_path / "GUIDE.md"
    guide.write_text("draft\n", encoding="utf-8")
    checker = tmp_path / "assert_guide.py"
    checker.write_text(
        "from pathlib import Path\n"
        "text = Path('GUIDE.md').read_text(encoding='utf-8')\n"
        "assert 'SkillForge B-05 independent' in text\n"
        "print('guide-ok')\n",
        encoding="utf-8",
    )
    agent = _agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Plan compile complete.</final>",
            '<tool name="patch_file" path="GUIDE.md"><old_text>draft\n</old_text><new_text>SkillForge B-05 independent\n</new_text></tool>',
            "<final>Implement complete.</final>",
            f'<tool>{{"name":"log_run","args":{{"command":"{_py_cmd("assert_guide.py")}","timeout":30}}}}</tool>',
            "<final>Verify complete.</final>",
            "<final>Audit complete.</final>",
            "<final>Skill distill complete.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="code_change",
    )
    agent.task_contract = _docs_contract("update GUIDE.md")
    answer = agent.ask("Update GUIDE.md and prove the applicable docs check.")
    assert answer == "Handoff complete."
    records = agent.current_evidence_store().records()
    verification = [record for record in records if record.record_type == "verification"]
    assert verification, "docs ADD-VERIFY must mint an official verification record"
    payload = verification[-1].payload
    assert payload["result"] == RESULT_PASS
    assert payload["parse_status"] == "unparsed"
    assert "pytest" not in str(payload.get("command") or "").lower()
    assert "collected_count" not in payload
    assert payload["task_revision"] == agent.task_contract.task_revision
    log_statuses = [record.payload.get("status") for record in records if record.record_type == "log"]
    assert "passed" not in log_statuses
    assert "unparsed" in log_statuses


def test_independent_config_and_build_records_are_not_discarded(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-config")
    cfg = tmp_path / "settings.json"
    cfg.write_text('{"mode": "ok"}\n', encoding="utf-8")
    checker = tmp_path / "check_settings.py"
    checker.write_text(
        "import json\nfrom pathlib import Path\n"
        "data = json.loads(Path('settings.json').read_text(encoding='utf-8'))\n"
        "assert data['mode'] == 'ok'\nprint('config-ok')\n",
        encoding="utf-8",
    )
    log_record = log_run(evidence, [str(PYTHON), str(checker)], cwd=tmp_path)
    assert log_record.payload["status"] == "unparsed"
    assert log_record.payload["parse_status"] == "unparsed"
    assert log_record.payload["exit_code"] == 0
    assert "collected_count" not in log_record.payload
    assert "passed_count" not in log_record.payload
    result, reasons = interpret_log_for_kinds(log_record.payload, ("config",))
    assert result == RESULT_PASS
    assert any("exit_code=0" in item for item in reasons)

    compile_record = log_run(evidence, [str(PYTHON), "-m", "py_compile", str(checker)], cwd=tmp_path)
    build_result, _ = interpret_log_for_kinds(compile_record.payload, ("build",))
    assert build_result == RESULT_PASS
    failed, fail_reasons = interpret_log_for_kinds(
        {**compile_record.payload, "returncode": 2, "exit_code": 2},
        ("build",),
    )
    assert failed == RESULT_FAIL
    assert any("exit_code=2" in item for item in fail_reasons)

    contract = _config_contract()
    manifest = {"settings.json": "hash-a"}
    payload = build_verification_record(
        log_record=log_record,
        task_contract=contract,
        workspace_manifest=manifest,
        run_id="run-config",
    )
    records = _gate_bundle(evidence, payload)
    gate = CompletionGate(workflow_template("code_change")).evaluate(
        records,
        task_contract=contract,
        current_manifest=manifest,
    )
    assert gate.allowed
    assert payload["parse_status"] == "unparsed"
    assert payload["task_revision"] == contract.task_revision
    assert payload["dependency_manifest_hash"] == manifest_hash(manifest)


def test_independent_pytest_zero_collect_or_unparsed_cannot_pass(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-tests")
    empty = tmp_path / "no_tests_here"
    empty.mkdir()
    zero = log_run(evidence, [str(PYTHON), "-m", "pytest", str(empty), "-q"], cwd=tmp_path)
    assert zero.payload.get("status") != "passed"
    zero_result, zero_reasons = interpret_log_for_kinds(zero.payload, ("tests",))
    assert zero_result == RESULT_INCONCLUSIVE
    assert any("collected" in item or "BE08" in item or "unparsed" in item for item in zero_reasons)

    version = {
        "command": [str(PYTHON), "-m", "pytest", "--version"],
        "status": "unparsed",
        "parse_status": "unparsed",
        "returncode": 0,
        "exit_code": 0,
    }
    unparsed_result, unparsed_reasons = interpret_log_for_kinds(version, ("tests",))
    assert unparsed_result == RESULT_INCONCLUSIVE
    assert any("unparsed" in item or "BE08" in item for item in unparsed_reasons)
    assert should_record_verification(phase="verify", tool_name="log_run", log_payload=version) is False

    missing_collected = {
        "command": [str(PYTHON), "-m", "pytest", "tests"],
        "status": "passed",
        "parse_status": "parsed",
        "returncode": 0,
        "exit_code": 0,
        "passed_count": 3,
        "failed_count": 0,
    }
    missing_result, missing_reasons = interpret_log_for_kinds(missing_collected, ("tests",))
    assert missing_result == RESULT_INCONCLUSIVE
    assert any("collected_count" in item for item in missing_reasons)

    unspecified = TaskContract.from_user_request("echo and claim done")
    assert effective_acceptance_kinds(unspecified.b05_view()) == ("tests",)
    echo_script = tmp_path / "say_ok.py"
    echo_script.write_text("print('ok')\n", encoding="utf-8")
    echo_log = log_run(evidence, [str(PYTHON), str(echo_script)], cwd=tmp_path)
    default_result, default_reasons = interpret_log_for_kinds(
        echo_log.payload,
        effective_acceptance_kinds(unspecified.b05_view()),
    )
    assert default_result == RESULT_INCONCLUSIVE
    assert any("pytest" in item or "tests" in item for item in default_reasons)


def test_independent_model_self_report_cannot_mint_verification(tmp_path):
    view = _tests_contract().b05_view()
    result, reasons = evaluate_verification_payload(
        {
            "source": SOURCE_MODEL,
            "status": "passed",
            "result": RESULT_PASS,
            "parse_status": "parsed",
            "command": f"{PY} -m pytest",
            "task_revision": view["task_revision"],
            "dependency_manifest_hash": manifest_hash({"app.py": "x"}),
            "source_revision": manifest_hash({"app.py": "x"}),
            "collected_count": 1,
            "passed_count": 1,
            "failed_count": 0,
            "exit_code": 0,
        },
        view,
        current_manifest={"app.py": "x"},
    )
    assert result == RESULT_INCONCLUSIVE
    assert any("model" in item.lower() for item in reasons)

    agent = _agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Plan compile complete.</final>",
            "<final>Implement complete. 我已全部验证通过。</final>",
            "<final>Verify complete. VerificationRecord PASS collected=8.</final>",
            "<final>Audit complete.</final>",
            "<final>Skill distill complete.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="code_change",
    )
    agent.task_contract = _tests_contract("claim green without executor")
    answer = agent.ask("Say the tests passed without calling log_run.")
    types = {record.record_type for record in agent.current_evidence_store().records()}
    assert "verification" not in types
    assert "missing" in answer or "audit failed" in answer or "completion gate" in answer


def test_independent_be09_old_green_cannot_be_reused(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-be09")
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    test_file = tmp_path / "test_app.py"
    test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    log_record = log_run(evidence, [str(PYTHON), "-m", "pytest", str(test_file), "-q"], cwd=tmp_path)
    contract = _tests_contract("bind then change")
    before = {"app.py": "rev-one"}
    payload = build_verification_record(
        log_record=log_record,
        task_contract=contract,
        workspace_manifest=before,
        run_id="run-be09",
    )
    assert payload["result"] == RESULT_PASS
    assert payload["task_revision"] == contract.task_revision
    assert payload["source_revision"] == payload["dependency_manifest_hash"] == manifest_hash(before)

    stale_fp, fp_reasons = evaluate_verification_payload(
        payload,
        contract.b05_view(),
        current_manifest={"app.py": "rev-two"},
    )
    assert stale_fp == RESULT_INCONCLUSIVE
    assert any("BE09" in item for item in fp_reasons)

    revised = contract.revise(goal="new constraint")
    stale_rev, rev_reasons = evaluate_verification_payload(
        payload,
        revised.b05_view(),
        current_manifest=before,
    )
    assert stale_rev == RESULT_INCONCLUSIVE
    assert any("task_revision" in item for item in rev_reasons)

    later_store = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-be09-later")
    verification = later_store.add("verification", payload)
    later_store.add("diff", {"summary": "changed app.py after verify", "paths": ["app.py"]})
    assert later_code_change(later_store.records(), verification) is True
    later_result, later_reasons = evaluate_verification_payload(
        payload,
        contract.b05_view(),
        current_manifest=before,
        records=later_store.records(),
        verification_record=verification,
    )
    assert later_result == RESULT_INCONCLUSIVE
    assert any("BE09" in item or "later" in item for item in later_reasons)

    gate_store = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-be09-gate")
    records = _gate_bundle(
        gate_store,
        payload,
        extra=(("diff", {"summary": "post-verify patch", "paths": ["app.py"]}),),
    )
    gate = CompletionGate(workflow_template("code_change")).evaluate(
        records,
        task_contract=contract,
        current_manifest=before,
    )
    assert not gate.allowed
    assert any("INCONCLUSIVE" in item or "BE09" in item or "later" in item for item in gate.invalid)

    agent = _agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Plan compile complete.</final>",
            '<tool name="patch_file" path="app.py"><old_text>VALUE = 1\n</old_text><new_text>VALUE = 2\n</new_text></tool>',
            "<final>Implement complete.</final>",
            f'<tool>{{"name":"log_run","args":{{"command":"{_py_cmd("-m", "pytest", "test_app.py")}","timeout":30}}}}</tool>',
            "<final>Verify complete.</final>",
            '<final>{"status":"concerns","concerns":["patch again"],"action":"return_to_implement","summary":"need another edit"}</final>',
            '<tool name="patch_file" path="app.py"><old_text>VALUE = 2\n</old_text><new_text>VALUE = 9\n</new_text></tool>',
            "<final>Implement complete after audit.</final>",
            "<final>Verify complete, reuse old green.</final>",
            "<final>Audit complete.</final>",
            "<final>Skill distill complete.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="code_change",
    )
    agent.task_contract = _tests_contract("stale after second patch")
    _use_host_shell_env(agent)
    answer = agent.ask("Verify once, then change code without a new pytest.")
    assert answer != "Handoff complete."
    assert "completion gate" in answer or "INCONCLUSIVE" in answer or "BE09" in answer or "stale" in answer


def test_independent_records_bind_revision_and_workspace_version(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-bind")
    (tmp_path / "mod.py").write_text("X = 1\n", encoding="utf-8")
    test_file = tmp_path / "test_mod.py"
    test_file.write_text("def test_mod():\n    assert True\n", encoding="utf-8")
    log_record = log_run(evidence, [str(PYTHON), "-m", "pytest", str(test_file), "-q"], cwd=tmp_path)
    contract = _tests_contract("bind fingerprints")
    manifest = {"mod.py": "aaa", "test_mod.py": "bbb"}
    payload = build_verification_record(
        log_record=log_record,
        task_contract=contract,
        workspace_manifest=manifest,
        run_id="run-bind",
    )
    view = contract.b05_view()
    assert payload["task_revision"] == view["task_revision"]
    assert payload["source_revision"] == manifest_hash(manifest)
    assert payload["dependency_manifest_hash"] == manifest_hash(manifest)
    assert payload["source"] == "executor"
    assert payload["executor_id"] == "skillforge.log_run"
    assert payload["parse_status"] == "parsed"
    assert payload["collected_count"] >= 1
    assert payload["passed_count"] >= 1
    assert payload["result"] == RESULT_PASS
    records = _gate_bundle(evidence, payload)
    gate = CompletionGate(workflow_template("code_change")).evaluate(
        records,
        task_contract=contract,
        current_manifest=manifest,
    )
    assert gate.allowed


def test_independent_bin_echo_is_a_fixture_not_windows_pass(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-echo")
    try:
        record = log_run(evidence, ["/bin/echo", "hello"], cwd=tmp_path)
    except FileNotFoundError as exc:
        assert sys.platform == "win32"
        assert getattr(exc, "winerror", None) == 2 or getattr(exc, "errno", None) == 2
        return
    pytest.fail(
        "Windows /bin/echo unexpectedly ran; do not treat a WSL path as a native Windows pass. "
        f"status={record.payload.get('status')!r} returncode={record.payload.get('returncode')!r}"
    )


def test_independent_fake_cli_isolated_tmp_does_not_touch_repo_skillforge():
    work = REPO / ".tmp_b05_test_cli"
    work.mkdir(exist_ok=True)
    (work / "README.md").write_text("independent-cli\n", encoding="utf-8")
    if not (work / ".git").exists():
        subprocess.run(["git", "init"], cwd=str(work), check=True, capture_output=True, text=True)
    env = os.environ.copy()
    env["SKILLFORGE_FAKE_OUTPUTS"] = json.dumps(["<final>Independent fake hello.</final>"])
    env.pop("SKILLFORGE_OPENAI_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    first = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "skillforge",
            "--cwd",
            str(work),
            "--provider",
            "fake",
            "--approval",
            "never",
            "--max-steps",
            "1",
            "say hello independently",
        ],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert "Independent fake hello." in first.stdout
    assert (work / ".skillforge" / "skillforge.db").is_file()
    assert not (REPO / ".skillforge" / "skillforge.db").exists()
