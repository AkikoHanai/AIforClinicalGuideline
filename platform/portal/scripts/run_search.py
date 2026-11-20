"""検索計画(platform/data/search_plan.json)の検索を PubMed で実行し、結果(件数と、PMID・題名・著者の一覧)を保存する(Mac で実行。AWS は不要)。
  python3 platform/portal/scripts/run_search.py                      件数だけを調べる(全検索。未確認の式も、件数は調べる)
  python3 platform/portal/scripts/run_search.py --fetch              確認済みの検索の文献を取得して保存する
  python3 platform/portal/scripts/run_search.py --fetch --only P1-1,T1-1      指定した検索だけ(未確認の式は、--only で指定したときだけ取得する)
  python3 platform/portal/scripts/run_search.py --import <メールアドレス> --searcher <検索者の氏名> --dir <保存先>
                                                                      保存した結果を、ポータルの「検索の記録」と「スクリーニング」に登録する
保存先(既定): リポジトリの search_results/<実行日>/(git には入らない)。--out <フォルダ> で変える。
保存するもの: 検索ごとの <id>_<フォルダ名>.json(検索式、検索日時、件数、PubMed が解釈した式、文献)と .csv(No・PMID・題名・著者・誌名・年・DOI)、検索の記録.csv(一覧)。
件数(PubMed の検索結果の件数)と、取得した文献の数が一致しない検索は、その旨を表示し、ポータルに登録しない。"""
import csv, datetime, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "..", "api")); sys.path.insert(0, HERE)
import pubmed  # noqa: E402

PLAN = os.path.join(ROOT, "data", "search_plan.json")
MAX_IMPORT = 8000   # ポータルの 1つの CQ の対象の上限


def d2s(d): return d.strftime("%Y/%m/%d")
def s2d(s): return datetime.datetime.strptime(s, "%Y/%m/%d").date()
def term(q, a, b): return f'({q}) AND ("{d2s(a)}"[dp] : "{d2s(b)}"[dp])'


def all_pmids(q, a, b, limit=None):
    """期間 a〜b の検索結果の PMID を全て取る。件数が上限を超える期間は、2つに分けて取り、合わせる(PubMed は 1 回の検索で約 1 万件までしか返さないため)。
    戻り値: (PMID の一覧, その期間の件数)"""
    limit = limit or pubmed.ESEARCH_MAX
    n = pubmed.esearch(term(q, a, b))["count"]
    if n == 0: return [], 0
    if n <= limit or a >= b: return pubmed.esearch(term(q, a, b), retmax=limit)["ids"], n
    mid = a + (b - a) // 2
    left, _ = all_pmids(q, a, mid, limit); right, _ = all_pmids(q, mid + datetime.timedelta(days=1), b, limit)
    return list(dict.fromkeys(left + right)), n


def count_all(plan):
    print("ID    | CQ | 件数 | 式の確認 | 検索期間 | 式の種類")
    rows = []
    for s in plan:
        r = pubmed.esearch(s["full_query"]); rows.append((s, r))
        print(f"{s['id']:5} | {s['cq']} {s['cq_name']} | {r['count']} | {'確認済み' if s['confirmed'] else '未確認'} | {s['start']}〜{s['end']} | {s['formula_kind']}")
        for n in s["notes"]: print(f"        注意: {n}")
        if r["count"] > MAX_IMPORT: print(f"        注意: 件数が {MAX_IMPORT} 件を超える。ポータルに登録できない。式を統括委員会で確認する")
    return rows


