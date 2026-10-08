"""推奨作成会議の「決定記録シート」(HTML 1ファイル)を作る。
  python3 platform/core/render_meeting.py -o meeting/決定記録シート.html [--drafts 草案JSONのフォルダ]

Mindsの推奨作成の記録に必要な項目を、会議の場で入力・保存・共有できる形にする:
  推奨文、推奨の強さ(5段階)、エビデンスの確実性、考慮する項目、投票(最大3回、委員ごと)、
  投票除外(SR担当・直接評価した論文の筆頭著者。理由つき)、成立の判定(75%参加・80%賛成)、意見の概要、変更の履歴。
投票者は承認済み企画書の統括委員会・作成グループ委員。患者代表は含めない。
AI(Claude)は推奨や投票を決めない。このシートは、委員が決めた内容を記録するだけである。
"""
import argparse, glob, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
PLAN = json.load(open(os.path.join(os.path.dirname(HERE), "governance", "approved_plan.json"), encoding="utf-8"))

VOTERS = [re.sub(r"\(.*?\)", "", n) for n in PLAN["体制"]["統括委員会"] + PLAN["体制"]["診療ガイドライン作成グループ委員"]]
VOTERS = [re.sub(r"\(.*", "", n) for n in PLAN["体制"]["統括委員会"] + PLAN["体制"]["診療ガイドライン作成グループ委員"]]
VOTERS = [v.strip() for v in VOTERS]


def surname_match(voter, short):
    return voter.startswith(short) or short.startswith(voter[:2])


def items():
    out = []
    for it in PLAN["SR項目"] + PLAN["FRQ項目"]:
        for d in it["dir"]:
            sr = [v for v in VOTERS if any(v.startswith(s) for s in it["担当"])]
            out.append({"id": d, "name": it["名称"], "plan_id": it["id"], "kind": "FRQ" if it["id"].startswith("F") else "CQ",
                        "sr": it["担当"], "sr_voters": sr})
    return out


