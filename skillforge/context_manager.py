"""Prompt 组装与上下文预算控制。

这个模块负责决定：每一轮到底把多少 prefix、memory、相关笔记、历史
以及当前用户请求送进模型。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .compaction import (
    DEFAULT_INPUT_CAP_I,
    DEFAULT_MARGIN_M,
    DEFAULT_RESERVED_R,
    DEFAULT_SOFT_RATIO,
    DEFAULT_WINDOW_W,
    TOKEN_ESTIMATE_SOURCE,
    current_compaction,
    evaluate_admission,
    group_history,
    remaining_rounds_heuristic,
)
from .prompt_manifest import STABLE_BOUNDARY


DEFAULT_TOTAL_BUDGET = 12000
DEFAULT_SECTION_BUDGETS = {
    "prefix": 3600,
    "memory": 1600,
    "relevant_memory": 1200,
    "history": 5200,
}
DEFAULT_SECTION_FLOORS = {
    "prefix": 1200,
    "memory": 400,
    "relevant_memory": 300,
    "history": 1500,
}
# 当 prompt 超预算时，会优先压缩这些 section。
DEFAULT_REDUCTION_ORDER = ("relevant_memory", "history", "memory", "prefix")
SECTION_ORDER = ("prefix", "memory", "relevant_memory", "history", "current_request")
CURRENT_REQUEST_SECTION = "current_request"
RELEVANT_MEMORY_LIMIT = 3


def _tail_clip(text, limit):
    text = str(text)
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


@dataclass
class SectionRender:
    raw: str
    budget: int
    rendered: str
    details: dict | None = None

    @property
    def raw_chars(self):
        return len(self.raw)

    @property
    def rendered_chars(self):
        return len(self.rendered)


class ContextManager:
    def __init__(
        self,
        agent,
        total_budget=DEFAULT_TOTAL_BUDGET,
        section_budgets=None,
        section_floors=None,
        reduction_order=None,
        token_window_w=DEFAULT_WINDOW_W,
        token_input_cap=DEFAULT_INPUT_CAP_I,
        token_reserved=DEFAULT_RESERVED_R,
        token_margin=DEFAULT_MARGIN_M,
        token_soft_ratio=DEFAULT_SOFT_RATIO,
    ):
        self.agent = agent
        self.total_budget = int(total_budget)
        self.section_budgets = dict(DEFAULT_SECTION_BUDGETS)
        if section_budgets:
            self.section_budgets.update({str(key): int(value) for key, value in section_budgets.items()})
        self._section_floor_overrides = {str(key): int(value) for key, value in (section_floors or {}).items()}
        self.section_floors = self._compute_section_floors()
        self.reduction_order = tuple(reduction_order or DEFAULT_REDUCTION_ORDER)
        self.token_window_w = int(token_window_w)
        self.token_input_cap = int(token_input_cap)
        self.token_reserved = int(token_reserved)
        self.token_margin = int(token_margin)
        self.token_soft_ratio = float(token_soft_ratio)

    def build(self, user_message):
        """按预算组装一轮完整 prompt。

        为什么存在：
        仅靠用户这一轮输入，模型并不知道当前仓库状态、会话里已经读过什么、
        哪些旧信息还值得继续参考。这个函数负责把“稳定基线 + 工作记忆 +
        相关笔记 + 历史 + 当前请求”拼成真正发给模型的 prompt。

        输入 / 输出：
        - 输入：`user_message`，也就是用户当前这一轮的新请求。
        - 输出：`(prompt, metadata)`。
          `prompt` 是最终发送给模型的文本；
          `metadata` 记录了每个 section 的原始长度、裁剪后的长度、是否触发了
          预算收缩等信息，后续会进入 trace/report，便于解释这轮 prompt
          是怎么被拼出来的。

        在 agent 链路里的位置：
        它位于 `SkillForge.ask()` 的每轮模型调用之前，是“真正发请求给模型”
        的最后一道组装工序。`WorkspaceContext` 提供稳定前缀，`LayeredMemory`
        提供工作记忆，这个函数则把它们和当前请求合成一份可控大小的 prompt。
        """
        user_message = str(user_message)
        self.section_floors = self._compute_section_floors()
        memory_enabled = True
        relevant_memory_enabled = True
        context_reduction_enabled = True
        if hasattr(self.agent, "feature_enabled"):
            memory_enabled = self.agent.feature_enabled("memory")
            relevant_memory_enabled = self.agent.feature_enabled("relevant_memory")
            context_reduction_enabled = self.agent.feature_enabled("context_reduction")
        section_texts = {
            "prefix": str(getattr(self.agent, "prefix", "")),
            "memory": "Memory:\n- disabled" if not memory_enabled else str(self.agent.memory_text()),
            "history": "",
            CURRENT_REQUEST_SECTION: f"Current user request:\n{user_message}",
        }
        dynamic_text = self._dynamic_tail_text()
        selected_notes = []
        if memory_enabled and relevant_memory_enabled and hasattr(self.agent, "memory") and hasattr(self.agent.memory, "retrieval_candidates"):
            selected_notes = self.agent.memory.retrieval_candidates(user_message, limit=RELEVANT_MEMORY_LIMIT)

        if not context_reduction_enabled:
            rendered = self._render_sections_without_reduction(section_texts, selected_notes=selected_notes)
            prompt = self._assemble_prompt(rendered, dynamic_text=dynamic_text)
            metadata = self._metadata(
                prompt=prompt,
                rendered=rendered,
                budgets={section: render.budget for section, render in rendered.items() if section != CURRENT_REQUEST_SECTION},
                reduction_log=[],
                selected_notes=selected_notes,
                user_message=user_message,
                section_texts=section_texts,
                dynamic_text=dynamic_text,
            )
            return prompt, metadata

        budgets = dict(self.section_budgets)
        rendered = self._render_sections(section_texts, budgets, selected_notes=selected_notes)
        prompt = self._assemble_prompt(rendered, include_dynamic=False)
        reduction_log = []

        # 如果 prompt 超预算，就按固定顺序不断压缩。
        # 这里的顺序体现了平台偏好：
        # 先牺牲 relevant_memory，再牺牲 history，然后才动 memory 和 prefix。
        # 最新用户请求永远不裁剪，因为那是本轮最重要的输入。
        # 动态尾部不参与收缩，以免 checkpoint / git status 把 relevant_memory 额外压扁。
        while len(prompt) > self.total_budget:
            overflow = len(prompt) - self.total_budget
            reduced = False
            for section in self.reduction_order:
                floor = int(self.section_floors.get(section, 0))
                current_budget = int(budgets.get(section, 0))
                if current_budget <= floor:
                    continue
                new_budget = max(floor, current_budget - overflow)
                if new_budget >= current_budget:
                    continue
                reduction_log.append(
                    {
                        "section": section,
                        "before_chars": current_budget,
                        "after_chars": new_budget,
                        "overflow_chars": overflow,
                    }
                )
                budgets[section] = new_budget
                rendered = self._render_sections(section_texts, budgets, selected_notes=selected_notes)
                prompt = self._assemble_prompt(rendered, include_dynamic=False)
                reduced = True
                break
            if not reduced:
                break

        prompt = self._assemble_prompt(rendered, dynamic_text=dynamic_text, include_dynamic=True)
        metadata = self._metadata(
            prompt=prompt,
            rendered=rendered,
            budgets=budgets,
            reduction_log=reduction_log,
            selected_notes=selected_notes,
            user_message=user_message,
            section_texts=section_texts,
            dynamic_text=dynamic_text,
        )
        return prompt, metadata

    def _render_sections_without_reduction(self, section_texts, selected_notes=None):
        selected_notes = selected_notes or []
        relevant_lines = ["Relevant memory:"]
        if selected_notes:
            relevant_lines.extend(f"- {note['text']}" for note in selected_notes)
        else:
            relevant_lines.append("- none")
        relevant_raw = "\n".join(relevant_lines)
        history = self._view_history()
        history_raw = self._raw_history_text(history)
        return {
            "prefix": SectionRender(raw=section_texts["prefix"], budget=len(section_texts["prefix"]), rendered=section_texts["prefix"], details={}),
            "memory": SectionRender(raw=section_texts["memory"], budget=len(section_texts["memory"]), rendered=section_texts["memory"], details={}),
            "relevant_memory": SectionRender(
                raw=relevant_raw,
                budget=len(relevant_raw),
                rendered=relevant_raw,
                details={
                    "selected_notes": [note["text"] for note in selected_notes],
                    "rendered_notes": [note["text"] for note in selected_notes],
                    "selected_count": len(selected_notes),
                    "rendered_count": len(selected_notes),
                    "note_budget": 0,
                },
            ),
            "history": SectionRender(raw=history_raw, budget=len(history_raw), rendered=history_raw, details={"rendered_entries": []}),
            CURRENT_REQUEST_SECTION: SectionRender(
                raw=section_texts[CURRENT_REQUEST_SECTION],
                budget=0,
                rendered=section_texts[CURRENT_REQUEST_SECTION],
                details={},
            ),
        }

    def _compute_section_floors(self):
        floors = {
            section: max(20, int(budget) // 4)
            for section, budget in self.section_budgets.items()
        }
        floors.update(self._section_floor_overrides)
        return floors

    def _render_sections(self, section_texts, budgets, selected_notes=None):
        rendered = {}
        for section in SECTION_ORDER:
            budget = budgets.get(section)
            if section == CURRENT_REQUEST_SECTION:
                raw = section_texts[section]
                rendered[section] = SectionRender(raw=raw, budget=0, rendered=raw, details={})
            elif section == "relevant_memory":
                rendered[section] = self._render_relevant_memory(selected_notes or [], int(budget or 0))
            elif section == "history":
                rendered[section] = self._render_history_section(int(budget or 0))
            else:
                raw = section_texts[section]
                rendered_text = _tail_clip(raw, int(budget)) if budget is not None else raw
                rendered[section] = SectionRender(raw=raw, budget=int(budget) if budget is not None else 0, rendered=rendered_text, details={})
        return rendered

    def _render_relevant_memory(self, selected_notes, budget):
        header = "Relevant memory:"
        note_texts = [str(note.get("text", "")) for note in selected_notes if str(note.get("text", "")).strip()]
        raw_lines = [header] + [f"- {text}" for text in note_texts]
        raw = "\n".join(raw_lines) if note_texts else "\n".join([header, "- none"])
        if not note_texts:
            rendered = raw
            return SectionRender(
                raw=raw,
                budget=budget,
                rendered=rendered,
                details={
                    "selected_notes": [],
                    "rendered_notes": [],
                    "selected_count": 0,
                    "rendered_count": 0,
                    "note_budget": 0,
                },
            )

        per_note_budget = self._per_note_budget(budget, len(note_texts), header)
        rendered_notes = []
        while True:
            # 让每条 note 平分这一段的预算，避免一条超长笔记把其他笔记都挤掉。
            rendered_notes = [_tail_clip(text, per_note_budget) for text in note_texts]
            rendered = "\n".join([header] + [f"- {text}" for text in rendered_notes])
            if len(rendered) <= budget or per_note_budget <= 1:
                break
            per_note_budget -= 1

        if len(rendered) > budget and budget > 0:
            rendered = _tail_clip(raw, budget)
            rendered_notes = [rendered]

        return SectionRender(
            raw=raw,
            budget=budget,
            rendered=rendered,
            details={
                "selected_notes": note_texts,
                "rendered_notes": rendered_notes,
                "selected_count": len(note_texts),
                "rendered_count": len(rendered_notes),
                "note_budget": per_note_budget,
            },
        )

    def _per_note_budget(self, budget, note_count, header):
        if note_count <= 0:
            return 0
        overhead = len(header) + 3 * note_count
        usable = max(0, budget - overhead)
        return max(1, usable // note_count)

    def _view_history(self):
        """模型视图 V：压缩覆盖的区间不再进入 transcript，原文仍留在 E。"""
        history = list(getattr(self.agent, "session", {}).get("history", []) or [])
        checkpoint = current_compaction(getattr(self.agent, "session", {}) or {})
        if not checkpoint:
            return history
        through = checkpoint.get("source_through_seq")
        if through is None:
            return history
        return [item for index, item in enumerate(history) if index > int(through)]

    def _render_history_section(self, budget):
        history = self._view_history()
        raw = self._raw_history_text(history)
        if not history:
            rendered = "Transcript:\n- empty"
            return SectionRender(
                raw=raw,
                budget=budget,
                rendered=rendered,
                details={
                    "rendered_entries": [],
                    "older_entries_count": 0,
                    "collapsed_duplicate_reads": 0,
                    "reused_file_summary_count": 0,
                    "summarized_tool_count": 0,
                    "open_groups_preserved": 0,
                },
            )

        # 优先保留最近的历史，因为下一步决策通常最依赖刚刚发生的工具结果。
        # 保留单元是完整交互组：未闭合组整组留下，不按单条切断。
        recent_window = 6
        recent_start = max(0, len(history) - recent_window)
        history_entries, history_details = self._compressed_history_entries(history, recent_start)
        rendered_entries = []
        for entry in reversed(history_entries):
            recent = bool(entry.get("recent", False))
            protected = bool(entry.get("protected", False))
            candidate_lines = list(entry.get("lines", []))
            candidate_entries = candidate_lines + rendered_entries
            candidate_rendered = "\n".join(["Transcript:", *candidate_entries])
            if len(candidate_rendered) <= budget:
                rendered_entries = candidate_entries
                continue
            if protected:
                # 未闭合组 / 待审批：即使超预算也整组保留，不拆调用与结果。
                rendered_entries = candidate_entries
                continue
            if recent:
                available = budget - len("Transcript:")
                if rendered_entries:
                    available -= sum(len(line) + 1 for line in rendered_entries)
                available = max(20, available - 1)
                candidate_lines = [_tail_clip(line, available) for line in candidate_lines]
                candidate_entries = candidate_lines + rendered_entries
                candidate_rendered = "\n".join(["Transcript:", *candidate_entries])
                if len(candidate_rendered) <= budget:
                    rendered_entries = candidate_entries
            else:
                smaller_lines = [_tail_clip(line, 20) for line in candidate_lines]
                smaller_entries = smaller_lines + rendered_entries
                smaller_rendered = "\n".join(["Transcript:", *smaller_entries])
                if len(smaller_rendered) <= budget:
                    rendered_entries = smaller_entries
        rendered = "\n".join(["Transcript:", *rendered_entries])

        # 保护组存在时不要用原文尾部裁剪把调用组切断。
        if len(rendered) > budget and budget > 0 and not history_details.get("open_groups_preserved"):
            rendered = _tail_clip(raw, budget)

        return SectionRender(
            raw=raw,
            budget=budget,
            rendered=rendered,
            details={
                "recent_window": recent_window,
                "recent_start": recent_start,
                "rendered_entries": rendered_entries,
                **history_details,
            },
        )

    def _compressed_history_entries(self, history, recent_start):
        entries = []
        seen_older_reads = set()
        details = {
            "older_entries_count": 0,
            "collapsed_duplicate_reads": 0,
            "reused_file_summary_count": 0,
            "summarized_tool_count": 0,
            "open_groups_preserved": 0,
        }
        groups = group_history(history)

        for group in groups:
            protected = (not group.closed) or group.pending_approval
            recent = group.seq_end >= recent_start
            if protected:
                details["open_groups_preserved"] += 1
                lines = []
                for item in group.items:
                    lines.extend(self._render_history_item(item, 900))
                entries.append({"recent": True, "protected": True, "lines": lines, "group_id": group.group_id})
                continue
            if recent:
                lines = []
                for item in group.items:
                    lines.extend(self._render_history_item(item, 900))
                entries.append({"recent": True, "protected": False, "lines": lines, "group_id": group.group_id})
                continue

            group_lines = []
            for item in group.items:
                if item.get("role") == "tool" and item.get("name") == "read_file":
                    path = str((item.get("args") or {}).get("path", "")).strip()
                    if path in seen_older_reads:
                        details["collapsed_duplicate_reads"] += 1
                        continue
                    if path:
                        seen_older_reads.add(path)
                    summary = self._reusable_file_summary(path)
                    if summary:
                        group_lines.append(f"{path} -> {summary}")
                        details["reused_file_summary_count"] += 1
                        details["older_entries_count"] += 1
                        continue
                if item.get("role") == "tool":
                    group_lines.append(self._summarize_old_tool_item(item))
                    details["older_entries_count"] += 1
                    details["summarized_tool_count"] += 1
                    continue
                group_lines.extend(self._render_history_item(item, 60))
            if group_lines:
                entries.append({"recent": False, "protected": False, "lines": group_lines, "group_id": group.group_id})

        return entries, details

    def _reusable_file_summary(self, path):
        memory = getattr(self.agent, "memory", None)
        if memory is None or not hasattr(memory, "to_dict"):
            return ""
        snapshot = memory.to_dict()
        summary = snapshot.get("file_summaries", {}).get(str(path), {})
        if not summary:
            return ""
        return str(summary.get("summary", "")).strip()

    def _summarize_old_tool_item(self, item):
        if item["name"] == "run_shell":
            command = str(item["args"].get("command", "")).strip() or "shell"
            lines = [line.strip() for line in str(item.get("content", "")).splitlines() if line.strip()]
            summary = " | ".join(lines[:3]) if lines else "(empty)"
            return f"{command} -> {summary}"
        return self._render_history_item(item, 60)[0]

    def _raw_history_text(self, history):
        if not history:
            return "Transcript:\n- empty"
        lines = []
        for item in history:
            if item["role"] == "tool":
                lines.append(f"[tool:{item['name']}] {json.dumps(item['args'], sort_keys=True)}")
                lines.append(str(item["content"]))
            else:
                lines.append(f"[{item['role']}] {item['content']}")
        return "\n".join(["Transcript:", *lines])

    def _render_history_item(self, item, line_limit):
        if item.get("role") == "tool":
            prefix = f"[tool:{item['name']}] {json.dumps(item.get('args') or {}, sort_keys=True)}"
            if item.get("call_id"):
                prefix += f" call_id={item['call_id']}"
            content = _tail_clip(item.get("content", ""), max(20, line_limit))
            return [prefix, content]
        lines = [f"[{item.get('role')}] {_tail_clip(item.get('content', ''), line_limit)}"]
        tool_calls = item.get("tool_calls") or ()
        if tool_calls:
            for call in tool_calls:
                name = str(call.get("name") or "")
                call_id = str(call.get("call_id") or "")
                args = call.get("arguments") if "arguments" in call else call.get("args") or {}
                lines.append(f"[tool_call:{name}] call_id={call_id} {json.dumps(args, sort_keys=True)}")
        return lines

    def _dynamic_tail_text(self):
        """checkpoint / compaction / workflow packet / 当前 git status 只能出现在稳定边界之后。"""
        parts = []
        if hasattr(self.agent, "render_checkpoint_text"):
            checkpoint_text = str(self.agent.render_checkpoint_text() or "").strip()
            if checkpoint_text:
                parts.append(checkpoint_text)
        if hasattr(self.agent, "render_compaction_text"):
            compaction_text = str(self.agent.render_compaction_text() or "").strip()
            if compaction_text:
                parts.append(compaction_text)
        if hasattr(self.agent, "render_workflow_prompt_context"):
            workflow_prompt_context = str(self.agent.render_workflow_prompt_context() or "").strip()
            if workflow_prompt_context:
                parts.append("Workflow task packet:\n" + workflow_prompt_context)
        if hasattr(self.agent, "render_live_workspace_tail"):
            live_status = str(self.agent.render_live_workspace_tail() or "").strip()
            if live_status:
                parts.append(live_status)
        return "\n\n".join(parts)

    def _assemble_prompt(self, rendered, dynamic_text="", include_dynamic=True):
        # 顺序是刻意设计的：P0/P1 稳定区最前，动态状态只向后追加，最新请求放最后。
        # 预算收缩按不含动态尾部的骨架计算，避免 checkpoint/status 把 relevant_memory 额外压扁。
        chunks = [rendered["prefix"].rendered]
        if include_dynamic:
            chunks.append(STABLE_BOUNDARY)
            dynamic_text = str(dynamic_text or "").strip()
            if dynamic_text:
                chunks.append(dynamic_text)
        chunks.extend(
            [
                rendered["memory"].rendered,
                rendered["relevant_memory"].rendered,
                rendered["history"].rendered,
                rendered[CURRENT_REQUEST_SECTION].rendered,
            ]
        )
        return "\n\n".join(chunks).strip()

    def _metadata(self, prompt, rendered, budgets, reduction_log, selected_notes, user_message, section_texts, dynamic_text=""):
        section_metadata = {}
        for section in SECTION_ORDER[:-1]:
            section_metadata[section] = {
                "raw_chars": rendered[section].raw_chars,
                "budget_chars": int(budgets.get(section, 0)),
                "rendered_chars": rendered[section].rendered_chars,
            }
        section_metadata[CURRENT_REQUEST_SECTION] = {
            "raw_chars": len(section_texts[CURRENT_REQUEST_SECTION]),
            "budget_chars": None,
            "rendered_chars": len(rendered[CURRENT_REQUEST_SECTION].rendered),
        }
        metadata = {
            "prompt_chars": len(prompt),
            "prompt_budget_chars": self.total_budget,
            "prompt_over_budget": len(prompt) > self.total_budget,
            "section_order": list(SECTION_ORDER),
            "section_budgets": {
                section: (None if section == CURRENT_REQUEST_SECTION else int(budgets.get(section, 0)))
                for section in SECTION_ORDER
            },
            "sections": section_metadata,
            "budget_reductions": reduction_log,
            "reduction_order": list(self.reduction_order),
            "relevant_memory": {
                "limit": RELEVANT_MEMORY_LIMIT,
                "selected_count": len(selected_notes),
                "selected_notes": [note["text"] for note in selected_notes],
                "selected_sources": [str(note.get("source", "")).strip() for note in selected_notes],
                "selected_kinds": [str(note.get("kind", "episodic")).strip() or "episodic" for note in selected_notes],
                "selected_durable_count": sum(
                    1 for note in selected_notes if (str(note.get("kind", "episodic")).strip() or "episodic") == "durable"
                ),
                "raw_chars": rendered["relevant_memory"].raw_chars,
                "rendered_chars": rendered["relevant_memory"].rendered_chars,
                "rendered_notes": list(rendered["relevant_memory"].details.get("rendered_notes", [])),
                "rendered_count": int(rendered["relevant_memory"].details.get("rendered_count", 0)),
            },
            "history": {
                "raw_chars": rendered["history"].raw_chars,
                "rendered_chars": rendered["history"].rendered_chars,
                "older_entries_count": int(rendered["history"].details.get("older_entries_count", 0)),
                "collapsed_duplicate_reads": int(rendered["history"].details.get("collapsed_duplicate_reads", 0)),
                "reused_file_summary_count": int(rendered["history"].details.get("reused_file_summary_count", 0)),
                "summarized_tool_count": int(rendered["history"].details.get("summarized_tool_count", 0)),
                "open_groups_preserved": int(rendered["history"].details.get("open_groups_preserved", 0)),
            },
            "current_request": {
                "text": user_message,
                "raw_chars": len(user_message),
                "rendered_chars": len(user_message),
                "section_chars": len(rendered[CURRENT_REQUEST_SECTION].rendered),
                "truncated": False,
            },
            "stable_boundary": STABLE_BOUNDARY,
            "p0_hash": str(getattr(getattr(self.agent, "prefix_state", None), "p0_hash", "") or ""),
            "p1_hash": str(getattr(getattr(self.agent, "prefix_state", None), "p1_hash", "") or ""),
            "dynamic_chars": len(str(dynamic_text or "")),
            "dynamic_after_boundary": True,
        }
        metadata.update(self._token_admission_metadata(prompt, user_message, metadata))
        return metadata

    def _token_admission_metadata(self, prompt, user_message, metadata):
        session = getattr(self.agent, "session", {}) or {}
        state = dict(session.get("compaction") or {}) if isinstance(session, dict) else {}
        history = list(session.get("history", []) or []) if isinstance(session, dict) else []
        remaining = remaining_rounds_heuristic(self.agent)
        prefix = str(getattr(self.agent, "prefix", "") or "")
        admission = evaluate_admission(
            prompt_text=prompt,
            prefix_text=prefix,
            user_message=user_message,
            history=history,
            remaining_rounds=remaining,
            window_w=self.token_window_w,
            input_cap_i=self.token_input_cap,
            reserved_r=self.token_reserved,
            margin_m=self.token_margin,
            soft_ratio=self.token_soft_ratio,
            context_epoch=int(state.get("context_epoch") or 1),
            last_compaction_epoch=int(state.get("last_compaction_epoch") or 0),
        )
        payload = admission.to_dict()
        estimated = int(admission.estimated_input_tokens)
        return {
            "estimated_input_tokens": estimated,
            "estimated_input_tokens_source": TOKEN_ESTIMATE_SOURCE,
            "token_estimate_calibrated": False,
            "token_admission": payload,
            "admission_code": admission.code,
            "admission_message": admission.message,
            "admission_reasons": list(admission.reasons),
        }
