"""Scope を Minds診療ガイドライン作成マニュアル2020 ver.3.0 第3章の様式ごとに、Excel(.xlsx)で生成する。
  python3 platform/scope/build_scope_minds.py       出力: platform/scope/out/minds/
    SC-1_疾患トピックの基本的特徴.xlsx / SC-2_診療アルゴリズム.xlsx / SC-3_スコープ.xlsx / SC-4_<番号>_<名称>.xlsx(CQ・FRQごとに 15件)
出典: 提案書v2、承認済み企画書、前回Scope(2021-07-02)、統括委員長の決定(approved_plan.json と指示)、2023年版 総論(units.json。原文のまま引用)。
出典にない項目は書かない。Minds公式のExcelテンプレートは参照できないため、項目と順序は、第3章の様式の記載項目に合わせる。"""
import json, os, re, sys
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "minds")
PLAN = json.load(open(os.path.join(HERE, "..", "governance", "approved_plan.json"), encoding="utf-8"))
UNITS = {u["key"]: u for u in json.load(open(os.path.join(HERE, "..", "data", "gl2023", "units.json"), encoding="utf-8"))}
TITLE = PLAN["タイトル"]; ITEMS = PLAN["SR項目"] + PLAN["FRQ項目"]
FONT = "Yu Gothic"
thin = Side(style="thin", color="000000"); BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)
HEAD = PatternFill("solid", fgColor="D9E1F2"); LABEL = PatternFill("solid", fgColor="EDEDED")
WRAP = Alignment(wrap_text=True, vertical="top")


def sentences(key, idx):
    t = re.sub(r"\^[^^]*\^", "", UNITS[key]["paras"][idx])
    return [s.strip() for s in re.split(r"(?<=。)", t) if s.strip()]


def quote(key, idx, which):
    return "".join(sentences(key, idx)[i] for i in which)


def book(widths):
    wb = openpyxl.Workbook(); ws = wb.active
    ws.page_setup.orientation = "landscape"; ws.page_setup.paperSize = ws.PAPERSIZE_A4; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = openpyxl.worksheet.properties.PageSetupProperties(fitToPage=True)   # 印刷・PDFで、横幅を1ページに収める
    for i, w in enumerate(widths): ws.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = w
    return wb, ws


def put(ws, r, vals, head=False, label=False, bold=False):
    for j, v in enumerate(vals):
        c = ws.cell(row=r, column=j + 1, value=v); c.alignment = WRAP; c.border = BORDER
        c.font = Font(name=FONT, size=10, bold=head or bold or (label and j == 0))
        if head: c.fill = HEAD
        elif label and j == 0: c.fill = LABEL
    n = max(len(str(v or "")) / max(1, ws.column_dimensions[openpyxl.utils.get_column_letter(j + 1)].width * 0.9) for j, v in enumerate(vals)) if vals else 1
    ws.row_dimensions[r].height = max(18, 15 * (int(n) + 1 + str(vals[-1] if vals else "").count("\n")))


def header(ws, form, name, ncol):
    ws.cell(row=1, column=1, value=f"{form} {name}").font = Font(name=FONT, size=14, bold=True)
    ws.cell(row=2, column=1, value=f"{TITLE}　/　日本がんサポーティブケア学会 編　/　Minds診療ガイドライン作成マニュアル2020 ver.3.0 第3章 {form}").font = Font(name=FONT, size=9)
    return 4


def safe(s):
    return re.sub(r'[\\/:*?"<>|\n\r]', "_", s).strip()


def kubun(x):
    return re.sub(r"\(監修:.*\)", "", x.get("区分", "FRQ(薬物療法による治療)"))


def is_treat(x):
    return x["id"].startswith("F") or "治療" in x.get("区分", "")


