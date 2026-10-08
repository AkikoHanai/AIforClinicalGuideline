"""画面の動作検証(ブラウザ操作)。playwright が必要: pip install playwright
  WS=<作業ディレクトリ> OUT=<出力フォルダ> PLATFORM=<platformのパス> python3 platform/tests/ui_check.py
検証内容: 論文概要の絞り込み、草案の入力・自動保存・JSON書き出し、会議の投票(成立・不成立・3回で推奨なし)、投票除外、書き出し・読み込み。"""
import json,os,sys
from playwright.sync_api import sync_playwright
V=os.environ['WS']
CH=os.environ.get('CHROME','/opt/pw-browsers/chromium-1194/chrome-linux/chrome')
res=[]
def ok(name,cond,info=''):
    res.append((name,bool(cond),info)); print(('PASS' if cond else 'FAIL'),name,info)
with sync_playwright() as p:
    b=p.chromium.launch(executable_path=CH)
    ctx=b.new_context(accept_downloads=True); pg=ctx.new_page()
    dialogs=[]; pg.on('dialog',lambda d:(dialogs.append(d.message),d.accept()))
    # ---- A. 草案作成シート
    pg.goto('file://'+V+'/_draft_sheets/CQ1-牛車腎気丸.review.html')
    ok('A1 概要表がある',pg.query_selector('#ovTable') is not None)
    n=len(pg.query_selector_all('#ovTable tr[data-chemo]'))
    pg.click('#chemoChips .chip:nth-child(3)')
    vis=sum(1 for r in pg.query_selector_all('#ovTable tr[data-chemo]') if r.is_visible())
    ok('A2 化学療法の絞り込み',0<vis<n,f'全{n}件→{vis}件')
    pg.fill('#reviewer','検証太郎'); pg.fill('#rec_text','検証用の推奨文草案です。'); pg.select_option('#rec_strength','4'); pg.select_option('#rec_certainty','C')
    pg.fill('#cons_balance','益害のメモ')
    with pg.expect_download() as dl: pg.click('text=草案をJSONで書き出す')
    path=os.environ['OUT']+'/'+dl.value.suggested_filename; dl.value.save_as(path); d=json.load(open(path))
    ok('A3 JSON書き出し',d['reviewer']=='検証太郎' and d['draft']['rec_text'].startswith('検証用') and d['draft']['rec_strength']=='4' and d['draft']['cons_balance']=='益害のメモ',os.path.basename(path))
    pg.reload()
    ok('A4 再読込後も入力が残る(自動保存)',pg.input_value('#rec_text').startswith('検証用'))
    # 除外は理由が必要
    cands=pg.query_selector_all('tr.cand input[value="exclude"]')
    if cands:
        cands[0].check(); dialogs.clear()
        pg.click('text=草案をJSONで書き出す'); ok('A5 除外に理由がないと書き出せない',any('理由' in m for m in dialogs),str(dialogs[:1]))
    pg.click('text=この画面の入力を消去') if pg.query_selector('text=この画面の入力を消去') else None
    ctx2=b.new_context(accept_downloads=True); pg=ctx2.new_page(); pg.on('dialog',lambda d:d.accept())
    # ---- B. 会議の決定記録
    os.system(f'python3 {os.environ["PLATFORM"]}/core/render_meeting.py -o {V}/meeting.html --drafts {os.environ["OUT"]} >/dev/null')
    pg.goto('file://'+V+'/meeting.html')
    ok('B1 投票者17名・患者代表なし',pg.evaluate('VOTERS.length')==17 and not any('桜井' in v or '浜野' in v for v in pg.evaluate('VOTERS')))
    pg.click('nav button:has-text("牛車腎気丸")')
    ok('B2 草案の推奨文が初期値になる',pg.input_value('textarea').startswith('検証用'))
    ok('B3 SR担当(菊池)が自動で投票除外',pg.evaluate("cq('CQ1-牛車腎気丸').excl['菊池健']")=='SR担当')
    el=pg.evaluate("eligible('CQ1-牛車腎気丸')"); ok('B4 有資格16名',len(el)==16,str(len(el)))
    def vote(r,votes):
        pg.evaluate(f"round={r};draw()")
        for v,val in zip(pg.evaluate("eligible('CQ1-牛車腎気丸')"),votes): pg.evaluate(f"setVote('{v}','{val}')")
    # 第1回: 欠席5名 → 参加69%で不成立
    vote(1,['4']*11+['欠席']*5); t=pg.evaluate("tally('CQ1-牛車腎気丸',1)")
    ok('B5 参加75%未満は不成立',not t['ok'] and t['part']==11,f"参加{t['part']}/16")
    # 第2回: 参加16・賛成12/16=75% → 不成立
    vote(2,['4']*12+['3']*4); t=pg.evaluate("tally('CQ1-牛車腎気丸',2)")
    ok('B6 賛成80%未満は不成立',not t['ok'],f"{t['ag']:.2f}")
    # 第3回: 13/16=81% → 成立
    vote(3,['4']*13+['3']*3); t=pg.evaluate("tally('CQ1-牛車腎気丸',3)")
    ok('B7 賛成80%以上・参加75%以上で成立',t['ok'] and t['best']=='4',f"{t['ag']:.2f}")
    pg.evaluate("finalize()")
    ok('B8 確定で強さ4を記録',pg.evaluate("cq('CQ1-牛車腎気丸').final.strength")=='4' and pg.evaluate("cq('CQ1-牛車腎気丸').final.round")==3)
    # 3回不成立 → 推奨なし
    pg.click('nav button:has-text("CQ 運動")') if False else pg.evaluate("go('CQ1-運動')")
    pg.evaluate("setf('rec','x')")
    for r in (1,2,3):
        pg.evaluate(f"round={r};draw()")
        for i,v in enumerate(pg.evaluate("eligible('CQ1-運動')")): pg.evaluate(f"setVote('{v}','{['1','2','3','4'][i%4]}')")
    pg.evaluate("finalize()")
    ok('B9 3回で集約しなければ推奨なし(3)',pg.evaluate("cq('CQ1-運動').final.strength")=='3')
    # 分母はCOI除外で変わる
    pg.evaluate("go('CQ1-鍼灸')"); pg.evaluate("round=1;draw()")
    el=pg.evaluate("eligible('CQ1-鍼灸')")
    for i,v in enumerate(el): pg.evaluate(f"setVote('{v}','{'2' if i<12 else '欠席'}')")
    t=pg.evaluate("tally('CQ1-鍼灸',1)")
    ok('B15a 有資格16名・参加12名(75%)で成立',len(el)==16 and t['n']==16 and t['part']==12 and t['ok'],f"n={t['n']} 参加={t['part']}")
    pg.evaluate(f"setExcl('{el[0]}','直接評価した論文の筆頭著者')")
    t=pg.evaluate("tally('CQ1-鍼灸',1)")
    ok('B15b 1名を除外すると分母15名・参加11名(73%)で不成立',t['n']==15 and t['part']==11 and not t['ok'],f"n={t['n']} 参加={t['part']} 参加率={t['pr']:.2f}")
    pg.evaluate(f"setExcl('{el[0]}','')")
    t=pg.evaluate("tally('CQ1-鍼灸',1)"); ok('B15c 除外を解除すると分母16名に戻る',t['n']==16 and t['ok'])
    # FRQ
    pg.evaluate("go('CQ2-ビタミン-B12')"); ok('B10 FRQは投票欄なし',pg.query_selector('text=投票除外') is None)
    # 変更履歴・保存・書き出し・取り込み
    ok('B11 変更履歴が残る',pg.evaluate('S.log.length')>20,str(pg.evaluate('S.log.length')))
    pg.fill('#chair','議長A'); pg.fill('#scribe','記録者B'); pg.fill('#mdate','2027-05-15')
    with pg.expect_download() as dl: pg.click('text=JSONで書き出す')
    jp=os.environ['OUT']+'/meeting.json'; dl.value.save_as(jp)
    with pg.expect_download() as dl: pg.click('text=CSVで書き出す')
    cp=os.environ['OUT']+'/meeting.csv'; dl.value.save_as(cp); csv=open(cp,encoding='utf-8-sig').read()
    ok('B12 CSVに確定結果',('4 行わないことを弱く推奨' in csv) and ('3 推奨なし' in csv))
    pg.evaluate("localStorage.clear()"); pg.reload(); ok('B13 保存を消すと未決に戻る',pg.evaluate("status('CQ1-牛車腎気丸')")=='未決')
    pg.set_input_files('#imp',jp); pg.wait_for_load_state()
    pg.wait_for_timeout(500); ok('B14 JSONを読み込んで復元(共有)',pg.evaluate("status('CQ1-牛車腎気丸')").startswith('確定'))
    b.close()
json.dump(res,open(os.environ['OUT']+'/result.json','w'),ensure_ascii=False)
print(sum(1 for r in res if r[1]),'/',len(res))
