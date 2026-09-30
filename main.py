"""香川高専Webシラバス PDF 化ツールの起動スクリプト.

使い方: uv run main.py [オプション]  (オプションは uv run main.py --help を参照)
"""

import sys
from pathlib import Path

# src/ 内のモジュール (cli, pdf, render, scraper, merge) を読み込めるようにする
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from cli import main  # noqa: E402

if __name__ == "__main__":
    main()
