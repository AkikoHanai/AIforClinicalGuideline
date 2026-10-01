"""
CQパッケージ → 委員会レビュー作業一式(Minds様式ファイル + 文献フォルダ)
====================================================================
extract_cipn_guideline.py が作る CQ パッケージ(JSON)から、CQ(介入)ごとに
以下をまとめて用意する。

  <outdir>/<cq_id>/
    minds_review.xlsx   Minds様式のレビュー用ワークブック
                         (CQ・PICO / 4-5 個別研究評価 / SR-8 エビデンス総体 / 研究特性 / 文献リスト / 投票)
    MANIFEST.md          引用文献の書誌情報一覧(PMID・著者・誌名・年)。
                          論文PDF本体は著作権上ここでは収集できないため、
                          「papers/」フォルダに手作業で集めてもらうためのチェックリスト
    papers/               論文PDFを手作業で入れてもらうための空フォルダ

Minds様式の対応(『Minds診療ガイドライン作成の手引き』準拠):
  シート「検索式」               = Minds 3.5 (文献検索式・DB・検索期間の記録)
  シート「CQ・PICO」            = Minds 3.3-3.5 (CQ設定・PICO・アウトカム重要度)
  シート「スクリーニングログ」    = Minds 3.5/4.2 (一次・二次スクリーニング、除外理由、PRISMAフロー用)
  シート「4-5_評価者1/2」       = Minds 4.3 / 様式4-5 評価シート 介入研究(個別研究のバイアスリスク・非直接性。2名が独立に記入)
  シート「4-5_照合」             = 2名の評価を項目ごとに自動照合し不一致を検出→委員が確定
  シート「研究特性」             = 化学療法の分類など(非直接性 対象 の判断材料)
  シート「RoB2(参考)」          = Cochrane RoB 2.0 を参考として併記(公式様式ではない)
  シート「SR-8_エビデンス総体」   = Minds 4.4 / 様式SR-8 (エビデンス総体の確実性評価。化学療法別の層別行つき)
  シート「文献リスト」           = Minds 3.5/4.2 (適格文献リスト)
  シート「投票」                = Minds 6.2-6.3 (推奨作成の投票)

4-5評価シート(評価者2名)・SR-8エビデンス総体シートは空欄で出力する(2023年版の評価は参考として下書きに入る)。ここを
Minds 公式様式の手順(0/-1/-2評価)でSR委員が埋めたものを merge_rob2_evidence.py で
CQパッケージ(JSON)に戻し、platform/core/review_bundle.py の
Minds規則検証(R1-R8)にかける設計。
"""
import argparse
import glob
import json
import os
import re

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from minds_forms import (ITEMS, ITEM_KEYS, C_ITEM0, HEAD_ROWS, SPARE_ROWS, CHEMO_CLASSES, block_start, build_45_sheet, build_sr8_sheet)

HERE = os.path.dirname(os.path.abspath(__file__))

# 印刷時のインク消費を抑えるため、濃い塗り＋白抜き文字は使わない(白地に黒文字)
HEADER_FILL = PatternFill("solid", fgColor="EDEDED")
HEADER_FONT = Font(color="000000", bold=True)
NOTE_FILL = PatternFill("solid", fgColor="FFF3CD")
WARN_FILL = PatternFill("solid", fgColor="F8D7DA")
MISMATCH_FILL = PatternFill("solid", fgColor="F8D7DA")
WRAP = Alignment(wrap_text=True, vertical="top")

# ------------------------------------------------------------------
# 検索式(委員会から提示されたもの。介入語句部分のみCQごとに変わる)
# DBはPubMedのみ、期間は「前回検索から現在まで」。
# ------------------------------------------------------------------
SEARCH_P = '(((survivor OR (survivor AND cancer) OR "cancer survivor" OR cancer))'
SEARCH_C = ('(neuropathy OR "neuropathy" OR "neuropathies" OR chemotherapy-induced '
            'OR "chemotherapy-induced neuropathy" OR "chemotherapy-induced peripheral neuropathy" '
            'OR CIPN OR peripheral nervous system/drug effects OR peripheral nerve diseases/chemically induced '
            'OR antineoplastic agents/adverse effects OR neoplasms/drug therapy OR neoplasms/complications)')
SEARCH_I_FULL = ('(Goshajinkigan OR (Calcium and Magnesium) OR Acetyl-L-carnitine OR Alpha-lipoic acid '
                  'OR Pregabalin OR gabapentin OR Venlafaxine OR duloxetine OR Vitamin E '
                  'OR Ganglioside-monosialic acid OR amitriptyline/ketamine OR cannabinoid OR nabiximols '
                  'OR LC07 OR cryotherapy OR scrambler therapy)')
SEARCH_DB = "PubMed"
SEARCH_PERIOD = "前回検索日(要確認) 〜 今回検索実施日"

# CQごとに検索式の第3節(介入語)のうち対応する語句。無いCQは
# 「本検索式に個別対応語なし」として要確認フラグを立てる(機械マッチではなく
# 人手で確認した対応表。誤りに気づいたら書き換えてよい)
SEARCH_TERM_MAP = {
    "CQ1-牛車腎気丸": (["Goshajinkigan"], None),
    "CQ1-プレガバリン": (["Pregabalin"], None),
    "CQ1-カルニチン-アセチル‒L‒カルニチン": (["Acetyl-L-carnitine"], None),
    "CQ1-冷却": (["cryotherapy"], None),
    # 以下は共通のI節に語が無いCQ。委員会指定のMeSH語をI節として使う
    "CQ1-圧迫": (['"Compression Bandages"[Mesh]'], None),
    "CQ1-運動": (['"Exercise"[Mesh] OR "Exercise Therapy"[Mesh]'], None),
    "CQ1-鍼灸": (['"Acupuncture Therapy"[Mesh]'], None),
    "CQ2-デュロキセチン": (["duloxetine"], None),
    "CQ2-アミトリプチリン": (["amitriptyline/ketamine"], None),
    "CQ2-プレガバリン": (["Pregabalin", "gabapentin"], None),
    "CQ2-ミロガバリン": (['"Mirogabalin"[Supplementary Concept]'], None),
    "CQ2-ビタミン-B12": (['"Vitamin B 12"[Mesh]'], None),
    "CQ2-非ステロイド性消炎鎮痛薬-NSAIDs": (['"Anti-Inflammatory Agents, Non-Steroidal"[Mesh]'], None),
    "CQ2-オピオイド": (['"Analgesics, Opioid"[Mesh]'], None),
    "CQ2-薬物の併用療法": (['"Drug Therapy, Combination"[Mesh]'], None),
    "CQ2-運動": (['"Exercise"[Mesh] OR "Exercise Therapy"[Mesh]'], None),
    "CQ2-鍼灸": (['"Acupuncture Therapy"[Mesh]'], None),
}

