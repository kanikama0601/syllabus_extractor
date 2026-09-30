"""科目ごとの PDF を1つの PDF にまとめる (学年ごとに1つ)."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter


def merge_pdfs(items: list[tuple[str, Path]], output: Path) -> int:
    """PDF を順に結合し、科目名のしおりを付けて保存する。結合したページ数を返す."""
    writer = PdfWriter()
    for name, path in items:
        start = len(writer.pages)
        writer.append(path, import_outline=False)
        writer.add_outline_item(name, start)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as f:
        writer.write(f)
    return len(writer.pages)
