# claude-judge

A Claude Code plugin that judges your Claude Code usage — roast or coach — across seven dimensions
(review discipline, security hygiene, outcome correlation, rework rate, leverage fit, skill progression,
prompt quality).

Runs fully local. No network, no telemetry, no GitHub posting. Output lives under
`~/Documents/projects/claude-judge/`.

## Status

Slice 1 (tracer bullet) — installable plugin, `/judge-me` reads the current project's Claude Code
JSONL transcripts and prints tool-call counts with a templated verdict. Real scoring ships in
subsequent slices.

## Install (local dev)

```bash
cd claude-judge
uv venv --python 3.13 .venv
uv pip install -e ".[dev]"
```

Then add this repo as a Claude Code plugin via the marketplace, or symlink
`.claude-plugin/plugin.json` into your Claude Code plugin path.

## Usage

```bash
/judge-me        # in a Claude Code session
./bin/judge      # from the shell, same thing
./bin/judge --all  # every session across all projects
```

## Dev

```bash
.venv/bin/pytest
```