HTML = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>推奨作成会議 決定記録シート</title>
<style>
body{font-family:"Yu Gothic","Hiragino Sans",sans-serif;color:#000;background:#fff;margin:0;font-size:14px}
header{padding:10px 20px;border-bottom:2px solid #000}
h1{font-size:18px;margin:0 0 4px}h2{font-size:15px;margin:0 0 6px;border-left:5px solid #000;padding-left:8px}
main{display:flex}nav{width:290px;border-right:1px solid #000;padding:8px;box-sizing:border-box;height:calc(100vh - 78px);overflow:auto;position:sticky;top:0}
nav button{display:block;width:100%;text-align:left;border:1px solid #000;background:#fff;color:#000;padding:4px 6px;margin:0 0 4px;font-size:12.5px;cursor:pointer}
nav button.sel{border-width:3px;font-weight:bold}.st{float:right;font-size:11px}
section{flex:1;padding:12px 20px;max-width:1000px}
table{border-collapse:collapse;width:100%}th,td{border:1px solid #000;padding:3px 6px;vertical-align:top;font-size:13px}th{background:#eee}
textarea,input,select{font:inherit;border:1px solid #000;padding:3px;box-sizing:border-box}textarea{width:100%;min-height:54px}
.btn{border:1px solid #000;background:#fff;color:#000;padding:4px 12px;cursor:pointer;margin-right:6px}.note{font-size:12px}
.box{border:2px solid #000;padding:6px 10px;margin:8px 0}.ng{text-decoration:underline}.hide{display:none}
.tabs button{border:1px solid #000;background:#fff;padding:3px 12px;cursor:pointer}.tabs button.sel{font-weight:bold;border-width:3px}
@media print{nav,.noprint{display:none}main{display:block}}
</style></head><body>
<header><h1>推奨作成会議 決定記録シート　<span id="ttl"></span></h1>
<div class="noprint">会議日 <input type="date" id="mdate"> 議長 <input id="chair" size="10"> 記録者 <input id="scribe" size="10">
<button class="btn" onclick="exportJson()">JSONで書き出す(共有用)</button><button class="btn" onclick="exportCsv()">CSVで書き出す</button>
<label class="btn">JSONを読み込む<input type="file" id="imp" accept=".json" class="hide"></label>
<button class="btn" onclick="window.print()">印刷</button></div>
<div class="note">投票者は統括委員と作成グループ委員(患者代表は含まない)。入力はこの端末のブラウザに自動保存される。共有は、JSONを書き出して事務局へ送る。</div></header>
<main><nav id="nav"></nav><section id="main"></section></main>
<script>
const TITLE = __TITLE__, VOTERS = __VOTERS__, ITEMS = __ITEMS__, DRAFTS = __DRAFTS__;
const STR = {"1":"1 強く推奨","2":"2 弱く推奨","3":"3 推奨なし","4":"4 行わないことを弱く推奨","5":"5 行わないことを強く推奨"};
const KEY = "cipn-meeting-record";
let S = {meta:{}, cq:{}, log:[]}; let cur = ITEMS[0].id; let round = 1;
try { const r = localStorage.getItem(KEY); if (r) S = JSON.parse(r); } catch(e) {}
function item(id){ return ITEMS.find(x=>x.id===id); }
function cq(id){ if(!S.cq[id]){ const d = DRAFTS[id]||{}; S.cq[id] = {rec:d.rec||"", strength:d.strength||"", certainty:d.certainty||"", etd:{benefit:d.benefit||"",certainty:d.etd_certainty||"",values:d.values||"",cost:d.cost||""},
  excl:{}, votes:{1:{},2:{},3:{}}, memo:"", final:null}; const it=item(id); it.sr_voters.forEach(v=>S.cq[id].excl[v]="SR担当"); } return S.cq[id]; }
function save(){ try{ localStorage.setItem(KEY, JSON.stringify(S)); }catch(e){} }
function logc(id,f,v){ S.log.push({t:new Date().toISOString(), cq:id, field:f, value:String(v).slice(0,200), by:(S.meta.scribe||"")}); }
function eligible(id){ const c=cq(id); return VOTERS.filter(v=>!c.excl[v]); }
function tally(id,r){
  const c=cq(id), el=eligible(id), vt=c.votes[r]||{};
  const part=el.filter(v=>vt[v] && vt[v]!=="欠席"), n=el.length;
  const cnt={}; part.forEach(v=>{ cnt[vt[v]]=(cnt[vt[v]]||0)+1; });
  let best=null,bc=0; for(const k of ["1","2","3","4","5"]) if((cnt[k]||0)>bc){bc=cnt[k];best=k;}
  const pr = n? part.length/n : 0, ag = part.length? bc/part.length : 0;
  const entered = el.filter(v=>vt[v]).length;
  return {n,part:part.length,cnt,best,pr,ag,entered,ok:(pr>=0.75 && ag>=0.8), complete: entered===n};
}
function status(id){
  const it=item(id); if(it.kind==="FRQ") return "FRQ(投票なし)";
  const c=cq(id); if(c.final) return "確定: "+(STR[c.final.strength]||"");
  for(let r=1;r<=3;r++){ const t=tally(id,r); if(t.complete && t.ok) return "R"+r+"で成立(未確定)"; }
  return "未決";
}
function nav(){ document.getElementById("nav").innerHTML = ITEMS.map(it=>`<button class="${it.id===cur?'sel':''}" onclick="go('${it.id}')">${it.kind} ${it.name}<span class="st">${status(it.id)}</span></button>`).join(""); }
function go(id){ cur=id; round=1; draw(); }
function setf(path,v){ const c=cq(cur); const p=path.split("."); let o=c; for(let i=0;i<p.length-1;i++){o=o[p[i]]} o[p[p.length-1]]=v; logc(cur,path,v); save(); nav(); }
function setVote(v,val){ const c=cq(cur); if(c.final) return; c.votes[round][v]=val; logc(cur,"vote R"+round+" "+v,val); save(); draw(); }
function setExcl(v,reason){ const c=cq(cur); if(reason) c.excl[v]=reason; else delete c.excl[v]; logc(cur,"除外 "+v,reason||"解除"); save(); draw(); }
function finalize(){
  const c=cq(cur); const msgs=[];
  let decided=null;
  for(let r=1;r<=3;r++){ const t=tally(cur,r); if(t.complete && t.ok){ decided={round:r,strength:t.best}; break; } }
  if(!decided){ const t3=tally(cur,3); if(t3.complete){ decided={round:3,strength:"3",note:"3回の投票で意見が集約しなかったため推奨なし"}; } }
  if(!decided){ alert("成立した投票がなく、3回目の投票も完了していません。"); return; }
  if(!c.rec.trim() && decided.strength!=="3"){ alert("推奨文が空です。"); return; }
  c.final={round:decided.round,strength:decided.strength,note:decided.note||"",at:new Date().toISOString(),by:S.meta.scribe||""};
  c.strength=decided.strength; logc(cur,"確定",decided.strength); save(); draw();
}
function unfinal(){ if(!confirm("確定を取り消します(履歴に残ります)。")) return; cq(cur).final=null; logc(cur,"確定取消",""); save(); draw(); }
function draw(){
  nav(); const it=item(cur), c=cq(cur), frq=it.kind==="FRQ";
  let h=`<h2>${it.kind}: ${it.name}　<span class="note">(${it.plan_id}。SR担当: ${it.sr.join("、")})</span></h2>`;
  if(c.final) h+=`<div class="box">確定: <b>${STR[c.final.strength]}</b>(第${c.final.round}回の投票${c.final.note?"。"+c.final.note:""})　${c.final.at.slice(0,16).replace("T"," ")}　記録者: ${c.final.by||"—"} <button class="btn noprint" onclick="unfinal()">確定を取り消す</button></div>`;
  h+=`<h3>${frq?"研究課題の記載(推奨は出さない)":"推奨文"}</h3><textarea ${c.final?"disabled":""} oninput="setf('rec',this.value)">${esc(c.rec)}</textarea>`;
  if(!frq){
    h+=`<table><tr><th>エビデンスの確実性(SR-8)</th><td><select onchange="setf('certainty',this.value)"><option value=""></option>${["A","B","C","D"].map(x=>`<option ${c.certainty===x?'selected':''}>${x}</option>`).join("")}</select></td></tr></table>
<h3>推奨を決める際に考慮した項目(Minds)</h3><table>
<tr><th>益と害のバランス</th><td><textarea oninput="setf('etd.benefit',this.value)">${esc(c.etd.benefit)}</textarea></td></tr>
<tr><th>エビデンス全体の確実性</th><td><textarea oninput="setf('etd.certainty',this.value)">${esc(c.etd.certainty)}</textarea></td></tr>
<tr><th>患者・市民の価値観と希望</th><td><textarea oninput="setf('etd.values',this.value)">${esc(c.etd.values)}</textarea></td></tr>
<tr><th>資源(高額な場合のみ)</th><td><textarea oninput="setf('etd.cost',this.value)">${esc(c.etd.cost)}</textarea></td></tr></table>`;
    // 投票除外
    h+=`<h3>投票除外(SR担当、直接評価した論文の筆頭著者。理由を記録)</h3><table><tr><th>委員</th><th>除外の理由</th></tr>`+
      VOTERS.map(v=>`<tr><td>${v}</td><td><select ${c.final?"disabled":""} onchange="setExcl('${v}',this.value)"><option value=""></option>${["SR担当","直接評価した論文の筆頭著者","その他の利益相反"].map(x=>`<option ${c.excl[v]===x?'selected':''}>${x}</option>`).join("")}</select></td></tr>`).join("")+`</table>`;
    // 投票
    const el=eligible(cur);
    h+=`<h3>投票　<span class="note">有資格者 ${el.length}名(${VOTERS.length}名中、除外 ${VOTERS.length-el.length}名)。成立の分母はこの有資格者数。除外を変えると、判定が再計算される</span></h3><div class="tabs">${[1,2,3].map(r=>`<button class="${r===round?'sel':''}" onclick="round=${r};draw()">第${r}回</button>`).join("")}</div>`;
    const t=tally(cur,round);
    h+=`<table><tr><th>委員(有資格 ${el.length}名)</th><th>投票</th></tr>`+el.map(v=>`<tr><td>${v}</td><td><select ${c.final?"disabled":""} onchange="setVote('${v}',this.value)"><option value=""></option>${["1","2","3","4","5"].map(x=>`<option value="${x}" ${c.votes[round][v]===x?'selected':''}>${STR[x]}</option>`).join("")}<option ${c.votes[round][v]==="棄権"?'selected':''}>棄権</option><option ${c.votes[round][v]==="欠席"?'selected':''}>欠席</option></select></td></tr>`).join("")+`</table>`;
    h+=`<div class="box">参加 ${t.part}/${t.n}名(有資格者数が分母。${(t.pr*100).toFixed(0)}%。基準75%以上。参加に必要な最少人数 ${Math.ceil(0.75*t.n)}名)　最多の選択肢 ${t.best?STR[t.best]:"—"}: ${t.best?t.cnt[t.best]:0}票(参加者の${(t.ag*100).toFixed(0)}%。基準80%以上)　→ <b>${t.complete?(t.ok?"成立":"不成立"):"入力中("+t.entered+"/"+t.n+")"}</b><br><span class="note">参加=欠席でない委員。賛成の割合の分母は参加者(棄権を含む)。過半数の反対がある場合は、推奨文の変更を考慮して次の回に進む。3回で集約しなければ「推奨なし」。</span></div>`;
    h+=`<button class="btn noprint" ${c.final?"disabled":""} onclick="finalize()">この結果で確定する</button>`;
  }
  h+=`<h3>意見の概要・議事メモ</h3><textarea oninput="setf('memo',this.value)">${esc(c.memo)}</textarea>`;
  document.getElementById("main").innerHTML=h;
}
function esc(s){ return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function meta(){ S.meta={date:document.getElementById("mdate").value,chair:document.getElementById("chair").value,scribe:document.getElementById("scribe").value}; save(); }
["mdate","chair","scribe"].forEach(i=>{ const e=document.getElementById(i); e.value=(S.meta||{})[i==="mdate"?"date":i]||""; e.addEventListener("input",meta); });
function dl(name,text,type){ const a=document.createElement("a"); a.href=URL.createObjectURL(new Blob([text],{type})); a.download=name; a.click(); }
function exportJson(){ dl("決定記録_"+(S.meta.date||"未設定")+".json", JSON.stringify({title:TITLE,exported:new Date().toISOString(),voters:VOTERS,items:ITEMS.map(x=>({id:x.id,name:x.name,kind:x.kind})),state:S},null,1),"application/json"); }
function exportCsv(){
  const rows=[["ID","種別","項目","推奨文/研究課題","確定の強さ","確定の回","確実性","有資格者数(分母)","除外者数","第1回参加","第1回成立","第2回参加","第2回成立","第3回参加","第3回成立","除外(委員:理由)","意見の概要"]];
  ITEMS.forEach(it=>{ const c=cq(it.id); const ts=[1,2,3].map(r=>tally(it.id,r));
    rows.push([it.id,it.kind,it.name,c.rec,c.final?STR[c.final.strength]:"",c.final?c.final.round:"",c.certainty,eligible(it.id).length,VOTERS.length-eligible(it.id).length,
      ts[0].part,ts[0].complete?(ts[0].ok?"成立":"不成立"):"",ts[1].part,ts[1].complete?(ts[1].ok?"成立":"不成立"):"",ts[2].part,ts[2].complete?(ts[2].ok?"成立":"不成立"):"",
      Object.entries(c.excl).map(([k,v])=>k+":"+v).join(" / "),c.memo]); });
  dl("決定記録_"+(S.meta.date||"未設定")+".csv","﻿"+rows.map(r=>r.map(x=>'"'+String(x==null?"":x).replace(/"/g,'""')+'"').join(",")).join("\n"),"text/csv");
}
document.getElementById("imp").addEventListener("change",e=>{ const f=e.target.files[0]; if(!f) return; const r=new FileReader(); r.onload=()=>{ try{ const d=JSON.parse(r.result); if(!confirm("この端末の入力を、読み込んだ内容で置き換えます。")) return; S=d.state; save(); location.reload(); }catch(x){ alert("読み込めません: "+x); } }; r.readAsText(f); });
document.getElementById("ttl").textContent=TITLE; draw();
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="meeting/決定記録シート.html")
    ap.add_argument("--drafts", help="委員が書き出した草案JSON(CQ_委員.draft.json)のフォルダ。推奨文などを初期値にする")
    a = ap.parse_args()
    drafts = {}
    if a.drafts:
        for f in sorted(glob.glob(os.path.join(a.drafts, "*.draft.json"))):
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            cid = d.get("cq"); dr = d.get("draft") or {}
            if not cid or cid in drafts:
                continue
            drafts[cid] = {"rec": dr.get("rec_text") or dr.get("frq_future") or "", "strength": str(dr.get("rec_strength") or ""),
                           "certainty": dr.get("rec_certainty") or "", "benefit": dr.get("cons_balance") or "",
                           "etd_certainty": dr.get("cons_certainty") or "", "values": dr.get("cons_values") or "", "cost": dr.get("cons_cost") or "",
                           "from": d.get("reviewer") or ""}
    html = (HTML.replace("__TITLE__", json.dumps(PLAN["タイトル"], ensure_ascii=False)).replace("__VOTERS__", json.dumps(VOTERS, ensure_ascii=False))
            .replace("__ITEMS__", json.dumps(items(), ensure_ascii=False)).replace("__DRAFTS__", json.dumps(drafts, ensure_ascii=False)))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(html)
    print(a.out, "投票者", len(VOTERS), "名 / 項目", len(items()))


if __name__ == "__main__":
    main()