# 冷却と圧迫は改訂でCQ・検索式・担当を統合する(委員会決定)。
# 2つのCQパッケージを1つにまとめ、2023年版の推奨は両方とも残す
CQ_MERGES = {
    "CQ1-冷却・圧迫": ["CQ1-冷却", "CQ1-圧迫"],
}
MERGED_SEARCH_TERMS = {
    "CQ1-冷却・圧迫": (["cryotherapy", '"Compression Bandages"[Mesh]'], None),
}

# FRQ(Future Research Question)。Minds 2020では、SRの結果エビデンスが不足し
# 推奨を出せないCQを FRQ として扱い、推奨文・強さの代わりに
# 「現時点のエビデンスの状況」と「今後必要な研究」を記述する(要: 手引き2020の
# FRQの項で最終確認)。委員会の割り振り表で FRQ とされた4件
FRQ_CQS = {"CQ2-ビタミン-B12", "CQ2-非ステロイド性消炎鎮痛薬-NSAIDs",
           "CQ2-オピオイド", "CQ2-薬物の併用療法"}

# 2023年版 第1章4「アウトカムの重要性について」:
#   予防: CIPN発症頻度、症状(しびれ・疼痛)の軽減 / 治療: 症状(しびれ・疼痛)の軽減
#   重要性の点数化・デルファイは行わなかった(2023年版の限界として明記)
# → 改訂でも同じアウトカムを出発点にし、重要度は「重大」扱い(9)で置き、委員会で確定する
OUTCOMES_BY_CQ_TYPE = {
    "CQ1": [
        {"id": "O:CIPN発症頻度", "label": "CIPN発症頻度", "importance": 9,
         "_note": "2023年版で設定。重要度は未点数化のため暫定9(重大)。委員会で確定"},
        {"id": "O:症状の軽減", "label": "症状（しびれ・疼痛）の軽減", "importance": 9,
         "_note": "2023年版で設定。重要度は未点数化のため暫定9(重大)。委員会で確定"},
    ],
    "CQ2": [
        {"id": "O:症状の軽減", "label": "症状（しびれ・疼痛）の軽減", "importance": 9,
         "_note": "2023年版で設定。重要度は未点数化のため暫定9(重大)。委員会で確定"},
    ],
}
# 評価指標(アウトカムの測定尺度)。2023年版 第2章H「CIPNの評価」に基づく。
# Mindsではアウトカムは「何をどの尺度で測ったか」で扱うため、各研究がどの指標を
# 使ったかを4-5評価シートの「評価指標(使用尺度)」列に記録し、総体評価はアウトカム概念ごとに行う
INSTRUMENTS = [
    # (分類, 名称, 略称/版, 何を測るか, 備考)
    ("医療者評価", "Common Terminology Criteria for Adverse Events", "CTCAE (v3.0/v4.0/v5.0)",
     "有害事象グレード(G1 症状なし/G2 IADL障害/G3 ADL障害)", "最も広く使用。評価者裁量が入りやすくPROと乖離あり"),
    ("医療者評価", "ECOG neuropathy scores", "ECOG", "客観所見と機能障害の程度", ""),
    ("医療者評価", "Debiopharm 神経症状—感覚性毒性基準", "DEB-NTC", "オキサリプラチン起因性、7日以上の持続の有無", ""),
    ("患者報告(PRO)", "EORTC QLQ-CIPN20", "QLQ-CIPN20 (20/16/15項目版)", "過去7日間の感覚・運動・自律神経症状", "信頼性・妥当性検証済み。NCI推奨"),
    ("患者報告(PRO)", "FACT/GOG-Neurotoxicity", "FACT-Ntx (38/12/4項目版)", "身体・社会・感情・機能と神経毒性", "NCI推奨。類似にFACT-Taxane"),
    ("患者報告(PRO)", "Patient Neurotoxicity Questionnaire", "PNQ", "感覚・運動障害(5件法)と生活障害", "デルファイで最高評価"),
    ("患者報告(PRO)", "PRO-CTCAE", "PRO-CTCAE", "CTCAEの患者報告版", ""),
    ("患者報告(PRO)", "CAS-CIPN(がんサバイバーのCIPN包括的評価尺度)", "CAS-CIPN (15項目)", "生活支障の脅威/手の巧緻動作/自信/手掌足底の感覚異常", "本邦開発。FACT-Ntxと強い相関"),
    ("疼痛尺度", "Visual Analogue Scale", "VAS", "痛みの重症度(10cm線上)", "CIPN特異的ではない"),
    ("疼痛尺度", "Numerical Rating Scale", "NRS", "24時間以内の痛み(0-10)", "CIPN特異的ではない"),
    ("疼痛尺度", "Brief Pain Inventory", "BPI (短縮版)", "痛みの頻度・強度・場所・質", "短縮版の使用が推奨"),
    ("複合指標", "Total Neuropathy Score", "TNS / mTNS / TNSc", "自覚症状+腱反射・握力等の定量評価", "CTCAEと相関"),
    ("定量評価(感覚)", "Semmes-Weinstein monofilament / 10g test", "SWM", "静的触覚閾値", ""),
    ("定量評価(感覚)", "二点識別覚", "2PD", "受容器・神経線維単位の分布密度", ""),
    ("定量評価(感覚)", "音叉(128Hz)振動覚", "tuning fork", "振動覚(10秒感知できなければ疑う)", ""),
    ("定量評価(運動)", "Timed Up and Go / 6分間歩行", "TUG / 6MWT", "移動能力・転倒リスク", ""),
    ("定量評価(運動)", "Grooved Pegboard / STEF", "GPT / STEF", "手指の巧緻性", ""),
    ("電気生理", "神経伝導検査 / 電流知覚閾値", "NCS / CPT(2000Hz)", "感覚振幅、電流知覚閾値", "カットオフ未確立"),
]

