"""Daily + weekly digests composed from scores.json.

Weekly digest input is the week's daily aggregates — never raw transcripts —
to keep token cost bounded and stable.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable


@dataclass
class DailyDigest:
    date: str
    session_count: int
    average_overall: float
    intents: dict[str, int]
    markdown_path: Path
    narrative: str


@dataclass
class WeeklyDigest:
    iso_week: str
    session_count: int
    average_overall: float
    prior_average_overall: float | None
    delta_overall: float | None
    intents: dict[str, int]
    markdown_path: Path
    narrative: str
    daily_sparkline: list[float] = field(default_factory=list)


def _load_scores(scores_path: Path) -> list[dict]:
    if not scores_path.exists():
        return []
    try:
        data = json.loads(scores_path.read_text())
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _parse_dt(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, AttributeError):
        return None


def _rows_on_date(rows: Iterable[dict], target: date) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        dt = _parse_dt(row.get("started_at", ""))
        if dt and dt.date() == target:
            out.append(row)
    return out


def _rows_in_iso_week(rows: Iterable[dict], iso_year: int, iso_week: int) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        dt = _parse_dt(row.get("started_at", ""))
        if not dt:
            continue
        y, w, _ = dt.isocalendar()
        if y == iso_year and w == iso_week:
            out.append(row)
    return out


def build_daily_digest(
    root: Path,
    date: str,
    llm=None,  # ClaudeCLIBackend | None (untyped to avoid import cycle for tests)
) -> DailyDigest | None:
    target = datetime.fromisoformat(date).date()
    rows = _load_scores(root / "scores.json")
    today_rows = _rows_on_date(rows, target)
    if not today_rows:
        return None

    overall_avg = round(sum(r["overall"] for r in today_rows) / len(today_rows), 1)
    intents = Counter(r.get("intent", "unknown") for r in today_rows)

    narrative = ""
    if llm is not None:
        narrative = _compose_daily_narrative(llm, today_rows, overall_avg, dict(intents))

    md = _render_daily_markdown(date, today_rows, overall_avg, dict(intents), narrative)
    daily_dir = root / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    out_path = daily_dir / f"{date}.md"
    out_path.write_text(md)

    return DailyDigest(
        date=date,
        session_count=len(today_rows),
        average_overall=overall_avg,
        intents=dict(intents),
        markdown_path=out_path,
        narrative=narrative,
    )


def build_weekly_digest(
    root: Path,
    iso_week: str,
    llm=None,
) -> WeeklyDigest | None:
    year_str, week_str = iso_week.split("-W")
    iso_year = int(year_str)
    wk = int(week_str)
    rows = _load_scores(root / "scores.json")
    week_rows = _rows_in_iso_week(rows, iso_year, wk)
    if not week_rows:
        return None

    overall_avg = round(sum(r["overall"] for r in week_rows) / len(week_rows), 1)
    intents = Counter(r.get("intent", "unknown") for r in week_rows)

    prior_rows = _rows_in_iso_week(rows, iso_year, wk - 1) if wk > 1 else []
    prior_avg: float | None = None
    delta: float | None = None
    if prior_rows:
        prior_avg = round(sum(r["overall"] for r in prior_rows) / len(prior_rows), 1)
        delta = round(overall_avg - prior_avg, 1)

    # Build per-day sparkline of overall averages
    daily_avgs: list[float] = []
    monday = datetime.fromisocalendar(iso_year, wk, 1).date()
    for i in range(7):
        d = monday + timedelta(days=i)
        day_rows = _rows_on_date(week_rows, d)
        if day_rows:
            daily_avgs.append(round(sum(r["overall"] for r in day_rows) / len(day_rows), 1))
        else:
            daily_avgs.append(0.0)

    narrative = ""
    if llm is not None:
        narrative = _compose_weekly_narrative(llm, iso_week, overall_avg, prior_avg, delta, dict(intents), daily_avgs)

    md = _render_weekly_markdown(iso_week, week_rows, overall_avg, prior_avg, delta, dict(intents), daily_avgs, narrative)
    weekly_dir = root / "weekly"
    weekly_dir.mkdir(parents=True, exist_ok=True)
    out_path = weekly_dir / f"{iso_week}.md"
    out_path.write_text(md)

    return WeeklyDigest(
        iso_week=iso_week,
        session_count=len(week_rows),
        average_overall=overall_avg,
        prior_average_overall=prior_avg,
        delta_overall=delta,
        intents=dict(intents),
        markdown_path=out_path,
        narrative=narrative,
        daily_sparkline=daily_avgs,
    )


# --- narrative composition ---


def _compose_daily_narrative(
    llm, rows: list[dict], avg: float, intents: dict[str, int]
) -> str:
    prompt = (
        "Compose a terse daily wrap-up for these Claude Code sessions. "
        "Pattern engineering-manager voice. 3-5 sentences. No emojis, no "
        "exclamation points. Pick one win, one failure, one nudge.\n\n"
        f"Sessions: {len(rows)}, average overall: {avg}/100\n"
        f"Intent breakdown: {intents}\n"
        "Per-session summaries:\n"
    )
    for r in rows:
        prompt += (
            f"- {r.get('session_id', '')[:12]} intent={r.get('intent')} "
            f"overall={r.get('overall')} tierA={r.get('tier_a_average')} "
            f"tierB={r.get('tier_b_average')}\n"
        )
    try:
        return llm.complete(prompt=prompt, model="sonnet").strip()
    except Exception:
        return ""


def _compose_weekly_narrative(
    llm,
    iso_week: str,
    avg: float,
    prior_avg: float | None,
    delta: float | None,
    intents: dict[str, int],
    sparkline: list[float],
) -> str:
    delta_line = (
        f"delta vs prior: {delta:+.1f} (prior {prior_avg:.1f})" if delta is not None else "no prior week"
    )
    prompt = (
        "Compose a weekly review of Claude Code usage. Pattern engineering-"
        "manager voice. 5-8 sentences. Identify up to 3 recurring patterns, "
        "highlight biggest regression + biggest improvement, end with ONE "
        "concrete behavior change for next week.\n\n"
        f"Week: {iso_week}\n"
        f"Avg overall: {avg}/100  ({delta_line})\n"
        f"Intent breakdown: {intents}\n"
        f"Daily avgs Mon..Sun: {sparkline}\n"
    )
    try:
        return llm.complete(prompt=prompt, model="sonnet").strip()
    except Exception:
        return ""


# --- markdown rendering ---


def _sparkline_ascii(values: list[float]) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    out = []
    for v in values:
        if v <= 0:
            out.append(" ")
            continue
        idx = min(len(blocks) - 1, int(v / 100 * len(blocks)))
        out.append(blocks[idx])
    return "".join(out)


def _render_daily_markdown(
    date: str,
    rows: list[dict],
    avg: float,
    intents: dict[str, int],
    narrative: str,
) -> str:
    lines = [
        f"# Daily Digest — {date}",
        "",
        f"- Sessions: **{len(rows)}**",
        f"- Average overall: **{avg:.1f} / 100**",
        f"- Intent breakdown: {intents}",
        "",
    ]
    if narrative:
        lines.extend(["## Narrative", "", narrative, ""])
    lines.extend(["## Sessions", "", "| id | intent | overall | tierA | tierB |", "| --- | --- | ---: | ---: | ---: |"])
    for r in rows:
        sid = r.get("session_id", "")[:12]
        lines.append(
            f"| `{sid}` | {r.get('intent')} | {r.get('overall')} | "
            f"{r.get('tier_a_average')} | {r.get('tier_b_average')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_weekly_markdown(
    iso_week: str,
    rows: list[dict],
    avg: float,
    prior_avg: float | None,
    delta: float | None,
    intents: dict[str, int],
    sparkline: list[float],
    narrative: str,
) -> str:
    lines = [
        f"# Weekly Digest — {iso_week}",
        "",
        f"- Sessions: **{len(rows)}**",
        f"- Average overall: **{avg:.1f} / 100**",
    ]
    if delta is not None:
        lines.append(f"- Delta vs prior week: **{delta:+.1f}** (prior: {prior_avg:.1f})")
    else:
        lines.append("- Prior week: no data")
    lines.append(f"- Intent breakdown: {intents}")
    lines.append("")
    lines.append(f"**Daily sparkline (Mon..Sun):** `{_sparkline_ascii(sparkline)}`  {sparkline}")
    lines.append("")
    if narrative:
        lines.extend(["## Narrative", "", narrative, ""])
    return "\n".join(lines)
