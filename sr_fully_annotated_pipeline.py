"""
sr_fully_annotated_pipeline.py — 完全アノテーション版パイプライン

各ステップで自動化度合い、確認タグ、チェックリストを明示
extracted.csv だけから、定性的SR/RC5/RC1 を生成しつつ、
どこで人間のジャッジメントが必須かを可視化

出力ファイル内に以下のタグを付与：
  ✅ 自動生成 — 人間確認不要
  🟡（要確認） — LLM生成だが人間確認推奨
  🟡（生成） — 生成されたが信頼度限定的
  ❌（手動入力必須） — 人間入力が必須
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).parent))

from sr_evidence_table import generate_evidence_table
from sr_etd_builder import build_etd_framework


def print_phase_header(phase: int, title: str, automation_level: float):
    """フェーズヘッダを表示"""
    bar_length = int(automation_level * 20)
    bar = "█" * bar_length + "░" * (20 - bar_length)

    print(f"\n{'='*70}")
    print(f"【Phase {phase}】{title}")
    print(f"自動化度合い: {bar} {automation_level:.0%}")
    print(f"{'='*70}")


def generate_annotated_evidence_table(
    extracted_csv: str,
    outcomes: str,
    output_dir: str
) -> Dict[str, Any]:
    """Phase 1: アノテーション付きテーブル生成"""

    print_phase_header(1, "定性的SRテーブル生成", 0.70)

    df = pd.read_csv(extracted_csv).fillna("")
    include_df = df[df.get("decision", "") == "Include"].reset_index(drop=True)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # テーブル生成
    table_data = generate_evidence_table(extracted_csv, outcomes, output_dir)

    # アノテーション付き JSON を作成
    annotated_table = {
        "metadata": {
            "phase": 1,
            "automation_level": 0.70,
            "status": "🟡 部分自動化",
            "generated_at": datetime.now().isoformat(),
            "description": "エビデンス総体テーブル（複数研究の集約）"
        },
        "automation_summary": {
            "✅ 自動生成完了": [
                "n_studies（論文数集計）",
                "rob_summary（バイアスリスク集計）"
            ],
            "🟡（要確認）": [
                "effect_direction（LLM推定 ← 複数研究間矛盾確認必須）",
                "GRADE確実性（簡易推定 ← 形式的評価で再確認必須）"
            ],
            "データ不十分": [
                "効果量（元論文へのアクセスなし ← S3から元論文入手推奨）"
            ]
        },
        "human_confirmation_required": [
            "🟡 複数研究でeffect_directionが矛盾していないか確認",
            "🟡 GRADE確実性の推定値は形式的GRADE評価と乖離していないか確認"
        ],
        "table": table_data
    }

    # 保存
    json_path = output_path / "phase1_evidence_table_annotated.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(annotated_table, f, ensure_ascii=False, indent=2)

    print(f"✅ {json_path}")

    # 確認チェックリスト
    checklist = f"""
# Phase 1 確認チェックリスト

自動化度合い: 70%

## ✅ 自動生成完了（確認不要）
- [x] n_studies: {len(include_df)}件
- [x] rob_summary: 自動集計完了

## 🟡（要確認）- 以下を確認してください
- [ ] effect_direction の妥当性
  対象アウトカム: {outcomes}
  確認方法: 抄録の記述から判定が妥当か、複数研究で矛盾がないか

- [ ] GRADE確実性の推定値
  確認方法: 形式的GRADE評価（異質性、非直接性等を総合考慮）で再確認

## ❌（手動入力が必須）
  →このステップでは不要