# 推奨作成時に考慮する項目(2023年版 第1章9「作成手順」に明記)
RECOMMENDATION_CONSIDERATIONS = [
    "アウトカム全体にわたる総括的なエビデンスの確実性",
    "望ましい効果と望ましくない効果のバランス",
    "患者・市民の価値観と希望",
    "資源の利用（コスト）※特に高額が予想される場合のみ",
]

# CQごとの担当委員2名(2026/09収集の割り振り表より)。4-5評価の独立二重評価シートの
# 見出しに使う。ここに無いcq_idは "評価者1"/"評価者2" の汎用名で出力する
REVIEWERS_BY_CQ = {
    "CQ1-牛車腎気丸": ["元雄", "菊池"],
    "CQ1-プレガバリン": ["中島", "伊藤"],
    "CQ1-カルニチン-アセチル‒L‒カルニチン": ["内藤"],
    "CQ1-冷却・圧迫": ["川口", "上野"],
    "CQ1-運動": ["山本", "中川夏樹"],
    "CQ1-鍼灸": ["在原", "田辺"],
    "CQ2-デュロキセチン": ["神林", "武井"],
    "CQ2-アミトリプチリン": ["縄田", "平川"],
    "CQ2-プレガバリン": ["渡辺", "釆野"],
    "CQ2-ミロガバリン": ["渡辺", "釆野"],
    "CQ2-ビタミン-B12": ["坂下", "中川貴之"],
    "CQ2-非ステロイド性消炎鎮痛薬-NSAIDs": ["松岡宏", "松坂"],
    "CQ2-オピオイド": ["高木", "山田"],
    "CQ2-薬物の併用療法": ["宇和川", "佐藤"],
    "CQ2-運動": ["荒尾", "大岩"],
    "CQ2-鍼灸": ["神田", "京田", "草場", "久保"],
}

STRENGTH_TEXT = {
    "1": "1(強い推奨・実施)", "2": "2(弱い推奨・実施を提案)",
    "3": "3(推奨なし)", "4": "4(弱い推奨・非実施を提案)", "5": "5(強い推奨・非実施)",
}
CERT_TEXT = {"A": "A(強)", "B": "B(中)", "C": "C(弱)", "D": "D(非常に弱い)"}
DOWNGRADE_DOMAINS = ["risk_of_bias(バイアスリスク)", "inconsistency(非一貫性)",
                     "indirectness(非直接性)", "imprecision(不精確)",
                     "publication_bias(出版バイアス)"]
ROB2_DOMAINS = ["D1 ランダム化の過程", "D2 意図した介入からの逸脱",
                "D3 アウトカムデータの欠測", "D4 アウトカム測定",
                "D5 選択的な結果報告", "総合(Overall)"]



