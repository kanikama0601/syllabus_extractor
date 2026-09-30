"""シラバスページをブラウザで開き、公式 PDF と同じレイアウトに組み直して PDF 化する.

サイトの「PDF出力」ボタン (ロボット認証付き) は使わない。
シラバスページの内容を render.py で公式 PDF 風の HTML に変換し、Chromium で印刷する。
万一ページ閲覧時に認証画面が出た場合は、表示ありのブラウザを開いて
利用者自身に認証してもらい、その Cookie を引き継いで処理を続ける。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

if TYPE_CHECKING:
    from playwright._impl._api_structures import StorageState

from render import CONTENT_HEIGHT_MM, PAGINATE_JS, PRINT_SCALE, build_official_html
from scraper import USER_AGENT

# シラバス本文が表示されていることの目印
CONTENT_MARKER = "科目基礎情報"


def render_official_page(page: Page, source_html: str) -> None:
    """シラバスページの HTML を公式 PDF 風に組み直し、ページ分割まで済ませる."""
    page.emulate_media(media="print")
    page.set_content(build_official_html(source_html), wait_until="load")
    page.evaluate(PAGINATE_JS, CONTENT_HEIGHT_MM)


class SyllabusPrinter:
    def __init__(self, interval: float = 1.0) -> None:
        self.interval = interval
        self._pw = sync_playwright().start()
        self._browser: Browser = self._pw.chromium.launch(headless=True)
        self._context: BrowserContext = self._new_context()

    def _new_context(self, storage_state: StorageState | None = None) -> BrowserContext:
        return self._browser.new_context(
            user_agent=USER_AGENT,
            locale="ja-JP",
            storage_state=storage_state,
        )

    def close(self) -> None:
        self._context.close()
        self._browser.close()
        self._pw.stop()

    def __enter__(self) -> SyllabusPrinter:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _fetch(self, page: Page, url: str) -> str | None:
        """シラバスページの HTML を返す。認証画面などで本文が無ければ None."""
        page.goto(url, wait_until="networkidle", timeout=60_000)
        content = page.content()
        return content if CONTENT_MARKER in content else None

    def _manual_verification(self, url: str) -> None:
        """表示ありのブラウザを開き、利用者に認証してもらってから Cookie を引き継ぐ."""
        print("\n⚠ シラバスページの代わりに認証画面が表示されました。")
        print("  ブラウザウィンドウを開くので、画面の指示に従って認証を完了してください。")
        visible = self._pw.chromium.launch(headless=False)
        try:
            ctx = visible.new_context(user_agent=USER_AGENT, locale="ja-JP")
            ctx.new_page().goto(url)
            input("  シラバスが表示されたら Enter を押してください... ")
            state = ctx.storage_state()
        finally:
            visible.close()
        self._context.close()
        self._context = self._new_context(storage_state=state)

    def print_to_pdf(self, url: str, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        page = self._context.new_page()
        try:
            source = self._fetch(page, url)
            if source is None:
                page.close()
                self._manual_verification(url)
                page = self._context.new_page()
                source = self._fetch(page, url)
                if source is None:
                    raise RuntimeError("シラバス本文を取得できませんでした")
            render_official_page(page, source)
            page.pdf(
                path=str(output),
                prefer_css_page_size=True,
                print_background=True,
                scale=PRINT_SCALE,
            )
        finally:
            page.close()
            time.sleep(self.interval)  # サーバーに負荷をかけないよう間隔を空ける
