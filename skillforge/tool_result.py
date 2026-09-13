"""按工具类型把第一次进入上下文的结果收成短信封。

原文先落 B-01 Artifact（READY 才可读），history 只收摘要、范围、哈希和回查入口。
不要把全文写进 history 再回头删改。
"""

from __future__ import annotations

import hashlib
import re

INLINE_BODY_BUDGET = 1800
MAX_LINE_CHARS = 400
SHELL_HEAD_LINES = 40
SHELL_TAIL_LINES = 40
SEARCH_PAGE_SIZE = 20
SEARCH_SCAN_CAP = 400
LIST_PAGE_SIZE = 200

ERROR_ANCHOR_RE = re.compile(
    r"(traceback \(most recent call last\)|^\s*error:|exception:|fatal:|"
    r"panic:|assertionerror|errno\b|failed\b)",
    re.IGNORECASE,
)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def clip_line(line, limit=MAX_LINE_CHARS):
    text = str(line).replace("\r", "")
    if len(text) <= limit:
        return text
    return text[:limit] + "...[line truncated]"


def numbered_lines(lines, start=1):
    return [f"{number:>4}: {clip_line(line)}" for number, line in enumerate(lines, start=start)]


def lookup_read(artifact_id, start, end):
    return f"artifact_read({artifact_id!r}, {int(start)}, {int(end)})"


def lookup_search(artifact_id, pattern="pattern"):
    return f"artifact_search({artifact_id!r}, {pattern!r})"


def omission(artifact_id, start, end, reason="truncated"):
    return (
        f"...[{reason}; {lookup_read(artifact_id, start, end)} / "
        f"{lookup_search(artifact_id)}]"
    )


def render_fields(fields):
    lines = []
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
            continue
        if isinstance(value, (list, tuple)):
            if not value:
                continue
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  {item}")
            continue
        text = str(value)
        if text == "":
            continue
        lines.append(f"{key}: {text}")
    return lines


def render_envelope(fields, body="", body_first=False):
    field_lines = render_fields(fields)
    body = str(body or "").rstrip("\n")
    if body_first and body:
        lines = [body]
        if field_lines:
            lines.append("---")
            lines.extend(field_lines)
        return "\n".join(lines)
    lines = list(field_lines)
    if body:
        if lines:
            lines.append("---")
        lines.append(body)
    return "\n".join(lines)


def agent_store(agent):
    getter = getattr(agent, "artifact_store", None)
    if callable(getter):
        return getter()
    return None


def agent_run_id(agent):
    if not getattr(agent, "current_run_dir", None):
        return None
    state = getattr(agent, "current_task_state", None)
    return getattr(state, "run_id", None) if state is not None else None


def persist_ready_bytes(store, data, *, media_type="text/plain", run_id=None):
    if store is None:
        raise RuntimeError("artifact store is required to persist a ToolResult body")
    payload = data if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8")
    handle = store.begin_artifact(run_id=run_id, media_type=media_type)
    store.write_artifact_payload(handle, payload)
    return store.finalize_artifact(handle)


def persist_ready_text(store, text, *, media_type="text/plain", run_id=None):
    return persist_ready_bytes(store, str(text).encode("utf-8"), media_type=media_type, run_id=run_id)


def decode_text(data):
    if isinstance(data, str):
        return data
    return bytes(data).decode("utf-8", errors="replace")


def budget_prefix_lines(lines, budget=INLINE_BODY_BUDGET):
    shown = []
    used = 0
    for line in lines:
        piece = clip_line(line)
        extra = len(piece) + (1 if shown else 0)
        if shown and used + extra > budget:
            break
        shown.append(piece)
        used += extra
        if used >= budget:
            break
    return shown


def find_error_anchors(text, limit=8):
    anchors = []
    for number, line in enumerate(str(text).splitlines(), start=1):
        if ERROR_ANCHOR_RE.search(line):
            anchors.append(f"L{number}: {clip_line(line, 180)}")
            if len(anchors) >= limit:
                break
    return anchors


