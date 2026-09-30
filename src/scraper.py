"""高専Webシラバスの学科一覧・開講科目一覧の取得と解析."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://syllabus.kosen-k.go.jp"
KAGAWA_SCHOOL_ID = 39
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)


@dataclass(frozen=True)
class Department:
    id: int
    name: str


@dataclass(frozen=True)
class Subject:
    name: str
    code: str
    category: str  # 例: "一般 / 必修"
    credit_type: str  # 例: "履修単位"
    credits: str
    url: str | None  # シラバスページのURL (リンクが無い科目は None)


def make_client() -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=30,
    )


def _soup(client: httpx.Client, path: str, params: dict) -> BeautifulSoup:
    res = client.get(path, params=params)
    res.raise_for_status()
    return BeautifulSoup(res.text, "html.parser")


def fetch_departments(client: httpx.Client, school_id: int = KAGAWA_SCHOOL_ID) -> list[Department]:
    """学科一覧ページから学科 (id, 名前) を取得する."""
    soup = _soup(client, "/Pages/PublicDepartments", {"school_id": school_id, "lang": "ja"})
    departments: list[Department] = []
    seen: set[int] = set()
    for heading in soup.select("h4.list-group-item-heading"):
        row = heading.find_parent("div", class_="row")
        link = row.find("a", href=re.compile("PublicSubjects")) if row else None
        if link is None:
            continue
        dep_id = int(parse_qs(urlparse(str(link["href"])).query)["department_id"][0])
        if dep_id in seen:
            continue
        seen.add(dep_id)
        departments.append(Department(dep_id, heading.get_text(strip=True)))
    return departments


def fetch_subjects_for_grade(
    client: httpx.Client,
    department_id: int,
    year: int,
    grade: int,
    school_id: int = KAGAWA_SCHOOL_ID,
) -> list[Subject]:
    """指定年度の開講科目一覧から、指定学年に授業時数がある科目を取得する."""
    soup = _soup(
        client,
        "/Pages/PublicSubjects",
        {"school_id": school_id, "department_id": department_id, "year": year, "lang": "ja"},
    )
    table = soup.find("table", id="sytablenc")
    if table is None:
        return []

    subjects: list[Subject] = []
    seen: set[str] = set()
    for row in table.find_all("tr"):
        item = row.find("div", class_="subject-item")
        if item is None:
            continue
        # 学年別週当授業時数のセル (c{学年}m) のいずれかに値があれば、その学年の科目
        grade_cells = row.find_all("td", class_=f"c{grade}m")
        if not any(td.get_text(strip=True) for td in grade_cells):
            continue

        tds = row.find_all("td", recursive=False)
        idx = next(i for i, td in enumerate(tds) if td.find("div", class_="subject-item"))
        category = " / ".join(td.get_text(strip=True) for td in tds[:idx])
        code = tds[idx + 1].get_text(strip=True)
        if code in seen:
            continue
        seen.add(code)

        link = item.find("a", href=True)
        name_el = link or item.find("span") or item
        subjects.append(
            Subject(
                name=name_el.get_text(strip=True),
                code=code,
                category=category,
                credit_type=tds[idx + 2].get_text(strip=True),
                credits=tds[idx + 3].get_text(strip=True),
                url=urljoin(BASE_URL, str(link["href"])) if link else None,
            )
        )
    return subjects
