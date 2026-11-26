"""Scope を、Minds診療ガイドライン作成マニュアル2020 ver.3.0 の公式テンプレート(all_template_2020ver3_0_r3.xlsx)の SC-1〜SC-4 に記入して、Excel で出力する。
  python3 platform/scope/build_scope_minds.py [テンプレートのパス]     出力: platform/scope/out/minds/
    SC-1_疾患トピックの基本的特徴.xlsx / SC-2_診療アルゴリズム.xlsx / SC-3_スコープ.xlsx / SC-4_<番号>_<名称>.xlsx(CQ・FRQごとに 15件)
テンプレートの書式(罫線・結合・入力規則)をそのまま使い、記入するセルだけを書く。セルの高さと一部の列幅だけを、本文が収まるように変える。
出典: 提案書v2、承認済み企画書、前回Scope(2021-07-02)、統括委員長の決定(approved_plan.json と指示)、2023年版 総論(units.json。原文のまま引用)。出典にない項目は書かない。
公式テンプレートは Minds の著作物であり、リポジトリには置かない(引数または環境変数 MINDS_TEMPLATE で指定する)。"""
import json, math, os, re, sys
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "minds")
DEFAULT_TEMPLATE = "/root/.claude/uploads/35fc0347-4843-50a8-8bae-67db746000d0/b454e3c2-all_template_2020ver3_0_r3.xlsx"
PLAN = json.load(open(os.path.join(HERE, "..", "governance", "approved_plan.json"), encoding="utf-8"))
UNITS = {u["key"]: u for u in json.load(open(os.path.join(HERE, "..", "data", "gl2023", "units.json"), encoding="utf-8"))}
TITLE = PLAN["タイトル"]; ITEMS = PLAN["SR項目"] + PLAN["FRQ項目"]
LINE = 16.5   # 1行の高さ(11pt)


def sentences(key, idx):
    t = re.sub(r"\^[^^]*\^", "", UNITS[key]["paras"][idx])
    return [s.strip() for s in re.split(r"(?<=。)", t) if s.strip()]


def quote(key, idx, which):
    return "".join(sentences(key, idx)[i] for i in which)


def units(s):
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)


def lines_needed(text, width_units):
    cpl = max(8, width_units * 0.80)
    return sum(max(1, math.ceil(units(p) / cpl)) for p in str(text).split("\n"))


def load(template, sheet, new_title):
    """テンプレートを読み、指定のシートだけを残す(目次への戻りリンクは外す)。"""
    wb = openpyxl.load_workbook(template)
    for ws in list(wb.worksheets):
        if ws.title != sheet: wb.remove(ws)
    ws = wb[sheet]; ws.title = new_title
    ws["A1"].hyperlink = None; ws["A1"].value = None
    return wb, ws


def fit(ws, area):
    """印刷・PDFで、横幅を1ページに収める。"""
    ws.print_area = area; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = openpyxl.worksheet.properties.PageSetupProperties(fitToPage=True)


def width(ws, c1, c2):
    from openpyxl.utils import get_column_letter as L, column_index_from_string as I
    return sum((ws.column_dimensions[L(c)].width or 8.43) for c in range(I(c1), I(c2) + 1))


def set_text(ws, anchor, text, r1, r2, c1, c2, wrap_center=False):
    """結合セルに本文を書き、本文が収まるように行の高さを上げる(既存の高さより低くしない)。"""
    cell = ws[anchor]; cell.value = text
    cell.alignment = Alignment(wrap_text=True, vertical="top", horizontal=cell.alignment.horizontal)
    need = lines_needed(text, width(ws, c1, c2)) * LINE + 14; have = sum((ws.row_dimensions[r].height or 15.0) for r in range(r1, r2 + 1))
    if need > have:
        for r in range(r1, r2 + 1): ws.row_dimensions[r].height = need / (r2 - r1 + 1)


