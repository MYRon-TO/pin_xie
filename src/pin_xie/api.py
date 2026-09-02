from __future__ import annotations

# pyright: standard
import json
import random
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .cluster import LCSObject
from .config import (
    DemoConfig,
    InputMode,
    load_demo_config,
    parse_demo_config,
    read_toml_config,
)
from .header import (
    CONTEXT_ONLY_STRUCTURE,
    HeaderConfigurationError,
    HeaderValidationIssue,
    RegexHeaderParser,
)
from .models import (
    InputToken,
    ParameterCapture,
    TemplateToken,
    input_token_to_json,
    parameter_capture_to_json,
    template_token_to_json,
    token_source_to_json,
)
from .multiline import LogRecordAssembler
from .parser import SpellParser
from .template import render_template_tokens
from .tokenizer import LogTokenizer

TEMPLATE_CACHE_FILE = "templates.json"


class RunMode(str, Enum):
    LEARN_PARSE = "learn_parse"
    LEARN = "learn"
    PARSE = "parse"


@dataclass
class ParsedRecord:
    line_id: int
    end_line_id: int
    physical_line_count: int
    header_matched: bool
    cluster_id: int
    context: str
    template: str
    template_tokens: list[TemplateToken]
    parameters: list[ParameterCapture]
    log: str
    header_fields: dict[str, str]
    tokens: list[InputToken] | None = None


@dataclass
class RunReport:
    mode: RunMode
    processed_records: int
    processed_physical_lines: int
    parsed_output_path: Path | None
    template_output_path: Path | None
    template_cache_path: Path | None


@dataclass
class ConfigValidationReport:
    requires_header_validation: bool
    total_samples: int
    successful_samples: int
    failures: list[FailureItem]

    @property
    def all_samples_valid(self) -> bool:
        return not self.failures

    @property
    def failed_sample_indexes(self) -> list[int]:
        return [failure.index for failure in self.failures if failure.stage == "sample"]

    @property
    def failed_samples(self) -> list[str]:
        return [
            failure.sample for failure in self.failures if failure.stage == "sample"
        ]


@dataclass
class FailureItem:
    index: int
    sample: str
    stage: str
    reason: str
    message: str
    field: str | None = None
    pattern: str | None = None
    structure_part: str | None = None