# 既存の海外ガイドライン(2020年)の立ち位置。改訂で「国際的に何が言われているか」を並べて見るための参考表。
# 記載は原文の要約であり、事務局が原文と照合して「確認」列を☑にするまでは参考扱い。
ASCO2020 = ("ASCO 2020", "Loprinzi CL, et al. J Clin Oncol 2020;38:3325-48. PMID 32663120 (Data Supplement 4, Table 4)")
ESMO2020 = ("ESMO-EONS-EANO 2020", "Jordan B, et al. Ann Oncol 2020;31:1306-19. PMID 32739407")
EXISTING_GL = {
    # (介入キーワード, CQ) : [(GL, 推奨要約, 強さ/エビデンス)]
    # ASCO 2020 の記載は Loprinzi 2020 の Data Supplement 4 (Table 4) に基づき確認済み。[ ]内は推奨番号
    ("牛車腎気丸", "CQ1"): [(ASCO2020, "予防目的で提供すべきでない(should not offer)リストに掲載 [1.4]", "種別: エビデンスに基づく(有益性なし) / エビデンス: 中 / 強さ: 中等度"),
                            (ESMO2020, "予防に有効性が示された薬剤はなく推奨しない(個別言及なし)", "要原文確認")],
    ("プレガバリン", "CQ1"): [(ASCO2020, "ガバペンチン/プレガバリンは予防目的で提供すべきでない(should not offer)リストに掲載 [1.4]", "種別: エビデンスに基づく(有益性なし) / エビデンス: 中 / 強さ: 中等度"),
                              (ESMO2020, "予防に推奨しない", "要原文確認")],
    ("カルニチン", "CQ1"): [(ASCO2020, "予防目的で提供すべきでなく、使用を控えるよう勧める(害が益を上回る) [1.2]", "種別: エビデンスに基づく / エビデンス: 高 / 強さ: 強い"),
                            (ESMO2020, "予防に推奨しない(害の報告)", "要原文確認")],
    ("冷却", "CQ1"): [(ASCO2020, "冷却療法(cryotherapy)は臨床試験以外では推奨を出せない(no recommendation)。有望だが大規模検証試験が必要と付記 [1.3]", "種別: 推奨なし / エビデンス: 低 / 強さ: 該当なし"),
                      (ESMO2020, "予防目的で検討してもよいとの記載(要原文確認)", "要原文確認")],
    ("圧迫", "CQ1"): [(ASCO2020, "圧迫療法(compression therapy)は臨床試験以外では推奨を出せない(no recommendation)。有望だが大規模検証試験が必要と付記 [1.3]", "種別: 推奨なし / エビデンス: 低 / 強さ: 該当なし"),
                      (ESMO2020, "予防目的で検討してもよいとの記載(要原文確認)", "要原文確認")],
    ("運動", "CQ1"): [(ASCO2020, "運動療法は臨床試験以外では推奨を出せない(no recommendation)。有望だが大規模検証試験が必要と付記 [1.3]", "種別: 推奨なし / エビデンス: 低 / 強さ: 該当なし"),
                      (ESMO2020, "運動療法(感覚運動トレーニング等)は症状軽減に考慮してよい(要原文確認)", "要原文確認")],
    ("鍼灸", "CQ1"): [(ASCO2020, "鍼治療は臨床試験以外では推奨を出せない(no recommendation)。有望だが大規模検証試験が必要と付記 [1.3]", "種別: 推奨なし / エビデンス: 低 / 強さ: 該当なし"),
                      (ESMO2020, "予防での言及なし/不十分(要原文確認)", "要原文確認")],
    ("デュロキセチン", "CQ2"): [(ASCO2020, "有痛性CIPNの患者に提供してもよい(may offer) [3.1]。治療中に発症した場合はまず減量・休薬・中止を検討 [2.1]", "種別: エビデンスに基づく(益=害) / エビデンス: 中 / 強さ: 中等度"),
                                (ESMO2020, "確立したCIPN疼痛治療として第一に挙げる薬剤", "II, B(要原文確認)")],
    ("アミトリプチリン", "CQ2"): [(ASCO2020, "三環系抗うつ薬は治療として臨床試験以外では推奨を出せない(no recommendation)。有望だが大規模検証試験が必要と付記 [3.2]", "種別: 推奨なし / エビデンス: 低 / 強さ: 該当なし"),
                                  (ESMO2020, "エビデンスは限られるが試みてもよい(要原文確認)", "要原文確認")],
    ("プレガバリン", "CQ2"): [(ASCO2020, "ガバペンチン/プレガバリンは治療として臨床試験以外では推奨を出せない(no recommendation)。有望だが大規模検証試験が必要と付記 [3.2]", "種別: 推奨なし / エビデンス: 低 / 強さ: 該当なし"),
                              (ESMO2020, "エビデンスは限られるが試みてもよい(要原文確認)", "要原文確認")],
    ("ミロガバリン", "CQ2"): [(ASCO2020, "言及なし", "—"), (ESMO2020, "言及なし", "—")],
    ("B12", "CQ2"): [(ASCO2020, "治療での言及なし(ビタミンBは予防で「提供すべきでない」[1.4])", "—"), (ESMO2020, "言及なし(要原文確認)", "—")],
    ("NSAIDs", "CQ2"): [(ASCO2020, "言及なし", "—"), (ESMO2020, "言及なし(要原文確認)", "—")],
    ("オピオイド", "CQ2"): [(ASCO2020, "言及なし", "—"), (ESMO2020, "重度の神経障害性疼痛で一般原則に沿って考慮(要原文確認)", "要原文確認")],
    ("併用療法", "CQ2"): [(ASCO2020, "言及なし(外用ゲル[バクロフェン+アミトリプチリン±ケタミン]は推奨なし [3.2])", "—"), (ESMO2020, "言及なし(要原文確認)", "—")],
    ("運動", "CQ2"): [(ASCO2020, "運動療法は治療として臨床試験以外では推奨を出せない(no recommendation)。有望だが大規模検証試験が必要と付記 [3.2]", "種別: 推奨なし / エビデンス: 低 / 強さ: 該当なし"),
                      (ESMO2020, "運動療法は症状軽減に考慮してよい(要原文確認)", "要原文確認")],
    ("鍼灸", "CQ2"): [(ASCO2020, "鍼治療は治療として臨床試験以外では推奨を出せない(no recommendation)。有望だが大規模検証試験が必要と付記 [3.2]", "種別: 推奨なし / エビデンス: 低 / 強さ: 該当なし"),
                      (ESMO2020, "考慮してもよいとの記載(要原文確認)", "要原文確認")],
}


def existing_guidelines_for(item):
    """介入名(統合CQは「冷却・圧迫」など)とCQ種別から既存GLの行を集める"""
    cq = item["_source"]["cq"]
    names = item["_source"].get("merged_from") or [item["cq_id"]]
    rows = []
    for (kw, c), entries in EXISTING_GL.items():
        if c != cq:
            continue
        if any(kw in n for n in names) or kw in item["_source"]["intervention"]:
            for (gl, src), rec, grade in entries:
                rows.append({"intervention": kw, "guideline": gl, "recommendation": rec,
                             "grade": grade, "source": src,
                             "checked": "☑(補足資料Table4で確認)" if gl == ASCO2020[0] else "☐"})
    return rows


def sheet_existing_gl(wb, item):
    ws = wb.create_sheet("既存GL比較")
    header_row(ws, 1, ["介入", "ガイドライン", "推奨(要約)", "強さ/エビデンス", "出典", "事務局確認(☐/☑)"],
               widths=[14, 22, 60, 26, 48, 14])
    rows = existing_guidelines_for(item)
    for r in rows:
        ws.append([r["intervention"], r["guideline"], r["recommendation"], r["grade"], r["source"], r["checked"]])
    ws.append(["※", "2020年の海外GLの記載を要約した参考表。原文と照合し「確認」を☑にしてください。"
               "修正はこのシートに直接行うと草案作成シートに反映されます", "", "", "", ""])
    ws.cell(row=ws.max_row, column=2).fill = NOTE_FILL
    for r in ws.iter_rows(min_row=2):
        for c in r:
            c.alignment = WRAP
    item["existing_guidelines"] = rows


def short_cite(citation: str) -> str:
    """"1）Loprinzi CL, Lacchetti C, ... J Clin Oncol. 2020； 38： 3325—48.［PMID： x］"
    → "Loprinzi et al. 2020"。単著なら "Kuriyama 2018"。
    和文 "石川雄大，高木昭佳，他．…2021；" → "石川雄大 et al. 2021" """
    c = re.sub(r"^\s*\d+[）)]\s*", "", citation or "")
    m = re.match(r"\s*([A-Z][A-Za-z\-']+)", c)
    if m:
        author = m.group(1)
    else:
        m2 = re.match(r"\s*([^\s，,．.]+)", c)
        author = m2.group(1) if m2 else "?"
    # 著者ブロック(最初のピリオド/「．」まで)に区切りが2つ以上 or "et al"/"他" があれば複数著者
    head = re.split(r"[.．]\s", c, 1)[0]
    n_sep = len(re.findall(r"[，,]", head))
    y = re.search(r"((?:19|20)\d{2})\s*[；;：:]", c) or re.search(r"((?:19|20)\d{2})", c)
    year = y.group(1) if y else ""
    if ("et al" in head) or ("他" in head) or n_sep >= 2:
        return f"{author} et al. {year}".strip()
    if n_sep == 1:  # 2著者: "Kuriyama and Endo 2018"
        second = re.split(r"[，,]\s*", head, 1)[1]
        m3 = re.match(r"\s*([A-Z][A-Za-z\-']+|[^\s，,．.]+)", second)
        if m3:
            return f"{author} and {m3.group(1)} {year}".strip()
    return f"{author} {year}".strip()