# ---------------------------------------------------------------- SC-1
def sc1():
    wb, ws = book([22, 100, 22]); r = header(ws, "SC-1", "疾患トピックの基本的特徴", 3)
    put(ws, r, ["項目", "内容", "出典"], head=True); r += 1
    rows = [("臨床的特徴", "がん薬物療法に伴う末梢神経障害(CIPN)は、がん薬物療法に関連して高頻度にみられる有害事象である。主な症状には、しびれ、疼痛、感覚低下、異常感覚、運動障害などがあり、患者の生活の質(quality of life:QOL)の低下、日常生活動作(activities of daily living:ADL)の制限、治療継続への影響、および全人的苦痛の増大につながる重要な病態である。", "提案書v2"),
            ("", quote("B", 0, [0, 1]), "2023年版 総論B(原文)"),
            ("疫学的特徴", quote("A", 0, [0, 2]), "2023年版 総論A(原文)"), ("", quote("E", 0, [0]), "2023年版 総論E(原文)"),
            ("診療の全体的な流れ", quote("H", 1, [0]), "2023年版 総論H(原文)"), ("", quote("J_1", 5, [0]), "2023年版 総論J-1(原文)"),
            ("", "本ガイドラインは、CIPNの予防(薬物療法・非薬物療法)と治療(薬物療法・非薬物療法)をCQとして扱う(SC-2、SC-4)。", "承認済み企画書")]
    for a, b, c in rows: put(ws, r, [a, b, c], label=True); r += 1
    return wb


# ---------------------------------------------------------------- SC-2
def sc2():
    wb, ws = book([26] * 8); r = header(ws, "SC-2", "診療アルゴリズム", 8)
    ws.cell(row=3, column=1, value="診療の流れと選択肢を示す。推奨を作成していない選択肢は、対応するCQ・FRQの番号で示す。").font = Font(name=FONT, size=9)
    def box(r1, c1, c2, text, fill=None, bold=False, h=None):
        ws.merge_cells(start_row=r1, start_column=c1, end_row=r1, end_column=c2)
        for c in range(c1, c2 + 1): ws.cell(row=r1, column=c).border = BORDER
        cell = ws.cell(row=r1, column=c1, value=text); cell.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center"); cell.font = Font(name=FONT, size=10, bold=bold)
        if fill: cell.fill = fill
        ws.row_dimensions[r1].height = h or 22
    def arrow(r1, c1, c2):
        ws.merge_cells(start_row=r1, start_column=c1, end_row=r1, end_column=c2); ws.cell(row=r1, column=c1, value="↓").alignment = Alignment(horizontal="center"); ws.cell(row=r1, column=c1).font = Font(name=FONT, size=12)
    nm = {x["id"]: x["名称"] for x in ITEMS}
    box(5, 1, 8, "がん薬物療法を受ける患者(CIPNを呈しうる、あるいは呈している)", HEAD, True, 28); arrow(6, 1, 8)
    box(7, 1, 4, "予防", HEAD, True); box(7, 5, 8, "治療(CIPNを呈している患者)", HEAD, True)
    left = [("薬物療法による予防", None)] + [(f"{i} {nm[i]}", i) for i in ("P1", "P2", "P3")] + [("非薬物療法による予防", None)] + [(f"{i} {nm[i]}", i) for i in ("N1", "N2", "N3")]
    right = [("CIPNの評価(総論H)", "t"), ("↓", "a"), ("被疑薬の延期・減量・中止(総論J-1)", "t"), ("↓", "a"), ("薬物療法による治療", None)] + [(f"{i} {nm[i]}", i) for i in ("T1", "T2", "T3")] + \
            [("FRQ(薬物療法による治療)", None)] + [(f"{i} {nm[i]}", i) for i in ("F1", "F2", "F3", "F4")] + [("非薬物療法による治療", None)] + [(f"{i} {nm[i]}", i) for i in ("N4", "N5")]
    for k, (text, tag) in enumerate(left):
        box(8 + k, 1, 4, text, LABEL if tag is None else None, tag is None)
    for k, (text, tag) in enumerate(right):
        if tag == "a": arrow(8 + k, 5, 8)
        else: box(8 + k, 5, 8, text, LABEL if tag is None else None, tag is None)
    end = 8 + max(len(left), len(right)) + 1
    ws.cell(row=end, column=1, value="CQ・FRQの番号は、承認済み企画書のSR項目・FRQ項目に対応する(SC-4)。").font = Font(name=FONT, size=9)
    return wb