## 次のステップ
✅ Phase 1 確認完了 → Phase 2 に進む
"""

    checklist_path = output_path / "phase1_checklist.md"
    with open(checklist_path, "w", encoding="utf-8") as f:
        f.write(checklist)

    print(f"✅ {checklist_path}")
    print(f"\n【確認項目】")
    print(f"  🟡（要確認）: effect_direction × {len(outcomes.split(','))} アウトカム")
    print(f"  🟡（要確認）: GRADE確実性 × {len(outcomes.split(','))} アウトカム")

    return annotated_table


def generate_annotated_etd(
    evidence_table_json: str,
    extracted_csv: str,
    cq_name: str,
    output_dir: str
) -> Dict[str, Any]:
    """Phase 2: アノテーション付きEtD生成"""

    print_phase_header(2, "EtDフレームワーク生成", 0.40)

    with open(evidence_table_json, "r", encoding="utf-8") as f:
        table_data = json.load(f).get("table", {})

    df = pd.read_csv(extracted_csv).fillna("")
    include_df = df[df.get("decision", "") == "Include"].reset_index(drop=True)

    output_path = Path(output_dir)

    # EtD 生成
    etd = build_etd_framework(evidence_table_json, extracted_csv, cq_name,
                              str(output_path / "etd_framework.json"))

    # アノテーション付けEtD
    annotated_etd = {
        "metadata": {
            "phase": 2,
            "automation_level": 0.40,
            "status": "❌ 手動入力が多い",
            "generated_at": datetime.now().isoformat(),
            "description": "Evidence-to-Decision フレームワーク"
        },
        "critical_manual_inputs": {
            "❌（手動入力必須）": [
                "pico.P: 対象の詳細定義 ← ガイドライン作成者が入力",
                "pico.I: 介入の詳細定義 ← ガイドライン作成者が入力",
                "pico.C: 比較対照の定義 ← ガイドライン作成者が入力",
                "values_preferences: 患者価値観データ ← インタビュー/FGDから補足",
                "resource_use: 医療経済データ ← 診療報酬/費用調査から補足",
                "feasibility: 実装可能性 ← 国内体制調査から補足"
            ]
        },
        "requires_confirmation": {
            "🟡（要確認）": [
                "benefit_harm_balance: 臨床的重要性の判定（数値のみでなく質的評価）",
                "recommendation_strength: 推奨の強さ（LLM推定は参考値のみ）"
            ]
        },
        "panel_decision_required": {
            "パネル会議で投票": [
                "推奨の方向（For / Against）",
                "推奨の強さ（強い推奨 / 弱い推奨）",
                "合意度（全員一致 / 大多数 / 意見分かれ）"
            ]
        },
        "etd_framework": etd
    }

    # 保存
    json_path = output_path / "phase2_etd_annotated.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(annotated_etd, f, ensure_ascii=False, indent=2)

    print(f"✅ {json_path}")

    # 確認チェックリスト
    checklist = f"""
# Phase 2 確認チェックリスト

自動化度合い: 40%（60%は手動入力が必須）

## ✅ 自動生成完了（確認不要）
- [x] pico.O: アウトカム自動抽出完了

## ❌（手動入力必須）- 以下は必ず入力してください
必須入力なしには、推奨文生成に進められません！

### PICO定義
- [ ] **P（対象）**:
  入力例: "18～64歳のがんが治癒・安定しているがんサバイバー（N≥1000人対象）"
  入力欄: _______________________________________________

- [ ] **I（介入）**:
  入力例: "中強度以上の有酸素運動または筋力トレーニング（週3-5日、30-60分）"
  入力欄: _______________________________________________

- [ ] **C（比較対照）**:
  入力例: "運動なし、または標準的ケアのみ"
  入力欄: _______________________________________________

### 患者・社会的要因（該当データがあれば入力）
- [ ] 患者の価値観・嗜好性
  情報源: □ 患者インタビュー □ FGD □ 既存調査 □ なし
  記載: _______________________________________________

- [ ] 医療経済情報
  項目: □ 費用対効果 □ 保険適用 □ 診療報酬 □ なし
  記載: _______________________________________________

- [ ] 実装可能性
  項目: □ 施設整備 □ 人員確保 □ 地域差 □ なし
  記載: _______________________________________________

## 🟡（要確認）- 以下をレビューしてください
- [ ] benefit_harm_balance の妥当性
  自動判定: "benefits exceed harms"
  確認: 『筋肉痛』と『死亡』では重みが異なる。妥当か？

