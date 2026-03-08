from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_demo_config
from .header import HeaderParseResult, RegexHeaderParser
from .parser import ParseResult, SpellParser
from .tokenizer import LogTokenizer


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
    return parser


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


def _parse_line_to_payload(
    *,
    line_id: int,
    log: str,
    header_parser: RegexHeaderParser,
    parser: SpellParser,
    show_tokens: bool,
) -> dict[str, object]:
    header = header_parser.parse(log)
    result = parser.process(header.context, line_id=line_id)
    return _build_jsonl_payload(
        line_id=line_id,
        log=log,
        header=header,
        result=result,
        show_tokens=show_tokens,
    )


def run_demo(args: argparse.Namespace) -> int:
    if not args.log_file.exists() or not args.log_file.is_file():
        raise FileNotFoundError(f"Log file not found: {args.log_file}")

    config = load_demo_config(args.config)

    output_dir = config.output.dir
    output_dir.mkdir(parents=True, exist_ok=True)
    parsed_output_path = output_dir / config.output.parsed_file
    template_output_path = output_dir / config.output.template_file

    tokenizer = LogTokenizer(
        delimiters=config.tokenizer.delimiters,
        extra_delimiters=config.tokenizer.extra_delimiters,
        mask_patterns=config.tokenizer.mask_patterns,
        use_jieba=config.tokenizer.use_jieba,
    )
    parser = SpellParser(tau_ratio=config.spell.tau_ratio, tokenizer=tokenizer)
    header_parser = RegexHeaderParser(
        parse_structure=config.header.parse_structure,
        field_patterns=config.header.field_patterns,
        strict_mode=config.header.strict_mode,
    )

    parsed_count = 0

    with (
        args.log_file.open("r", encoding="utf-8") as input_fp,
        parsed_output_path.open("w", encoding="utf-8") as parsed_fp,
    ):
        for index, raw_line in enumerate(input_fp, start=1):
            log = raw_line.strip()
            if not log:
                continue

            payload = _parse_line_to_payload(
                line_id=index,
                log=log,
                header_parser=header_parser,
                parser=parser,
                show_tokens=config.output.show_tokens,
            )
            parsed_fp.write(json.dumps(payload, ensure_ascii=False))
            parsed_fp.write("\n")

            parsed_count += 1

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

    print(f"Parsed lines: {parsed_count}")
    print(f"Per-line output: {parsed_output_path}")
    print(f"Templates output: {template_output_path}")

    return 0


def main() -> int:
    arg_parser = _build_arg_parser()
    args = arg_parser.parse_args()
    return run_demo(args)


if __name__ == "__main__":
    raise SystemExit(main())
