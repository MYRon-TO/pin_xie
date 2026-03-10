# AGENTS.md
Guide for agentic coding tools in this repository.
Use this file as default policy unless a user request explicitly overrides it.

## 1) Repo Facts
- Language: Python 3.11+
- Build backend: `setuptools.build_meta`
- Source root: `src/pin_xie/`
- Runtime deps: `regex`, `jieba`
- Dev deps: `pytest`, `ruff`
- Main components:
  - `api.py`: `PinXieEngine`, run modes, file processing
  - `parser.py`: Spell pipeline (Trie -> Jaccard -> LCS -> merge/create)
  - `tokenizer.py`: Han/ASCII tokenization and mask handling
  - `header.py`: regex parse-structure extraction
  - `template.py`: wildcard merge and parameter extraction

## 2) Cursor/Copilot Rule Files
Checked locations:
- `.cursor/rules/`: not present
- `.cursorrules`: not present
- `.github/copilot-instructions.md`: not present
Implication:
- No external Cursor/Copilot rules need to be merged.
- Follow this file + current in-repo conventions.

## 3) Environment Setup
Run from repository root:
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```
Non-editable install alternative:
```bash
python -m pip install ".[dev]"
```

## 4) Build / Lint / Test Commands
Build package:
```bash
python -m pip install build
python -m build
```
Lint + format:
```bash
ruff format src
ruff check src
ruff check src --fix
```
Recommended final check before handoff:
```bash
ruff format src && ruff check src
```
Run all tests:
```bash
pytest
```
Run a single test (node ID syntax):
```bash
pytest tests/test_x.py::test_case_name
pytest tests/test_x.py::TestClass::test_method
```
Run focused selection by keyword:
```bash
pytest -k "tokenizer and not slow"
```
Useful focused flags:
```bash
pytest -q tests/test_x.py::test_case_name
pytest -x -q
```
Current test status:
- No `tests/` directory exists yet in this repo.
- When adding tests, use `tests/test_*.py` naming.

## 5) Runtime Commands
Run module CLI:
```bash
PYTHONPATH=src python -m pin_xie.demo /path/to/log.log --config config/Config.toml
```
Run specific modes:
```bash
PYTHONPATH=src python -m pin_xie.demo /path/to/train.log --mode learn --template-dir ./cache
PYTHONPATH=src python -m pin_xie.demo /path/to/infer.log --mode parse --template-dir ./cache
PYTHONPATH=src python -m pin_xie.demo /path/to/log.log --mode learn_parse
```
Installed script form:
```bash
pin-xie-demo /path/to/log.log --config config/Config.toml
```

## 6) Code Style and Engineering Rules
### Imports
- Begin modules with `from __future__ import annotations`.
- Group imports: stdlib, third-party, local relative imports.
- Keep explicit imports; avoid `from x import *`.
### Formatting
- Use `ruff format` as canonical style.
- Keep existing wrap style and trailing commas.
- Prefer early returns to reduce nested branching.
- Add comments only when logic is not obvious from names/structure.
### Typing
- Annotate all public functions/methods and dataclass fields.
- Prefer modern forms: `list[str]`, `dict[str, str]`, `Path | str`.
- Prefer `A | B` over `Optional`/`Union`.
- Use `Mapping`/`Iterable` when read-only abstractions are useful.
- Keep return types explicit on parser/API boundaries.
### Naming
- `snake_case`: modules, functions, variables.
- `PascalCase`: classes, dataclasses, enums.
- `UPPER_SNAKE_CASE`: constants.
- Prefix internal helpers with `_`.
- Keep enum values lowercase strings (example: `RunMode`).
### Dataclasses and state
- Use dataclasses for record/config/report containers.
- Keep business logic in engine/parser classes.
- Use `field(default_factory=...)` for mutable defaults.
### Error handling
- Use `FileNotFoundError` for required path absence.
- Use `ValueError` for invalid config/cache/input shape.
- Validate external inputs early and fail fast.
- Include actionable context in errors (path, field, expected type).
- Do not silently swallow config/cache schema errors.
### File and JSON I/O
- Use `pathlib.Path` over manual path string handling.
- Always set `encoding="utf-8"` for text I/O.
- Use `ensure_ascii=False` for JSON output with Chinese text.
- Ensure output dirs exist via `mkdir(parents=True, exist_ok=True)`.
### Algorithm contracts
- Keep parser stage order stable:
  1) Trie fast path
  2) Jaccard candidate filter
  3) LCS best-cluster selection
  4) merge template or create cluster
- Preserve wildcard semantics: `*` means variable token span.
- Keep tie-break behavior deterministic.
### API compatibility
- Keep `PinXieEngine` as primary integration surface.
- Preserve run mode values: `learn_parse`, `learn`, `parse`.
- Avoid breaking `templates.json` structure without migration notes.
- Keep CLI flags backward compatible when practical.

## 7) Test Expectations for New Work
- Add targeted tests for every behavior change.
- Add regression tests for bug fixes.
- Prefer deterministic small fixtures over large corpora.
- Priority coverage areas:
  - tokenizer splitting and mask precedence
  - header parser strict vs non-strict behavior
  - cluster selection and template merge behavior
  - template cache save/load round-trip

## 8) Change Safety Checklist for Agents
- Keep diffs minimal and focused.
- Avoid adding dependencies unless clearly justified.
- Do not combine broad refactors with behavior changes.
- If schema/output contracts change, update docs and tests together.
- Before handoff, run format/lint/relevant tests or state what was not run.