# ---------------------------------------------------------------- SC-1
def sc1(template):
    wb, ws = load(template, "SC-1　テンプレート", "SC-1")
    for c in "ABCDEFGHI": ws.column_dimensions[c].width = 12
    feat = ("がん薬物療法に伴う末梢神経障害(CIPN)は、がん薬物療法に関連して高頻度にみられる有害事象である。主な症状には、しびれ、疼痛、感覚低下、異常感覚、運動障害などがあり、患者の生活の質(quality of life:QOL)の低下、日常生活動作(activities of daily living:ADL)の制限、治療継続への影響、および全人的苦痛の増大につながる重要な病態である。\n"
            + quote("B", 0, [0, 1]) + "(2023年版 総論B)")
    epi = quote("A", 0, [0, 2]) + "(2023年版 総論A)\n" + quote("E", 0, [0]) + "(2023年版 総論E)"
    flow = (quote("H", 1, [0]) + "(2023年版 総論H)\n" + quote("J_1", 5, [0]) + "(2023年版 総論J-1)\n本ガイドラインは、CIPNの予防(薬物療法・非薬物療法)と治療(薬物療法・非薬物療法)をCQとして扱う(SC-2、SC-4)。")
    for anchor, text, r1, r2 in (("A4", feat, 4, 14), ("A16", epi, 16, 26), ("A28", flow, 28, 38)): set_text(ws, anchor, text, r1, r2, "A", "I")
    fit(ws, "A2:I38")
    return wb


# ---------------------------------------------------------------- SC-2
def sc2(template):
    wb, ws = load(template, "SC-2　テンプレート", "SC-2")
    for rng in list(ws.merged_cells.ranges):
        if str(rng) == "A4:I14": ws.unmerge_cells(str(rng))
    ws["A4"].value = None
    for c in "ABCDEFGHI": ws.column_dimensions[c].width = 15
    thin = Side(style="thin", color="000000"); border = Border(left=thin, right=thin, top=thin, bottom=thin)
    font = Font(name="游ゴシック Medium", size=11); head = PatternFill("solid", fgColor="DAE3F3"); grp = PatternFill("solid", fgColor="EDEDED")
    nm = {x["id"]: x["名称"] for x in ITEMS}

    def box(r, c1, c2, text, fill=None, bold=False):
        ws.merge_cells(start_row=r, start_column=c1, end_row=r, end_column=c2)
        for c in range(c1, c2 + 1): ws.cell(row=r, column=c).border = border
        cell = ws.cell(row=r, column=c1, value=text); cell.font = Font(name=font.name, size=11, bold=bold); cell.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
        if fill: cell.fill = fill
        ws.row_dimensions[r].height = 22 if lines_needed(text, (c2 - c1 + 1) * 15) < 2 else 40

    def arrow(r, c1, c2):
        ws.merge_cells(start_row=r, start_column=c1, end_row=r, end_column=c2); cell = ws.cell(row=r, column=c1, value="↓"); cell.alignment = Alignment(horizontal="center"); cell.font = font
    box(4, 1, 9, "がん薬物療法を受ける患者(CIPNを呈しうる、あるいは呈している)", head, True); arrow(5, 1, 9)
    box(6, 1, 4, "予防", head, True); box(6, 6, 9, "治療(CIPNを呈している患者)", head, True)
    left = [("薬物療法による予防", True)] + [(nm[i], False) for i in ("P1", "P2", "P3")] + [("非薬物療法による予防", True)] + [(nm[i], False) for i in ("N1", "N2", "N3")]
    right = [("CIPNの評価(総論H)", False), ("↓", None), ("被疑薬の延期・減量・中止(総論J-1)", False), ("↓", None), ("薬物療法による治療", True)] + [(nm[i], False) for i in ("T1", "T2", "T3")] + \
            [("FRQ(薬物療法による治療)", True)] + [(nm[i], False) for i in ("F1", "F2", "F3", "F4")] + [("非薬物療法による治療", True)] + [(nm[i], False) for i in ("N4", "N5")]
    for k, (t, g) in enumerate(left): box(7 + k, 1, 4, t, grp if g else None, g)
    for k, (t, g) in enumerate(right):
        if g is None: arrow(7 + k, 6, 9)
        else: box(7 + k, 6, 9, t, grp if g else None, g)
    end = 7 + max(len(left), len(right)) + 1
    ws.cell(row=end, column=1, value="CQ・FRQは、承認済み企画書のSR項目・FRQ項目である(SC-4)。").font = Font(name=font.name, size=10)
    fit(ws, f"A2:I{end}")
    return wb


