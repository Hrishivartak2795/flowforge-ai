"""Tests for :mod:`app.services.ingestion.ast_parser`."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.services.ingestion.ast_parser import parse_python_file
from app.services.ingestion.errors import ParseError


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content)
    return path


class TestEmptyAndDocstring:
    def test_empty_module(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "empty.py", "")

        result = parse_python_file(path)

        assert result.imports == ()
        assert result.functions == ()
        assert result.classes == ()
        assert result.docstring is None
        assert result.module_identifier == "empty"
        assert result.file_hash == hashlib.sha256(b"").hexdigest()

    def test_module_docstring_extracted(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "mod.py", '"""Module doc."""\n\nx = 1\n')

        result = parse_python_file(path)

        assert result.docstring == "Module doc."


class TestFunctions:
    def test_top_level_function_full_metadata(self, tmp_path: Path) -> None:
        source = (
            "@staticmethod\n"
            "def greet(name: str) -> str:\n"
            '    """Say hi."""\n'
            "    return f'hi {name}'\n"
        )
        path = _write(tmp_path, "mod.py", source)

        result = parse_python_file(path)

        assert len(result.functions) == 1
        fn = result.functions[0]
        assert fn.name == "greet"
        assert fn.qualified_name == "mod.greet"
        assert fn.signature == "(name: str) -> str"
        assert fn.decorators == ("staticmethod",)
        assert fn.docstring == "Say hi."
        assert fn.is_async is False
        assert fn.line_start == 2
        assert fn.line_end == 4
        assert "def greet" in fn.source_snippet
        assert fn.content_hash == hashlib.sha256(
            fn.source_snippet.encode("utf-8")
        ).hexdigest()

    def test_function_without_return_annotation(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "mod.py", "def f(x):\n    return x\n")

        result = parse_python_file(path)

        assert result.functions[0].signature == "(x)"

    def test_async_function(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "mod.py", "async def f():\n    pass\n")

        result = parse_python_file(path)

        assert result.functions[0].is_async is True

    def test_nested_function_not_emitted_separately(self, tmp_path: Path) -> None:
        source = (
            "def outer():\n"
            "    def inner():\n"
            "        pass\n"
            "    return inner\n"
        )
        path = _write(tmp_path, "mod.py", source)

        result = parse_python_file(path)

        assert [f.name for f in result.functions] == ["outer"]
        assert "def inner" in result.functions[0].source_snippet


class TestClasses:
    def test_class_with_bases_decorators_docstring_methods(
        self, tmp_path: Path
    ) -> None:
        source = (
            "@final\n"
            "class Widget(Base, Mixin):\n"
            '    """A widget."""\n'
            "\n"
            "    def render(self) -> None:\n"
            "        pass\n"
        )
        path = _write(tmp_path, "mod.py", source)

        result = parse_python_file(path)

        assert len(result.classes) == 1
        cls = result.classes[0]
        assert cls.name == "Widget"
        assert cls.qualified_name == "mod.Widget"
        assert cls.decorators == ("final",)
        assert cls.base_classes == ("Base", "Mixin")
        assert cls.docstring == "A widget."
        assert len(cls.methods) == 1

    def test_method_qualified_name_and_distinct_hash(self, tmp_path: Path) -> None:
        source = "class C:\n    def m(self):\n        pass\n"
        path = _write(tmp_path, "mod.py", source)

        result = parse_python_file(path)

        cls = result.classes[0]
        method = cls.methods[0]
        assert method.qualified_name == "mod.C.m"
        assert method.content_hash != cls.content_hash

    def test_nested_class_not_recursed_into(self, tmp_path: Path) -> None:
        source = (
            "class Outer:\n"
            "    class Inner:\n"
            "        pass\n"
            "    def m(self):\n"
            "        pass\n"
        )
        path = _write(tmp_path, "mod.py", source)

        result = parse_python_file(path)

        assert len(result.classes) == 1
        assert [m.name for m in result.classes[0].methods] == ["m"]


class TestImports:
    def test_plain_import(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "mod.py", "import os\n")

        result = parse_python_file(path)

        assert result.imports == (
            _import(from_module=None, imported_name="os", alias=None, line=1),
        )

    def test_import_with_alias(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "mod.py", "import numpy as np\n")

        result = parse_python_file(path)

        assert result.imports[0].imported_name == "numpy"
        assert result.imports[0].alias == "np"

    def test_from_import(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "mod.py", "from a import b\n")

        result = parse_python_file(path)

        imp = result.imports[0]
        assert imp.from_module == "a"
        assert imp.imported_name == "b"
        assert imp.alias is None
        assert imp.is_relative is False
        assert imp.relative_level == 0

    def test_from_import_with_alias(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "mod.py", "from a import b as c\n")

        result = parse_python_file(path)

        assert result.imports[0].alias == "c"

    def test_relative_import_dot(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "mod.py", "from . import x\n")

        result = parse_python_file(path)

        imp = result.imports[0]
        assert imp.from_module is None
        assert imp.imported_name == "x"
        assert imp.is_relative is True
        assert imp.relative_level == 1

    def test_relative_import_double_dot_with_module(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "mod.py", "from ..pkg import y\n")

        result = parse_python_file(path)

        imp = result.imports[0]
        assert imp.from_module == "pkg"
        assert imp.imported_name == "y"
        assert imp.is_relative is True
        assert imp.relative_level == 2

    def test_import_order_matches_source_order(self, tmp_path: Path) -> None:
        source = "import os\nimport sys\nfrom a import b\n"
        path = _write(tmp_path, "mod.py", source)

        result = parse_python_file(path)

        assert [i.imported_name for i in result.imports] == ["os", "sys", "b"]


def _import(
    *, from_module: str | None, imported_name: str, alias: str | None, line: int
) -> object:
    from app.services.ingestion.ast_parser import ImportIR

    return ImportIR(
        from_module=from_module,
        imported_name=imported_name,
        alias=alias,
        is_relative=False,
        relative_level=0,
        line=line,
    )


class TestDeterminism:
    def test_reparse_yields_equal_module_ir(self, tmp_path: Path) -> None:
        source = (
            "import os\n\n\nclass C:\n    def m(self):\n        pass\n\n\n"
            "def f(x: int) -> int:\n    return x\n"
        )
        path = _write(tmp_path, "mod.py", source)

        first = parse_python_file(path)
        second = parse_python_file(path)

        assert first == second

    def test_content_hash_stable_for_identical_source(self, tmp_path: Path) -> None:
        source = "def f():\n    pass\n"
        path_a = _write(tmp_path, "a.py", source)
        path_b = _write(tmp_path, "b.py", source)

        result_a = parse_python_file(path_a)
        result_b = parse_python_file(path_b)

        assert result_a.functions[0].content_hash == result_b.functions[0].content_hash


class TestEncoding:
    def test_pep263_declared_encoding_parses(self, tmp_path: Path) -> None:
        path = tmp_path / "latin1.py"
        source = "# -*- coding: latin-1 -*-\nx = 'caf\xe9'\n"
        path.write_bytes(source.encode("latin-1"))

        result = parse_python_file(path)

        assert "café" in result.source


class TestErrors:
    def test_syntax_error_raises_parse_error(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "bad.py", "def f(:\n    pass\n")

        with pytest.raises(ParseError) as exc_info:
            parse_python_file(path)

        assert isinstance(exc_info.value.__cause__, SyntaxError)
        assert exc_info.value.path == path

    def test_nonexistent_path_raises_parse_error(self, tmp_path: Path) -> None:
        path = tmp_path / "does_not_exist.py"

        with pytest.raises(ParseError) as exc_info:
            parse_python_file(path)

        assert isinstance(exc_info.value.__cause__, OSError)

    def test_bad_encoding_raises_parse_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad_encoding.py"
        # Declares utf-8 (the default) but contains a byte sequence that is
        # not valid utf-8 -> UnicodeDecodeError while reading.
        path.write_bytes(b"x = '\xff\xfe'\n")

        with pytest.raises(ParseError) as exc_info:
            parse_python_file(path)

        assert isinstance(exc_info.value.__cause__, (UnicodeDecodeError, SyntaxError))
