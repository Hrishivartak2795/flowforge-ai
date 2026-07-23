"""Tests for :mod:`app.services.ingestion.extractors`."""

from __future__ import annotations

from pathlib import Path

from app.services.ingestion.ast_parser import ClassIR, FunctionIR, ModuleIR
from app.services.ingestion.extractors import extract_units


def _function(
    name: str,
    *,
    qualified_name: str = "",
    signature: str = "()",
    docstring: str | None = None,
    is_async: bool = False,
    line_start: int = 1,
    line_end: int = 2,
    source_snippet: str = "",
    content_hash: str = "",
) -> FunctionIR:
    return FunctionIR(
        qualified_name=qualified_name or name,
        name=name,
        signature=signature,
        decorators=(),
        docstring=docstring,
        is_async=is_async,
        line_start=line_start,
        line_end=line_end,
        source_snippet=source_snippet or f"def {name}(): pass",
        content_hash=content_hash or f"hash-{name}",
    )


def _class(
    name: str,
    *,
    methods: tuple[FunctionIR, ...] = (),
    docstring: str | None = None,
    line_start: int = 1,
    line_end: int = 5,
    source_snippet: str = "",
    content_hash: str = "",
) -> ClassIR:
    return ClassIR(
        qualified_name=name,
        name=name,
        decorators=(),
        base_classes=(),
        docstring=docstring,
        line_start=line_start,
        line_end=line_end,
        source_snippet=source_snippet or f"class {name}: pass",
        content_hash=content_hash or f"hash-{name}",
        methods=methods,
    )


def _module(
    *,
    functions: tuple[FunctionIR, ...] = (),
    classes: tuple[ClassIR, ...] = (),
) -> ModuleIR:
    return ModuleIR(
        module_identifier="unused",
        file_path=Path("/tmp/unused.py"),
        docstring=None,
        imports=(),
        functions=functions,
        classes=classes,
        source="",
        file_hash="unused-hash",
    )


class TestCodeExtraction:
    def test_top_level_function(self) -> None:
        fn = _function("greet", signature="(name: str) -> str", docstring="hi")
        module = _module(functions=(fn,))

        result = extract_units(module, Path("mod.py"), "code")

        assert len(result.code_units) == 1
        unit = result.code_units[0]
        assert unit.unit_type == "function"
        assert unit.qualified_name == "mod.greet"
        assert unit.signature == "(name: str) -> str"
        assert unit.docstring == "hi"
        assert unit.source_code == fn.source_snippet
        assert unit.start_line == fn.line_start
        assert unit.end_line == fn.line_end
        assert unit.content_hash == fn.content_hash
        assert result.test_units == ()

    def test_top_level_class_no_methods(self) -> None:
        cls = _class("Widget")
        module = _module(classes=(cls,))

        result = extract_units(module, Path("mod.py"), "code")

        assert len(result.code_units) == 1
        unit = result.code_units[0]
        assert unit.unit_type == "class"
        assert unit.qualified_name == "mod.Widget"
        assert unit.signature is None

    def test_class_with_methods(self) -> None:
        method = _function("render")
        cls = _class("Widget", methods=(method,))
        module = _module(classes=(cls,))

        result = extract_units(module, Path("mod.py"), "code")

        assert len(result.code_units) == 2
        class_unit, method_unit = result.code_units
        assert class_unit.unit_type == "class"
        assert class_unit.qualified_name == "mod.Widget"
        assert method_unit.unit_type == "method"
        assert method_unit.qualified_name == "mod.Widget.render"

    def test_async_function_emitted_with_signature(self) -> None:
        fn = _function("fetch", signature="() -> None", is_async=True)
        module = _module(functions=(fn,))

        result = extract_units(module, Path("mod.py"), "code")

        assert result.code_units[0].signature == "() -> None"

    def test_code_classification_produces_no_test_units(self) -> None:
        module = _module(functions=(_function("f"),))

        result = extract_units(module, Path("mod.py"), "code")

        assert result.test_units == ()

    def test_function_named_test_something_still_emitted_as_code(self) -> None:
        module = _module(functions=(_function("test_something"),))

        result = extract_units(module, Path("mod.py"), "code")

        assert len(result.code_units) == 1
        assert result.code_units[0].qualified_name == "mod.test_something"
        assert result.test_units == ()


class TestTestExtraction:
    def test_top_level_test_function(self) -> None:
        fn = _function("test_login")
        module = _module(functions=(fn,))

        result = extract_units(module, Path("test_mod.py"), "test")

        assert len(result.test_units) == 1
        unit = result.test_units[0]
        assert unit.test_name == "test_login"
        assert unit.qualified_name == "test_mod.test_login"
        assert unit.source_code == fn.source_snippet
        assert unit.start_line == fn.line_start
        assert unit.end_line == fn.line_end
        assert result.code_units == ()

    def test_class_test_and_non_test_methods(self) -> None:
        test_method = _function("test_a")
        helper_method = _function("setup")
        cls = _class("TestSuite", methods=(test_method, helper_method))
        module = _module(classes=(cls,))

        result = extract_units(module, Path("test_mod.py"), "test")

        assert len(result.test_units) == 1
        unit = result.test_units[0]
        assert unit.test_name == "test_a"
        assert unit.qualified_name == "test_mod.TestSuite.test_a"

    def test_helper_function_ignored(self) -> None:
        module = _module(functions=(_function("helper"),))

        result = extract_units(module, Path("test_mod.py"), "test")

        assert result.test_units == ()

    def test_test_classification_produces_no_code_units(self) -> None:
        module = _module(
            functions=(_function("helper"),),
            classes=(_class("PlainClass"),),
        )

        result = extract_units(module, Path("test_mod.py"), "test")

        assert result.code_units == ()
        assert result.test_units == ()


class TestPathsAndIdentifiers:
    def test_file_path_is_posix_relative_path(self) -> None:
        module = _module(functions=(_function("f"),))

        result = extract_units(module, Path("pkg") / "sub" / "mod.py", "code")

        assert result.code_units[0].file_path == "pkg/sub/mod.py"

    def test_module_identifier_preserves_src_prefix(self) -> None:
        module = _module(functions=(_function("foo"),))

        result = extract_units(module, Path("src/pkg/mod.py"), "code")

        assert result.code_units[0].qualified_name == "src.pkg.mod.foo"


class TestEmptyModule:
    def test_empty_module_code(self) -> None:
        result = extract_units(_module(), Path("mod.py"), "code")

        assert result.code_units == ()
        assert result.test_units == ()

    def test_empty_module_test(self) -> None:
        result = extract_units(_module(), Path("test_mod.py"), "test")

        assert result.code_units == ()
        assert result.test_units == ()


class TestPropagationAndOrdering:
    def test_content_hash_and_line_spans_propagate(self) -> None:
        fn = _function(
            "f", line_start=10, line_end=20, content_hash="deadbeef"
        )
        module = _module(functions=(fn,))

        result = extract_units(module, Path("mod.py"), "code")

        unit = result.code_units[0]
        assert unit.start_line == 10
        assert unit.end_line == 20
        assert unit.content_hash == "deadbeef"

    def test_source_order_preserved(self) -> None:
        module = _module(functions=(_function("a"), _function("b")))

        result = extract_units(module, Path("mod.py"), "code")

        assert [u.qualified_name for u in result.code_units] == ["mod.a", "mod.b"]
