#!/usr/bin/env python3
"""Build a sequence-aware training CSV from labeled structured logs.

Input format (default column names):
    host,content,is_attack,attack_type,technique,tactic,attack_name

Output format:
    entity_col,event_col,content,label,attack_name

Label rules:
    0: normal log in a normal sequence
    1: attack log in an abnormal sequence
    2: normal log in an abnormal sequence

Rows with technique == "T1070" are processed for sequence-level decisions and for
Pin Xie model updates, but are not emitted to the output CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

# Allow running this script directly from the repository without installation:
#   python scripts/build_sequence_training_csv.py ...
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


TRUE_VALUES = {"1", "true", "t", "yes", "y"}
FALSE_VALUES = {"0", "false", "f", "no", "n", ""}
SKIPPED_TECHNIQUE = {"T1070", "T1550"}


@dataclass(frozen=True)
class ProcessedRow:
    row: dict[str, str]
    row_number: int
    event_id: str
    is_attack: bool


@dataclass(frozen=True)
class OutputStats:
    read_rows: int
    written_rows: int
    sequence_count: int



def _optional_path(value: str) -> Path | None:
    return None if value == "" else Path(value)



def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Parse structured labeled logs with Pin Xie and emit a sequence-aware "
            "training CSV: entity_col,event_col,content,label,attack_name."
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("examples/key_logs_sequence_labeled.csv"),
        help="Structured labeled CSV path (default: examples/key_logs_sequence_labeled.csv)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/key_logs_sequence_training.csv"),
        help="Output training CSV path (default: output/key_logs_sequence_training.csv)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/Config.toml"),
        help="Pin Xie TOML config path. Default uses parse_structure='<context>'.",
    )
    parser.add_argument("--host-col", default="host", help="Input host/entity column name")
    parser.add_argument("--content-col", default="content", help="Input log content column name")
    parser.add_argument("--is-attack-col", default="is_attack", help="Input attack flag column name")
    parser.add_argument("--technique-col", default="technique", help="Input technique column name")
    parser.add_argument("--attack-name-col", default="attack_name", help="Input attack name column name")
    parser.add_argument(
        "--output-entity-col",
        default="entity_col",
        help="Output entity column name (default: entity_col)",
    )
    parser.add_argument(
        "--output-event-col",
        default="event_col",
        help="Output event id column name (default: event_col)",
    )
    parser.add_argument(
        "--output-content-col",
        default="content",
        help="Output content column name (default: content)",
    )
    parser.add_argument(
        "--output-label-col",
        default="label",
        help="Output label column name (default: label)",
    )
    parser.add_argument(
        "--output-attack-name-col",
        default="attack_name",
        help="Output attack-name column name (default: attack_name)",
    )
    parser.add_argument(
        "--event-prefix",
        default="",
        help="Optional prefix for event ids, e.g. 'E' writes E0/E1 instead of 0/1",
    )
    parser.add_argument(
        "--template-dir",
        type=Path,
        default=Path("cache/sequence_training"),
        help="Directory used to save/load Pin Xie template cache (default: cache/sequence_training)",
    )
    parser.add_argument(
        "--template-summary",
        type=_optional_path,
        default=Path("output/key_logs_sequence_templates.txt"),
        help="Human-readable template summary path saved after training; pass '' to disable.",
    )
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="Load existing templates from --template-dir and do not update/retrain the Pin Xie model.",
    )
    parser.add_argument(
        "--no-save-template-cache",
        action="store_true",
        help="Do not save template cache after training. Ignored when --parse-only is set.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Only process the first N input rows; useful for smoke tests.",
    )
    return parser



def _require_columns(fieldnames: Sequence[str] | None, required: list[str]) -> None:
    if fieldnames is None:
        raise ValueError("Input CSV is empty or missing a header row")

    missing = [name for name in required if name not in fieldnames]
    if missing:
        raise ValueError(
            "Input CSV missing required columns: "
            + ", ".join(missing)
            + f". Available columns: {', '.join(fieldnames)}"
        )



def _parse_bool(value: str, *, column_name: str, row_number: int) -> bool:
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(
        f"Invalid boolean value at row {row_number}, column {column_name}: {value!r}. "
        "Expected one of true/false, 1/0, yes/no."
    )



def _append_unique_non_empty(values: list[str], value: str) -> None:
    normalized = value.strip()
    if normalized and normalized not in values:
        values.append(normalized)



def _sequence_attack_names(
    sequence_rows: Iterable[ProcessedRow],
    *,
    attack_name_col: str,
) -> list[str]:
    attack_names: list[str] = []
    for processed_row in sequence_rows:
        if processed_row.is_attack:
            _append_unique_non_empty(attack_names, processed_row.row[attack_name_col])
    return attack_names



def _write_sequence(
    writer: csv.DictWriter[str],
    sequence_rows: list[ProcessedRow],
    *,
    host_col: str,
    content_col: str,
    technique_col: str,
    attack_name_col: str,
    output_entity_col: str,
    output_event_col: str,
    output_content_col: str,
    output_label_col: str,
    output_attack_name_col: str,
) -> int:
    if not sequence_rows:
        return 0

    attack_names = _sequence_attack_names(sequence_rows, attack_name_col=attack_name_col)
    is_abnormal_sequence = bool(attack_names)
    serialized_attack_names = json.dumps(attack_names, ensure_ascii=False) if is_abnormal_sequence else ""

    written = 0
    for processed_row in sequence_rows:
        row = processed_row.row
        if row[technique_col].strip() in SKIPPED_TECHNIQUE:
            continue

        if processed_row.is_attack:
            label = 1
        elif is_abnormal_sequence:
            label = 2
        else:
            label = 0

        writer.writerow(
            {
                output_entity_col: row[host_col],
                output_event_col: processed_row.event_id,
                output_content_col: row[content_col],
                output_label_col: label,
                output_attack_name_col: serialized_attack_names,
            }
        )
        written += 1

    return written



def build_sequence_training_csv(args: argparse.Namespace) -> OutputStats:
    from pin_xie import PinXieEngine

    if not args.input.is_file():
        raise FileNotFoundError(f"Input CSV not found: {args.input}")
    if not args.config.is_file():
        raise FileNotFoundError(f"Config not found: {args.config}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    engine = PinXieEngine.from_config_path(args.config)
    if args.parse_only:
        engine.load_template_cache(args.template_dir)

    should_update_model = not args.parse_only

    required_columns = [
        args.host_col,
        args.content_col,
        args.is_attack_col,
        args.technique_col,
        args.attack_name_col,
    ]

    read_rows = 0
    written_rows = 0
    sequence_count = 0
    current_host: str | None = None
    current_sequence: list[ProcessedRow] = []

    with (
        args.input.open("r", encoding="utf-8", newline="") as input_fp,
        args.output.open("w", encoding="utf-8", newline="") as output_fp,
    ):
        reader = csv.DictReader(input_fp)
        _require_columns(reader.fieldnames, required_columns)

        writer = csv.DictWriter(
            output_fp,
            fieldnames=[
                args.output_entity_col,
                args.output_event_col,
                args.output_content_col,
                args.output_label_col,
                args.output_attack_name_col,
            ],
        )
        writer.writeheader()

        for row_number, row in enumerate(reader, start=1):
            if args.max_rows is not None and read_rows >= args.max_rows:
                break

            host = row[args.host_col]
            if current_host is not None and host != current_host:
                written_rows += _write_sequence(
                    writer,
                    current_sequence,
                    host_col=args.host_col,
                    content_col=args.content_col,
                    technique_col=args.technique_col,
                    attack_name_col=args.attack_name_col,
                    output_entity_col=args.output_entity_col,
                    output_event_col=args.output_event_col,
                    output_content_col=args.output_content_col,
                    output_label_col=args.output_label_col,
                    output_attack_name_col=args.output_attack_name_col,
                )
                sequence_count += 1
                current_sequence = []

            current_host = host

            record = engine.process_line(
                row[args.content_col],
                line_id=row_number,
                update_model=should_update_model,
            )
            current_sequence.append(
                ProcessedRow(
                    row=row,
                    row_number=row_number,
                    event_id=f"{args.event_prefix}{record.cluster_id}",
                    is_attack=_parse_bool(
                        row[args.is_attack_col],
                        column_name=args.is_attack_col,
                        row_number=row_number,
                    ),
                )
            )
            read_rows += 1

        if current_sequence:
            written_rows += _write_sequence(
                writer,
                current_sequence,
                host_col=args.host_col,
                content_col=args.content_col,
                technique_col=args.technique_col,
                attack_name_col=args.attack_name_col,
                output_entity_col=args.output_entity_col,
                output_event_col=args.output_event_col,
                output_content_col=args.output_content_col,
                output_label_col=args.output_label_col,
                output_attack_name_col=args.output_attack_name_col,
            )
            sequence_count += 1

    if should_update_model and not args.no_save_template_cache:
        cache_path = engine.save_template_cache(args.template_dir)
        print(f"Template cache: {cache_path}")

        if args.template_summary:
            summary_path = engine.write_template_summary(args.template_summary)
            print(f"Template summary: {summary_path}")

    return OutputStats(read_rows=read_rows, written_rows=written_rows, sequence_count=sequence_count)



def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    stats = build_sequence_training_csv(args)
    print(f"Read rows: {stats.read_rows}")
    print(f"Written rows: {stats.written_rows}")
    print(f"Sequences: {stats.sequence_count}")
    print(f"Training CSV: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
