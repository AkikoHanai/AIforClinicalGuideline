"""CLI

  python -m etd_draft ingest  <guideline.pdf|docx|txt> [-o work/state.json]
  python -m etd_draft draft   work/state.json --llm none|mock|bedrock|openai [--model ...] [--cq CQ3 ...]
  python -m etd_draft verify  work/state.json work/drafts/
  python -m etd_draft render  work/state.json work/drafts/ -o work/out/ [--format docx,md]
  python -m etd_draft run     <guideline> --llm none -o work/     （上記を一括）

全工程で state.json（元GLの構造化状態）と drafts/*.json（CQ ごとの EtD 状態）が真のソース。
DOCX/Markdown はその描画に過ぎない。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .draft import draft_worksheet
from .ingest import read_any
from .llm import make_llm
from .render import to_docx, to_markdown
from .schema import EtDWorksheet, GuidelineState
from .segment import split_into_cqs
from .verify import verify_worksheet


def _load_state(path: Path) -> GuidelineState:
    return GuidelineState.model_validate_json(path.read_text(encoding="utf-8"))


def _save(model, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")


def cmd_ingest(args) -> Path:
    blocks = []
    for f in args.files:
        blocks.extend(read_any(f))
    state = split_into_cqs(blocks)
    out = Path(args.output)
    _save(state, out)
    print(f"[ingest] {len(blocks)} 段落 → {len(state.cqs)} CQ を検出: {', '.join(c.code for c in state.cqs)}")
    for cq in state.cqs:
        print(
            f"  {cq.code}: 段落 {len(cq.passages):3d}  推奨文={'有' if cq.recommendation_text.value != '情報なし' else '無'}  "
            f"強さ={cq.recommendation_strength.value}  確実性={cq.evidence_certainty.value}"
        )
    print(f"[ingest] 保存: {out}")
    return out


def _select_cqs(state: GuidelineState, codes: list[str] | None):
    if not codes:
        return state.cqs
    want = {c.upper() for c in codes}
    return [cq for cq in state.cqs if cq.code.upper() in want]


def cmd_draft(args) -> Path:
    state = _load_state(Path(args.state))
    llm = make_llm(args.llm, args.model)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    for cq in _select_cqs(state, args.cq):
        ws = draft_worksheet(cq, llm)
        if not args.no_verify:
            ws = verify_worksheet(ws, cq)
        _save(ws, out_dir / f"{cq.code}.json")
        v = ws.verification
        print(f"[draft] {cq.code}: status={ws.status} 除去={v.get('n_rejected', 0)} エラー={v.get('n_errors', 0)} 警告={v.get('n_warnings', 0)}")
    return out_dir


def cmd_verify(args) -> None:
    state = _load_state(Path(args.state))
    cqmap = {c.code: c for c in state.cqs}
    for f in sorted(Path(args.drafts).glob("*.json")):
        ws = EtDWorksheet.model_validate_json(f.read_text(encoding="utf-8"))
        cq = cqmap.get(ws.cq_code)
        if cq is None:
            print(f"[verify] {f.name}: state に {ws.cq_code} が無い → skip")
            continue
        ws = verify_worksheet(ws, cq)
        _save(ws, f)
        print(f"[verify] {ws.cq_code}: status={ws.status} {json.dumps({k: ws.verification[k] for k in ('n_rejected', 'n_errors', 'n_warnings')}, ensure_ascii=False)}")


def cmd_render(args) -> None:
    state = _load_state(Path(args.state))
    cqmap = {c.code: c for c in state.cqs}
    fmts = {f.strip() for f in args.format.split(",")}
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in sorted(Path(args.drafts).glob("*.json")):
        ws = EtDWorksheet.model_validate_json(f.read_text(encoding="utf-8"))
        cq = cqmap.get(ws.cq_code)
        if cq is None:
            continue
        if "md" in fmts:
            (out_dir / f"EtD_{ws.cq_code}.md").write_text(to_markdown(ws, cq), encoding="utf-8")
        if "docx" in fmts:
            to_docx(ws, cq, out_dir / f"EtD_{ws.cq_code}.docx")
        print(f"[render] {ws.cq_code} → {out_dir}")


def cmd_run(args) -> None:
    work = Path(args.output)
    args.output = str(work / "state.json")
    cmd_ingest(args)
    args.state = str(work / "state.json")
    args.output = str(work / "drafts")
    cmd_draft(args)
    args.drafts = str(work / "drafts")
    args.output = str(work / "worksheets")
    cmd_render(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="etd_draft", description="既存ガイドライン → GRADE EtD ワークシート下書き")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest", help="PDF/DOCX/TXT を CQ 単位に構造化")
    s.add_argument("files", nargs="+")
    s.add_argument("-o", "--output", default="work/state.json")
    s.set_defaults(func=cmd_ingest)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--llm", default="none", choices=["none", "mock", "bedrock", "openai"])
    common.add_argument("--model", default=None, help="Bedrock model id / OpenAI 互換モデル名")
    common.add_argument("--cq", nargs="*", default=None, help="対象 CQ コード（省略時は全 CQ）")
    common.add_argument("--no-verify", action="store_true")
    common.add_argument("--format", default="docx,md")

    s = sub.add_parser("draft", parents=[common], help="EtD 下書き生成（+検証）")
    s.add_argument("state")
    s.add_argument("-o", "--output", default="work/drafts")
    s.set_defaults(func=cmd_draft)

    s = sub.add_parser("verify", help="下書きの出典検証をやり直す")
    s.add_argument("state")
    s.add_argument("drafts")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("render", help="DOCX / Markdown に描画")
    s.add_argument("state")
    s.add_argument("drafts")
    s.add_argument("-o", "--output", default="work/worksheets")
    s.add_argument("--format", default="docx,md")
    s.set_defaults(func=cmd_render)

    s = sub.add_parser("run", parents=[common], help="ingest → draft → verify → render を一括実行")
    s.add_argument("files", nargs="+")
    s.add_argument("-o", "--output", default="work")
    s.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