def ensure_history_envelope(result, *, store=None, run_id=None, tool_name=""):
    """History 只收短信封。超预算且尚无句柄时先落 READY 工件，而不是 clip 4000。"""
    text = str(result)
    has_lookup = (
        re.search(r"^artifact_id:\s*\S+", text, re.MULTILINE)
        and ("artifact_read(" in text or re.search(r"^lookup:", text, re.MULTILINE))
    )
    if has_lookup:
        return text
    if len(text) <= 4000:
        return text
    if store is None:
        raise RuntimeError(f"tool {tool_name or 'unknown'} exceeded inline budget without an artifact store")
    record = persist_ready_text(store, text, media_type="text/plain", run_id=run_id)
    lines = text.splitlines()
    shown = budget_prefix_lines(lines, INLINE_BODY_BUDGET // 2)
    next_start = len(shown) + 1
    body = "\n".join(shown)
    if len(shown) < len(lines):
        body = body + "\n" + omission(record["id"], next_start, len(lines))
    return render_envelope(
        {
            "status": "ok",
            "summary": f"{tool_name or 'tool'} output stored as artifact",
            "truncated": True,
            "total_lines": len(lines),
            "shown_range": f"1-{len(shown)}" if shown else "0-0",
            "artifact_id": record["id"],
            "sha256": record["hash"],
            "byte_size": record["size"],
            "lookup": lookup_read(record["id"], next_start, min(len(lines), next_start + 80)),
            "lookup_search": lookup_search(record["id"]),
        },
        body,
    )


def shape_read_file(*, path, raw_bytes, requested_start, requested_end, store, run_id=None):
    text = decode_text(raw_bytes)
    lines = text.splitlines()
    total = len(lines)
    start = max(1, int(requested_start))
    end = min(int(requested_end), total) if total else 0
    payload = raw_bytes if isinstance(raw_bytes, (bytes, bytearray)) else str(raw_bytes).encode("utf-8")
    record = persist_ready_bytes(store, payload, media_type="text/plain", run_id=run_id)
    selected = lines[start - 1 : end] if total else []
    shown = budget_prefix_lines(numbered_lines(selected, start=start))
    shown_end = start + len(shown) - 1 if shown else start - 1
    truncated = bool(shown_end < end)
    body_lines = [f"# {path}"]
    body_lines.extend(shown)
    if truncated:
        next_start = shown_end + 1 if shown else start
        body_lines.append(omission(record["id"], next_start, max(end, total)))
    fields = {
        "status": "ok",
        "path": path,
        "content_hash": record["hash"],
        "total_lines": total,
        "requested_range": f"{requested_start}-{requested_end}",
        "shown_range": f"{start}-{shown_end}" if shown else "0-0",
        "truncated": truncated,
        "artifact_id": record["id"],
        "sha256": record["hash"],
        "byte_size": record["size"],
        "lookup": lookup_read(record["id"], shown_end + 1 if truncated else start, total or 1),
        "lookup_search": lookup_search(record["id"]),
    }
    return render_envelope(fields, "\n".join(body_lines), body_first=True)


def shape_search(*, matches, scanned_cap=SEARCH_SCAN_CAP, page_size=SEARCH_PAGE_SIZE, store, run_id=None, summary=""):
    matches = [str(item) for item in matches]
    hit_cap = len(matches) > scanned_cap
    stored_matches = matches[:scanned_cap]
    has_more = hit_cap or len(stored_matches) > page_size
    page = stored_matches[:page_size]
    shown = budget_prefix_lines([clip_line(item, 240) for item in page])
    if len(shown) < len(page):
        has_more = True
    body = "\n".join(shown) if shown else "(no matches)"
    if not stored_matches:
        return render_envelope(
            {
                "status": "ok",
                "summary": summary or "(no matches)",
                "has_more": False,
                "next_page": False,
                "truncated": False,
                "match_count_shown": 0,
                "match_count_scanned": 0,
            },
            "(no matches)",
        )
    record = persist_ready_text(
        store,
        "\n".join(stored_matches) + ("\n" if stored_matches else ""),
        media_type="text/x-search-results",
        run_id=run_id,
    )
    if has_more:
        body = body + "\n" + omission(record["id"], len(shown) + 1, len(stored_matches), reason="more matches")
    return render_envelope(
        {
            "status": "ok",
            "summary": summary or f"{len(stored_matches)} matches",
            "has_more": has_more,
            "next_page": has_more,
            "truncated": has_more,
            "match_count_shown": len(shown),
            "match_count_scanned": len(stored_matches),
            "artifact_id": record["id"],
            "sha256": record["hash"],
            "byte_size": record["size"],
            "lookup": lookup_read(record["id"], len(shown) + 1, min(len(stored_matches), len(shown) + page_size)),
            "lookup_search": lookup_search(record["id"]),
        },
        body,
    )


def _head_tail_segments(lines, head=SHELL_HEAD_LINES, tail=SHELL_TAIL_LINES):
    total = len(lines)
    if total == 0:
        return [], False
    if total <= head + tail:
        return [("all", 1, total, lines)], False
    head_lines = lines[:head]
    tail_lines = lines[-tail:] if tail else []
    segments = [("head", 1, head, head_lines)]
    if tail_lines:
        tail_start = total - tail + 1
        segments.append(("tail", tail_start, total, tail_lines))
    return segments, True


def shape_shell(*, exit_code, stdout, stderr, store, run_id=None):
    stdout = "" if stdout is None else str(stdout)
    stderr = "" if stderr is None else str(stderr)
    raw = (
        f"exit_code: {int(exit_code)}\n"
        f"stdout:\n{stdout.strip() or '(empty)'}\n"
        f"stderr:\n{stderr.strip() or '(empty)'}\n"
    )
    stdout_lines = stdout.splitlines()
    stderr_lines = stderr.splitlines()
    stdout_segments, stdout_trunc = _head_tail_segments(stdout_lines)
    stderr_segments, stderr_trunc = _head_tail_segments(stderr_lines, head=20, tail=20)
    truncated = stdout_trunc or stderr_trunc or len(raw) > INLINE_BODY_BUDGET
    record = persist_ready_text(store, raw, media_type="text/x-shell-output", run_id=run_id)
    anchors = find_error_anchors(stdout + "\n" + stderr)
    body_parts = []
    shown_ranges = []
    for kind, start, end, segment_lines in stdout_segments:
        shown_ranges.append(f"stdout[{start}-{end}]")
        label = "stdout" if kind == "all" else f"stdout_{kind}"
        body_parts.append(f"{label}:")
        body_parts.extend(segment_lines if segment_lines else ["(empty)"])
        if kind == "head" and stdout_trunc:
            tail_start = stdout_segments[-1][1] if stdout_segments[-1][0] == "tail" else end + 1
            body_parts.append(omission(record["id"], end + 1, tail_start - 1))
    if not stdout_lines:
        shown_ranges.append("stdout[0-0]")
        body_parts.append("stdout:")
        body_parts.append("(empty)")
    for kind, start, end, segment_lines in stderr_segments:
        shown_ranges.append(f"stderr[{start}-{end}]")
        label = "stderr" if kind == "all" else f"stderr_{kind}"
        body_parts.append(f"{label}:")
        body_parts.extend(segment_lines if segment_lines else ["(empty)"])
        if kind == "head" and stderr_trunc:
            tail_start = stderr_segments[-1][1] if stderr_segments[-1][0] == "tail" else end + 1
            body_parts.append(omission(record["id"], end + 1, tail_start - 1))
    if not stderr_lines:
        shown_ranges.append("stderr[0-0]")
        if "stderr:" not in "\n".join(body_parts):
            body_parts.append("stderr:")
            body_parts.append("(empty)")
    status = "ok" if int(exit_code) == 0 else "error"
    return render_envelope(
        {
            "status": status,
            "exit_code": int(exit_code),
            "truncated": truncated,
            "shown_ranges": shown_ranges,
            "error_anchors": anchors,
            "artifact_id": record["id"],
            "sha256": record["hash"],
            "byte_size": record["size"],
            "lookup": lookup_read(record["id"], 1, 80),
            "lookup_search": lookup_search(record["id"], "Error"),
        },
        "\n".join(body_parts),
    )


def shape_log_run(*, evidence_id, status, summary, artifact_id="", sha256="", byte_size=None, truncated=False, extra_fields=None):
    fields = {
        "evidence_id": evidence_id,
        "status": status,
        "summary": summary,
        "truncated": bool(truncated),
    }
    if artifact_id:
        fields["artifact_id"] = artifact_id
        fields["sha256"] = sha256
        fields["byte_size"] = byte_size
        fields["lookup"] = lookup_read(artifact_id, 1, 80)
        fields["lookup_search"] = lookup_search(artifact_id)
    if extra_fields:
        fields.update(extra_fields)
    return render_envelope(fields)


def shape_list_files(*, lines, store, run_id=None):
    lines = [str(item) for item in lines]
    if not lines:
        return "(empty)"
    joined = "\n".join(lines)
    if len(lines) <= LIST_PAGE_SIZE and len(joined) <= INLINE_BODY_BUDGET:
        return joined
    record = persist_ready_text(store, joined + "\n", media_type="text/plain", run_id=run_id)
    shown = budget_prefix_lines(lines[:LIST_PAGE_SIZE])
    body = "\n".join(shown)
    if len(shown) < len(lines):
        body = body + "\n" + omission(record["id"], len(shown) + 1, len(lines), reason="more files")
    return render_envelope(
        {
            "status": "ok",
            "truncated": True,
            "has_more": True,
            "total_lines": len(lines),
            "shown_range": f"1-{len(shown)}",
            "artifact_id": record["id"],
            "sha256": record["hash"],
            "byte_size": record["size"],
            "lookup": lookup_read(record["id"], len(shown) + 1, min(len(lines), len(shown) + LIST_PAGE_SIZE)),
            "lookup_search": lookup_search(record["id"]),
        },
        body,
    )


def read_ready_range(store, artifact_id, start, end):
    record = store.get_ready_artifact(artifact_id)
    data = store.read_ready_bytes(artifact_id)
    lines = decode_text(data).splitlines()
    total = len(lines)
    start = max(1, int(start))
    end = min(int(end), total) if total else 0
    selected = lines[start - 1 : end] if total else []
    shown = budget_prefix_lines(numbered_lines(selected, start=start))
    shown_end = start + len(shown) - 1 if shown else start - 1
    truncated = shown_end < end
    body = "\n".join(shown) if shown else "(empty)"
    if truncated:
        body = body + "\n" + omission(artifact_id, shown_end + 1, end)
    return render_envelope(
        {
            "status": "ok",
            "artifact_id": artifact_id,
            "sha256": record["hash"],
            "byte_size": record["size"],
            "state": record["state"],
            "total_lines": total,
            "shown_range": f"{start}-{shown_end}" if shown else "0-0",
            "truncated": truncated,
            "lookup": lookup_read(artifact_id, shown_end + 1 if truncated else start, total or 1),
            "lookup_search": lookup_search(artifact_id),
        },
        body,
    )


def search_ready_artifact(store, artifact_id, pattern, *, page_size=SEARCH_PAGE_SIZE):
    record = store.get_ready_artifact(artifact_id)
    data = store.read_ready_bytes(artifact_id)
    needle = str(pattern)
    hits = []
    for number, line in enumerate(decode_text(data).splitlines(), start=1):
        if needle.lower() in line.lower():
            hits.append(f"{number}:{clip_line(line, 240)}")
    has_more = len(hits) > page_size
    shown = hits[:page_size]
    body = "\n".join(shown) if shown else "(no matches)"
    if has_more:
        body = body + "\n" + omission(artifact_id, page_size + 1, len(hits), reason="more matches")
    return render_envelope(
        {
            "status": "ok",
            "artifact_id": artifact_id,
            "sha256": record["hash"],
            "pattern": needle,
            "has_more": has_more,
            "next_page": has_more,
            "truncated": has_more,
            "match_count_shown": len(shown),
            "match_count_scanned": len(hits),
            "lookup": lookup_read(artifact_id, 1, 80),
            "lookup_search": lookup_search(artifact_id, needle),
        },
        body,
    )


def require_ready_store(agent):
    store = agent_store(agent)
    if store is None:
        raise RuntimeError("artifact_read requires the B-01 persistence store")
    return store
