# claude-judge

**A Claude Code plugin that grades how you use Claude Code, session by session, across seven dimensions.**

Most AI-coding dashboards count tokens and tool calls. claude-judge looks at behaviour instead: did you actually review what the agent did before approving it, did secrets or destructive commands slip through, did the edits end up in commits, how much work was redone. It reads the session transcripts Claude Code already keeps on your machine, scores each session out of 100, and tells you the weakest habit to fix, in a blunt "roast" voice or a gentler "coach" voice.

## What it does

- **Scores every session** from Claude Code's local JSONL transcripts (`~/.claude/projects/`), split into work sessions at 30-minute idle gaps.
- **Correlates with git:** looks at the repo's `git log` for the session's time window to see whether edits turned into commits and whether anything got reverted.
- **Flags risky behaviour:** secrets pasted into prompts (OpenAI, GitHub, AWS, Slack keys, JWTs, credentials in URLs) and dangerous commands (`rm -rf`, force-push, `--no-verify`, `reset --hard`, and more).
- **Writes a report per session** (Markdown) and keeps a `scores.json` history.
- **Daily and weekly digests** with averages, an intent breakdown, a week-over-week delta, a sparkline, and a short written review with one concrete thing to change next week.
- **`/judge-me` slash command** to see your latest sessions from inside Claude Code.

## The seven dimensions

| Tier | Dimension | How it's measured |
|---|---|---|
| A (deterministic, 2× weight) | **Review discipline** | Share of tool approvals made in under 500 ms in ask/prompt mode (a sign of blind approval) |
| | **Security hygiene** | Starts at 10, minus a weighted deduction per red flag (secret in a prompt, destructive git or shell command) |
| | **Outcome correlation** | Edits versus commits, in the session and in the repo's git log for that window; planning and exploration sessions are scored neutral |
| | **Rework rate** | Share of files edited more than once, minus a penalty per revert commit |
| B (LLM-judged, 1× weight) | **Leverage fit** | Was the right model and tooling used for the kind of work? |
| | **Skill progression** | Use of plan mode, subagents, skills, memory and MCP where they would help |
| | **Prompt quality** | Clarity, context, constraints and scope of the prompts |

The overall score is a weighted average of the dimensions that apply, scaled to 0–100. Review discipline and the LLM-judged dimensions skip trivial sessions (fewer than 5 tool calls).

## How it works

```
~/.claude/projects/*.jsonl
        │
        ▼
TranscriptSource ──▶ SessionSegmenter ──▶ TranscriptSummarizer ──▶ SessionStats
 (find + parse)       (split on 30-min       (tool calls, edits,        │
                       idle gaps)             approval latency,         │
                                              red flags, excerpts)      │
                                                                         ▼
                         GitCorrelator ─────────────────────────▶  Tier A scorers (pure functions)
                         (git log in the session window)                 │
                                                                         ▼
                         ClaudeCLIBackend (`claude -p`) ───────▶  Tier B scorers, intent classifier,
                         daily call cap + result cache                    roast/coach verdict, digests
                                                                         │
                                                                         ▼
                                                    Aggregator ──▶ OutputStore (session .md + scores.json)
```

Design choices worth noting:

- **Raw transcripts never leave the summarizer.** Downstream scorers and LLM prompts only see structured stats, a few capped excerpts and red-flag labels.
- **No API key needed.** LLM calls go through your existing Claude Code login via `claude -p` (Haiku for scoring and intent, Sonnet for verdicts and digests).
- **Cost guardrails.** A per-day call cap (default 50) and on-disk caches for intent, scores and verdicts. When the cap is hit or the CLI is unavailable, it falls back to deterministic scoring.
- **Fast interactive mode.** `judge` and `/judge-me` run only the deterministic Tier A scorers, so they return quickly and cost nothing. The LLM is used for the scheduled daily and weekly digests.
- **Intent-aware.** Sessions are classified (coding, planning, exploration, and so on) so a planning session isn't punished for having no commits.

## Tech stack

- Python 3.11+, standard library only at runtime
- pytest (about 100 tests, one file per module)
- Claude Code plugin manifest and slash command
- `claude` CLI as the LLM backend
- cron for scheduled digests

## Install

```bash
git clone https://github.com/rohan-ahire1/claude-judge.git
cd claude-judge
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

Then add the repo as a local Claude Code plugin so `/judge-me` is available (the manifest is in `.claude-plugin/plugin.json`).

## Usage

Inside Claude Code:

```text
/judge-me
```

From the shell:

```bash
./bin/judge                  # latest 3 sessions for the current project
./bin/judge --latest 10      # latest 10
./bin/judge --all            # every project
./bin/judge --output DIR     # where reports and scores.json go
```

Each session prints its intent, duration, tool calls, edits, commits and reverts, then the overall score and one line per dimension with the reason behind the number.

### Daily and weekly digests

```bash
./bin/judge-daily              # today's digest
./bin/judge-weekly             # this ISO week's digest, with a delta against last week
./scheduled/install-cron.sh    # run them nightly at 23:00 and Sundays at 23:30
```

Set `CLAUDE_JUDGE_DATA` to choose the data folder. `judge-weekly` can also email the digest through `sendmail` if you set `CLAUDE_JUDGE_EMAIL`.

## Development

```bash
.venv/bin/pytest
```

## Project layout

| Path | What |
|---|---|
| `src/claude_judge/transcript_source.py`, `segmenter.py`, `summarizer.py` | Read, split and reduce transcripts to `SessionStats` |
| `src/claude_judge/scorers.py` | Tier A deterministic scorers |
| `src/claude_judge/llm_scorers.py`, `intent_classifier.py`, `verdict_writer.py` | Tier B scorers, intent and roast/coach verdicts |
| `src/claude_judge/claude_cli_backend.py` | `claude -p` wrapper with daily cap |
| `src/claude_judge/git_correlator.py` | Commits and reverts in a session's time window |
| `src/claude_judge/aggregator.py`, `output_store.py`, `digest.py` | Overall score, reports, daily/weekly digests |
| `bin/`, `commands/`, `scheduled/` | CLI wrappers, slash command, cron installer |
| `tests/` | pytest suite |