def header_row(ws, row, headers, widths=None):
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=i, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = WRAP
        if widths:
            ws.column_dimensions[get_column_letter(i)].width = widths[i - 1]
    # ws.cell()でセルに触れるとappend()の開始行がずれる(空行混入の原因になる)ため
    # 文字列座標を組み立てるだけにする
    ws.freeze_panes = f"A{row + 1}"


def sheet_search(wb, item):
    ws = wb.active
    ws.title = "検索式"
    terms, warn = MERGED_SEARCH_TERMS.get(
        item["cq_id"], SEARCH_TERM_MAP.get(item["cq_id"], ([], "対応表未登録。要確認")))
    ws.append(["項目", "内容"])
    for i in range(1, 3):
        ws.cell(row=1, column=i).fill = HEADER_FILL
        ws.cell(row=1, column=i).font = HEADER_FONT
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 100
    rows = [
        ("DB", SEARCH_DB),
        ("検索期間", SEARCH_PERIOD),
        ("検索実施日(委員記入)", ""),
        ("検索実施者(委員記入)", ""),
        ("P節(対象)", SEARCH_P),
        ("C節(病態)", SEARCH_C),
        ("I節(介入・全CQ共通の検索式全文)", SEARCH_I_FULL),
        ("本CQのI節(介入語)", " OR ".join(terms) if terms else "(なし)"),
        ("本CQの完成検索式", f"{SEARCH_P} AND {SEARCH_C} AND ({' OR '.join(terms)})"
                          if terms else "(I節が未定のため未生成)"),
        ("ヒット件数(委員記入)", ""),
        ("重複除去後件数(委員記入)", ""),
    ]
    for label, val in rows:
        ws.append([label, val])
    for r in ws.iter_rows(min_row=2):
        r[1].alignment = WRAP
    if warn:
        ws.append(["⚠要確認", warn])
        ws.cell(row=ws.max_row, column=1).fill = WARN_FILL
        ws.cell(row=ws.max_row, column=2).fill = WARN_FILL
        ws.cell(row=ws.max_row, column=2).alignment = WRAP


def sheet_screening(wb, item):
    ws = wb.create_sheet("スクリーニングログ")
    headers = ["PMID", "タイトル", "出典(検索/ハンドサーチ)",
               "一次スクリーニング(採用/除外/保留)", "一次除外理由",
               "二次スクリーニング(採用/除外)", "二次除外理由", "備考"]
    header_row(ws, 1, headers, widths=[12, 40, 16, 22, 26, 22, 26, 26])
    r = 2
    for ref in item["references"]:
        ws.cell(row=r, column=1, value=ref["pmid"] or "")
        ws.cell(row=r, column=2, value=f"{short_cite(ref['citation'])}: " + ref["citation"][:110])
        ws.cell(row=r, column=2).alignment = WRAP
        ws.cell(row=r, column=3, value="2023年版で採用済み")
        ws.cell(row=r, column=4, value="採用")
        ws.cell(row=r, column=6, value="採用")
        r += 1
    ws.append(["", "", "", "", "", "", "",
               "(新規文献はここに1行ずつ追記。除外した文献も理由とともに必ず残す = PRISMAフロー用)"])
    note_row = ws.max_row
    ws.cell(row=note_row, column=8).fill = NOTE_FILL
    ws.cell(row=note_row, column=8).alignment = WRAP
    ws.append(["", "", "", "", "", "", "", ""])
    ws.append(["── 除外理由コードの例 ──", "PICO不一致 / 対象外デザイン(RCT以外等) / "
               "重複掲載 / 全文入手不可 / 会議抄録のみ / その他(備考に記載)", "", "", "", "", "", ""])
    ws.cell(row=ws.max_row, column=1).fill = NOTE_FILL
    ws.cell(row=ws.max_row, column=2).fill = NOTE_FILL
    ws.cell(row=ws.max_row, column=2).alignment = WRAP


