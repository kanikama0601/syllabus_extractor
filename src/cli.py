"""香川高専Webシラバスを学年ごとに選択して PDF 化するツール."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import questionary

from merge import merge_pdfs
from scraper import Department, Subject, fetch_departments, fetch_subjects_for_grade, make_client


def current_school_year(today: date | None = None) -> int:
    """4月始まりの年度 (西暦) を返す."""
    today = today or date.today()
    return today.year if today.month >= 4 else today.year - 1


def wareki(year: int) -> str:
    if year >= 2019:
        return f"令和{year - 2018:02d}年度"
    return f"平成{year - 1988:02d}年度"


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--department-id", type=int, help="学科ID (省略時は一覧から選択)")
    p.add_argument("--grade", type=int, choices=range(1, 6), help="現在の学年 (省略時は選択)")
    p.add_argument("--year", type=int, default=current_school_year(), help="現在の年度 (西暦, 既定: 今年度)")
    p.add_argument("--output", type=Path, default=Path("output"), help="出力先フォルダ (既定: ./output)")
    p.add_argument("--all", action="store_true", help="科目を選択せず、全科目を PDF 化する")
    p.add_argument(
        "--merge",
        action=argparse.BooleanOptionalAction,
        help="学年ごとに1つの PDF にまとめる (--no-merge でまとめない。省略時は確認する)",
    )
    return p.parse_args()


def ask(question):
    """questionary の質問を実行し、Ctrl+C で中断されたら終了する."""
    answer = question.ask()
    if answer is None:
        sys.exit("中断しました")
    return answer


def choose_department(departments: list[Department], department_id: int | None) -> Department:
    if department_id is not None:
        for d in departments:
            if d.id == department_id:
                return d
        sys.exit(f"学科ID {department_id} が見つかりません")
    return ask(
        questionary.select(
            "学科を選択してください",
            choices=[questionary.Choice(d.name, value=d) for d in departments],
        )
    )


def choose_subjects(grade: int, year: int, subjects: list[Subject], select_all: bool) -> list[Subject]:
    available = [s for s in subjects if s.url]
    if select_all:
        return available
    choices = [
        questionary.Choice(
            f"{s.name}  ({s.category}・{s.credit_type}{s.credits})",
            value=s,
            checked=True,
            disabled=None if s.url else "シラバスなし",
        )
        for s in subjects
    ]
    return ask(
        questionary.checkbox(
            f"{grade}年 ({wareki(year)}) の PDF 化する科目を選択してください"
            "  [Space: 切替 / a: 全選択・全解除 / i: 反転 / Enter: 決定]",
            choices=choices,
        )
    )


def main() -> None:
    args = parse_args()

    with make_client() as client:
        department = choose_department(fetch_departments(client), args.department_id)
        grade = args.grade or ask(
            questionary.select(
                "現在の学年を選択してください",
                choices=[questionary.Choice(f"{g}年", value=g) for g in range(1, 6)],
            )
        )

        # 学年ごとに「その学年だった年度」の開講科目から選択する
        # 例: 令和8年度に5年生 → 1年は令和4年度、2年は令和5年度 ... 5年は令和8年度
        plan: list[tuple[int, int, list[Subject]]] = []
        for g in range(1, grade + 1):
            year = args.year - (grade - g)
            print(f"\n{g}年 ({wareki(year)}) の開講科目を取得中...")
            subjects = fetch_subjects_for_grade(client, department.id, year, g)
            if not subjects:
                print(f"  {wareki(year)} に {g}年の開講科目が見つかりませんでした")
                continue
            selected = choose_subjects(g, year, subjects, args.all)
            plan.append((g, year, selected))

    total = sum(len(s) for _, _, s in plan)
    if total == 0:
        print("PDF 化する科目がありません")
        return
    merge = args.merge
    if merge is None:
        merge = ask(questionary.confirm("科目ごとの PDF に加えて、学年ごとにまとめた PDF も作成しますか?", default=True))
    print(f"\n合計 {total} 科目を PDF 化します")

    # Playwright は PDF 化の段階でのみ読み込む (ブラウザ未インストール時のエラーを遅らせる)
    from pdf import SyllabusPrinter

    out_root = args.output / safe_filename(department.name)
    failures: list[str] = []
    merged_files: list[tuple[Path, int]] = []
    done = 0
    with SyllabusPrinter() as printer:
        for g, year, subjects in plan:
            printed: list[tuple[str, Path]] = []
            for s in subjects:
                if s.url is None:  # choose_subjects はシラバスのある科目だけを返すので通常は起きない
                    continue
                done += 1
                # 例: 26開講情報工学科（2019年度以降入学者）5画像工学.pdf
                filename = safe_filename(f"{year % 100:02d}開講{department.name}{g}{s.name}") + ".pdf"
                path = out_root / f"{g}年_{wareki(year)}" / filename
                print(f"[{done}/{total}] {g}年 {s.name}", end=" ... ", flush=True)
                try:
                    printer.print_to_pdf(s.url, path)
                    printed.append((s.name, path))
                    print("OK")
                except Exception as e:  # 1科目の失敗で全体を止めない
                    print(f"失敗 ({e})")
                    failures.append(f"{g}年 {s.name}: {s.url}")

            # 学年ごとに1つの PDF にまとめる (例: 22開講情報工学科（2019年度以降入学者）1年_シラバス.pdf)
            if merge and printed:
                merged = out_root / (safe_filename(f"{year % 100:02d}開講{department.name}{g}年_シラバス") + ".pdf")
                merged_files.append((merged, merge_pdfs(printed, merged)))

    print(f"\n完了: {total - len(failures)}/{total} 科目 → {out_root.resolve()}")
    if merged_files:
        print("学年ごとにまとめた PDF:")
        for merged, pages in merged_files:
            print(f"  - {merged.name} ({pages} ページ)")
    if failures:
        print("取得に失敗した科目:")
        for f in failures:
            print(f"  - {f}")
