"""シラバスページの HTML を、公式 PDF と同じレイアウトの HTML に組み直す.

公式 PDF の特徴:
- 先頭に「学校名｜開講年度｜年度｜授業科目｜科目名」のヘッダー行
- 各セクション見出しも表の1行として、黒罫線の表が途切れずに続く
- 見出しセル (th) も太字にせず左寄せ、背景色なし
"""

from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup, NavigableString, Tag

# セクションごとの列幅 (%)。列数が一致しない場合は均等割り
COLUMN_WIDTHS: dict[str, list[float]] = {
    "科目基礎情報": [16.7, 33.3, 16.7, 33.3],
    "授業計画": [7.7, 7.7, 7.6, 38.5, 38.5],
    "モデルコアカリキュラムの学習内容と到達目標": [9, 9.2, 9.1, 9.1, 45.4, 9.2, 9],
}
FIRST_COLUMN_WIDTHS: dict[str, float] = {"ルーブリック": 25}

# Chromium は 1px (0.75pt) 未満の罫線を 1px に切り上げてしまうため、
# 2倍の大きさでレイアウトし、PDF 出力時に PRINT_SCALE 倍に縮小して公式と同じ細い罫線にする。
# 以下の CSS の寸法は縮小前 (実寸の2倍) の値。
PRINT_SCALE = 0.5
PAGE_MARGIN_MM = 12.7
# 縮小前の寸法での、1ページに収まる本文の幅と高さ
CONTENT_WIDTH_MM = (210 - 2 * PAGE_MARGIN_MM) / PRINT_SCALE
CONTENT_HEIGHT_MM = (297 - 2 * PAGE_MARGIN_MM) / PRINT_SCALE

CSS = """
@page { size: A4; margin: PAGE_MARGINmm; }
* { box-sizing: border-box; }
body {
    margin: 0;
    font-family: "Meiryo", "メイリオ", "Hiragino Kaku Gothic ProN", "Hiragino Sans", "Noto Sans JP", sans-serif;
    font-size: 16pt;
    line-height: 1.05;
    color: #000;
}
#source { display: none; }
.page { width: CONTENT_WIDTHmm; break-after: page; }
.page:last-child { break-after: auto; }
table.blk {
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
}
table.blk td {
    border: 1px solid #000;
    padding: 3.2pt 3pt 2.8pt;
    vertical-align: middle;
    text-align: left;
    font-weight: normal;
    word-break: break-all;
}
/* 同じページ内で表を縦に積んだとき、罫線が二重にならないようにする */
table.blk + table.blk > tbody > tr:first-child > td { border-top: none; }
table.head td { font-size: 20pt; padding: 5pt 6pt; }
table.head td.center { text-align: center; }
table.sec td { font-size: 19pt; padding: 3pt 3pt; }
tr.empty td { height: 24pt; }
""".replace("PAGE_MARGIN", str(PAGE_MARGIN_MM)).replace("CONTENT_WIDTH", str(CONTENT_WIDTH_MM))