# ---------------------------------------------------------------- SC-3
def sc3(template):
    wb, ws = load(template, "SC-3　テンプレート", "SC-3")
    for c in "IJK": ws.column_dimensions[c].width = 24
    ws["D3"].value = "第1版"; ws["C4"].value = "2026年11月25日"; ws["C5"].value = "ガイドライン統括委員会 委員長 華井明子"
    cq = "【SR項目(CQ)】\n" + "\n".join(f"・{x['名称']}" for x in PLAN["SR項目"]) + "\n【FRQ】\n" + "\n".join(f"・{x['名称']}" for x in PLAN["FRQ項目"])
    V = {  # アンカー: (本文, 先頭行, 末尾行, 先頭列, 末尾列)
      "F7": (TITLE + "(日本がんサポーティブケア学会 編)", 7, 9),
      "F10": ("がん薬物療法に伴う末梢神経障害(chemotherapy-induced peripheral neuropathy:CIPN)を有する、または発症する可能性のある成人がん患者を対象とし、医師、看護師、薬剤師、作業療法士、理学療法士などを含む多職種医療チームが診療に活用できる指針を示すことを目的とする。\n改善するアウトカム: 予防としてはCIPNの発症頻度や症状(しびれ、疼痛)の軽減、治療としては症状(しびれ、疼痛)の軽減。", 10, 12),
      "F13": ("がん薬物療法に伴う末梢神経障害(CIPN)の診療(予防・治療)", 13, 15),
      "F16": ("Individual perspective(個人の視点)", 16, 18),
      "F19": ("医師、看護師、薬剤師、理学療法士、作業療法士など、がん薬物療法に関わる医療者。がん薬物療法に関わる医療施設。", 19, 21),
      "F22": ("米国臨床腫瘍学会(ASCO)2014年版、ASCO 2020年update版、欧州臨床腫瘍学会(ESMO)2020年版のガイドライン、およびがん薬物療法に伴う末梢神経障害マネジメントの手引き2017年版が存在する。本ガイドラインは、2023年版の改訂であり、今回新規の海外ガイドラインはない。", 22, 24),
      "F25": ("カバーする範囲: がん薬物療法に伴う末梢神経障害を呈しうる、あるいは呈している成人(18歳以上)のがん患者。性別は、男性・女性を含む(がん種による差がある)。地理的要件はない。\nカバーしない範囲: 急性神経障害、神経疾患の合併例。糖尿病性神経障害や脊髄・脳病変など他の原因による神経障害、診断・治療上の境界領域は、必要に応じて総論で解説する。小児患者のCIPN対策は、総論Nとしてガイドライン委員会に依頼する。", 25, 27),
      "F52": ("記載しない", 52, 54),
      "F55": ("文献データベース: PubMed(英語)。Cochrane Library、医中誌Webは検索しない(理由は方法に記載する)。\n検索期間: 前回の検索の終了日の翌日から2026年10月1日まで。\n検索式: 前回(2023年版)の式を用いる。担当者は、自分の担当部分で該当しない介入語を省いて検索してよい。\n既存のガイドライン: ASCO 2014年版・2020年update版、ESMO 2020年版。\n文献のソース: ① PubMedを用いた系統的文献検索、② 既存のガイドラインに引用されている文献、③ がん薬物療法に伴う末梢神経障害マネジメントの手引き2017年版に引用されている文献、④ 作成委員の任意のサーベイランスにより抽出した文献。\n検索の過程は、再現できるように記録し、ガイドライン内に記載する。効果のサーベイランスの範囲は、CIPNに限定する。", 55, 60),
      "F61": ("適格基準: 18歳以上を対象とする。英語(総説および原著)で記載されている。対象患者はがん患者である。国内で施行可能な方法・薬物である(保険適応の有無は問わない)。原著は、メタアナリシス、無作為化比較試験、または分析疫学的研究(コホート研究、症例対照研究、横断研究)、記述研究(症例報告、ケースシリーズ)のいずれかである。記述研究と英語総説の内容は、解説で紹介してよいが、推奨の根拠にはしない。原著は英語に限定する(予備調査で、評価に値する日本語論文がなかったため)。\n選択の手順: 一次スクリーニング(題名・抄録)と二次スクリーニング(全文)を、それぞれ2名が独立に行う。2名の判定が一致しないときは、2名の協議に第三者の意見(SR委員長への報告)を加えて決める。", 61, 63),
      "F64": ("個別研究の評価: Minds SR-5(旧称 様式4-5)。バイアスリスクと非直接性を、0/-1/-2で、2名が独立に評価する。盲検化は、二重盲検=0、単盲検=-1、非盲検=-1、記載なし=-1とし、-2は使わない。\n研究特性: 癌腫、薬剤名、化学療法の分類を記録し、エビデンス総体(SR-8)とSoFは、分類で層別する。\nエビデンス総体: Minds SR-8(絶対効果指標の結果を記入する場合)。確実性は、A(強)〜D(非常に弱い)。統合値と絶対効果は、委員が記入する。アウトカムは、全CQ・FRQで「CIPN」の1つである。", 64, 66),
      "F68": ("推奨の決定は、エビデンスの評価と統合で作成した資料を参考に、「アウトカム全体にわたる総括的なエビデンスの確実性」「望ましい効果と望ましくない効果のバランス」「患者・市民の価値観と希望」を考慮して行う。資源の利用(コスト)は、特に高額が予想される場合にのみ検討する。\n投票: 会議は開かず、ポータルの電子投票で行う(1人1票、変更不可、無記名、終了まで集計を表示しない)。投票者は、統括委員会と診療ガイドライン作成グループであり、患者代表は含めない。COIなどで除外された委員、直接評価された論文の筆頭著者、そのCQのSRを行った委員は、そのCQに投票しない。\n成立: 資格のある委員の75%以上が参加し、参加者の80%以上が同じ選択肢を選んだとき。意見の一致をみないときは、投票を繰り返し、3回で一致をみないときは「推奨なし」とする。\n推奨の強さ: 1 強い推奨(行う)、2 弱い推奨(行う)、3 なし(明確な推奨はできない)、4 弱い推奨(行わない)、5 強い推奨(行わない)。", 68, 70),
      "F71": ("追加すべき事項(活用方法、評価方法など)を記載し、草案を作成する。草案に対して、外部評価とパブリックコメントを募集する。評価を参考にして、最終調整する。", 71, 73),
      "F74": ("外部評価委員(仮。松岡歩、横田知哉、浜野純、桜井なおみ)が、Scopeの完成前と、ガイドラインの完成前に、個別にコメントを提出する。診療ガイドライン作成グループは、各コメントについて、内容を変更する必要性を討議して、対応を決定する。パブリックコメントも同様とする。", 74, 76),
      "F77": ("外部評価とパブリックコメントへの対応が終了したら、診療ガイドライン統括委員会が公開の最終決定をする。出版は2028年6月頃。書籍(予定出版社 金原出版)、学会ホームページ(出版1年後より)、Mindsホームページ。継続的な改訂体制は、有り。", 77, 79)}
    for anchor, (text, r1, r2) in V.items(): set_text(ws, anchor, text, r1, r2, "F", "K")
    # (8) 重要臨床課題
    issue2 = ("CIPNの治療(薬物療法および非薬物療法)。日本国内で使用されているものの海外ガイドラインでは扱いが少ない薬剤(ビタミンB12製剤、漢方薬、NSAIDs、オピオイドなど)と、冷却、圧迫、運動療法、鍼灸などの非薬物療法について、有効性と安全性を検討し、国内の診療実態に即した推奨を示す。前回エビデンスが不足していた項目は、FRQ(Future Research Question)として今回新設した。")
    set_text(ws, "H28", "CIPNの予防(薬物療法および非薬物療法)", 28, 30, "H", "K")
    ws["F34"].value = None   # 重要臨床課題は2つ(3は該当なし)。課題3の枠は、課題2の枠に合わせる
    ws.unmerge_cells("H31:K33"); ws.unmerge_cells("H34:K40"); ws.merge_cells("H31:K40"); set_text(ws, "H31", issue2, 31, 40, "H", "K")
    # (9) CQリスト: 15行を1つの枠に書く(テンプレートの CQ1〜CQ3 の枠を、1つの結合セルにまとめる)
    for rng in ("G41:K42", "G43:K44", "G45:K50"): ws.unmerge_cells(rng)
    for c in ("F43", "F45"): ws[c].value = None
    ws["F41"].value = "CQ・FRQ："; ws.merge_cells("F41:F50"); ws.merge_cells("G41:K50")
    ws["F41"].alignment = Alignment(wrap_text=True, vertical="top"); set_text(ws, "G41", cq, 41, 50, "G", "K")
    fit(ws, "A2:K79")
    return wb