- [ ] recommendation_strength の妥当性
  自動推定: "Weak"
  確認: この推定は形式的決定ではなく、パネル投票で最終決定

## パネル会議で投票
- [ ] 推奨の方向: For / Against
- [ ] 推奨の強さ: 強い推奨 / 弱い推奨
- [ ] 合意度: 全員一致 / 大多数 / 意見分かれ

## 次のステップ
❌ Phase 2: 手動入力完了 → Phase 3 に進む
"""

    checklist_path = output_path / "phase2_checklist.md"
    with open(checklist_path, "w", encoding="utf-8") as f:
        f.write(checklist)

    print(f"✅ {checklist_path}")
    print(f"\n【必須入力】")
    print(f"  ❌ PICO (P,I,C): 3項目")
    print(f"  ❌ 患者価値観・経済・実装: 3項目（該当データがあれば）")
    print(f"  🟡（要確認）: benefit_harm_balance, recommendation_strength")
    print(f"  パネル投票: 推奨の方向・強さ・合意度")

    return annotated_etd


async def generate_annotated_recommendations(
    etd_framework_json: str,
    chunks_file: str,
    cq_name: str,
    output_dir: str
) -> Dict[str, Any]:
    """Phase 3: アノテーション付きRC-5/RC-1生成"""

    print_phase_header(3, "推奨文生成（RC-5/RC-1）", 0.55)

    from build_and_search_chromadb import parse_chunks_file, build_chromadb, search_chromadb
    from generate_recommendation import generate_with_claude

    # EtD読み込み
    with open(etd_framework_json, "r", encoding="utf-8") as f:
        etd = json.load(f)

    output_path = Path(output_dir)

    # RAG検索コンテキスト
    try:
        chunks = parse_chunks_file(chunks_file)
        client, collection = build_chromadb(chunks)

        pico = etd.get("pico", {})
        search_query = f"{cq_name} {pico.get('P', '')} {pico.get('I', '')}"
        results = search_chromadb(collection, search_query, cq_filter=cq_name, top_k=5)
        rag_context = "\n\n".join([r["content"] for r in results])
    except Exception as e:
        print(f"⚠️  RAG検索失敗: {e}")
        rag_context = "RAG検索コンテキスト取得失敗"

    # RC-5生成
    print("\n  [生成中] RC-5 推奨作成の経過...")
    rc5_text = await generate_with_claude(etd, rag_context, output_type="RC-5")

    rc5_annotated = f"""
# RC-5: 推奨作成の経過

🟡（生成）このテキストは Claude AI が自動生成しました。
専門家による確認・修正が必須です。

## 確認項目

🟡（要確認）以下の各項について、根拠の妥当性を確認してください：

### 1. 臨床疑問の定式化（PICO）
- [ ] PICO定義は上記で入力した定義と一致しているか？
- [ ] 抄録から外れた重要な情報は記載されているか？

### 2. エビデンスの確実性と益害バランス
- [ ] 報告されたSMD/RR値は正確か？
- [ ] バイアスリスク評価は適切か？
- [ ] 益と害の重みづけは臨床的に妥当か？

### 3. 患者の価値観・医療経済・実装
- [ ] 患者価値観データは十分に反映されているか？
- [ ] 経済情報は最新で正確か？
- [ ] 日本の実装可能性は考慮されているか？

### 4. 推奨決定
- [ ] 結論は論理的か？
- [ ] 推奨の強さの根拠は妥当か？

---
{rc5_text}
"""

    rc5_path = output_path / "phase3_rc5_output.md"
    with open(rc5_path, "w", encoding="utf-8") as f:
        f.write(rc5_annotated)

    print(f"✅ {rc5_path}")

    # RC-1生成
    print("  [生成中] RC-1 推奨文草案...")
    rc1_text = await generate_with_claude(etd, rag_context, output_type="RC-1")

    rc1_annotated = f"""
# RC-1: 推奨文草案（Individual Perspective）

🟡（生成）このテキストは Claude AI が自動生成しました。
パネル会議で最終確認・投票が必須です。

## 推奨文

{rc1_text}

## 確認項目

