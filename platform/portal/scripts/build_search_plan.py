"""検索計画(platform/data/search_plan.json)を作る。
  python3 platform/portal/scripts/build_search_plan.py
統括委員長の決定(2026-11-20): 検索期間は 2026年10月1日まで。検索式は前回(2023年版)の式。
前回の式は、2023年版の検索過程の記録(platform/prior_worksheets)から写す。記録に式が残っていない検索は「未確認」とし、
統括委員会(または SR担当)が式を確認するまで、文献の取得と登録を行わない(件数の確認だけを行う)。"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
END = "2026/10/01"
P = '((survivor OR (survivor AND cancer) OR "cancer survivor" OR cancer))'
C = ('((neuropathy OR "neuropathy" OR "neuropathies" OR chemotherapy-induced OR "chemotherapy-induced neuropathy" OR "chemotherapy-induced peripheral neuropathy" OR CIPN '
     'OR peripheral nervous system/drug effects OR peripheral nerve diseases/chemically induced OR antineoplastic agents/adverse effects OR neoplasms/drug therapy OR neoplasms/complications))')
asco = lambda term: f"{P} AND {C} AND {term}"
A = "ASCO の式(P・C)+介入語"; T = "手引き2017 の式"
GL = "2023年版 第1章5「文献検索」と CQ の解説の記載(検索期間 2021年6月)"
NSAIDS = ('Cancer peripheral (neuropathy OR neurotoxi*) ("non steroidal anti inflammatory drugs" OR NSAIDs OR Aspirin OR Acemetacin OR Ampiroxicam OR Ibuprofen OR Indometacin OR Ethenzamide OR Etodolac '
          'OR Oxaprozin OR Zaltoprofen OR Diclofenac OR Sulindac OR Celecoxib OR Tiaprofenic acid OR Nabumetone OR Naproxen OR Piroxicam OR Pranoprofen OR Flufenamic acid OR Mefenamic acid OR Meloxicam '
          'OR Loxoprofen OR Lornoxicam OR Ketoprofen OR Sodium salicylate) (effect OR management OR treat* OR therapy) NOT diabet*')

# (id, CQ, フォルダ, 式, 式の種類, 式の出典, 確認済みか, 前回の終了, 開始日, 開始日の根拠, 注意)
S = [
 ("P1-1", "P1", "CQ1-牛車腎気丸", "goshajinkigan (neuropathy OR neurotoxi*) (prevent* OR management* OR effect*)", T, "2023年版の委員ワークシート(PubMed 2020〜2021.6、53件)", True, "2021-06", "2021/07/01", "前回の検索の終了月(2021年6月)の翌月", []),
 ("P2-1", "P2", "CQ1-プレガバリン", asco("Pregabalin"), A, "検索過程 プレガバリン・ミロガバリン.docx(治療の CQ と同じ文書。予防の CQ だけの記録はない)", True, "2021-08-12", "2021/08/13", "前回の検索の終了日(2021年8月12日)の翌日", []),
 ("P2-2", "P2", "CQ1-プレガバリン", asco("Mirogabalin"), "案(予防にミロガバリンを加える)", "統括委員長の決定(2026-11-27): 予防のガバペンチノイドに、ミロガバリンを加える。2023年版の予防の CQ はプレガバリンだけで、ミロガバリンの予防の検索の記録はない。介入語は、治療の検索(T3-2)と同じ語", False, "", "2021/08/13", "案: プレガバリン(P2-1)と同じ開始日。期間を置かない場合も、件数は同じ(PubMed コネクタ 2026-11-27: どちらも 21 件)", ["介入語(Mirogabalin)と開始日を、統括委員長が確認する。確認まで、検索を実行しない", "T3-2(治療)と同じ式のため、同じ文献が、予防と治療の両方に入る"]),
 ("P3-1", "P3", "CQ1-カルニチン-アセチル‒L‒カルニチン", asco("Acetyl-L-carnitine"), A, "カルニチン 平山検索過程.docx(検索式1)", True, "2021-06-30", "2021/07/01", "前回の検索の終了日(2021年6月30日)の翌日", ["2023年版は「検索式2」でも検索している(2件)。検索式2 の式は記録に残っていない"]),
 ("N1-1", "N1", "CQ1-冷却・圧迫", asco("Cryotherapy"), A, "検索過程_冷却_山田華井.docx「検索式: ASCO 検索式(Cryotherapy のみ)」", True, "2021-08-03", "2021/08/04", "前回の検索の日(2021年8月3日)の翌日", []),
 ("N1-2", "N1", "CQ1-冷却・圧迫", asco('"Compression Bandages"[Mesh]'), A, "圧迫の 2023年版の検索式は記録に残っていない。介入語は委員会提示の語", False, "", "2021/07/01", GL, ["圧迫の前回の式と検索の終了日を確認する"]),
 ("N1-3", "N1", "CQ1-冷却・圧迫", asco('(Cryotherapy OR cooling OR "frozen glove*" OR compression OR "Compression Bandages"[Mesh])'), "案(2023年版の引用文献で再現率を確認した式)", "冷却と圧迫を 1つの式にした案。2023年版の冷却・圧迫の引用文献 13件のうち 11件を拾う(拾えない 2件は、ASCOガイドラインとメタアナリシス)。N1-1(冷却)と N1-2(圧迫)を置き換える。統括委員会の承認が必要", False, "2021-08-03", "2021/07/01", "圧迫の前回の検索の終了日が記録にないため、冷却の終了日(2021年8月3日)より前の 2021/07/01。重複は取り込みのときに除く", ["案である。N1-1 と N1-2 の代わりに使う場合は、統括委員会の承認が必要", "「Cryotherapy」だけでは、「regional cooling」の論文(Sato 2016、PMID 27891244)を拾えない。「cooling」「frozen glove*」を加えた"]),
 ("N2-1", "N2", "CQ1-運動", asco('("Exercise"[Mesh] OR "Exercise Therapy"[Mesh])'), A, "【運動】検索過程.docx は C の部分だけが記録に残っている(867件)。介入語は委員会提示の語", False, "2021-09-04", "2021/09/05", "前回の検索の終了日(2021年9月4日)の翌日", ["運動の前回の式(介入語の部分)を、検索過程の原本で確認する"]),
 ("N3-1", "N3", "CQ1-鍼灸", asco("acupuncture"), A, "検索式.docx", True, "2021", "2021/07/01", GL, ["記録の検索期間は「2019,9から2021」で、終了の月日がない。開始日を確認する"]),
 ("T1-1", "T1", "CQ2-デュロキセチン", asco("(duloxetine)"), A, "検索過程 武井_デュロキセチン.docx、検索過程 神林＿デュロキセチン.docx", True, "2021-12-12", "2021/12/13", "前回の検索の終了日(2021年12月12日)の翌日", []),
 ("T2-1", "T2", "CQ2-アミトリプチリン", asco("amitriptyline/ketamine"), A, "前回Scope(2021-07-02)の ASCO の式の介入語「amitriptyline/ketamine」(担当者が該当しない用語を省いてよい、と前回Scope に記載)。2023年版の検索過程の記録はない", True, "", "2021/07/01", GL, ["「amitriptyline/ketamine」は MeSH になく、PubMed は語句として検索する。2021/07〜2026/10 の件数は 0 に近い(コネクタでの確認: 0 件)。アミトリプチリン全般を拾う案は T2-2"]),
 ("T2-2", "T2", "CQ2-アミトリプチリン", asco("amitriptyline"), "案(アミトリプチリン全般)", "T2-1 は、外用ゲル(amitriptyline/ketamine)の語句で、アミトリプチリンの内服の文献を拾えない。「amitriptyline」を介入語にした案。統括委員会の承認が必要", False, "", "2021/07/01", GL, ["案である。T2-1 の代わりに使う場合は、統括委員会の承認が必要"]),
 ("T3-1", "T3", "CQ2-プレガバリン", asco("Pregabalin"), A, "検索過程 プレガバリン・ミロガバリン.docx", True, "2021-08-12", "2021/08/13", "前回の検索の終了日(2021年8月12日)の翌日", []),
 ("T3-2", "T3", "CQ2-ミロガバリン", asco("Mirogabalin"), A, "検索過程 プレガバリン・ミロガバリン.docx は、プレガバリンの式だけが記録に残っている。介入語は仮の語", False, "2021-08-12", "2021/08/13", "前回の検索の終了日(2021年8月12日)の翌日", ["ミロガバリンの前回の式を、検索過程の原本で確認する"]),
 ("N4-1", "N4", "CQ2-運動", asco('("Exercise"[Mesh] OR "Exercise Therapy"[Mesh])'), A, "【運動】検索過程.docx は C の部分だけが記録に残っている(867件)。介入語は委員会提示の語", False, "2021-09-04", "2021/09/05", "前回の検索の終了日(2021年9月4日)の翌日", ["運動の前回の式(介入語の部分)を、検索過程の原本で確認する"]),
 ("N5-1", "N5", "CQ2-鍼灸", asco("acupuncture"), A, "検索式.docx", True, "2021", "2021/07/01", GL, ["記録の検索期間は「2019,9から2021」で、終了の月日がない。開始日を確認する"]),
 ("F1-1", "F1", "CQ2-ビタミン-B12", asco('"Vitamin B 12"[Mesh]'), A, "CIPN SR_VB12 検索過程.docx に式が残っていない(2023年版は手引き2017 の式で 2016年6月〜2021年6月)。介入語は委員会提示の語", False, "2021-06", "2021/07/01", "前回の検索の終了月(2021年6月)の翌月", ["ビタミンB12 の前回の式(手引き2017 の式)を確認する"]),
 ("F2-1", "F2", "CQ2-非ステロイド性消炎鎮痛薬-NSAIDs", NSAIDS, T, "NSAIDs 松坂 検索式記録.docx", True, "2021-06-30", "2021/07/01", "前回の検索の終了日(2021年6月30日)の翌日", []),
 ("F3-1", "F3", "CQ2-オピオイド", asco('"Analgesics, Opioid"[Mesh]'), A, "2023年版の検索過程の記録がない(2023年版は手引き2017 の式)。介入語は委員会提示の語", False, "", "2021/07/01", GL, ["オピオイドの前回の式(手引き2017 の式)と検索の終了日を確認する"]),
 ("F4-1", "F4", "CQ2-薬物の併用療法", asco('("combination therapy" OR "combined therapy")'), A, "統括委員長の指示(2026-11-22): 併用療法の語は combination therapy / combined therapy。P節・C節は ASCO の式。前回の式の記録はない", False, "", "2021/07/01", GL, ["件数が 8,000 件を超える(コネクタでの確認: 8,305 件)。ASCO の C 節が「neoplasms/drug therapy」などの MeSH を含み、がん薬物療法の文献の大半に当たり、「combination therapy」はがん薬物療法の一般的な語のため。ポータルに登録できない", "絞り込んだ案は F4-2"]),
 ("F4-2", "F4", "CQ2-薬物の併用療法", '((survivor OR (survivor AND cancer) OR "cancer survivor" OR cancer)) AND ("combination therapy"[tiab] OR "combined therapy"[tiab]) AND (neuropathy[tiab] OR "chemotherapy-induced peripheral neuropathy"[tiab] OR CIPN[tiab])', "案(神経障害の語を題名・抄録に限定した式)", "F4-1 の C 節を、題名・抄録の神経障害の語に限定した案。コネクタでの確認では 57 件(2021/07〜2026/10)。CIPN の語に限ると 11 件。統括委員会の承認が必要", False, "", "2021/07/01", GL, ["案である。F4-1 の代わりに使う場合は、統括委員会の承認が必要。前回の式ではない"]),
]

plan = json.load(open(os.path.join(ROOT, "governance", "approved_plan.json"), encoding="utf-8"))
names = {it["id"]: it["名称"] for it in plan["SR項目"] + plan["FRQ項目"]}; dirs = {d for it in plan["SR項目"] + plan["FRQ項目"] for d in it["dir"]}
out = []
for sid, cq, d, q, kind, src, ok, prior_end, start, basis, notes in S:
    assert cq in names and d in dirs and q.count("(") == q.count(")"), sid
    out.append({"id": sid, "cq": cq, "cq_name": names[cq], "dir": d, "database": "PubMed", "query": q, "formula_kind": kind, "formula_source": src, "confirmed": ok, "prior_end": prior_end,
                "start": start, "start_basis": basis, "end": END, "notes": notes, "full_query": f'({q}) AND ("{start}"[dp] : "{END}"[dp])'})
for s_ in out: s_["proposal"] = s_["id"] in ("N1-3", "T2-2", "F4-2", "P2-2")   # 案は、確認済み・未確認の件数に数えず、--only で指定したときだけ取得する
assert {s["cq"] for s in out} == set(names)
_old = os.path.join(ROOT, "data", "search_plan.json"); _keep = {k: v for k, v in (json.load(open(_old, encoding="utf-8")) if os.path.exists(_old) else {}).items() if k not in ("decision", "date_field", "searches")}   # 確認結果(mesh_check、count_check、recall_check)は残す
json.dump({**_keep, "decision": "統括委員長の決定(2026-11-20): 検索期間は 2026年10月1日まで。検索式は前回(2023年版)の式。開始日は、前回の検索の終了日の翌日(終了が月だけの記録は翌月の 1 日)",
           "date_field": "dp(出版日。2023年版の記録と同じ)", "searches": out}, open(os.path.join(ROOT, "data", "search_plan.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(out), "検索(案を除く", sum(not s["proposal"] for s in out), "。確認済み", sum(s["confirmed"] for s in out), "/ 未確認", sum(not s["confirmed"] and not s["proposal"] for s in out), "/ 案", sum(s["proposal"] for s in out), ")")