# ---------------------------------------------------------------- SC-4
def plain(n):
    return re.sub(r"による治療$", "", re.sub(r"\((予防|治療)\)$", "", n))


def sc4(template, x):
    wb, ws = load(template, "SC-4　テンプレート", "SC-4")
    treat = x["id"].startswith("F") or "治療" in x.get("区分", "")
    ws["A4"].value = "CIPNの治療(薬物療法および非薬物療法)" if treat else "CIPNの予防(薬物療法および非薬物療法)"
    ws["B11"].value = "指定なし"                                        # 男性・女性を含む
    ws["B12"].value = None; ws["D12"].value = "18歳以上(成人)"
    ws["B13"].value = "がん化学療法を受ける患者(" + ("CIPNを呈している" if treat else "CIPNを発症しうる") + ")"
    ws["B14"].value = "なし"
    ws["B15"].value = "男性・女性を含む。がん種によって、性別の構成に差がある。"
    ws["A17"].value = x["名称"]; ws["E17"].value = "無治療"
    ws["B22"].value = "CIPN(症状の有無で評価する)"; ws["F22"].value = "益"; ws["G22"].value = "評価しない"; ws["I22"].value = None; ws["J22"].value = "○"
    ws["A33"].value = ("CIPNを呈している患者に対して、CIPNの治療として、" if treat else "がん化学療法を受ける患者に対して、CIPNの予防として、") + plain(x["名称"]) + "は推奨されるか。"
    for a in ("A4", "B15", "A17", "E17", "A33"): ws[a].alignment = Alignment(wrap_text=True, vertical="top", horizontal="left")
    ws["B13"].alignment = Alignment(wrap_text=True, vertical="center", horizontal="left"); ws["B22"].alignment = Alignment(wrap_text=True, vertical="center", horizontal="left")
    ws.row_dimensions[22].height = 32; ws.row_dimensions[13].height = 32; ws.row_dimensions[15].height = 32
    fit(ws, "A2:J40")
    return wb


def safe(s):
    return re.sub(r'[\\/:*?"<>|\n\r]', "_", s).strip()


def main(template):
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        if f.endswith(".xlsx"): os.remove(os.path.join(OUT, f))
    made = {"SC-1_疾患トピックの基本的特徴.xlsx": sc1(template), "SC-2_診療アルゴリズム.xlsx": sc2(template), "SC-3_スコープ.xlsx": sc3(template)}
    for x in ITEMS: made[f"SC-4_{safe(x['名称'])}.xlsx"] = sc4(template, x)
    for name, wb in made.items(): wb.save(os.path.join(OUT, name))
    print(f"{len(made)}件: {OUT}")


if __name__ == "__main__":
    t = (sys.argv[1] if len(sys.argv) > 1 else "") or os.environ.get("MINDS_TEMPLATE", "") or DEFAULT_TEMPLATE
    if not os.path.exists(t): sys.exit(f"Minds の公式テンプレートがありません: {t}")
    main(t)