# 公式 PDF と同じように、行単位でページを分割する JavaScript。
# Chromium 任せの改ページでは、ページをまたぐ結合セル (rowspan) の罫線が欠けるため、
# 1行ずつページ枠に追加して高さを測り、はみ出したら次のページへ送る。
# ページをまたぐ結合セルは、前のページで閉じ、次のページ先頭に空のセルとして続ける。
PAGINATE_JS = """
(pageHeightMm) => {
  const limit = pageHeightMm * 96 / 25.4 - 1;
  const source = document.getElementById('source');
  let page;
  const newPage = () => {
    page = document.createElement('div');
    page.className = 'page';
    document.body.appendChild(page);
  };
  const fits = () => page.getBoundingClientRect().height <= limit;
  // 万一の不具合で処理が終わらなくなった場合に、固まらずエラーにする
  let steps = 0;
  const tick = () => {
    if (++steps > 100000) throw new Error('ページ分割の処理が終わりません');
  };
  newPage();

  for (const table of Array.from(source.children)) {
    const rows = Array.from(table.tBodies[0].rows);

    // 各セルの開始列と、複数行にまたがるセルを求める
    const occupied = rows.map(() => new Set());
    const cols = rows.map(() => []);
    const spans = [];
    rows.forEach((tr, r) => {
      let c = 0;
      for (const cell of tr.cells) {
        while (occupied[r].has(c)) c++;
        cols[r].push(c);
        for (let dr = 0; dr < cell.rowSpan && r + dr < rows.length; dr++)
          for (let dc = 0; dc < cell.colSpan; dc++) occupied[r + dr].add(c + dc);
        if (cell.rowSpan > 1) spans.push({ row: r, col: c, rowSpan: cell.rowSpan, colSpan: cell.colSpan });
        c += cell.colSpan;
      }
    });

    // i 行目を複製する。ページ先頭の行なら、上から続く結合セルを空セルとして補う
    const buildRow = (i, continued) => {
      const tr = rows[i].cloneNode(true);
      if (!continued) return tr;
      const cells = Array.from(tr.cells).map((cell, k) => [cols[i][k], cell]);
      for (const s of spans.filter((s) => s.row < i && s.row + s.rowSpan > i)) {
        const td = document.createElement('td');
        td.colSpan = s.colSpan;
        td.rowSpan = s.row + s.rowSpan - i;
        cells.push([s.col, td]);
      }
      cells.sort((a, b) => a[0] - b[0]).forEach(([, cell]) => tr.appendChild(cell));
      return tr;
    };

    let frag, body;
    const startFragment = () => {
      frag = table.cloneNode(false);
      const colgroup = table.querySelector('colgroup');
      if (colgroup) frag.appendChild(colgroup.cloneNode(true));
      body = frag.appendChild(document.createElement('tbody'));
      page.appendChild(frag);
    };
    startFragment();

    for (let i = 0; i < rows.length; i++) {
      tick();
      let tr = body.appendChild(buildRow(i, body.rows.length === 0 && i > 0));
      if (fits()) continue;
      tr.remove();
      if (body.rows.length === 0 && page.children.length === 1) {
        body.appendChild(tr);  // 1行だけで1ページを超える場合はそのまま置く
        continue;
      }
      if (body.rows.length === 0) frag.remove();
      // セクション見出しだけがページ末尾に残らないよう、次のページへ一緒に送る
      const carried = [];
      // (取り除いてから送る。取り除かないと末尾が見出しのままになり、無限ループになる)
      while (page.lastElementChild && page.lastElementChild.classList.contains('sec') && page.children.length > 1) {
        tick();
        const heading = page.lastElementChild;
        heading.remove();
        carried.unshift(heading);
      }
      newPage();
      carried.forEach((el) => page.appendChild(el));
      startFragment();
      body.appendChild(buildRow(i, i > 0));
    }
  }
  source.remove();
}
"""


def _text_html(el: Tag | NavigableString | None) -> str:
    """要素内のテキストを、<br> による改行だけ残した HTML 断片にする."""
    if el is None:
        return ""
    if isinstance(el, NavigableString):
        return html.escape(re.sub(r"\s+", " ", str(el)).strip())

    parts: list[str] = []

    def walk(node: Tag) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                parts.append(html.escape(re.sub(r"\s+", " ", str(child))))
            elif isinstance(child, Tag):
                if child.name == "br":
                    parts.append("\n")
                elif child.name in ("input", "script", "style", "button"):
                    continue
                elif "btn" in (child.get("class") or []) or "hide" in (child.get("class") or []):
                    continue
                else:
                    if child.name in ("div", "p") and parts and not parts[-1].endswith("\n"):
                        parts.append("\n")
                    walk(child)

    walk(el)
    lines = [line.strip() for line in "".join(parts).split("\n")]
    # 先頭・末尾の空行を落とす
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "<br>".join(lines)