# ---------------------------------------------------------------- SC-3
def sc3():
    wb, ws = book([30, 100, 26]); r = header(ws, "SC-3", "スコープ", 3)
    for a, b in (("版", "第1版"), ("作成日", "2026年11月25日"), ("作成者", "ガイドライン統括委員会 委員長 華井明子"), ("改訂の関係", "改訂版(前回: がん薬物療法に伴う末梢神経障害診療ガイドライン2023年版、2023年6月20日発刊)")):
        put(ws, r, [a, b, ""], label=True); r += 1
    r += 1
    cq = "、".join(f"{x['id']} {x['名称']}" for x in PLAN["SR項目"]); frq = "、".join(f"{x['id']} {x['名称']}" for x in PLAN["FRQ項目"])
    sections = [
      ("診療ガイドラインがカバーする内容に関する事項", [
        ("1. タイトル", TITLE + "(日本がんサポーティブケア学会 編)", "承認済み企画書"),
        ("2. 目的", "がん薬物療法に伴う末梢神経障害(chemotherapy-induced peripheral neuropathy:CIPN)を有する、または発症する可能性のある成人がん患者を対象とし、医師、看護師、薬剤師、作業療法士、理学療法士などを含む多職種医療チームが診療に活用できる指針を示すことを目的とする。\n改善するアウトカム: 予防としてはCIPNの発症頻度や症状(しびれ、疼痛)の軽減、治療としては症状(しびれ、疼痛)の軽減。", "提案書v2、前回Scope"),
        ("3. トピック", "がん薬物療法に伴う末梢神経障害(CIPN)の診療(予防・治療)", "前回Scope"),
        ("4. 視点", "Individual perspective(個人の視点)", "統括委員長の決定"),
        ("5. 想定される利用者、利用施設", "医師、看護師、薬剤師、理学療法士、作業療法士など、がん薬物療法に関わる医療者。がん薬物療法に関わる医療施設。", "提案書v2、前回Scope"),
        ("6. 既存ガイドラインとの関係", "米国臨床腫瘍学会(ASCO)2014年版、ASCO 2020年update版、欧州臨床腫瘍学会(ESMO)2020年版のガイドライン、およびがん薬物療法に伴う末梢神経障害マネジメントの手引き2017年版が存在する。本ガイドラインは、2023年版の改訂であり、今回新規の海外ガイドラインはない。", "前回Scope、承認済み企画書"),
        ("7. 診療ガイドラインがカバーする範囲", "カバーする範囲: がん薬物療法に伴う末梢神経障害を呈しうる、あるいは呈している成人(18歳以上)のがん患者。性別は、男性・女性を含む(がん種による差がある)。地理的要件はない。\nカバーしない範囲: 急性神経障害、神経疾患の合併例。糖尿病性神経障害や脊髄・脳病変など他の原因による神経障害、診断・治療上の境界領域は、必要に応じて総論で解説する。小児患者のCIPN対策は、総論Nとしてガイドライン委員会に依頼する。", "前回Scope、提案書v2、承認済み企画書、統括委員長の決定"),
        ("8. 重要臨床課題", "1. CIPNの予防(薬物療法および非薬物療法)\n2. CIPNの治療(薬物療法および非薬物療法)\n日本国内で使用されているものの海外ガイドラインでは扱いが少ない薬剤(ビタミンB12製剤、漢方薬、NSAIDs、オピオイドなど)と、冷却、圧迫、運動療法、鍼灸などの非薬物療法について、有効性と安全性を検討し、国内の診療実態に即した推奨を示す。前回エビデンスが不足していた項目は、FRQ(Future Research Question)として今回新設した。", "提案書v2、前回Scope、承認済み企画書"),
        ("9. CQリスト", f"SR項目(CQ)11: {cq}\nFRQ項目4: {frq}\n詳細は SC-4。企画書にない項目は追加しない。", "承認済み企画書")]),
      ("作成方法に関する事項: システマティックレビュー", [
        ("実施スケジュール", "記載しない", "統括委員長の決定"),
        ("エビデンスの検索", "文献データベース: PubMed(英語)。Cochrane Library、医中誌Webは検索しない(理由は方法に記載する)。\n検索期間: 前回の検索の終了日の翌日から2026年10月1日まで。\n検索式: 前回(2023年版)の式を用いる。担当者は、自分の担当部分で該当しない介入語を省いて検索してよい。\n既存のガイドライン: ASCO 2014年版・2020年update版、ESMO 2020年版。\n文献のソース: ① PubMedを用いた系統的文献検索、② 既存のガイドラインに引用されている文献、③ がん薬物療法に伴う末梢神経障害マネジメントの手引き2017年版に引用されている文献、④ 作成委員の任意のサーベイランスにより抽出した文献。\n検索の過程は、再現できるように記録し、ガイドライン内に記載する。\n効果のサーベイランスの範囲は、CIPNに限定する。", "統括委員長の決定、前回Scope"),
        ("文献の選択基準、除外基準", "適格基準: 18歳以上を対象とする。英語(総説および原著)で記載されている。対象患者はがん患者である。国内で施行可能な方法・薬物である(保険適応の有無は問わない)。原著は、メタアナリシス、無作為化比較試験、または分析疫学的研究(コホート研究、症例対照研究、横断研究)、記述研究(症例報告、ケースシリーズ)のいずれかである。\n記述研究と英語総説の内容は、解説で紹介してよいが、推奨の根拠にはしない。\n原著は英語に限定する(予備調査で、評価に値する日本語論文がなかったため)。\n選択の手順: 一次スクリーニング(題名・抄録)と二次スクリーニング(全文)を、それぞれ2名が独立に行う。2名の判定が一致しないときは、2名の協議に第三者の意見(SR委員長への報告)を加えて決める。", "前回Scope、統括委員長の決定"),
        ("エビデンスの評価と統合の方法", "個別研究の評価: Minds SR-5(旧称 様式4-5)。バイアスリスクと非直接性を、0/-1/-2で、2名が独立に評価する。盲検化は、二重盲検=0、単盲検=-1、非盲検=-1、記載なし=-1とし、-2は使わない。\n研究特性: 癌腫、薬剤名、化学療法の分類を記録し、エビデンス総体(SR-8)とSoFは、分類で層別する。\nエビデンス総体: Minds SR-8(絶対効果指標の結果を記入する場合)。確実性は、A(強)〜D(非常に弱い)。統合値と絶対効果は、委員が記入する。\nアウトカムは、全CQ・FRQで「CIPN」の1つである。", "統括委員長の決定")]),
      ("作成方法に関する事項: 推奨作成から公開まで", [
        ("推奨作成", "推奨の決定は、エビデンスの評価と統合で作成した資料を参考に、「アウトカム全体にわたる総括的なエビデンスの確実性」「望ましい効果と望ましくない効果のバランス」「患者・市民の価値観と希望」を考慮して行う。資源の利用(コスト)は、特に高額が予想される場合にのみ検討する。\n投票: 会議は開かず、ポータルの電子投票で行う(1人1票、変更不可、無記名、終了まで集計を表示しない)。投票者は、統括委員会と診療ガイドライン作成グループであり、患者代表は含めない。COIなどで除外された委員、直接評価された論文の筆頭著者、そのCQのSRを行った委員は、そのCQに投票しない。\n成立: 資格のある委員の75%以上が参加し、参加者の80%以上が同じ選択肢を選んだとき。意見の一致をみないときは、投票を繰り返し、3回で一致をみないときは「推奨なし」とする。\n推奨の強さ: 1 強い推奨(行う)、2 弱い推奨(行う)、3 なし(明確な推奨はできない)、4 弱い推奨(行わない)、5 強い推奨(行わない)。", "前回Scope、統括委員長の決定"),
        ("最終調整", "追加すべき事項(活用方法、評価方法など)を記載し、草案を作成する。草案に対して、外部評価とパブリックコメントを募集する。評価を参考にして、最終調整する。", "前回Scope"),
        ("外部評価", "外部評価委員(仮。松岡歩、横田知哉、浜野純、桜井なおみ)が、Scopeの完成前と、ガイドラインの完成前に、個別にコメントを提出する。診療ガイドライン作成グループは、各コメントについて、内容を変更する必要性を討議して、対応を決定する。パブリックコメントも同様とする。", "承認済み企画書、前回Scope"),
        ("公開", "外部評価とパブリックコメントへの対応が終了したら、診療ガイドライン統括委員会が公開の最終決定をする。出版は2028年6月頃。書籍(予定出版社 金原出版)、学会ホームページ(出版1年後より)、Mindsホームページ。継続的な改訂体制は、有り。", "前回Scope、提案書v2")])]
    for sec, rows in sections:
        put(ws, r, [sec, "", ""], head=True); ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3); r += 1
        put(ws, r, ["項目", "内容", "出典"], head=True); r += 1
        for a, b, c in rows: put(ws, r, [a, b, c], label=True); r += 1
        r += 1
    return wb