class PinXieEngine:
    def __init__(self, config: DemoConfig) -> None:
        self.config = config
        self.tokenizer = self._create_tokenizer()
        self.header_parser = self._create_header_parser()
        self.parser = self._create_spell_parser()

    @classmethod
    def from_config_path(cls, config_path: Path | str) -> PinXieEngine:
        config = load_demo_config(Path(config_path))
        return cls(config)

    @classmethod
    def from_config_data(cls, data: Mapping[str, Any]) -> PinXieEngine:
        config = parse_demo_config(data)
        return cls(config)

    @staticmethod
    def _normalize_samples(samples: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        for sample in samples:
            if sample.endswith("\r\n"):
                sample = sample[:-2]
            elif sample.endswith(("\n", "\r")):
                sample = sample[:-1]
            normalized.append(sample)
        return normalized

    @staticmethod
    def _build_failure_item(
        issue: HeaderValidationIssue,
        *,
        index: int,
        sample: str,
    ) -> FailureItem:
        return FailureItem(
            index=index,
            sample=sample,
            stage=issue.stage,
            reason=issue.reason,
            message=issue.message,
            field=issue.field,
            pattern=issue.pattern,
            structure_part=issue.structure_part,
        )

    @classmethod
    def _build_config_failure_report(
        cls,
        issue: HeaderValidationIssue,
        samples: Iterable[str],
    ) -> ConfigValidationReport:
        normalized_samples = cls._normalize_samples(samples)
        # INFO: stage=config has no natural sample reference, so use index=0 and sample="".
        return ConfigValidationReport(
            requires_header_validation=True,
            total_samples=len(normalized_samples),
            successful_samples=0,
            failures=[cls._build_failure_item(issue, index=0, sample="")],
        )

    @staticmethod
    def read_toml_config(config_path: Path | str) -> dict[str, Any]:
        return read_toml_config(Path(config_path))

    @staticmethod
    def parse_config_data(data: Mapping[str, Any]) -> DemoConfig:
        return parse_demo_config(data)

    @classmethod
    def from_demo_config(cls, config: DemoConfig) -> PinXieEngine:
        return cls(config)

    @staticmethod
    def validate_header_extraction(
        config: DemoConfig,
        samples: Iterable[str],
    ) -> ConfigValidationReport:
        normalized_samples = PinXieEngine._normalize_samples(samples)

        try:
            parser = RegexHeaderParser(
                parse_structure=config.header.parse_structure,
                field_patterns=config.header.field_patterns,
                strict_mode=config.header.strict_mode,
            )
        except HeaderConfigurationError as exc:
            return PinXieEngine._build_config_failure_report(
                exc.issue, normalized_samples
            )

        non_context_fields = [
            field_name
            for field_name in parser.fields_in_structure
            if field_name != "context"
        ]
        has_literal_constraints = any(
            not char.isspace()
            for char in parser.parse_structure.replace(CONTEXT_ONLY_STRUCTURE, "")
        )

        if (
            config.input.mode is InputMode.SINGLE
            and not non_context_fields
            and not has_literal_constraints
        ):
            return ConfigValidationReport(
                requires_header_validation=False,
                total_samples=len(normalized_samples),
                successful_samples=len(normalized_samples),
                failures=[],
            )

        failures: list[FailureItem] = []
        success_count = 0

        for sample_index, sample in enumerate(normalized_samples, start=1):
            issue: HeaderValidationIssue | None = None
            if config.input.mode is InputMode.MULTILINE:
                first_line = sample.split("\n", 1)[0].removesuffix("\r")
                if not parser.is_header_line(first_line):
                    issue = HeaderValidationIssue(
                        stage="sample",
                        reason="sample_first_line_not_header",
                        message="Sample first physical line does not match the configured header",
                    )
            if issue is None:
                issue = parser.validate_sample(sample)
            if issue is None:
                success_count += 1
                continue

            failures.append(
                PinXieEngine._build_failure_item(
                    issue,
                    index=sample_index,
                    sample=sample,
                )
            )

        return ConfigValidationReport(
            requires_header_validation=True,
            total_samples=len(normalized_samples),
            successful_samples=success_count,
            failures=failures,
        )

    @classmethod
    def validate_config_path(
        cls,
        config_path: Path | str,
        samples: Iterable[str],
    ) -> ConfigValidationReport:
        config_data = cls.read_toml_config(config_path)
        normalized_samples = cls._normalize_samples(samples)

        header_data = config_data.get("header", {})
        if isinstance(header_data, Mapping):
            parse_structure = str(
                header_data.get("parse_structure", CONTEXT_ONLY_STRUCTURE)
            )
            if "<context>" not in parse_structure:
                return cls._build_config_failure_report(
                    HeaderValidationIssue(
                        stage="config",
                        reason="parse_structure_missing_context",
                        message="header.parse_structure must contain '<context>'",
                    ),
                    normalized_samples,
                )

        config = cls.parse_config_data(config_data)
        return cls.validate_header_extraction(config, normalized_samples)

    def set_template_variable_name(
        self,
        cluster_id: int,
        var_index: int,
        var_name: str | None,
    ) -> None:
        cluster = self._get_cluster_or_raise(cluster_id)
        cluster.set_variable_name(var_index, var_name)

    def set_template_variable_names(
        self,
        cluster_id: int,
        variable_names: Mapping[int, str | None],
    ) -> dict[int, str]:
        cluster = self._get_cluster_or_raise(cluster_id)
        cluster.replace_variable_names(variable_names)
        return cluster.get_variable_names()

    def get_template_variable_names(self, cluster_id: int) -> dict[int, str]:
        cluster = self._get_cluster_or_raise(cluster_id)
        return cluster.get_variable_names()

    def reset_model(self) -> None:
        self.parser = self._create_spell_parser()

    def process_log(
        self,
        log: str,
        *,
        line_id: int | None = None,
        end_line_id: int | None = None,
        update_model: bool = True,
    ) -> ParsedRecord:
        effective_line_id = self.parser.next_line_id if line_id is None else line_id
        effective_end_line_id = (
            effective_line_id if end_line_id is None else end_line_id
        )
        if effective_end_line_id < effective_line_id:
            raise ValueError("end_line_id must be greater than or equal to line_id")

        header = self.header_parser.parse(log)
        result = self.parser.process(
            header.context, line_id=line_id, update_model=update_model
        )
        header_fields = {
            name: value for name, value in header.fields.items() if name != "context"
        }
        rendered_template_tokens = render_template_tokens(result.template_tokens)
        return ParsedRecord(
            line_id=effective_line_id,
            end_line_id=effective_end_line_id,
            physical_line_count=effective_end_line_id - effective_line_id + 1,
            header_matched=header.matched,
            cluster_id=result.cluster_id,
            context=header.context,
            template=" ".join(rendered_template_tokens),
            template_tokens=result.template_tokens,
            parameters=result.parameters,
            log=log,
            header_fields=header_fields,
            tokens=result.tokens,
        )

    def process_line(
        self,
        log: str,
        *,
        line_id: int | None = None,
        end_line_id: int | None = None,
        update_model: bool = True,
    ) -> ParsedRecord:
        return self.process_log(
            log,
            line_id=line_id,
            end_line_id=end_line_id,
            update_model=update_model,
        )

    def process_lines(
        self,
        logs: Iterable[str],
        *,
        start_line_id: int = 1,
        update_model: bool = True,
    ) -> Iterator[ParsedRecord]:
        assembler = LogRecordAssembler(self.config.input.mode, self.header_parser)
        for logical_log in assembler.assemble(logs, start_line=start_line_id):
            yield self.process_log(
                logical_log.text,
                line_id=logical_log.start_line,
                end_line_id=logical_log.end_line,
                update_model=update_model,
            )

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

        cache_path = self.template_cache_path(template_dir_path)
        if selected_mode is RunMode.PARSE or cache_path.is_file():
            _ = self.load_template_cache(template_dir_path)
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

        processed_records = 0
        processed_physical_lines = 0

        def count_lines(lines: Iterable[str]) -> Iterator[str]:
            nonlocal processed_physical_lines
            for raw_line in lines:
                processed_physical_lines += 1
                yield raw_line

        with log_path.open("r", encoding="utf-8") as input_fp:
            if should_update_model and self.config.learning.shuffle:
                assembler = LogRecordAssembler(
                    self.config.input.mode, self.header_parser
                )
                logical_logs = list(
                    assembler.assemble(count_lines(input_fp), start_line=1)
                )
                learning_logs = list(logical_logs)
                random.Random(self.config.learning.random_seed).shuffle(learning_logs)
                for logical_log in learning_logs:
                    self.process_log(
                        logical_log.text,
                        line_id=logical_log.start_line,
                        end_line_id=logical_log.end_line,
                        update_model=True,
                    )

                if should_write_parsed_output:
                    records = (
                        self.process_log(
                            logical_log.text,
                            line_id=logical_log.start_line,
                            end_line_id=logical_log.end_line,
                            update_model=False,
                        )
                        for logical_log in logical_logs
                    )
                else:
                    records = iter(())
                    processed_records = len(logical_logs)
            else:
                records = self.process_lines(
                    count_lines(input_fp), update_model=should_update_model
                )

            if should_write_parsed_output and parsed_output_path is not None:
                with parsed_output_path.open("w", encoding="utf-8") as parsed_fp:
                    for record in records:
                        payload = self._record_to_payload(
                            record, show_tokens=self.config.output.show_tokens
                        )
                        parsed_fp.write(json.dumps(payload, ensure_ascii=False))
                        parsed_fp.write("\n")
                        processed_records += 1
            else:
                for _record in records:
                    processed_records += 1

        if should_write_template_summary and template_output_path is not None:
            self.write_template_summary(template_output_path)

        template_cache_path: Path | None = None
        if should_update_model:
            template_cache_path = self.save_template_cache(template_dir_path)

        return RunReport(
            mode=selected_mode,
            processed_records=processed_records,
            processed_physical_lines=processed_physical_lines,
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
        header_config = {
            "parse_structure": self.config.header.parse_structure,
            "strict_mode": self.config.header.strict_mode,
            "field_patterns": dict(self.config.header.field_patterns),
        }
        input_config = {"mode": self.config.input.mode.value}
        learning_config = {
            "shuffle": self.config.learning.shuffle,
            "random_seed": self.config.learning.random_seed,
        }
        tokenizer_config = {
            "delimiters": self.config.tokenizer.delimiters,
            "extra_delimiters": list(self.config.tokenizer.extra_delimiters),
            "use_jieba": self.config.tokenizer.use_jieba,
            "mask_patterns": [
                {"name": mask.name, "pattern": mask.pattern}
                for mask in self.config.tokenizer.mask_patterns
            ],
        }
        state = self.parser.to_template_state(
            input_config=input_config,
            header_config=header_config,
            learning_config=learning_config,
            tokenizer_config=tokenizer_config,
        )

        with cache_path.open("w", encoding="utf-8") as fp:
            json.dump(state, fp, ensure_ascii=False, indent=2)
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
            raise ValueError(  # noqa: TRY004 - public cache API uses ValueError
                "Invalid template cache: root must be an object"
            )

        input_config = {"mode": self.config.input.mode.value}
        header_config = {
            "parse_structure": self.config.header.parse_structure,
            "strict_mode": self.config.header.strict_mode,
            "field_patterns": dict(self.config.header.field_patterns),
        }
        tokenizer_config = {
            "delimiters": self.config.tokenizer.delimiters,
            "extra_delimiters": list(self.config.tokenizer.extra_delimiters),
            "use_jieba": self.config.tokenizer.use_jieba,
            "mask_patterns": [
                {"name": mask.name, "pattern": mask.pattern}
                for mask in self.config.tokenizer.mask_patterns
            ],
        }
        loaded_parser = SpellParser.from_template_state(
            state,
            tokenizer=self.tokenizer,
            input_config=input_config,
            header_config=header_config,
            tokenizer_config=tokenizer_config,
        )
        self.parser = loaded_parser
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
                f"mask_patterns_count={len(self.config.tokenizer.mask_patterns)} "
                f"mask_pattern_names={json.dumps([mask.name for mask in self.config.tokenizer.mask_patterns], ensure_ascii=False)}\n\n"
            )

            for cluster in self.parser.all_clusters():
                rendered_template_tokens = render_template_tokens(
                    cluster.template_tokens
                )
                template = " ".join(rendered_template_tokens)
                line_ids_preview = ", ".join(
                    str(line_id) for line_id in cluster.line_ids[:20]
                )
                if len(cluster.line_ids) > 20:
                    line_ids_preview = f"{line_ids_preview}, ..."

                tpl_fp.write(f"Cluster {cluster.cluster_id}\n")
                tpl_fp.write(f"  size: {cluster.size}\n")
                tpl_fp.write(f"  template: {template}\n")
                for template_index, token in enumerate(cluster.template_tokens):
                    if token.kind == "variable":
                        sources = [
                            token_source_to_json(source) for source in token.sources
                        ]
                        tpl_fp.write(
                            f"  variable[{template_index}]: var_name={token.var_name} "
                            f"sources={json.dumps(sources, ensure_ascii=False)}\n"
                        )
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
            "end_line_id": record.end_line_id,
            "physical_line_count": record.physical_line_count,
            "header_matched": record.header_matched,
            "cluster_id": record.cluster_id,
            "context": record.context,
            "template": record.template,
            "template_tokens": [
                template_token_to_json(token) for token in record.template_tokens
            ],
            "parameters": [
                parameter_capture_to_json(parameter) for parameter in record.parameters
            ],
            "log": record.log,
        }
        for field_name, field_value in record.header_fields.items():
            payload[f"header_{field_name}"] = field_value

        if show_tokens and record.tokens is not None:
            payload["tokens"] = [input_token_to_json(token) for token in record.tokens]

        return payload

    def _get_cluster_or_raise(self, cluster_id: int) -> LCSObject:
        cluster = self.parser.clusters_by_id.get(cluster_id)
        if cluster is None:
            raise KeyError(f"Cluster not found: {cluster_id}")
        return cluster