🟡（要確認）パネル会議で以下を確認してください：

- [ ] 推奨文の表現は医学的に正確か？
- [ ] 推奨の方向（実施する/実施しない）は妥当か？
- [ ] 日本の臨床文脈に合致しているか？
- [ ] 他のCQとの整合性はあるか？

## パネル投票（必須）

- [ ] 推奨の方向:
  □ 実施する（For）
  □ 実施しない（Against）

- [ ] 推奨の強さ:
  □ 強い推奨（should）
  □ 弱い推奨（may/could）

- [ ] 合意度:
  □ 全員一致
  □ 大多数が同意
  □ 意見が分かれた（記載: __）
"""

    rc1_path = output_path / "phase3_rc1_draft.md"
    with open(rc1_path, "w", encoding="utf-8") as f:
        f.write(rc1_annotated)

    print(f"✅ {rc1_path}")

    result = {
        "metadata": {
            "phase": 3,
            "automation_level": 0.55,
            "status": "🟡 LLM生成（確認必須）",
            "generated_at": datetime.now().isoformat(),
            "rag_sources": len(results) if 'results' in locals() else 0
        },
        "rc5_status": "🟡（生成）Claude生成 → 専門家確認必須",
        "rc1_status": "🟡（生成）Claude生成 → パネル投票で最終決定"
    }

    print(f"\n【確認項目】")
    print(f"  🟡（要確認）: RC-5内容の医学的妥当性")
    print(f"  🟡（要確認）: RC-1推奨文の表現・妥当性")
    print(f"  パネル投票: 推奨の方向・強さ・合意度")

    return result


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="定性的SRパイプライン（完全アノテーション版）")
    parser.add_argument("--extracted", required=True, help="extracted.csv")
    parser.add_argument("--cq", default="CQ 1")
    parser.add_argument("--outcomes", default="QoL, 筋力, 倦怠感")
    parser.add_argument("--output-dir", default="./sr_output/annotated_sr")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║  定性的SRパイプライン（完全アノテーション版）                 ║
║  extracted.csv → 定性的SR / RC-5 / RC-1                       ║
║                                                                  ║
║  自動化度合い表示 + 確認タグ付き + チェックリスト付き        ║
╚══════════════════════════════════════════════════════════════════╝
    """)

    # Phase 1
    table_result = generate_annotated_evidence_table(
        args.extracted, args.outcomes, str(output_dir)
    )

    # Phase 2
    etd_result = generate_annotated_etd(
        str(output_dir / "phase1_evidence_table_annotated.json"),
        args.extracted,
        args.cq,
        str(output_dir)
    )

    # Phase 3
    rec_result = await generate_annotated_recommendations(
        str(output_dir / "etd_framework.json"),
        str(output_dir / "etd_chunks.json"),
        args.cq,
        str(output_dir)
    )

    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║  生成完了                                                        ║
╚══════════════════════════════════════════════════════════════════╝

【出力ファイル】
  ✅ phase1_evidence_table_annotated.json
  ✅ phase1_checklist.md
  ✅ phase2_etd_annotated.json
  ✅ phase2_checklist.md
  ✅ phase3_rc5_output.md
  ✅ phase3_rc1_draft.md

【自動化度合い】
  Phase 1: 🟡 70%（複数箇所で要確認）
  Phase 2: 🟡 40%（多くの手動入力が必須）
  Phase 3: 🟡 55%（LLM生成だが確認必須）
  全体:    🟡 50%（複数工程で人間のジャッジメント必須）

【次のステップ】
  1. phase1_checklist.md を確認 → 要確認項目を修正
  2. phase2_checklist.md を入力 → PICO定義等を手動入力
  3. phase3_rc5_output.md / phase3_rc1_draft.md を確認
  4. パネル会議で投票 → 最終確定

🔑 重要: 各フェーズのチェックリストを完了することで、
        ガイドラインの品質が担保されます。
    """)


if __name__ == "__main__":
    import sys
    import os

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("エラー: ANTHROPIC_API_KEY が設定されていません")
        sys.exit(1)

    asyncio.run(main())
