#!/usr/bin/env python3
"""Build a model-training CSV from labeled raw logs.

Input format (default):
    _time,user,content,label
    2025/11/19 4:00,user16,用户 user16 请求登录系统,0

Output format (default):
    entity_col,event_col,label
    user16,1,0

`event_col` is the event/template id (`cluster_id`) produced by Pin Xie.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# Allow running this script directly from the repository without installation:
#   python examples/build_training_csv.py ...
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Parse labeled raw logs with Pin Xie and emit a training CSV: "
            "entity_col,event_col,label."
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("examples/key_logs_abnormal_labeled.csv"),
        help="Labeled raw CSV path (default: examples/key_logs_abnormal_labeled.csv)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/key_logs_training.csv"),
        help="Output training CSV path (default: output/key_logs_training.csv)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/Config.dynamic_example.toml"),
        help="Pin Xie TOML config path (default: config/Config.dynamic_example.toml)",
    )
    parser.add_argument("--time-col", default="_time", help="Time column name")
    parser.add_argument("--entity-col", default="user", help="Entity column name")
    parser.add_argument("--content-col", default="content", help="Log content column name")
    parser.add_argument("--label-col", default="label", help="Input label column name")
    parser.add_argument(
        "--output-label-col",
        default="label",
        help="Output label column name (default: label)",
    )
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
        "--event-prefix",
        default="",
        help="Optional prefix for event ids, e.g. 'E' writes E0/E1 instead of 0/1",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Only process the first N rows; useful for smoke tests.",
    )
    return parser


def _require_columns(fieldnames: list[str] | None, required: list[str]) -> None:
    if fieldnames is None:
        raise ValueError("Input CSV is empty or missing a header row")

    missing = [name for name in required if name not in fieldnames]
    if missing:
        raise ValueError(
            "Input CSV missing required columns: "
            + ", ".join(missing)
            + f". Available columns: {', '.join(fieldnames)}"
        )


def _compose_log(row: dict[str, str], *, time_col: str, entity_col: str, content_col: str) -> str:
    # Must match config/Config.dynamic_example.toml:
    # parse_structure = '<time>,<entity>,<context>'
    return f"{row[time_col]},{row[entity_col]},{row[content_col]}"


def build_training_csv(args: argparse.Namespace) -> int:
    from pin_xie import PinXieEngine

    if not args.input.is_file():
        raise FileNotFoundError(f"Input CSV not found: {args.input}")
    if not args.config.is_file():
        raise FileNotFoundError(f"Config not found: {args.config}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    engine = PinXieEngine.from_config_path(args.config)

    required_columns = [args.time_col, args.entity_col, args.content_col, args.label_col]
    processed = 0

    with (
        args.input.open("r", encoding="utf-8", newline="") as input_fp,
        args.output.open("w", encoding="utf-8", newline="") as output_fp,
    ):
        reader = csv.DictReader(input_fp)
        _require_columns(reader.fieldnames, required_columns)

        writer = csv.DictWriter(
            output_fp,
            fieldnames=[args.output_entity_col, args.output_event_col, args.output_label_col],
        )
        writer.writeheader()

        for row_number, row in enumerate(reader, start=1):
            if args.max_rows is not None and processed >= args.max_rows:
                break

            raw_log = _compose_log(
                row,
                time_col=args.time_col,
                entity_col=args.entity_col,
                content_col=args.content_col,
            )
            record = engine.process_line(raw_log, line_id=row_number, update_model=True)
            event_id = f"{args.event_prefix}{record.cluster_id}"

            writer.writerow(
                {
                    args.output_entity_col: row[args.entity_col],
                    args.output_event_col: event_id,
                    args.output_label_col: row[args.label_col],
                }
            )
            processed += 1

    print(f"Processed rows: {processed}")
    print(f"Training CSV: {args.output}")
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return build_training_csv(args)


if __name__ == "__main__":
    raise SystemExit(main())
