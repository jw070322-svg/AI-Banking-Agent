"""Extract prose sections and Python docstrings, keeping source line numbers."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
import re

from .sources import Document


@dataclass(frozen=True)
class Section:
    document: Document
    title: str
    start_line: int
    end_line: int
    lines: tuple[tuple[int, str], ...]
    kind: str


def extract(document: Document) -> list[Section]:
    if PurePosixPath(document.path).suffix.casefold() == ".py":
        return _docstrings(document)
    sections = []
    title, start, lines, fence = "Introduction", 1, [], None
    for number, line in enumerate(document.text.splitlines(), 1):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            delimiter = marker[1]
            if fence is None:
                fence = delimiter
            elif delimiter[0] == fence[0] and len(delimiter) >= len(fence):
                fence = None
            continue
        if fence:
            continue  # Examples never become documentation requirements.
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            if lines:
                sections.append(Section(document, title, start, number - 1, tuple(lines), "prose"))
            title, start, lines = heading[1], number, [(number, line)]
        else:
            lines.append((number, line))
    if lines:
        sections.append(Section(document, title, start, len(document.text.splitlines()),
                                tuple(lines), "prose"))
    return sections


def _docstrings(document: Document) -> list[Section]:
    # AST parsing does not import the module or execute top-level statements.
    tree = ast.parse(document.text, filename=document.path)
    sections = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.body or not isinstance(node.body[0], ast.Expr):
            continue
        value = node.body[0].value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        start, end = value.lineno, value.end_lineno or value.lineno
        raw_lines = document.text.splitlines()[start - 1:end]
        sections.append(Section(document, getattr(node, "name", "module"), start, end,
                                tuple(enumerate(raw_lines, start)), "python_docstring"))
    return sections
