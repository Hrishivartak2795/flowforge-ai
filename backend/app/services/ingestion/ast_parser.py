"""One Python source file → a typed, deterministic intermediate representation.

Uses only the standard library ``ast`` module, which parses without ever
executing or importing the target code — safe on untrusted repositories
(ADR-002/ADR-008). This module has no opinion on where the file sits inside a
repository; it takes a bare :class:`~pathlib.Path` and derives its internal
``module_identifier`` from the file stem alone. Step 5/6 (extractors,
persistence) compose a repo-relative identifier when they have the checkout
root available — that concern deliberately does not leak in here.
"""

from __future__ import annotations

import ast
import hashlib
import tokenize
from dataclasses import dataclass
from pathlib import Path

from app.services.ingestion.errors import ParseError

# ------------------------------------------------------------------------- IR


@dataclass(frozen=True)
class ImportIR:
    """One imported name, in source order."""

    from_module: str | None
    imported_name: str
    alias: str | None
    is_relative: bool
    relative_level: int
    line: int


@dataclass(frozen=True)
class FunctionIR:
    """A top-level function or a class method."""

    qualified_name: str
    name: str
    signature: str
    decorators: tuple[str, ...]
    docstring: str | None
    is_async: bool
    line_start: int
    line_end: int
    source_snippet: str
    content_hash: str


@dataclass(frozen=True)
class ClassIR:
    """A top-level class and its direct methods."""

    qualified_name: str
    name: str
    decorators: tuple[str, ...]
    base_classes: tuple[str, ...]
    docstring: str | None
    line_start: int
    line_end: int
    source_snippet: str
    content_hash: str
    methods: tuple[FunctionIR, ...]


@dataclass(frozen=True)
class ModuleIR:
    """The full parse result for one file."""

    module_identifier: str
    file_path: Path
    docstring: str | None
    imports: tuple[ImportIR, ...]
    functions: tuple[FunctionIR, ...]
    classes: tuple[ClassIR, ...]
    source: str
    file_hash: str


# --------------------------------------------------------------------- helpers

_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _get_source_segment(source: str, node: ast.stmt, path: Path) -> str:
    snippet = ast.get_source_segment(source, node)
    if snippet is None:
        raise ParseError(
            f"could not extract source segment for node at line {node.lineno}",
            path=path,
        )
    return snippet


def _build_signature(node: _FunctionNode) -> str:
    args_str = ast.unparse(node.args)
    signature = f"({args_str})"
    if node.returns is not None:
        signature += f" -> {ast.unparse(node.returns)}"
    return signature


def _extract_function(
    node: _FunctionNode, *, qualified_name: str, source: str, path: Path
) -> FunctionIR:
    snippet = _get_source_segment(source, node, path)
    assert node.end_lineno is not None  # guaranteed for parsed-from-text nodes
    return FunctionIR(
        qualified_name=qualified_name,
        name=node.name,
        signature=_build_signature(node),
        decorators=tuple(ast.unparse(d) for d in node.decorator_list),
        docstring=ast.get_docstring(node, clean=False),
        is_async=isinstance(node, ast.AsyncFunctionDef),
        line_start=node.lineno,
        line_end=node.end_lineno,
        source_snippet=snippet,
        content_hash=_hash_text(snippet),
    )


def _extract_class(
    node: ast.ClassDef, *, module_identifier: str, source: str, path: Path
) -> ClassIR:
    snippet = _get_source_segment(source, node, path)
    assert node.end_lineno is not None

    methods: list[FunctionIR] = []
    for child in node.body:
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            methods.append(
                _extract_function(
                    child,
                    qualified_name=f"{module_identifier}.{node.name}.{child.name}",
                    source=source,
                    path=path,
                )
            )

    return ClassIR(
        qualified_name=f"{module_identifier}.{node.name}",
        name=node.name,
        decorators=tuple(ast.unparse(d) for d in node.decorator_list),
        base_classes=tuple(ast.unparse(b) for b in node.bases),
        docstring=ast.get_docstring(node, clean=False),
        line_start=node.lineno,
        line_end=node.end_lineno,
        source_snippet=snippet,
        content_hash=_hash_text(snippet),
        methods=tuple(methods),
    )


def _extract_import(node: ast.Import) -> list[ImportIR]:
    return [
        ImportIR(
            from_module=None,
            imported_name=alias.name,
            alias=alias.asname,
            is_relative=False,
            relative_level=0,
            line=node.lineno,
        )
        for alias in node.names
    ]


def _extract_import_from(node: ast.ImportFrom) -> list[ImportIR]:
    return [
        ImportIR(
            from_module=node.module,
            imported_name=alias.name,
            alias=alias.asname,
            is_relative=node.level > 0,
            relative_level=node.level,
            line=node.lineno,
        )
        for alias in node.names
    ]


# ------------------------------------------------------------------- entrypoint


def parse_python_file(path: Path) -> ModuleIR:
    """Parse one Python file into a :class:`ModuleIR`, or raise :class:`ParseError`.

    Never executes or imports the target file — ``ast.parse`` only.
    """
    try:
        with tokenize.open(path) as f:
            source = f.read()
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise ParseError(f"could not read {path}: {exc}", path=path) from exc

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise ParseError(f"syntax error in {path}: {exc}", path=path) from exc

    module_identifier = path.stem

    imports: list[ImportIR] = []
    functions: list[FunctionIR] = []
    classes: list[ClassIR] = []

    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend(_extract_import(node))
        elif isinstance(node, ast.ImportFrom):
            imports.extend(_extract_import_from(node))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            functions.append(
                _extract_function(
                    node,
                    qualified_name=f"{module_identifier}.{node.name}",
                    source=source,
                    path=path,
                )
            )
        elif isinstance(node, ast.ClassDef):
            classes.append(
                _extract_class(
                    node,
                    module_identifier=module_identifier,
                    source=source,
                    path=path,
                )
            )

    return ModuleIR(
        module_identifier=module_identifier,
        file_path=path.resolve(),
        docstring=ast.get_docstring(tree, clean=False),
        imports=tuple(imports),
        functions=tuple(functions),
        classes=tuple(classes),
        source=source,
        file_hash=_hash_text(source),
    )
