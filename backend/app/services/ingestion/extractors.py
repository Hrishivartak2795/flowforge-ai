"""Step 4 ``ModuleIR`` → persistence-ready DTOs.

Pure functions: no I/O, no DB, no ``project_id`` (Step 6 attaches that when
mapping these DTOs to ORM instances). Consumes the Step 3 classification
("code" vs "test") to decide which DTO family a file's units become — the
split is strict and file-scoped, never per-unit naming.

Deferred design issue: ``ModuleIR.imports`` is computed in Step 4 but is not
consumed here. The M1 ``code_unit`` schema has no column for import edges, so
there is nowhere to put them yet. Do not add one silently — that needs a
future Alembic migration (and probably an ADR update) before any
import-graph feature reads it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.services.ingestion.ast_parser import ClassIR, FunctionIR, ModuleIR

# ------------------------------------------------------------------------- DTOs


@dataclass(frozen=True)
class CodeUnitDTO:
    """One citeable unit of implementation: a function, class, or method."""

    file_path: str
    unit_type: str
    qualified_name: str
    signature: str | None
    docstring: str | None
    source_code: str
    start_line: int
    end_line: int
    content_hash: str


@dataclass(frozen=True)
class TestUnitDTO:
    """One citeable unit of test coverage: a ``test_*`` function or method."""

    file_path: str
    test_name: str
    qualified_name: str
    source_code: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class ExtractionUnits:
    """The DTOs extracted from one file. Exactly one side is populated."""

    code_units: tuple[CodeUnitDTO, ...]
    test_units: tuple[TestUnitDTO, ...]


# --------------------------------------------------------------------- helpers


def _module_identifier(relative_path: Path) -> str:
    return relative_path.as_posix().removesuffix(".py").replace("/", ".")


def _code_unit_from_function(
    fn: FunctionIR, *, file_path: str, qualified_name: str, unit_type: str
) -> CodeUnitDTO:
    return CodeUnitDTO(
        file_path=file_path,
        unit_type=unit_type,
        qualified_name=qualified_name,
        signature=fn.signature,
        docstring=fn.docstring,
        source_code=fn.source_snippet,
        start_line=fn.line_start,
        end_line=fn.line_end,
        content_hash=fn.content_hash,
    )


def _code_unit_from_class(
    cls: ClassIR, *, file_path: str, qualified_name: str
) -> CodeUnitDTO:
    return CodeUnitDTO(
        file_path=file_path,
        unit_type="class",
        qualified_name=qualified_name,
        signature=None,
        docstring=cls.docstring,
        source_code=cls.source_snippet,
        start_line=cls.line_start,
        end_line=cls.line_end,
        content_hash=cls.content_hash,
    )


def _test_unit_from_function(
    fn: FunctionIR, *, file_path: str, qualified_name: str
) -> TestUnitDTO:
    return TestUnitDTO(
        file_path=file_path,
        test_name=fn.name,
        qualified_name=qualified_name,
        source_code=fn.source_snippet,
        start_line=fn.line_start,
        end_line=fn.line_end,
    )


def _extract_code_units(
    module: ModuleIR, *, file_path: str, module_identifier: str
) -> tuple[CodeUnitDTO, ...]:
    units: list[CodeUnitDTO] = []

    for fn in module.functions:
        units.append(
            _code_unit_from_function(
                fn,
                file_path=file_path,
                qualified_name=f"{module_identifier}.{fn.name}",
                unit_type="function",
            )
        )

    for cls in module.classes:
        units.append(
            _code_unit_from_class(
                cls,
                file_path=file_path,
                qualified_name=f"{module_identifier}.{cls.name}",
            )
        )
        for method in cls.methods:
            units.append(
                _code_unit_from_function(
                    method,
                    file_path=file_path,
                    qualified_name=f"{module_identifier}.{cls.name}.{method.name}",
                    unit_type="method",
                )
            )

    return tuple(units)


def _extract_test_units(
    module: ModuleIR, *, file_path: str, module_identifier: str
) -> tuple[TestUnitDTO, ...]:
    units: list[TestUnitDTO] = []

    for fn in module.functions:
        if fn.name.startswith("test_"):
            units.append(
                _test_unit_from_function(
                    fn,
                    file_path=file_path,
                    qualified_name=f"{module_identifier}.{fn.name}",
                )
            )

    for cls in module.classes:
        for method in cls.methods:
            if method.name.startswith("test_"):
                units.append(
                    _test_unit_from_function(
                        method,
                        file_path=file_path,
                        qualified_name=f"{module_identifier}.{cls.name}.{method.name}",
                    )
                )

    return tuple(units)


# ------------------------------------------------------------------- entrypoint


def extract_units(
    module: ModuleIR,
    relative_path: Path,
    classification: Literal["code", "test"],
) -> ExtractionUnits:
    """Map ``module`` into DTOs, split strictly by file-level classification."""
    file_path = relative_path.as_posix()
    module_identifier = _module_identifier(relative_path)

    if classification == "code":
        return ExtractionUnits(
            code_units=_extract_code_units(
                module, file_path=file_path, module_identifier=module_identifier
            ),
            test_units=(),
        )

    return ExtractionUnits(
        code_units=(),
        test_units=_extract_test_units(
            module, file_path=file_path, module_identifier=module_identifier
        ),
    )