def _cell(content: str, colspan: int = 1, rowspan: int = 1, cls: str = "") -> str:
    attrs = ""
    if colspan > 1:
        attrs += f' colspan="{colspan}"'
    if rowspan > 1:
        attrs += f' rowspan="{rowspan}"'
    if cls:
        attrs += f' class="{cls}"'
    return f"<td{attrs}>{content}</td>"


def _table(rows: list[str], widths: list[float] | None = None, cls: str = "") -> str:
    cols = "".join(f'<col style="width:{w}%">' for w in widths) if widths else ""
    colgroup = f"<colgroup>{cols}</colgroup>" if cols else ""
    return f'<table class="blk {cls}">{colgroup}<tbody>{"".join(rows)}</tbody></table>'


def _span(cell: Tag, name: str) -> int:
    try:
        return max(1, int(cell.get(name, 1)))
    except ValueError:
        return 1


def _column_count(table: Tag) -> int:
    counts = [
        sum(_span(c, "colspan") for c in tr.find_all(["th", "td"], recursive=False))
        for tr in table.find_all("tr")
    ]
    return max(counts, default=1)


def _widths_for(section: str, ncols: int) -> list[float]:
    preset = COLUMN_WIDTHS.get(section)
    if preset and len(preset) == ncols:
        return preset
    first = FIRST_COLUMN_WIDTHS.get(section)
    if first and ncols > 1:
        return [first] + [(100 - first) / (ncols - 1)] * (ncols - 1)
    return [100 / ncols] * ncols


Cell = tuple[str, int, int]  # (内容, colspan, rowspan)


def _start_columns(rows: list[list[Cell]]) -> list[list[int]]:
    """各セルの開始列を、上の行から続く結合セルを考慮して求める."""
    occupied: list[set[int]] = [set() for _ in rows]
    result: list[list[int]] = []
    for r, row in enumerate(rows):
        c, starts = 0, []
        for _, colspan, rowspan in row:
            while c in occupied[r]:
                c += 1
            starts.append(c)
            for dr in range(rowspan):
                if r + dr < len(rows):
                    occupied[r + dr].update(range(c, c + colspan))
            c += colspan
        result.append(starts)
    return result


def _fold_span_only_rows(rows: list[list[Cell]]) -> list[list[Cell]]:
    """結合セルしか無い行 (例: 授業計画の「前期」だけの行) を次の行にまとめる.

    元ページは <tr><th rowspan=19>前期</th></tr> のような高さの無い行を使っており、
    そのままだと改ページ位置の計算で「前期」だけが前のページに残ってしまう。
    """
    rows = [list(r) for r in rows]
    i = 0
    while i < len(rows) - 1:
        row = rows[i]
        if row and all(rowspan > 1 for _, _, rowspan in row):
            starts = _start_columns(rows)
            moved = [((text, cs, rs - 1), c) for (text, cs, rs), c in zip(row, starts[i])]
            merged = moved + list(zip(rows[i + 1], starts[i + 1]))
            rows[i + 1] = [cell for cell, _ in sorted(merged, key=lambda x: x[1])]
            # 消す行にかかっている、さらに上の行の結合セルは1行分短くする
            for r in range(i):
                rows[r] = [(t, cs, rs - 1 if r + rs > i else rs) for t, cs, rs in rows[r]]
            del rows[i]
        else:
            i += 1
    return rows


def _convert_table(table: Tag, section: str, skip_labels: set[str] = frozenset()) -> str:
    rows: list[list[Cell]] = []
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        cells = tr.find_all(["th", "td"], recursive=False)
        if any(c.get_text(strip=True) in skip_labels for c in cells if c.name == "th"):
            continue
        rows.append([(_text_html(c), _span(c, "colspan"), _span(c, "rowspan")) for c in cells])
    html_rows = [
        "<tr>" + "".join(_cell(text, cs, rs) for text, cs, rs in row) + "</tr>"
        for row in _fold_span_only_rows(rows)
    ]
    return _table(html_rows, _widths_for(section, _column_count(table)))


