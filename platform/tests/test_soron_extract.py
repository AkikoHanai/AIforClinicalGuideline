"""総論(2023年版の全文引用)の切り出しの試験。  python3 -m pytest platform/tests/test_soron_extract.py -q
PDF は使わない。文字の扱いの規則と、切り出しの結果(verify.json、units.json、out/)の整合を検査する。"""
import glob, importlib.util, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("extract_soron", os.path.join(ROOT, "soron", "extract_soron.py"))
X = importlib.util.module_from_spec(spec); spec.loader.exec_module(X)
PLAN = json.load(open(os.path.join(ROOT, "governance", "approved_plan.json"), encoding="utf-8"))["総論"]
UNITS = json.load(open(os.path.join(ROOT, "data", "gl2023", "units.json"), encoding="utf-8"))


def test_spacing_and_dash_rules():
    assert X.norm("CIPN の頻度は 50 論文 41 評価尺度") == "CIPNの頻度は50論文41評価尺度"          # 和文と英数字の間の空白(組版上のアキ)は入れない
    assert X.norm("Relative dose intensity （RDI） を低下") == "Relative dose intensity（RDI）を低下"   # 英単語の間の空白は残す
    for a, b in (("180—90", "180-90"), ("Chemotherapy—induced", "Chemotherapy-induced"), ("therapy —induced", "therapy-induced"), ("アセチル—L—カルニチン", "アセチル-L-カルニチン"),
                 ("taxane— and platinum", "taxane- and platinum"), ("α —fluoro—β—alanine", "α-fluoro-β-alanine")):
        assert X.norm(a) == b
    for keep in ("学会—欧州腫瘍看護学会", "cancer——a GERCOR", "頭頂葉—後頭葉"):                  # 和文どうしの間と「——」は変えない
        assert X.norm(keep) == keep


def test_line_joining():
    assert X.glue("（in-", "strumental activities") == ("（in", "strumental activities")   # 行末のハイフンで分かれた英単語を戻す
    assert X.glue("Neurotoxicity Questionnaire", "（PNQ）") == ("Neurotoxicity Questionnaire", "（PNQ）")
    assert X.glue("peripheral", "neuropathy") == ("peripheral ", "neuropathy")
    assert X.glue("発症する", "頻度は") == ("発症する", "頻度は")


def test_citation_marks_are_superscript_only_for_listed_references():
    blocks = [{"t": "p", "runs": [["報告されている7）～15）。一方，全生存期間23）～29），奏効率32）を悪化させる。中等度（Grade 2）は対象外99）。", False]]}] + [{"t": "ref", "runs": [[f"{i}）x", False]], "text": "x"} for i in range(1, 38)]
    blocks.insert(1, {"t": "p", "runs": [["介入には，目的別に1）予防，2）疼痛の緩和，3）リハビリテーションがある。評価尺度のscores11）や，別の報告4）5）がある。", False]]})
    X.mark_cites(blocks); sup = [t for t, _, s in blocks[0]["runs"] if s]
    assert [t for t, _, s in blocks[1]["runs"] if s] == ["11）", "4）5）"]   # 「1）…，2）…」の列挙は文献番号ではない。英単語の後の番号は文献番号
    assert sup == ["7）～15）", "23）～29）", "32）"] and "（Grade 2）は対象外99）" in "".join(t for t, _, s in blocks[0]["runs"] if not s)   # 文献一覧にない番号は上付きにしない


def test_roles_by_font():
    assert X.role(135.7, 78.3, 9.2, "RyuminPr6-Regular", "本文") == "body" and X.role(80, 78.3, 7.8, "RyuminPr6-Regular", "1）x") == "ref"
    assert X.role(41.6, 84.0, 7.8, "UDShinGoPr6-Light", "第 2 章 総論") is None and X.role(300, 250, 12.0, "MSPGothic", "無断転載禁止©JASCC") is None   # 柱と透かしは除く
    assert X.role(144.3, 78.3, 11.3, "UDShinGoPr6-Medium", "1．概要") == "h2" and X.role(212.8, 78.7, 8.5, "UDShinGoPr6-Regular", "表 1．x") == "band"
    assert X.role(500, 300, 8.5, "RyuminPr6-Regular", "（内藤　陽一）") == "sign" and X.role(500, 80, 8.5, "RyuminPr6-Regular", "※薬理作用に基づく") == "note"


def test_full_quotation_is_verified_and_mapped_to_the_plan():
    report = json.load(open(os.path.join(ROOT, "soron", "verify.json"), encoding="utf-8"))
    assert set(report) == set("ABCDEFGHIJLM") and all(r["missing"] == 0 and r["extra"] == 0 for r in report.values())   # 落ちた文字、余分な文字がない
    keys = {u["key"] for u in UNITS}
    assert keys == set(PLAN) - {"K", "N"}          # 2028年版の K・N は新設。2023年版の K(海外ガイドラインの紹介)は扱わない(統括委員長の決定)
    for u in UNITS:
        assert u["counts"]["paragraphs"] > 0 and u["paras"] and u["author2023"]
    assert sum(u["counts"]["tables"] for u in UNITS) == 9 and all(u["counts"]["table_diff"] == 0 for u in UNITS)   # 編集用の表 9 件。紙面の文字との差がない
    out = [os.path.basename(f) for f in glob.glob(os.path.join(ROOT, "soron", "out", "*.docx"))]
    for k in PLAN:
        assert sum(1 for f in out if f.startswith(f"総論{k}_")) == 1, k
    assert any(f.startswith("総論K_") and f.endswith("_新設.docx") for f in out) and any(f.startswith("総論N_") and f.endswith("_新設.docx") for f in out)
    assert not any("2023年版K" in f for f in out) and len(out) == len(PLAN)


def test_cell_text_and_table_note_rules():
    w = lambda x0, y1, t, h=13: (x0, y1 - h, x0 + 8 * len(t), y1, t)
    assert X._cell_text([w(81, 542, "パクリタキセル"), w(77, 554, "（アルブミン懸濁型）")]) == "パクリタキセル（アルブミン懸濁型）"     # セルの中の 2 行をつなぐ
    assert X._cell_text([w(118, 145, "メトトレキサート"), w(250, 140, "＊1", 8)]) == "メトトレキサート＊1"                         # 上付きは直後の行に入れる
    assert X._cell_text([w(300, 100, "Grade"), w(345, 100, "2")]) == "Grade 2"