# ---------------------------------------------------------------- SC-4(CQ・FRQごと)
def plain(n):
    return re.sub(r"による治療$", "", re.sub(r"\((予防|治療)\)$", "", n))


def sc4(x):
    wb, ws = book([26, 90, 26]); r = header(ws, "SC-4", f"クリニカルクエスチョン(CQ)の設定　{x['id']} {x['名称']}", 3)
    treat = is_treat(x)
    put(ws, r, ["項目", "内容", "出典"], head=True); r += 1
    rows = [("番号", x["id"] + ("(FRQ)" if x["id"].startswith("F") else "(SR項目)"), "承認済み企画書"),
            ("対応する重要臨床課題", "CIPNの治療(薬物療法および非薬物療法)" if treat else "CIPNの予防(薬物療法および非薬物療法)", "提案書v2"),
            ("P: 性別", "男性・女性を含む(がん種による差がある)", "統括委員長の決定"),
            ("P: 年齢", "18歳以上(成人)", "前回Scope"),
            ("P: 疾患・病態", "がん化学療法を受ける患者" + ("(CIPNを呈している)" if treat else "(CIPNを発症しうる)"), "統括委員長の決定、前回Scope"),
            ("P: 地理的要件", "なし", "統括委員長の決定"),
            ("I(介入)", x["名称"], "承認済み企画書"), ("C(対照)", "無治療", "統括委員長の決定"),
            ("O(アウトカム): 内容", "CIPN(症状の有無で評価する)", "統括委員長の決定"), ("O: 益/害", "益", "前回Scope"),
            ("O: 重要度(1〜9)", "評価しない(アウトカムが単一のため)", "統括委員長の決定"), ("O: 採用", "採用", "統括委員長の決定"),
            ("CQ文", ("CIPNを呈している患者に対して、CIPNの治療として、" if treat else "がん化学療法を受ける患者に対して、CIPNの予防として、") + plain(x["名称"]) + "は推奨されるか。", "前回Scope(CQの形)")]
    for a, b, c in rows: put(ws, r, [a, b, c], label=True); r += 1
    if x["id"].startswith("F"):
        put(ws, r, ["備考", "FRQ(Future Research Question): 前回エビデンスが不足していた項目について、今回より新設した。", "承認済み企画書"], label=True)
    return wb


def main():
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        if f.endswith(".xlsx"): os.remove(os.path.join(OUT, f))
    made = {"SC-1_疾患トピックの基本的特徴.xlsx": sc1(), "SC-2_診療アルゴリズム.xlsx": sc2(), "SC-3_スコープ.xlsx": sc3()}
    for x in ITEMS: made[f"SC-4_{x['id']}_{safe(x['名称'])}.xlsx"] = sc4(x)
    for name, wb in made.items():
        wb.save(os.path.join(OUT, name))
    print(f"{len(made)}件: {OUT}")


if __name__ == "__main__":
    main()
