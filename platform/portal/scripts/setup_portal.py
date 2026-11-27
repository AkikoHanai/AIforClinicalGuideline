"""ポータルに、委員が使う資料を全て登録し、登録された内容を確認する(統括委員長の Mac。何度実行しても同じ結果になる)。
  ./setup_portal.sh      (リポジトリ直下)
登録するもの:
  0. 企画書の項目(CQ・FRQ、総論)の名称・担当 → 登録済みの項目を、企画書に合わせる
  1. 手順書(Word)と用語の定義      → ポータルの「手順書」
  2. 2023年版の総論の本文・依頼書    → 「総論の執筆・査読」の各行(2023年版を参照する)
  3. 2023年版の CQ の記述           → 「EtD・推奨」の 2023年版の欄
  4. 検索の参考資料(前回の検索式・検索過程) → 「検索の記録」の参考の枠
  5. アウトカム CIPN(全 CQ・FRQ)
最後に、ポータルに登録された件数を表示する。[NG] の行が、登録されていないもの。
"""
import json, os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPECT_DOCS = ["操作マニュアル", "SR委員の手順書", "SR委員長の業務手順", "論文PDFの入手", "総説執筆者の手順書", "用語の定義", "統括委員会へのお願い"]


def verify(tok):
    """ポータルに登録された件数。戻り値: [(OKか, 内容)]"""
    out = []
    docs = tok.call("GET", "/docs?missing=1&kind=all")   # 手順書と Scope(SC-1〜SC-4の18件); docs = docs if isinstance(docs, list) else []
    have = [d["name"] for d in docs if d.get("available", True)]; miss = [d["name"] for d in docs if d.get("available") is False]
    out.append((not miss and bool(have), f"手順書・Scope: 登録 {len(have)}件" + (f"、未登録 {', '.join(miss)}" if miss else "")))
    sor = tok.call("GET", "/gl2023/soron"); sor = sor if isinstance(sor, list) else []
    plan = tok.call("GET", "/soron"); plan = plan if isinstance(plan, list) else []
    n23 = len(json.load(open(os.path.join(ROOT, "data", "gl2023", "units.json"), encoding="utf-8"))); n_text = sum(1 for x in sor if x.get("paragraphs"))   # 2023年版にある総論の数(2023年版にない項目の本文は、ない)
    out.append((n_text >= n23, f"2023年版の総論の本文: {n_text}件(2023年版にある総論 {n23}件。総論の項目 {len(plan)}件のうち、2023年版にない項目は、本文がない)"))
    out.append((bool(sor) and any(x.get("docx_key") for x in sor), f"総論の依頼書(Word): {sum(1 for x in sor if x.get('docx_key'))}件"))
    gl = tok.call("GET", "/gl2023"); gl = gl if isinstance(gl, list) else []
    cqs = tok.call("GET", "/cq"); cqs = cqs if isinstance(cqs, list) else []
    out.append((bool(gl) and all(g.get("rec") or g.get("paragraphs") for g in gl), f"2023年版の CQ の記述: {len(gl)}件(CQ・FRQ {len(cqs)}件。2023年版にない CQ は、登録がない)"))
    bad = [c["id"] for c in cqs if (c.get("outcomes") or []) != ["CIPN"]]
    out.append((not bad and bool(cqs), "アウトカム CIPN: " + ("全 CQ・FRQ に登録済み" if not bad else f"CIPN でない CQ: {', '.join(bad)}")))
    # 企画書の項目と担当: ポータルの CQ・FRQ(名称、担当、CQ か FRQ か)と総論(題名、担当)が、企画書と同じか
    P = json.load(open(os.path.join(ROOT, "governance", "approved_plan.json"), encoding="utf-8")); have = {c["id"]: c for c in cqs}
    want = [(it, "SR") for it in P["SR項目"]] + [(it, "FRQ") for it in P["FRQ項目"]]
    diff = [it["名称"] for it, kind in want if (have.get(it["id"], {}).get("title"), list(have.get(it["id"], {}).get("assignees") or []), have.get(it["id"], {}).get("kind")) != (it["名称"], it["担当"], kind)]
    diff += [f"総論{k}" for k, v in P["総論"].items() if (lambda s: (s.get("title"), s.get("author")))(next((x for x in plan if x.get("key") == k), {})) != (v.rpartition(":")[0], v.rpartition(":")[2])]
    out.append((not diff and len(have) == len(want), f"企画書の項目と担当: CQ {len(P['SR項目'])}件・FRQ {len(P['FRQ項目'])}件、総論 {len(P['総論'])}件" + ("。企画書と同じ" if not diff else f"。企画書と違う: {', '.join(diff)}")))
    return out


def main(email=None):
    import admin_user, upload_docs, import_soron2023, import_search_reference
    steps = [("企画書の項目と担当", lambda: admin_user.seed(email)), ("手順書", lambda: upload_docs.main(email)), ("2023年版の総論", lambda: import_soron2023.main(email)),
             ("2023年版の CQ の記述", lambda: admin_user.gl2023(os.path.join(ROOT, "data", "gl2023", "etd_2023.json"), email)),
             ("検索の参考資料", lambda: import_search_reference.main(email)), ("アウトカム CIPN", lambda: admin_user.outcomes(email))]
    failed = []
    for name, fn in steps:
        print(f"\n===== {name} =====")
        try: fn()
        except SystemExit as e: failed.append((name, str(e)[:200])); print("[NG]", name, e)
        except Exception as e: failed.append((name, f"{type(e).__name__}: {e}")); traceback.print_exc(); print("[NG]", name, e)
    print("\n===== ポータルに登録された内容 =====")
    tok = admin_user.token(email); res = verify(tok)
    for ok, msg in res: print(("[OK] " if ok else "[NG] ") + msg)
    bad = [m for ok, m in res if not ok] + [f"{n}: {m}" for n, m in failed]
    print("\n" + ("全て登録されています。" if not bad else "登録されていないものがあります。上の [NG] の行を確認してください。"))
    return 1 if bad else 0


if __name__ == "__main__":
    from admin_user import email_arg
    if {"-h", "--help"} & set(sys.argv[1:]): sys.exit(__doc__)
    sys.exit(main(email_arg(sys.argv[1:])))
