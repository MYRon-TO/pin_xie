from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_demo_config
from .header import HeaderParseResult, RegexHeaderParser
from .parser import ParseResult, SpellParser
from .tokenizer import LogTokenizer


MODE_LEARN_PARSE = "learn_parse"
MODE_LEARN = "learn"
MODE_PARSE = "parse"
TEMPLATE_CACHE_FILE = "templates.json"


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
        choices=[MODE_LEARN_PARSE, MODE_LEARN, MODE_PARSE],
        default=MODE_LEARN_PARSE,
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


def _template_cache_path(template_dir: Path) -> Path:
    return template_dir / TEMPLATE_CACHE_FILE


def _save_template_cache(parser: SpellParser, template_dir: Path) -> Path:
    template_dir.mkdir(parents=True, exist_ok=True)
    cache_path = _template_cache_path(template_dir)

    with cache_path.open("w", encoding="utf-8") as fp:
        json.dump(parser.to_template_state(), fp, ensure_ascii=False, indent=2)
        fp.write("\n")

    return cache_path


def _load_template_cache(
    *,
    template_dir: Path,
    tokenizer: LogTokenizer,
) -> SpellParser:
    cache_path = _template_cache_path(template_dir)
    if not cache_path.exists() or not cache_path.is_file():
        raise FileNotFoundError(
            f"Template cache not found: {cache_path}. "
            f"Run with --mode {MODE_LEARN} first to build templates."
        )

    with cache_path.open("r", encoding="utf-8") as fp:
        state = json.load(fp)

    if not isinstance(state, dict):
        raise ValueError("Invalid template cache: root must be an object")

    return SpellParser.from_template_state(
        state,
        tokenizer=tokenizer,
    )


def _build_jsonl_payload(
    *,
    line_id: int,
    log: str,
    header: HeaderParseResult,
    result: ParseResult,
    show_tokens: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "line_id": line_id,
        "header_matched": header.matched,
        "cluster_id": result.cluster_id,
        "context": header.context,
        "template": " ".join(result.template_tokens),
        "template_tokens": result.template_tokens,
        "parameters": result.parameters,
        "log": log,
    }

    for field_name, field_value in header.fields.items():
        if field_name == "context":
            continue
        payload[f"header_{field_name}"] = field_value

    if show_tokens:
        payload["tokens"] = result.tokens

    return payload


def run_demo(args: argparse.Namespace) -> int:
    if not args.log_file.exists() or not args.log_file.is_file():
        raise FileNotFoundError(f"Log file not found: {args.log_file}")

    config = load_demo_config(args.config)

    mode = args.mode

    tokenizer = LogTokenizer(
        delimiters=config.tokenizer.delimiters,
        extra_delimiters=config.tokenizer.extra_delimiters,
        mask_patterns=config.tokenizer.mask_patterns,
        use_jieba=config.tokenizer.use_jieba,
    )
    if mode == MODE_PARSE:
        parser = _load_template_cache(
            template_dir=args.template_dir,
            tokenizer=tokenizer,
        )
    else:
        parser = SpellParser(tau_ratio=config.spell.tau_ratio, tokenizer=tokenizer)

    header_parser = RegexHeaderParser(
        parse_structure=config.header.parse_structure,
        field_patterns=config.header.field_patterns,
        strict_mode=config.header.strict_mode,
    )

    should_update_model = mode != MODE_PARSE
    should_write_parsed_output = mode != MODE_LEARN
    should_write_template_summary = mode == MODE_LEARN_PARSE

    output_dir = config.output.dir
    parsed_output_path: Path | None = None
    template_output_path: Path | None = None

    if should_write_parsed_output or should_write_template_summary:
        output_dir.mkdir(parents=True, exist_ok=True)
        parsed_output_path = output_dir / config.output.parsed_file
        template_output_path = output_dir / config.output.template_file

    parsed_count = 0

    if should_write_parsed_output and parsed_output_path is not None:
        with (
            args.log_file.open("r", encoding="utf-8") as input_fp,
            parsed_output_path.open("w", encoding="utf-8") as parsed_fp,
        ):
            for index, raw_line in enumerate(input_fp, start=1):
                log = raw_line.strip()
                if not log:
                    continue

                header = header_parser.parse(log)
                result = parser.process(
                    header.context,
                    line_id=index,
                    update_model=should_update_model,
                )
                payload = _build_jsonl_payload(
                    line_id=index,
                    log=log,
                    header=header,
                    result=result,
                    show_tokens=config.output.show_tokens,
                )
                parsed_fp.write(json.dumps(payload, ensure_ascii=False))
                parsed_fp.write("\n")

                parsed_count += 1
    else:
        with args.log_file.open("r", encoding="utf-8") as input_fp:
            for index, raw_line in enumerate(input_fp, start=1):
                log = raw_line.strip()
                if not log:
                    continue

                header = header_parser.parse(log)
                parser.process(
                    header.context,
                    line_id=index,
                    update_model=should_update_model,
                )
                parsed_count += 1

    if should_write_template_summary and template_output_path is not None:
        with template_output_path.open("w", encoding="utf-8") as tpl_fp:
            tpl_fp.write("=== Final Templates ===\n")
            tpl_fp.write(f"total_clusters={len(parser.all_clusters())}\n\n")
            tpl_fp.write("=== Header Parse Config ===\n")
            tpl_fp.write(
                f"parse_structure={config.header.parse_structure} "
                f"strict_mode={config.header.strict_mode}\n"
            )
            for field_name, field_pattern in config.header.field_patterns.items():
                tpl_fp.write(f"field_pattern[{field_name}]={field_pattern}\n")
            tpl_fp.write("\n")
            tpl_fp.write("=== Spell Config ===\n")
            tpl_fp.write(f"tau_ratio={config.spell.tau_ratio}\n\n")
            tpl_fp.write("=== Tokenizer Config ===\n")
            tpl_fp.write(
                f"delimiters={config.tokenizer.delimiters} "
                f"use_jieba={config.tokenizer.use_jieba} "
                f"mask_patterns_count={len(config.tokenizer.mask_patterns)}\n\n"
            )

            for cluster in parser.all_clusters():
                template = " ".join(cluster.template_tokens)
                line_ids_preview = ", ".join(
                    str(line_id) for line_id in cluster.line_ids[:20]
                )
                if len(cluster.line_ids) > 20:
                    line_ids_preview = f"{line_ids_preview}, ..."

                tpl_fp.write(f"Cluster {cluster.cluster_id}\n")
                tpl_fp.write(f"  size: {cluster.size}\n")
                tpl_fp.write(f"  template: {template}\n")
                tpl_fp.write(f"  line_ids_count: {len(cluster.line_ids)}\n")
                tpl_fp.write(f"  line_ids_preview: [{line_ids_preview}]\n")
                tpl_fp.write("\n")

    cache_path: Path | None = None
    if should_update_model:
        cache_path = _save_template_cache(parser, args.template_dir)

    print(f"Mode: {mode}")
    print(f"Processed lines: {parsed_count}")
    if parsed_output_path is not None and should_write_parsed_output:
        print(f"Per-line output: {parsed_output_path}")
    if template_output_path is not None and should_write_template_summary:
        print(f"Templates output: {template_output_path}")
    if cache_path is not None:
        print(f"Template cache: {cache_path}")

    return 0


def main() -> int:
    arg_parser = _build_arg_parser()
    args = arg_parser.parse_args()
    return run_demo(args)


if __name__ == "__main__":
    raise SystemExit(main())
