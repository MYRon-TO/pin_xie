from __future__ import annotations

import argparse
from pathlib import Path

from .api import PinXieEngine, RunMode


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Spell demo: parse a log file and emit JSONL.",
    )
    parser.add_argument("log_file", type=Path, help="Path to input log file")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/Config.toml"),
        help="Path to TOML config file",
    )
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in RunMode],
        default=RunMode.LEARN_PARSE.value,
        help=(
            "learn_parse: learn+parse (default); "
            "learn: learn only and store templates; "
            "parse: parse only from stored templates"
        ),
    )
    parser.add_argument(
        "--template-dir",
        type=Path,
        default=Path("cache"),
        help="Directory for template cache storage (default: ./cache)",
    )
    return parser


def run_demo(args: argparse.Namespace) -> int:
    engine = PinXieEngine.from_config_path(args.config)
    report = engine.run_file(
        args.log_file,
        mode=RunMode(args.mode),
        template_dir=args.template_dir,
    )

    print(f"Mode: {report.mode.value}")
    print(f"Processed lines: {report.processed_lines}")
    if report.parsed_output_path is not None:
        print(f"Per-line output: {report.parsed_output_path}")
    if report.template_output_path is not None:
        print(f"Templates output: {report.template_output_path}")
    if report.template_cache_path is not None:
        print(f"Template cache: {report.template_cache_path}")

    return 0


def main() -> int:
    arg_parser = _build_arg_parser()
    args = arg_parser.parse_args()
    return run_demo(args)


if __name__ == "__main__":
    raise SystemExit(main())
