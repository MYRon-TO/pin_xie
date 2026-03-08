from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Iterator

from .config import DemoConfig, load_demo_config
from .header import RegexHeaderParser
from .parser import SpellParser
from .tokenizer import LogTokenizer


TEMPLATE_CACHE_FILE = "templates.json"


class RunMode(str, Enum):
    LEARN_PARSE = "learn_parse"
    LEARN = "learn"
    PARSE = "parse"


@dataclass
class ParsedRecord:
    line_id: int
    header_matched: bool
    cluster_id: int
    context: str
    template: str
    template_tokens: list[str]
    parameters: list[str]
    log: str
    header_fields: dict[str, str]
    tokens: list[str] | None = None


@dataclass
class RunReport:
    mode: RunMode
    processed_lines: int
    parsed_output_path: Path | None
    template_output_path: Path | None
    template_cache_path: Path | None


class PinXieEngine:
    def __init__(self, config: DemoConfig) -> None:
        self.config = config
        self.tokenizer = self._create_tokenizer()
        self.header_parser = self._create_header_parser()
        self.parser = self._create_spell_parser()

    @classmethod
    def from_config_path(cls, config_path: Path | str) -> "PinXieEngine":
        config = load_demo_config(Path(config_path))
        return cls(config)

    @classmethod
    def from_demo_config(cls, config: DemoConfig) -> "PinXieEngine":
        return cls(config)

    def reset_model(self) -> None:
        self.parser = self._create_spell_parser()

    def process_line(
        self,
        log: str,
        *,
        line_id: int | None = None,
        update_model: bool = True,
    ) -> ParsedRecord:
        effective_line_id = self.parser.next_line_id if line_id is None else line_id

        header = self.header_parser.parse(log)
        result = self.parser.process(
            header.context,
            line_id=line_id,
            update_model=update_model,
        )

        header_fields = {
            field_name: field_value
            for field_name, field_value in header.fields.items()
            if field_name != "context"
        }

        return ParsedRecord(
            line_id=effective_line_id,
            header_matched=header.matched,
            cluster_id=result.cluster_id,
            context=header.context,
            template=" ".join(result.template_tokens),
            template_tokens=result.template_tokens,
            parameters=result.parameters,
            log=log,
            header_fields=header_fields,
            tokens=result.tokens,
        )

    def process_lines(
        self,
        logs: Iterable[str],
        *,
        start_line_id: int = 1,
        update_model: bool = True,
    ) -> Iterator[ParsedRecord]:
        for index, raw_log in enumerate(logs, start=start_line_id):
            log = raw_log.strip()
            if not log:
                continue

            yield self.process_line(log, line_id=index, update_model=update_model)

    def run_file(
        self,
        log_file: Path | str,
        *,
        mode: RunMode | str = RunMode.LEARN_PARSE,
        template_dir: Path | str = Path("cache"),
        write_parsed_output: bool | None = None,
        write_template_summary: bool | None = None,
    ) -> RunReport:
        selected_mode = self._normalize_mode(mode)

        log_path = Path(log_file)
        if not log_path.exists() or not log_path.is_file():
            raise FileNotFoundError(f"Log file not found: {log_path}")

        template_dir_path = Path(template_dir)

        if selected_mode is RunMode.PARSE:
            self.load_template_cache(template_dir_path)
        else:
            self.reset_model()

        should_update_model = selected_mode is not RunMode.PARSE
        should_write_parsed_output = (
            selected_mode is not RunMode.LEARN
            if write_parsed_output is None
            else write_parsed_output
        )
        should_write_template_summary = (
            selected_mode is RunMode.LEARN_PARSE
            if write_template_summary is None
            else write_template_summary
        )

        parsed_output_path: Path | None = None
        template_output_path: Path | None = None
        if should_write_parsed_output or should_write_template_summary:
            output_dir = self.config.output.dir
            output_dir.mkdir(parents=True, exist_ok=True)
            parsed_output_path = output_dir / self.config.output.parsed_file
            template_output_path = output_dir / self.config.output.template_file

        processed_count = 0
        if should_write_parsed_output and parsed_output_path is not None:
            with (
                log_path.open("r", encoding="utf-8") as input_fp,
                parsed_output_path.open("w", encoding="utf-8") as parsed_fp,
            ):
                for index, raw_line in enumerate(input_fp, start=1):
                    log = raw_line.strip()
                    if not log:
                        continue

                    record = self.process_line(
                        log,
                        line_id=index,
                        update_model=should_update_model,
                    )
                    payload = self._record_to_payload(
                        record,
                        show_tokens=self.config.output.show_tokens,
                    )
                    parsed_fp.write(json.dumps(payload, ensure_ascii=False))
                    parsed_fp.write("\n")
                    processed_count += 1
        else:
            with log_path.open("r", encoding="utf-8") as input_fp:
                for index, raw_line in enumerate(input_fp, start=1):
                    log = raw_line.strip()
                    if not log:
                        continue

                    self.process_line(
                        log,
                        line_id=index,
                        update_model=should_update_model,
                    )
                    processed_count += 1

        if should_write_template_summary and template_output_path is not None:
            self.write_template_summary(template_output_path)

        template_cache_path: Path | None = None
        if should_update_model:
            template_cache_path = self.save_template_cache(template_dir_path)

        return RunReport(
            mode=selected_mode,
            processed_lines=processed_count,
            parsed_output_path=parsed_output_path
            if should_write_parsed_output
            else None,
            template_output_path=(
                template_output_path if should_write_template_summary else None
            ),
            template_cache_path=template_cache_path,
        )

    def save_template_cache(self, template_dir: Path | str = Path("cache")) -> Path:
        template_dir_path = Path(template_dir)
        template_dir_path.mkdir(parents=True, exist_ok=True)
        cache_path = self.template_cache_path(template_dir_path)

        with cache_path.open("w", encoding="utf-8") as fp:
            json.dump(self.parser.to_template_state(), fp, ensure_ascii=False, indent=2)
            fp.write("\n")

        return cache_path

    def load_template_cache(self, template_dir: Path | str = Path("cache")) -> Path:
        template_dir_path = Path(template_dir)
        cache_path = self.template_cache_path(template_dir_path)
        if not cache_path.exists() or not cache_path.is_file():
            raise FileNotFoundError(
                f"Template cache not found: {cache_path}. "
                f"Run with --mode {RunMode.LEARN.value} first to build templates."
            )

        with cache_path.open("r", encoding="utf-8") as fp:
            state = json.load(fp)

        if not isinstance(state, dict):
            raise ValueError("Invalid template cache: root must be an object")

        self.parser = SpellParser.from_template_state(
            state,
            tokenizer=self.tokenizer,
        )
        return cache_path

    def write_template_summary(self, output_path: Path | str) -> Path:
        target_path = Path(output_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        with target_path.open("w", encoding="utf-8") as tpl_fp:
            tpl_fp.write("=== Final Templates ===\n")
            tpl_fp.write(f"total_clusters={len(self.parser.all_clusters())}\n\n")
            tpl_fp.write("=== Header Parse Config ===\n")
            tpl_fp.write(
                f"parse_structure={self.config.header.parse_structure} "
                f"strict_mode={self.config.header.strict_mode}\n"
            )
            for field_name, field_pattern in self.config.header.field_patterns.items():
                tpl_fp.write(f"field_pattern[{field_name}]={field_pattern}\n")
            tpl_fp.write("\n")
            tpl_fp.write("=== Spell Config ===\n")
            tpl_fp.write(f"tau_ratio={self.config.spell.tau_ratio}\n\n")
            tpl_fp.write("=== Tokenizer Config ===\n")
            tpl_fp.write(
                f"delimiters={self.config.tokenizer.delimiters} "
                f"use_jieba={self.config.tokenizer.use_jieba} "
                f"mask_patterns_count={len(self.config.tokenizer.mask_patterns)}\n\n"
            )

            for cluster in self.parser.all_clusters():
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

        return target_path

    @staticmethod
    def template_cache_path(template_dir: Path | str = Path("cache")) -> Path:
        return Path(template_dir) / TEMPLATE_CACHE_FILE

    @staticmethod
    def _normalize_mode(mode: RunMode | str) -> RunMode:
        if isinstance(mode, RunMode):
            return mode
        return RunMode(mode)

    def _create_tokenizer(self) -> LogTokenizer:
        return LogTokenizer(
            delimiters=self.config.tokenizer.delimiters,
            extra_delimiters=self.config.tokenizer.extra_delimiters,
            mask_patterns=self.config.tokenizer.mask_patterns,
            use_jieba=self.config.tokenizer.use_jieba,
        )

    def _create_header_parser(self) -> RegexHeaderParser:
        return RegexHeaderParser(
            parse_structure=self.config.header.parse_structure,
            field_patterns=self.config.header.field_patterns,
            strict_mode=self.config.header.strict_mode,
        )

    def _create_spell_parser(self) -> SpellParser:
        return SpellParser(
            tau_ratio=self.config.spell.tau_ratio,
            tokenizer=self.tokenizer,
        )

    @staticmethod
    def _record_to_payload(
        record: ParsedRecord,
        *,
        show_tokens: bool,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "line_id": record.line_id,
            "header_matched": record.header_matched,
            "cluster_id": record.cluster_id,
            "context": record.context,
            "template": record.template,
            "template_tokens": record.template_tokens,
            "parameters": record.parameters,
            "log": record.log,
        }
        for field_name, field_value in record.header_fields.items():
            payload[f"header_{field_name}"] = field_value

        if show_tokens and record.tokens is not None:
            payload["tokens"] = record.tokens

        return payload