def sheet_pico(wb, item):
    ws = wb.create_sheet("CQ・PICO")
    d = item["draft"]
    rows = [
        ("cq_id", item["cq_id"]),
        ("CQ(分類)", item["_source"]["category"]),
        ("介入/薬剤", item["_source"]["intervention"]),
        ("P(対象)", item["pico"]["P"] or "(委員会で確定)"),
        ("I(介入)", item["pico"]["I"]),
        ("C(対照)", item["pico"]["C"] or "(委員会で確定 comparator_kind参照)"),
        ("comparator_kind", item["comparator_kind"]),
        ("O(アウトカム)", "; ".join(item["pico"]["O"]) or "(下の「SR-8_エビデンス総体」シートで設定)"),
        ("層別の方針(化学療法の種類)",
         "CIPNは化学療法の種類(白金製剤/タキサン系/ビンカアルカロイド系/プロテアソーム阻害薬 等)で病態・経過・介入の効果が異なる。"
         "①「研究特性」シートに各研究の化学療法の分類を記録する。②4-5評価シートの『非直接性 対象』で、本CQの対象との一致を評価する。"
         "③効果や異質性が薬剤クラスで異なる場合は、SR-8の層別行(白金製剤/タキサン系)で別々にエビデンス総体を作り、必要なら推奨文の対象を"
         "限定する(2023年版: 牛車腎気丸は『白金製剤由来に限る』)。層別しない場合は、その理由を作成経過に記録する。"),
        ("問いの種類", "FRQ（今後の研究課題）" if item.get("question_type") == "FRQ" else "CQ（推奨を作成）"),
        ("", ""),
    ]
    for k, dd in enumerate(item.get("drafts_2023") or [d], start=1):
        tag = f"（{dd.get('_intervention')}）" if dd.get("_intervention") else ""
        pv = dd.get("panel_vote") or {}
        rows += [
            (f"── 2023年版の推奨{tag} ──", ""),
            ("推奨文(原文)", dd["recommendation_text"]),
            ("推奨の強さ", STRENGTH_TEXT.get(dd.get("strength"), dd.get("strength_label"))),
            ("エビデンスの確実性", CERT_TEXT.get(dd.get("certainty"), dd.get("certainty_label"))),
            ("委員会合意率", (f"{round((pv.get('agreement_rate') or 0)*100)}% "
                           f"({pv.get('agreement_n')}/{pv.get('agreement_total')}名)")
                           if pv.get("agreement_rate") is not None else ""),
            ("引用PMID数(2023年版)", len(dd.get("cited_pmids") or [])),
        ]
    ws.append(["項目", "内容"])
    for i in range(1, 3):
        ws.cell(row=1, column=i).fill = HEADER_FILL
        ws.cell(row=1, column=i).font = HEADER_FONT
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 90
    for label, val in rows:
        ws.append([label, val])
    for r in ws.iter_rows(min_row=2):
        r[1].alignment = WRAP
        if r[0].value and str(r[0].value).startswith("──"):
            r[0].fill = NOTE_FILL
            r[1].fill = NOTE_FILL


def sheet_instruments(wb, item):
    ws = wb.create_sheet("評価指標")
    header_row(ws, 1, ["分類", "名称", "略称/版", "何を測るか", "備考",
                       "本CQの採用研究で使用(委員/自動記入)"], widths=[14, 40, 24, 40, 36, 24])
    for row in INSTRUMENTS:
        ws.append(list(row) + [""])
    ws.append(["※", "2023年版 第2章H「CIPNの評価」に基づく一覧。各研究がどの指標でアウトカムを測ったかは"
               "4-5評価シートの「評価指標(使用尺度)」列(AC列)に記録する", "", "", "", ""])
    ws.cell(row=ws.max_row, column=2).fill = NOTE_FILL
    for r in ws.iter_rows(min_row=2):
        for c in r:
            c.alignment = WRAP


def _study_list(item):
    """(キー, 研究コード「第一著者 et al. 年」, デザイン) の一覧。PMIDが無い和文誌等は NOPMID:<no>"""
    out = []
    for ref in item["references"]:
        key = ref["pmid"] or f"NOPMID:{ref['no']}"
        out.append((str(key), short_cite(ref["citation"]), ""))
    return out


def _outcome_list(item):
    return [{"id": oc["id"], "label": oc["label"], "importance": oc.get("importance")} for oc in (item.get("outcomes") or [])]


CHEMO_STRATA = ["白金製剤", "タキサン系"]


def sheet_study_chars(wb, item):
    """研究特性(Minds 4-5の『非直接性 対象』を判断するための表)。CIPNは化学療法の種類で病態・経過・
    介入効果が大きく異なるため、化学療法の分類を必ず記録する(Claudeが本文から推定→委員が確定)"""
    ws = wb.create_sheet("研究特性")
    headers = ["キー(PMID)", "研究コード", "デザイン", "国", "全症例数", "介入群症例数", "化学療法の分類(確定は委員)",
               "具体的な薬剤", "がん種", "介入の内容(用量・期間)", "対照の内容", "追跡期間・評価時点", "本文の入手", "備考"]
    header_row(ws, 1, headers, widths=[14, 22, 10, 8, 10, 10, 20, 24, 14, 34, 24, 18, 12, 30])
    for key, label, design in _study_list(item):
        ws.append([key, label, design])
    ws.append([""] * 13 + ["(新規論文は fill_rob2_from_papers.py が自動で行を追加します)"])
    last = ws.max_row
    dv = DataValidation(type="list", formula1='"' + ",".join(CHEMO_CLASSES) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"G2:G{last + 40}")
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = WRAP
    return ws


def sheet_45_set(wb, item):
    """個別研究の評価(Minds 4.3、様式 4-5 評価シート 介入研究)。評価者2名が互いを見ずに独立に記入する。
    Claude下書きは参考用で、2名の独立評価の代わりにはならない。"""
    reviewers = REVIEWERS_BY_CQ.get(item["cq_id"], ["評価者1", "評価者2"])
    r1 = reviewers[0] if len(reviewers) > 0 else "評価者1"
    r2 = reviewers[1] if len(reviewers) > 1 else "評価者2(未割当)"
    pico, outs, studies = item.get("pico", {}), _outcome_list(item), _study_list(item)
    title = item.get("title", item["cq_id"])
    for name in ("4-5_Claude下書き", f"4-5_{r1}", f"4-5_{r2}"):
        build_45_sheet(wb, name, title, pico, outs, studies)
    return r1, r2, outs, len(studies) + SPARE_ROWS


def sheet_45_recon(wb, item, r1, r2, outs, n_rows):
    """2名の評価を項目ごとに自動照合し、不一致を検出する(独立二重評価→照合→協議、Minds/コクラン標準)。
    値はすべて評価者シートを参照する数式。確定列だけ委員が記入する"""
    ws = wb.create_sheet("4-5_照合")
    header_row(ws, 1, ["アウトカム", "研究", "項目", f"評価者1({r1})", f"評価者2({r2})", "判定",
                       "確定(委員記入・不一致時は協議のうえ決定)"], widths=[22, 26, 24, 14, 14, 10, 30])
    s1, s2 = f"'4-5_{r1}'", f"'4-5_{r2}'"
    row = 2
    for b, oc in enumerate(outs):
        for j in range(n_rows):
            src = block_start(b, n_rows) + HEAD_ROWS + j
            for k, (iname, _) in enumerate(ITEMS):
                col = get_column_letter(C_ITEM0 + k)
                ws.cell(row=row, column=1, value=oc["label"])
                ws.cell(row=row, column=2, value=f'=IF({s1}!A{src}="","",{s1}!A{src})')
                ws.cell(row=row, column=3, value=iname)
                ws.cell(row=row, column=4, value=f'=IF({s1}!{col}{src}="","",{s1}!{col}{src})')
                ws.cell(row=row, column=5, value=f'=IF({s2}!{col}{src}="","",{s2}!{col}{src})')
                ws.cell(row=row, column=6, value=(
                    f'=IF(AND({s1}!{col}{src}="",{s2}!{col}{src}=""),"",'
                    f'IF({s1}!{col}{src}={s2}!{col}{src},"一致","不一致"))'))
                row += 1
    last = row - 1
    if last >= 2:
        ws.conditional_formatting.add(f"F2:F{last}", CellIsRule(operator="equal", formula=['"不一致"'], fill=MISMATCH_FILL))
    ws.freeze_panes = "A2"
    return ws


