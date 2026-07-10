# Claude Judge

A local Claude Code plugin and command-line tool that reviews how you use coding agents. It is designed to turn Claude Code session transcripts into an evidence-based **coach** or **roast** covering workflow quality—not merely token or tool-call counts.

## Project status

**Version `0.1.0` is a tracer-bullet implementation.**

The current slice can be installed, read Claude Code JSONL transcripts and report basic tool-use counts with a templated verdict. The seven-dimension scoring system described below is the intended product direction and is not yet fully implemented.

## Intended evaluation dimensions

1. **Review discipline** — whether generated changes were inspected, tested and challenged
2. **Security hygiene** — handling of secrets, unsafe commands and risky changes
3. **Outcome correlation** — whether agent activity produced a working result
4. **Rework rate** — repeated changes, reversions and avoidable churn
5. **Leverage fit** — whether the agent was used for suitable work
6. **Skill progression** — evidence that the developer is learning rather than delegating blindly
7. **Prompt quality** — clarity, context, constraints and verification instructions

## Privacy

Claude Judge is deliberately local-first:

- no network requests
- no telemetry
- no automatic GitHub comments or posts
- no transcript upload
- no language-model dependency

Reports are written under:

```text
~/Documents/projects/claude-judge/
```

Review the output directory before using the tool on a shared machine because reports may still contain derived information about local development sessions.

## Requirements

- Python 3.11 or newer
- `uv` recommended for environment management
- Claude Code transcripts available locally

## Installation

```bash
git clone https://github.com/rohan-ahire1/claude-judge.git
cd claude-judge
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

Python 3.13 is used in the example, but the package supports Python 3.11+.

The package installs the `judge` console command through the project entry point:

```toml
judge = "claude_judge.cli:main"
```

## Claude Code plugin setup

The repository contains `.claude-plugin/plugin.json`. Add the repository as a local Claude Code plugin/marketplace source, or symlink the plugin manifest into the appropriate local Claude Code plugin path.

Plugin installation conventions can change between Claude Code releases, so verify the current Claude Code plugin documentation when wiring the local manifest.

## Usage

Inside Claude Code:

```text
/judge-me
```

From the repository:

```bash
./bin/judge
./bin/judge --all
```

After editable installation:

```bash
judge
judge --all
```

The default command evaluates the current project's available sessions. `--all` expands analysis across discovered projects and sessions.

## Development

Run the test suite:

```bash
.venv/bin/pytest
```

Or through `uv`:

```bash
uv run pytest
```

## Repository structure

```text
claude-judge/
├── .claude-plugin/
│   └── plugin.json
├── bin/
│   └── judge
├── src/
│   └── claude_judge/
├── tests/
├── pyproject.toml
└── README.md
```

## Design principles

- **Evidence before judgment:** every score should map to observable transcript behavior.
- **Local by default:** analysis must not require uploading private sessions.
- **Actionable feedback:** reports should explain the behavior and suggest a concrete improvement.
- **No vanity scoring:** raw activity volume should not be mistaken for effective engineering.
- **Transparent heuristics:** scoring rules should be inspectable and testable.
- **Graceful parsing:** malformed or version-shifted transcript records should not destroy an entire report.

## Planned work

- Implement transcript normalization across Claude Code event types
- Add the seven scoring dimensions with explicit evidence
- Correlate edits, commands, tests and final outcomes
- Distinguish productive iteration from repeated rework
- Support coach and roast presentation modes
- Add per-project and cross-project trend reports
- Expand fixture-based parser and scoring tests

## Limitations

- Claude Code's transcript format is not a guaranteed public API and may change.
- Current scoring is incomplete and should not be treated as an objective developer assessment.
- Tool-call counts alone cannot determine code quality or engineering judgment.
- Reports may miss work performed outside the captured Claude Code session.

## Contributing

Keep changes local-first, dependency-light and covered by transcript fixtures. New scoring rules should include both positive and negative examples and document exactly which evidence affects the result.