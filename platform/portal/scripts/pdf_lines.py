"""PDF の文字の取り出し方を調べる(Mac で実行。AWS 不要)。節の見出しを判定できない PDF の原因を見るために使う。
  python3 platform/portal/scripts/pdf_lines.py <PDF> [語(既定: method|result|discussion|introduction)]
出力: ページごとの文字数と、語を含む行(行番号付き。見出しの形が分かる)。"""
import logging, re, sys
logging.getLogger("pypdf").setLevel(logging.ERROR)
from pypdf import PdfReader

path = sys.argv[1]; pat = re.compile(sys.argv[2] if len(sys.argv) > 2 else r"method|result|discussion|introduction", re.I)
rd = PdfReader(path)
for i, pg in enumerate(rd.pages, 1):
    t = pg.extract_text() or ""; lines = t.split("\n")
    print(f"--- p.{i}: {len(t)} 字、{len(lines)} 行")
    for n, ln in enumerate(lines, 1):
        if pat.search(ln) and len(ln) < 200: print(f"  {n:4d}: {ln!r}")