def _basic_info(table: Tag) -> dict[str, str]:
    """科目基礎情報の表から「見出し → 値」を取り出す."""
    info: dict[str, str] = {}
    for th in table.find_all("th"):
        td = th.find_next_sibling("td")
        if td is not None:
            info[th.get_text(strip=True)] = _text_html(td)
    return info


def _education_methods(div: Tag) -> str:
    """教育方法等: <b>概要:</b><div>...</div> の並びを「見出し｜本文」の行にする."""
    rows: list[str] = []
    label: str | None = None
    for child in div.children:
        if isinstance(child, Tag) and child.name == "b":
            label = child.get_text(strip=True).rstrip(":：")
        elif isinstance(child, Tag) and child.name == "div" and label is not None:
            rows.append(f"<tr>{_cell(html.escape(label))}{_cell(_text_html(child))}</tr>")
            label = None
    return _table(rows, [16.7, 83.3])


def _attributes(div: Tag) -> str:
    """授業の属性・履修上の区分: チェックボックスを □ / ☑ の文字にする."""
    rows: list[str] = []
    for tr in div.find_all("tr"):
        cells = []
        for td in tr.find_all("td", recursive=False):
            box = td.find("input", attrs={"type": "checkbox"})
            text = _text_html(td)
            if box is not None:
                text = ("☑ " if box.has_attr("checked") else "□ ") + text
            cells.append(_cell(text or "&nbsp;", _span(td, "colspan")))
        cls = ' class="empty"' if all(c.endswith("&nbsp;</td>") for c in cells) else ""
        rows.append(f"<tr{cls}>{''.join(cells)}</tr>")
    return _table(rows, [25, 25, 25, 25])


def _text_block(el: Tag) -> str:
    content = _text_html(el)
    return _table([f"<tr>{_cell(content)}</tr>"]) if content else ""


def build_official_html(page_html: str) -> str:
    soup = BeautifulSoup(page_html, "html.parser")
    root = soup.find(id="MainContent_SubjectSyllabus_UpdatePanelSyllabus") or soup.body or soup

    blocks: list[str] = []
    info: dict[str, str] = {}
    for h3 in root.find_all("h3", class_="bg-info"):
        section = h3.get_text(strip=True)
        blocks.append(_table([f"<tr>{_cell(html.escape(section))}</tr>"], cls="sec"))

        # 次の見出しまでの兄弟要素がこのセクションの内容
        for sib in h3.find_next_siblings():
            if sib.name == "h3" or sib.find("h3") is not None:
                break
            table = sib if sib.name == "table" else sib.find("table")
            if section == "科目基礎情報" and table is not None:
                info = _basic_info(table)
                blocks.append(_convert_table(table, section, skip_labels={"学校", "授業科目"}))
            elif section == "教育方法等":
                blocks.append(_education_methods(sib))
            elif section == "授業の属性・履修上の区分":
                blocks.append(_attributes(sib))
            elif table is not None:
                blocks.append(_convert_table(table, section))
            else:
                blocks.append(_text_block(sib))

    header = _table(
        [
            "<tr>"
            + _cell(info.get("学校", ""), cls="center")
            + _cell("開講年度", cls="center")
            + _cell(info.get("開講年度", ""))
            + _cell("授業科目", cls="center")
            + _cell(info.get("授業科目", ""))
            + "</tr>"
        ],
        [26, 10.5, 26, 10.5, 27],
        cls="head",
    )
    title = html.escape(re.sub(r"<br>", " ", info.get("授業科目", "シラバス")))
    return (
        '<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">'
        f"<title>{title}</title><style>{CSS}</style></head>"
        f'<body><div id="source">{header}{"".join(blocks)}</div></body></html>'
    )
