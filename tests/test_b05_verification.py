"""B-05：VerificationRecord 接入 CompletionGate（ADD-VERIFY / BE08 / BE09）。"""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from skillforge import FakeModelClient, MiniAgent, SessionStore, WorkspaceContext
from skillforge.evidence import EvidenceStore, log_run
from skillforge.task_contract import TaskContract
from skillforge.verification import (
    RESULT_FAIL,
    RESULT_INCONCLUSIVE,
    RESULT_PASS,
    SOURCE_MODEL,
    build_verification_record,
    evaluate_verification_payload,
    interpret_log_for_kinds,
    manifest_hash,
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
        (tmp_path / "README.md").write_text("workflow fixture\n", encoding="utf-8")
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
    """log_run 走受控执行器，但 Windows 过滤后的 shell_env 可能让 pytest 无法解析；测试里恢复宿主环境。"""
    root = str(agent.root)

    def _env():
        env = os.environ.copy()
        env["PWD"] = root
        return env

    agent.shell_env = _env


def _docs_contract(goal="update docs"):
    return TaskContract.from_user_request(goal, acceptance_kinds=("docs",))


def _tests_contract(goal="fix tests"):
    return TaskContract.from_user_request(goal, acceptance_kinds=("tests",))


def _build_contract(goal="type/build check"):
    return TaskContract.from_user_request(goal, acceptance_kinds=("build",))


def test_log_run_non_pytest_records_exit_and_parse_status_never_pass(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-1")
    script = tmp_path / "hello_b05.py"
    script.write_text("print('b05-hello')\n", encoding="utf-8")
    record = log_run(evidence, [str(PYTHON), str(script)], cwd=tmp_path)
    assert record.payload["status"] == "unparsed"
    assert record.payload["status"] != "passed"
    assert record.payload["parse_status"] == "unparsed"
    assert record.payload["returncode"] == 0
    assert record.payload["exit_code"] == 0
    assert "collected_count" not in record.payload
    assert "passed_count" not in record.payload


def test_docs_kind_allows_non_pytest_exit_zero(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-docs")
    script = tmp_path / "check_docs.py"
    script.write_text(
        "from pathlib import Path\nassert Path('README.md').exists()\nprint('docs-ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# docs\n", encoding="utf-8")
    log_record = log_run(evidence, [str(PYTHON), str(script)], cwd=tmp_path)
    result, reasons = interpret_log_for_kinds(log_record.payload, ("docs",))
    assert result == RESULT_PASS
    assert log_record.payload["parse_status"] == "unparsed"
    assert any("exit_code=0" in item for item in reasons)


def test_build_kind_keeps_non_pytest_command_not_discarded(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-build")
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    log_record = log_run(evidence, [str(PYTHON), "-m", "py_compile", "app.py"], cwd=tmp_path)
    assert log_record.payload["status"] == "unparsed"
    assert "collected_count" not in log_record.payload
    result, _reasons = interpret_log_for_kinds(log_record.payload, ("build",))
    assert result == RESULT_PASS
    failed, fail_reasons = interpret_log_for_kinds({**log_record.payload, "returncode": 1, "exit_code": 1}, ("build",))
    assert failed == RESULT_FAIL
    assert any("exit_code=1" in item for item in fail_reasons)


def test_tests_kind_zero_collection_is_inconclusive(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-zero")
    empty = tmp_path / "empty_suite"
    empty.mkdir()
    record = log_run(evidence, [str(PYTHON), "-m", "pytest", str(empty), "-q"], cwd=tmp_path)
    assert record.payload["status"] != "passed"
    assert record.payload.get("parse_status") in {"parsed", "unparsed"}
    if record.payload.get("parse_status") == "parsed":
        assert record.payload.get("collected_count") == 0
    result, reasons = interpret_log_for_kinds(record.payload, ("tests",))
    assert result == RESULT_INCONCLUSIVE
    assert any("BE08" in item or "collected" in item or "pytest" in item for item in reasons)


def test_tests_kind_unparsed_pytest_cannot_pass():
    payload = {
        "command": ["python", "-m", "pytest", "--version"],
        "status": "unparsed",
        "parse_status": "unparsed",
        "returncode": 0,
        "exit_code": 0,
    }
    result, reasons = interpret_log_for_kinds(payload, ("tests",))
    assert result == RESULT_INCONCLUSIVE
    assert any("unparsed" in item or "BE08" in item for item in reasons)


def test_missing_collected_count_fact_is_inconclusive_for_tests():
    payload = {
        "command": ["python", "-m", "pytest", "tests"],
        "status": "passed",
        "parse_status": "parsed",
        "returncode": 0,
        "exit_code": 0,
        "parsed_summary": "1 passed",
        "passed_count": 1,
        "failed_count": 0,
    }
    result, reasons = interpret_log_for_kinds(payload, ("tests",))
    assert result == RESULT_INCONCLUSIVE
    assert any("collected_count" in item for item in reasons)


def test_model_source_cannot_be_official_verification():
    view = _tests_contract().b05_view()
    result, reasons = evaluate_verification_payload(
        {
            "source": SOURCE_MODEL,
            "status": "passed",
            "result": RESULT_PASS,
            "parse_status": "parsed",
            "command": "python -m pytest",
            "task_revision": 1,
            "dependency_manifest_hash": "abc",
            "source_revision": "abc",
            "collected_count": 1,
            "passed_count": 1,
            "failed_count": 0,
        },
        view,
        current_manifest={"app.py": "hash"},
    )
    assert result == RESULT_INCONCLUSIVE
    assert any("model" in item for item in reasons)


def test_gate_reads_task_contract_b05_view(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-view")
    evidence.add("diff", {"summary": "changed README.md", "paths": ["README.md"]})
    evidence.add("audit", {"status": "pass"})
    evidence.add("handoff", {"next": "none"})
    (tmp_path / "README.md").write_text("ok\n", encoding="utf-8")
    script = tmp_path / "check_docs.py"
    script.write_text("print('docs-ok')\n", encoding="utf-8")
    log_record = log_run(evidence, [str(PYTHON), str(script)], cwd=tmp_path)
    contract = _docs_contract()
    manifest = {"README.md": "ok"}
    payload = build_verification_record(
        log_record=log_record,
        task_contract=contract,
        workspace_manifest=manifest,
        run_id="run-view",
    )
    evidence.add("verification", payload)
    with patch.object(TaskContract, "b05_view", wraps=contract.b05_view) as mocked:
        result = CompletionGate(workflow_template("code_change")).evaluate(
            evidence.records(),
            task_contract=contract,
            current_manifest=manifest,
        )
    mocked.assert_called()
    view = contract.b05_view()
    assert view["acceptance_requirements"] == ["docs"]
    assert view["task_revision"] == 1
    assert payload["task_revision"] == 1
    assert payload["source_revision"]
    assert payload["dependency_manifest_hash"] == manifest_hash(manifest)
    assert payload["parse_status"] == "unparsed"
    assert payload["status"] == "passed"
    assert result.allowed


def test_be09_stale_after_file_change(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-be09")
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    test_file = tmp_path / "test_app.py"
    test_file.write_text("def test_value():\n    assert True\n", encoding="utf-8")
    log_record = log_run(evidence, [str(PYTHON), "-m", "pytest", str(test_file), "-q"], cwd=tmp_path)
    contract = _tests_contract()
    before = {"app.py": "one"}
    payload = build_verification_record(
        log_record=log_record,
        task_contract=contract,
        workspace_manifest=before,
    )
    assert payload["result"] == RESULT_PASS
    result, reasons = evaluate_verification_payload(
        payload,
        contract.b05_view(),
        current_manifest={"app.py": "two"},
    )
    assert result == RESULT_INCONCLUSIVE
    assert any("BE09" in item for item in reasons)


def test_add_verify_docs_task_completes_without_pytest(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("before\n", encoding="utf-8")
    checker = tmp_path / "check_docs.py"
    checker.write_text(
        "from pathlib import Path\nassert Path('README.md').read_text(encoding='utf-8').startswith('after')\nprint('docs-ok')\n",
        encoding="utf-8",
    )
    agent = _agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Plan compile complete.</final>",
            '<tool name="patch_file" path="README.md"><old_text>before\n</old_text><new_text>after\n</new_text></tool>',
            "<final>Implement complete.</final>",
            f'<tool>{{"name":"log_run","args":{{"command":"{_py_cmd("check_docs.py")}","timeout":30}}}}</tool>',
            "<final>Verify complete.</final>",
            "<final>Audit complete.</final>",
            "<final>Skill distill complete.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="code_change",
    )
    agent.task_contract = _docs_contract("update the readme")
    answer = agent.ask("Update the README and prove the file exists.")
    assert answer == "Handoff complete."
    records = agent.current_evidence_store().records()
    verification = [record for record in records if record.record_type == "verification"]
    assert verification
    payload = verification[-1].payload
    assert payload["status"] == "passed"
    assert payload["result"] == RESULT_PASS
    assert payload["parse_status"] == "unparsed"
    assert "pytest" not in payload["command"]
    assert payload["task_revision"] == agent.task_contract.task_revision
    assert payload["source_revision"]
    assert payload["log_artifact_id"]
    log_types = [record.payload.get("status") for record in records if record.record_type == "log"]
    assert "unparsed" in log_types
    assert "passed" not in log_types


def test_build_check_is_recorded_and_can_complete(tmp_path):
    app = tmp_path / "app.py"
    app.write_text("VALUE = 1\n", encoding="utf-8")
    agent = _agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Plan compile complete.</final>",
            '<tool name="patch_file" path="app.py"><old_text>VALUE = 1\n</old_text><new_text>VALUE = 2\n</new_text></tool>',
            "<final>Implement complete.</final>",
            f'<tool>{{"name":"log_run","args":{{"command":"{_py_cmd("-m", "py_compile", "app.py")}","timeout":30}}}}</tool>',
            "<final>Verify complete.</final>",
            "<final>Audit complete.</final>",
            "<final>Skill distill complete.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="code_change",
    )
    agent.task_contract = _build_contract()
    answer = agent.ask("Change the constant and compile-check the file.")
    assert answer == "Handoff complete."
    payload = [record.payload for record in agent.current_evidence_store().records() if record.record_type == "verification"][-1]
    assert payload["parse_status"] == "unparsed"
    assert payload["exit_code"] == 0
    assert payload["result"] == RESULT_PASS
    assert "collected_count" not in payload


def test_model_text_passed_does_not_create_verification(tmp_path):
    agent = _agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Plan compile complete.</final>",
            "<final>Implement complete. 测试已通过。</final>",
            "<final>Verify complete. 已通过，全部测试通过。</final>",
            "<final>Audit complete.</final>",
            "<final>Skill distill complete.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="code_change",
    )
    agent.task_contract = _tests_contract()
    answer = agent.ask("Claim the tests passed in prose.")
    assert "verification" not in {record.record_type for record in agent.current_evidence_store().records()}
    assert "missing" in answer or "audit failed" in answer


def test_be09_later_patch_invalidates_old_verification(tmp_path):
    app_file = tmp_path / "app.py"
    app_file.write_text("VALUE = 1\n", encoding="utf-8")
    test_file = tmp_path / "test_app.py"
    test_file.write_text(
        "from app import VALUE\n\n"
        "def test_value():\n"
        "    assert VALUE == 2\n",
        encoding="utf-8",
    )
    agent = _agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Plan compile complete.</final>",
            '<tool name="patch_file" path="app.py"><old_text>VALUE = 1\n</old_text><new_text>VALUE = 2\n</new_text></tool>',
            "<final>Implement complete.</final>",
            f'<tool>{{"name":"log_run","args":{{"command":"{_py_cmd("-m", "pytest", "test_app.py")}","timeout":30}}}}</tool>',
            "<final>Verify complete.</final>",
            '<final>{"status":"concerns","concerns":["revise once after verification"],"action":"return_to_implement","summary":"Audit wants another implementation pass."}</final>',
            '<tool name="patch_file" path="app.py"><old_text>VALUE = 2\n</old_text><new_text>VALUE = 3\n</new_text></tool>',
            "<final>Implement complete after audit feedback.</final>",
            "<final>Verify complete without rerunning tests.</final>",
            "<final>Audit pass after revision.</final>",
            "<final>Skill distill complete.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="code_change",
    )
    agent.task_contract = _tests_contract("update the constant")
    _use_host_shell_env(agent)
    answer = agent.ask("Patch, verify, then patch again without re-verify.")
    assert answer != "Handoff complete."
    assert "completion gate" in answer or "INCONCLUSIVE" in answer or "BE09" in answer or "stale" in answer
    records = agent.current_evidence_store().records()
    verification = [record for record in records if record.record_type == "verification"]
    assert verification
    assert verification[-1].payload.get("result") == RESULT_PASS or verification[-1].payload.get("status") == "passed"


def test_tests_task_records_bind_revision_and_fingerprint(tmp_path):
    app_file = tmp_path / "app.py"
    app_file.write_text("VALUE = 1\n", encoding="utf-8")
    test_file = tmp_path / "test_app.py"
    test_file.write_text(
        "from app import VALUE\n\n"
        "def test_value():\n"
        "    assert VALUE == 2\n",
        encoding="utf-8",
    )
    agent = _agent(
        tmp_path,
        [
            "<final>Intake complete.</final>",
            "<final>Plan compile complete.</final>",
            '<tool name="patch_file" path="app.py"><old_text>VALUE = 1\n</old_text><new_text>VALUE = 2\n</new_text></tool>',
            "<final>Implement complete.</final>",
            f'<tool>{{"name":"log_run","args":{{"command":"{_py_cmd("-m", "pytest", "test_app.py")}","timeout":30}}}}</tool>',
            "<final>Verify complete.</final>",
            "<final>Audit complete.</final>",
            "<final>Skill distill complete.</final>",
            "<final>Handoff complete.</final>",
        ],
        workflow="code_change",
    )
    agent.task_contract = _tests_contract()
    _use_host_shell_env(agent)
    answer = agent.ask("Update the constant and verify the targeted pytest file.")
    assert answer == "Handoff complete."
    payload = [record.payload for record in agent.current_evidence_store().records() if record.record_type == "verification"][-1]
    assert payload["task_revision"] == agent.task_contract.task_revision
    assert payload["source_revision"] == payload["dependency_manifest_hash"]
    assert payload["parse_status"] == "parsed"
    assert payload["collected_count"] >= 1
    assert payload["passed_count"] >= 1
    assert payload["result"] == RESULT_PASS
    assert payload["executor_id"] == "skillforge.log_run"
    assert payload["source"] == "executor"


def test_manual_kind_cannot_be_passed_by_executor(tmp_path):
    evidence = EvidenceStore(tmp_path / ".skillforge" / "runs" / "run-manual")
    script = tmp_path / "ok.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    log_record = log_run(evidence, [str(PYTHON), str(script)], cwd=tmp_path)
    result, reasons = interpret_log_for_kinds(log_record.payload, ("manual",))
    assert result == RESULT_INCONCLUSIVE
    assert any("user" in item for item in reasons)


def test_fake_cli_one_shot_still_exits_zero():
    work = REPO / ".tmp_b05_cli"
    work.mkdir(exist_ok=True)
    (work / "README.md").write_text("cli\n", encoding="utf-8")
    if not (work / ".git").exists():
        subprocess.run(["git", "init"], cwd=str(work), check=True, capture_output=True, text=True)
    env = os.environ.copy()
    env["SKILLFORGE_FAKE_OUTPUTS"] = json.dumps(["<final>Hello from fake.</final>"])
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
            "say hello",
        ],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert "Hello from fake." in first.stdout
    assert (work / ".skillforge" / "skillforge.db").is_file()
    assert not (REPO / ".skillforge" / "skillforge.db").exists()
