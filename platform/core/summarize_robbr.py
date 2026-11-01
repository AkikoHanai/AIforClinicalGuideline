"""AIによる様式4-5判定の検証結果(学生の実験 RoBBR_result.xlsx)を要約し、項目別の一致度(κ)を保存する。
  python3 platform/core/summarize_robbr.py platform/review/validation/RoBBR_result_2026-10-28.xlsx
出力: platform/review/validation/AI様式4-5の検証結果.md、ai_item_reliability.json(minds_forms.py が読み、Claude下書きに一致度を併記する)
xlsx は検証のデータであり、判定の基準ではない。基準は Minds 2020 と統括委員長の決定。"""
import json, os, sys
import openpyxl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "review", "validation")
# 学生の項目名 → 様式4-5(minds_forms.ITEMS)の項目名
MAP = {"選択バイアス: ランダム系列の生成（ランダム化・ベースライン均衡）": "ランダム化", "選択バイアス: 割り付けの隠蔽（コンシールメント）": "コンシールメント",
       "実行バイアス: 参加者と医療提供者の盲検化": "盲検化(参加者・医療提供者)", "検出バイアス: アウトカム測定者の盲検化": "盲検化(アウトカム評価者)",
       "症例減少バイアス: ITT（治療企図分析）": "ITT", "症例減少バイアス: アウトカム不完全報告（不完全アウトカムデータ）": "アウトカム不完全報告",
       "その他のバイアス: 選択的アウトカム報告": "選択的アウトカム報告", "その他のバイアス: 早期試験中止": "早期試験中止",
       "その他のバイアス: その他のバイアス（COI・交絡・単施設等）": "その他のバイアス", "バイアスリスク まとめ": "バイアスリスク まとめ",
       "非直接性: 対象集団（P）": "非直接性 対象", "非直接性: 介入（I）": "非直接性 介入", "非直接性: 対照（C）": "非直接性 対照",
       "非直接性: アウトカム（O）": "非直接性 アウトカム", "非直接性 まとめ": "非直接性 まとめ"}
MULTI = ["16_pdf_endurance", "11_minds2017_v8_endurance"]  # 複数研究(20研究)の実験。PDF全文の16を優先し、ない項目は11で補う


def kappa_label(k):
    if k is None: return "算出不能"
    if k < 0: return "偶然以下"
    if k < 0.21: return "わずか"
    if k < 0.41: return "やや"
    if k < 0.61: return "中等度"
    if k < 0.81: return "かなり"
    return "ほぼ完全"


def main(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    exps = [r for r in wb["実験一覧"].iter_rows(values_only=True)][1:]
    items = [r for r in wb["項目別"].iter_rows(values_only=True)][1:]
    rel = {}
    for ex in MULTI:
        for r in items:
            if r[0] != ex or r[2] not in MAP or MAP[r[2]] in rel: continue
            k = r[5] if isinstance(r[5], (int, float)) else None
            rel[MAP[r[2]]] = {"kappa": k, "accuracy": r[4], "n": r[3], "label": kappa_label(k), "experiment": ex}
    os.makedirs(OUT, exist_ok=True)
    json.dump({"source": os.path.basename(path), "updated": str(wb["はじめに"]["A2"].value), "note": "20研究・1アウトカムの検証(他領域のRCT)。CIPNの論文での検証は未実施", "items": rel},
              open(os.path.join(OUT, "ai_item_reliability.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    L = ["# AIによる様式4-5判定の検証結果(要約)", "", f"出典: {os.path.basename(path)}(学生の実験。{wb['はじめに']['A2'].value})。判定は Minds の 0 / -1 / -2。正解は人の評価シート。", "",
         "## 実験ごとの成績", "", "| 実験 | 条件 | 対象 | 判定数 | 一致率 | κ | 解釈 |", "|---|---|---|---|---|---|---|"]
    for r in exps:
        if r[0]: L.append(f"| {r[0]} | {r[1]} | {r[3] or '—'} | {r[4]} | {r[5]} | {r[6]} | {r[9]} |")
    L += ["", "## 項目別の一致度(20研究の実験。Claude下書きに併記する値)", "", "| 様式4-5の項目 | κ | 一致率 | 判定数 | 解釈 | 実験 |", "|---|---|---|---|---|---|"]
    for name in ["ランダム化", "コンシールメント", "盲検化(参加者・医療提供者)", "盲検化(アウトカム評価者)", "ITT", "アウトカム不完全報告", "選択的アウトカム報告", "早期試験中止", "その他のバイアス", "バイアスリスク まとめ",
                 "非直接性 対象", "非直接性 介入", "非直接性 対照", "非直接性 アウトカム", "非直接性 まとめ"]:
        v = rel.get(name)
        L.append(f"| {name} | {v['kappa'] if v else '—'} | {v['accuracy'] if v else '—'} | {v['n'] if v else '—'} | {v['label'] if v else '未検証'} | {v['experiment'] if v else '—'} |")
    L += ["", "## 読み取れること", "",
          "1. 1研究(Goodwin 2020、15判定)では、Minds 2017 の手順書を改定した版(D3b・D5・D7)と PDF 全文で 15/15 が一致した。1研究の結果であり、動作確認の位置づけである。",
          "2. 20研究(持久性体力)では、一致率 0.48〜0.53、κ 0.15〜0.21 であり、人の判定の代わりにはならない。情報不足のときに -1 と判定しやすい。",
          "3. 項目別では、ランダム化(κ 0.65)は一致が高く、盲検化(アウトカム評価者)、選択的アウトカム報告、早期試験中止、その他のバイアスは偶然程度である。",
          "4. 抄録のみの入力(n=240)は、全文(n=60)より一致率が低い(0.47 対 0.53)。",
          "5. 本文を文字で渡す場合と PDF を渡す場合の差は小さい(1研究)。",
          "", "## この結果から定めた扱い(統括委員長の決定 2026-11-01)", "",
          "- 様式4-5 の判定は、2名の委員が独立に行う(Minds)。Claude下書きは、本文の該当箇所を探す補助に限り、委員のシートには転記しない。",
          "- Claude下書きは、本文(PDF または全文)があるときだけ作る。抄録のみの論文では、研究特性だけを抽出し、15項目の判定は空欄にする。",
          "- Claude下書きの各項目に、この検証の κ と解釈を併記する。κ が 0.21 未満の項目は「一致は偶然程度」と表示する。",
          "- CIPN の論文での検証(2023年版の採用論文を正解とする)を、SRチームの作業が始まる前に行う。", ""]
    open(os.path.join(OUT, "AI様式4-5の検証結果.md"), "w", encoding="utf-8").write("\n".join(L))
    print(f"項目 {len(rel)} 件の一致度を保存 → {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