def fetch_all(plan, out, only=None, limit=None):
    os.makedirs(out, exist_ok=True); summary = []
    for s in plan:
        if only is not None and s["id"] not in only: continue
        if only is None and not s["confirmed"]:
            print(f"{s['id']} {s['cq_name']}: 式が未確認のため、取得しない({'; '.join(s['notes'])})"); continue
        at = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        first = pubmed.esearch(s["full_query"]); ids, n = all_pmids(s["query"], s2d(s["start"]), s2d(s["end"]), limit)
        meta = pubmed.fetch(ids) if ids else {}
        recs = [{"pmid": pm, **(meta.get(pm) or {"title": "", "authors": "", "authors_all": "", "journal": "", "year": "", "doi": "", "abstract": ""})} for pm in sorted(ids, key=int)]
        missing = [pm for pm in ids if pm not in meta]; ok = len(ids) == first["count"] == n
        base = os.path.join(out, f"{s['id']}_{s['dir']}")
        json.dump({"plan": s, "searched_at": at, "count": first["count"], "translation": first["translation"], "fetched": len(ids), "match": ok, "no_metadata": missing, "records": recs},
                  open(base + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        with open(base + ".csv", "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh); w.writerow(["No", "PMID", "題名", "著者", "誌名", "年", "DOI"])
            for i, r in enumerate(recs, 1): w.writerow([i, r["pmid"], r["title"], r["authors_all"] or r["authors"], r["journal"], r["year"], r["doi"]])
        summary.append([s["id"], s["cq"], s["cq_name"], at, "PubMed", f"{s['start']}〜{s['end']}", s["full_query"], first["count"], len(ids), "一致" if ok else "不一致", len(missing), "確認済み" if s["confirmed"] else "未確認", first["translation"]])
        print(f"{s['id']} {s['cq_name']}: 件数 {first['count']}、取得した文献 {len(ids)}({'一致' if ok else '不一致。登録しない'})" + (f"、書誌を取得できなかった PMID {len(missing)} 件" if missing else ""))
    with open(os.path.join(out, "検索の記録.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh); w.writerow(["ID", "CQ", "名称", "検索日時", "データベース", "検索期間", "検索式", "件数", "取得した文献", "件数と文献の数", "書誌を取得できなかった PMID", "式の確認", "PubMed が解釈した式"]); w.writerows(summary)
    print("保存先:", out); return summary


def import_all(tok, folder, searcher, batch=200):
    """保存した結果(<id>_*.json)を、ポータルに登録する。検索を実行し直さない(保存した件数と文献を、そのまま登録する)。"""
    done = []
    for f in sorted(x for x in os.listdir(folder) if x.endswith(".json")):
        d = json.load(open(os.path.join(folder, f), encoding="utf-8")); s = d["plan"]; cq = s["cq"]
        if not d["match"]: print(f"{s['id']}: 件数と文献の数が一致しないため、登録しない"); continue
        if d["count"] > MAX_IMPORT: print(f"{s['id']}: {d['count']} 件。上限 {MAX_IMPORT} 件を超えるため、登録しない"); continue
        if any(x.get("query") == s["full_query"] and x.get("date") == d["searched_at"][:10] for x in tok.call("GET", f"/search/{cq}")):
            print(f"{s['id']}: 同じ検索日・検索式の記録が登録済みのため、飛ばす"); continue
        note = f"{s['id']}。{s['formula_kind']}。式の出典: {s['formula_source']}。開始日の根拠: {s['start_basis']}。検索日時 {d['searched_at']}" + ("" if s["confirmed"] else "。式は未確認")
        r = tok.call("POST", f"/search/{cq}", {"database": "PubMed", "date": d["searched_at"][:10], "searcher": searcher, "period": f"{s['start']}〜{s['end']}", "query": s["full_query"], "hits": d["count"], "note": note})
        if "error" in r: print(f"{s['id']}: {r['error']}"); continue
        added = dup = 0
        for i in range(0, len(d["records"]), batch):
            x = tok.call("POST", f"/screening/{cq}/candidates", {"source": "検索(PubMed)", "search_id": r["id"], "items": d["records"][i:i + batch]})
            if "error" in x: print(f"{s['id']}: {x['error']}"); break
            added += x["added"]; dup += x["duplicates"]
        print(f"{s['id']} {s['cq_name']}: 検索の記録 {d['count']} 件。新たに登録 {added} 件、登録済みのため除いた重複 {dup} 件、差 {d['count'] - added - dup}")
        done.append((s["id"], d["count"], added, dup))
    return done


def main(argv):
    plan = json.load(open(PLAN, encoding="utf-8"))["searches"]
    arg = lambda k: argv[argv.index(k) + 1] if k in argv else None
    if "--import" in argv:
        from admin_user import token
        if not arg("--searcher") or not arg("--dir"): sys.exit("--searcher <検索者の氏名> と --dir <保存先> が必要です")
        return import_all(token(arg("--import")), arg("--dir"), arg("--searcher"))
    if "--fetch" in argv:
        out = arg("--out") or os.path.join(os.path.dirname(ROOT), "search_results", datetime.date.today().isoformat())
        return fetch_all(plan, out, set(arg("--only").split(",")) if arg("--only") else None)
    return count_all(plan)


if __name__ == "__main__":
    main(sys.argv[1:])
