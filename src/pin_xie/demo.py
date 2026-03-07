from __future__ import annotations

import argparse
import json
from pathlib import Path

from .parser import SpellParser
from .tokenizer import DEFAULT_DELIMITERS, LogTokenizer


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Minimal Spell demo: parse a log file and write outputs to files.",
    )
    parser.add_argument("log_file", type=Path, help="Path to input log file")
    parser.add_argument(
        "--tau-ratio",
        type=float,
        default=0.5,
        help="LCS threshold ratio (default: 0.5)",
    )
    parser.add_argument(
        "--delimiters",
        type=str,
        default=DEFAULT_DELIMITERS,
        help="Regex delimiters for first-pass split",
    )
    parser.add_argument(
        "--no-jieba",
        action="store_true",
        help="Disable jieba and fallback to character-level Han splitting",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory for parsed output and templates (default: output)",
    )
    parser.add_argument(
        "--parsed-file",
        type=str,
        default="parsed_results.jsonl",
        help="Parsed per-line output file name",
    )
    parser.add_argument(
        "--template-file",
        type=str,
        default="templates.txt",
        help="Final templates output file name",
    )
    parser.add_argument(
        "--result-format",
        choices=("jsonl", "text"),
        default="jsonl",
        help="Per-line parsed output format (default: jsonl)",
    )
    parser.add_argument(
        "--show-tokens",
        action="store_true",
        help="Include tokens in per-line output",
    )
    return parser


def run_demo(args: argparse.Namespace) -> int:
    if not args.log_file.exists() or not args.log_file.is_file():
        raise FileNotFoundError(f"Log file not found: {args.log_file}")

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    parsed_output_path = output_dir / args.parsed_file
    template_output_path = output_dir / args.template_file

    tokenizer = LogTokenizer(delimiters=args.delimiters, use_jieba=not args.no_jieba)
    parser = SpellParser(tau_ratio=args.tau_ratio, tokenizer=tokenizer)
    parsed_count = 0

    with (
        args.log_file.open("r", encoding="utf-8") as input_fp,
        parsed_output_path.open("w", encoding="utf-8") as parsed_fp,
    ):
        for index, raw_line in enumerate(input_fp, start=1):
            log = raw_line.strip()
            if not log:
                continue

            result = parser.process(log, line_id=index)
            template = " ".join(result.template_tokens)

            if args.result_format == "jsonl":
                payload = {
                    "line_id": index,
                    "cluster_id": result.cluster_id,
                    "template": template,
                    "template_tokens": result.template_tokens,
                    "parameters": result.parameters,
                    "log": log,
                }
                if args.show_tokens:
                    payload["tokens"] = result.tokens

                parsed_fp.write(json.dumps(payload, ensure_ascii=False))
                parsed_fp.write("\n")
            else:
                if args.show_tokens:
                    parsed_fp.write(
                        f"[{index}] cid={result.cluster_id} tokens={result.tokens} "
                        f"template={template} params={result.parameters} log={log}\n"
                    )
                else:
                    parsed_fp.write(
                        f"[{index}] cid={result.cluster_id} "
                        f"template={template} params={result.parameters} log={log}\n"
                    )

            parsed_count += 1

    with template_output_path.open("w", encoding="utf-8") as tpl_fp:
        tpl_fp.write("=== Final Templates ===\n")
        tpl_fp.write(f"total_clusters={len(parser.all_clusters())}\n\n")

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