def sheet_sr8(wb, item):
    """エビデンス総体の評価(Minds 4.4、様式 SR-8)。アウトカムごとの確実性(A〜D)。
    CIPNは化学療法の種類で効果が異なりうるので、層別の行(任意)も置く"""
    strata = CHEMO_STRATA if item["_source"]["cq"] in ("CQ1", "CQ2") else None
    return build_sr8_sheet(wb, "SR-8_エビデンス総体", item.get("title", item["cq_id"]), item.get("pico", {}), _outcome_list(item),
                           strata=strata)


def sheet_rob2_ref(wb, item):
    """RoB 2(Cochrane RoB 2.0)は参考欄。公式様式(4-5)を主とし、補助として Claude が本文から下書きする。
    独立二重評価・照合の対象にはしない"""
    ws = wb.create_sheet("RoB2(参考)")
    header_row(ws, 1, ["キー(PMID)", "研究", "D1 ランダム化の過程", "D2 意図した介入からの逸脱", "D3 アウトカムデータの欠測",
                       "D4 アウトカム測定", "D5 選択的な結果報告", "総合", "根拠(Claude下書き)"],
               widths=[14, 24, 16, 16, 16, 14, 16, 10, 60])
    for key, label, _ in _study_list(item):
        ws.append([key, label])
    ws.append(["", "(参考欄。公式様式の評価は 4-5 シート。RoB2 は Some concerns / Low / High の記載でよい)"])
    return ws


def sheet_references(wb, item):
    ws = wb.create_sheet("文献リスト")
    header_row(ws, 1, ["No", "PMID", "citation(著者・誌名・年)", "papers/収集状況"],
               widths=[6, 12, 100, 16])
    for ref in item["references"]:
        ws.append([ref["no"], ref["pmid"] or "(PMIDなし・和文誌等)", ref["citation"], "未収集"])
    for row in ws.iter_rows(min_row=2):
        row[2].alignment = WRAP


def sheet_draft(wb, item):
    """Minds推奨文草案(CQ) または FRQ記載草案(FRQ)。委員が書く欄。
    2023年版の推奨文を初期値として置き、考慮項目(第1章9)ごとの記入欄を付ける"""
    d = item["draft"]
    if item.get("question_type") == "FRQ":
        ws = wb.create_sheet("FRQ記載草案")
        header_row(ws, 1, ["項目", "記入欄"], widths=[30, 100])
        rows = [
            ("2023年版の記載(参考)", d.get("recommendation_text", "")),
            ("背景・臨床上の重要性", ""),
            ("現時点のエビデンスの状況(SRの結果)", ""),
            ("推奨を出せない理由", ""),
            ("今後必要な研究(デザイン・対象・アウトカム)", ""),
            ("備考", ""),
        ]
        for r in rows:
            ws.append(list(r))
        ws.append(["※", "Minds 2020のFRQの項に沿って記載。推奨文・推奨の強さは付けない(要: 手引き最終確認)"])
        ws.cell(row=ws.max_row, column=2).fill = NOTE_FILL
    else:
        ws = wb.create_sheet("推奨文草案")
        header_row(ws, 1, ["項目", "記入欄"], widths=[34, 100])
        ws.append(["推奨文（草案）", d.get("recommendation_text", "")])
        ws.append(["推奨の強さ（1〜5）", d.get("strength", "")])
        ws.append(["エビデンスの確実性（A〜D）", d.get("certainty", "")])
        for c in RECOMMENDATION_CONSIDERATIONS:
            ws.append([c, ""])
        ws.append(["解説（草案）", item.get("narrative", "")])
        ws.append(["2023年版からの変更点と理由", ""])
        ws.append(["※", "初期値は2023年版。推奨の強さは1:強く実施 2:実施を提案 3:推奨なし "
                        "4:非実施を提案 5:強く非実施。投票は委員会会議で行う(80%以上で決定)"])
        ws.cell(row=ws.max_row, column=2).fill = NOTE_FILL
    for r in ws.iter_rows(min_row=2):
        r[1].alignment = WRAP


def sheet_vote(wb, item):
    ws = wb.create_sheet("投票")
    d = item["draft"]
    v = d.get("panel_vote", {})
    header_row(ws, 1, ["項目", "2023年版(参考)", "改訂版(今回)"], widths=[24, 30, 30])
    rows = [
        ("推奨の強さ", STRENGTH_TEXT.get(d["strength"], ""), ""),
        ("エビデンスの確実性", CERT_TEXT.get(d["certainty"], ""), ""),
        ("委員会人数", v.get("n_panel", ""), ""),
        ("合意人数/母数", f"{v.get('agreement_n','')}/{v.get('agreement_total','')}", ""),
        ("合意率", f"{round((v.get('agreement_rate') or 0)*100)}%" if v.get("agreement_rate") is not None else "", ""),
        ("棄権(利益相反)", "", ""),
        ("棄権(SR従事)", "", ""),
    ]
    for row in rows:
        ws.append(list(row))
    ws.column_dimensions["C"].fill = NOTE_FILL


