import json

import pytest

from skillforge.skills import SkillCandidate, SkillCard, SkillStore


def _candidate(**overrides):
    payload = {
        "candidate_id": "cand-pytest",
        "title": "Pytest failure triage",
        "triggers": ("pytest",),
        "workflow_tags": ("test_fix",),
        "file_patterns": ("tests/*.py",),
        "steps": ("Run log_run on pytest.",),
        "verification": ("Use log_failure_detail before editing.",),
        "evidence_refs": ("ev-1",),
    }
    payload.update(overrides)
    return SkillCandidate(**payload)


def _card(**overrides):
    payload = {
        "skill_id": "pytest-failure-triage",
        "title": "Pytest failure triage",
        "triggers": ("pytest",),
        "workflow_tags": ("test_fix",),
        "file_patterns": ("tests/*.py",),
        "steps": ("Run log_run on pytest.",),
        "verification": ("Use log_failure_detail before editing.",),
    }
    payload.update(overrides)
    return SkillCard(**payload)


def test_skill_candidate_schema_defaults_to_quarantine_and_round_trips_strictly():
    candidate = _candidate()

    payload = candidate.to_dict()

    assert payload["schema_version"] == "skill-candidate-v1"
    assert payload["artifact_type"] == "skill_candidate"
    assert payload["candidate_id"] == "cand-pytest"
    assert payload["status"] == "quarantine"
    assert SkillCandidate.from_dict(payload) == candidate

    with pytest.raises(ValueError, match="unexpected fields"):
        SkillCandidate.from_dict({**payload, "extra": True})


def test_skill_card_schema_round_trips_strictly():
    card = _card(uses=3, successes=2, failures=1, last_used="2026-06-28T12:00:00+00:00")

    payload = card.to_dict()

    assert payload["schema_version"] == "skill-card-v1"
    assert payload["artifact_type"] == "skill_card"
    assert payload["uses"] == 3
    assert SkillCard.from_dict(payload) == card

    with pytest.raises(ValueError, match="unexpected fields"):
        SkillCard.from_dict({**payload, "extra": True})


def test_skill_store_persists_active_candidates_and_archive_layout(tmp_path):
    store = SkillStore(tmp_path / ".skillforge" / "skills")
    candidate = _candidate()

    assert store.root == tmp_path / ".skillforge" / "skills"
    assert store.active_root.is_dir()
    assert store.candidate_root.is_dir()
    assert store.archive_root.is_dir()

    candidate_path = store.save_candidate(candidate)
    assert candidate_path == store.candidate_root / "cand-pytest.json"
    assert store.list_candidates() == [candidate]

    active = _card()
    active_path = store.save_active(active)
    assert active_path == store.active_root / "pytest-failure-triage.json"
    assert store.list_active() == [active]

    promoted = store.promote(candidate.candidate_id, skill_id="cand-promoted")
    assert promoted.skill_id == "cand-promoted"
    assert store.list_candidates() == []
    assert [item.candidate_id for item in store.list_archive()] == ["cand-pytest"]


def test_skill_store_rejects_non_quarantine_candidate_and_candidate_schema_in_active_slot(tmp_path):
    store = SkillStore(tmp_path / ".skillforge" / "skills")

    with pytest.raises(ValueError, match="quarantine"):
        store.save_candidate(_candidate(status="promoted"))

    misplaced_path = store.active_root / "misplaced.json"
    misplaced_path.write_text(json.dumps(_candidate().to_dict(), indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="skill card"):
        store.list_active()


def test_skill_store_updates_active_skill_stats_without_touching_candidates_or_archive(tmp_path):
    store = SkillStore(tmp_path / ".skillforge" / "skills")
    active = _card()
    candidate = _candidate(candidate_id="cand-keep")
    archived = _candidate(candidate_id="cand-archived", status="rejected")

    store.save_active(active)
    store.save_candidate(candidate)
    store.save_archive(archived)

    used = store.record_active_use(active.skill_id, used_at="2026-06-28T12:00:00+00:00")
    assert used.uses == 1
    assert used.successes == 0
    assert used.failures == 0
    assert used.last_used == "2026-06-28T12:00:00+00:00"

    succeeded = store.record_active_result(active.skill_id, succeeded=True)
    assert succeeded.uses == 1
    assert succeeded.successes == 1
    assert succeeded.failures == 0
    assert succeeded.last_used == "2026-06-28T12:00:00+00:00"

    failed = store.record_active_result(active.skill_id, succeeded=False)
    assert failed.uses == 1
    assert failed.successes == 1
    assert failed.failures == 1
    assert failed.last_used == "2026-06-28T12:00:00+00:00"

    assert store.list_candidates() == [candidate]
    assert store.list_archive() == [archived]