def build_workbook(item):
    wb = Workbook()
    sheet_search(wb, item)          # active/1枚目
    sheet_pico(wb, item)
    sheet_instruments(wb, item)
    sheet_existing_gl(wb, item)
    sheet_screening(wb, item)
    sheet_study_chars(wb, item)
    r1, r2, outs, n_rows = sheet_45_set(wb, item)
    sheet_45_recon(wb, item, r1, r2, outs, n_rows)
    sheet_sr8(wb, item)
    sheet_rob2_ref(wb, item)
    sheet_references(wb, item)
    sheet_draft(wb, item)
    return wb


def write_manifest(item, path):
    d = item["draft"]
    lines = [
        f"# 文献マニフェスト: {item['cq_id']}",
        "",
        f"介入/薬剤: **{item['_source']['intervention']}**"
        f"（{item['_source']['category']}, {item['_source']['cq']}）",
        "",
        "> 論文PDF本体は著作権のため自動収集していません。"
        "下記チェックリストを見ながら、入手できたPDFを `papers/` フォルダに置いてください。"
        "ファイル名は `PMID.pdf`（例: `23549581.pdf`）を推奨します。",
        "",
        "## 2023年版で引用されている文献",
        "",
        "| # | PMID | 収集 | 文献 |",
        "|---|---|---|---|",
    ]
    for ref in item["references"]:
        pmid = ref["pmid"] or "-"
        link = f"[{pmid}](https://pubmed.ncbi.nlm.nih.gov/{pmid}/)" if ref["pmid"] else pmid
        lines.append(f"| {ref['no']} | {link} | ☐ | {ref['citation']} |")
    lines += [
        "",
        "## 新規追加文献(改訂で追加するもの)",
        "",
        "| # | PMID | 収集 | 文献 |",
        "|---|---|---|---|",
        "|  |  | ☐ |  |",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def apply_merges_and_types(items):
    """CQ_MERGES に従って複数CQを1つにまとめ、FRQ種別と2023年版アウトカムを付与する"""
    out = {}
    consumed = set()
    for new_id, parts in CQ_MERGES.items():
        srcs = [items[p] for p in parts if p in items]
        if not srcs:
            continue
        base = json.loads(json.dumps(srcs[0]))
        base["cq_id"] = new_id
        names = "・".join(x["_source"]["intervention"] for x in srcs)
        base["_source"]["intervention"] = names
        base["_source"]["merged_from"] = parts
        base["title"] = f"{base['_source']['cq']} {base['_source']['category']}: {names}"
        base["pico"]["I"] = names
        # 2023年版の推奨は介入ごとに残す
        base["drafts_2023"] = []
        for x in srcs:
            dd = json.loads(json.dumps(x["draft"]))
            dd["_intervention"] = x["_source"]["intervention"]
            base["drafts_2023"].append(dd)
        base["draft"]["recommendation_text"] = " ／ ".join(
            f"【{x['_source']['intervention']}】{x['draft']['recommendation_text']}" for x in srcs)
        base["draft"]["cited_pmids"] = sorted({p for x in srcs for p in x["draft"].get("cited_pmids", [])})
        # 文献は PMID で重複除去(冷却と圧迫はASCO GL等を共有している)
        seen, refs = set(), []
        for x in srcs:
            for r in x.get("references", []):
                key = r.get("pmid") or r.get("citation")
                if key in seen:
                    continue
                seen.add(key)
                rr = dict(r); rr["_from"] = x["_source"]["intervention"]
                refs.append(rr)
        for i, r in enumerate(refs, start=1):
            r["no"] = i
            # 表題先頭の旧番号("3）")を統合後の番号に振り直す(画面の並び順にも使う)
            r["citation"] = re.sub(r"^\s*\d+[）)]\s*", f"{i}）", r.get("citation") or "")
        base["references"] = refs
        base["narrative"] = "\n\n".join(
            f"【{x['_source']['intervention']}】\n{x.get('narrative','')}" for x in srcs)
        out[new_id] = base
        consumed.update(parts)
    for cid, it in items.items():
        if cid not in consumed:
            out[cid] = it
    for cid, it in out.items():
        it["question_type"] = "FRQ" if cid in FRQ_CQS else "CQ"
        if not it.get("outcomes"):
            it["outcomes"] = json.loads(json.dumps(OUTCOMES_BY_CQ_TYPE[it["_source"]["cq"]]))
            it["pico"]["O"] = [o["label"] for o in it["outcomes"]]
    return out


def main():
    ap = argparse.ArgumentParser(description="CQパッケージ群 → 委員会レビュー作業一式")
    ap.add_argument("cq_dir", help="extract_cipn_guideline.py の出力先(CQ*.jsonがあるディレクトリ)")
    ap.add_argument("-o", "--outdir", required=True)
    ap.add_argument("--force", action="store_true",
                    help="既にある minds_review.xlsx も作り直す(委員の記入が消えるので注意)")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.cq_dir, "CQ*.json")))
    files = [f for f in files if not os.path.basename(f).startswith("_")]
    os.makedirs(args.outdir, exist_ok=True)

    items = {}
    for fp in files:
        it = json.load(open(fp, encoding="utf-8"))
        items[it["cq_id"]] = it
    items = apply_merges_and_types(items)

    for item in items.values():
        cq_dir = os.path.join(args.outdir, item["cq_id"])
        os.makedirs(os.path.join(cq_dir, "papers"), exist_ok=True)

        xlsx = os.path.join(cq_dir, "minds_review.xlsx")
        if os.path.exists(xlsx) and not args.force:
            print(f"{item['cq_id']:<28} 既存の minds_review.xlsx を保持(作り直すなら --force)")
        else:
            build_workbook(item).save(xlsx)
            write_manifest(item, os.path.join(cq_dir, "MANIFEST.md"))
        with open(os.path.join(cq_dir, "papers", ".gitkeep"), "w") as f:
            pass
        # 元のCQパッケージ自体もコピーしておく(後でmerge_rob2_evidence.pyが使う)
        with open(os.path.join(cq_dir, "cq_package.json"), "w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)

        print(f"{item['cq_id']:<28} {'FRQ ' if item.get('question_type')=='FRQ' else '    '}→ {cq_dir}/")

    print(f"\n{len(items)}件のCQ作業一式を {args.outdir}/ に作成しました")


if __name__ == "__main__":
    main()
