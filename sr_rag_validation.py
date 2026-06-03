"""
sr_rag_validation.py — RAG精度検証

既知のQ&A セットで RAG検索を検証
- 正しいCQから回答が得られるか
- 別CQのテキストが混ざっていないか
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import chromadb
from chromadb.utils import embedding_functions

sys.path.insert(0, str(Path(__file__).parent))
from build_and_search_chromadb import build_chromadb, search_chromadb


# 検証用 Q&A ペア（cancer_survivor_guidelines.pdf から）
VALIDATION_CASES = [
    {
        "cq": "CQ 1",
        "query": "運動習慣のない18～64歳のがんサバイバーに運動を勧めるべきか",
        "expected_keywords": ["18～64", "運動習慣", "推奨", "QoL"],
        "should_not_contain": ["65歳以上"],  # CQ2の内容
    },
    {
        "cq": "CQ 1",
        "query": "がんサバイバーの持久性体力改善",
        "expected_keywords": ["持久性体力", "メタアナリシス", "SMD"],
        "should_not_contain": ["高齢者"],
    },
    {
        "cq": "CQ 2",
        "query": "65歳以上のがんサバイバーへの運動推奨",
        "expected_keywords": ["65歳以上", "運動", "推奨"],
        "should_not_contain": ["18～64"],  # CQ1の内容
    },
    {
        "cq": "CQ 1",
        "query": "益と害のバランス評価",
        "expected_keywords": ["QoL", "倦怠感", "有害事象"],
        "should_not_contain": ["CQ 2"],
    },
]


def evaluate_retrieval(
    result: Dict[str, Any],
    case: Dict[str, Any]
) -> Dict[str, Any]:
    """
    検索結果を評価
    """
    content = result.get('content', '')
    metadata = result.get('metadata', {})

    # CQ一致性
    cq_match = metadata.get('Chapter_or_CQ') == case['cq']

    # 期待キーワードの有無
    keywords_found = sum(1 for kw in case['expected_keywords'] if kw in content)
    keywords_coverage = keywords_found / len(case['expected_keywords'])

    # コンタミチェック
    contaminated = any(term in content for term in case['should_not_contain'])

    return {
        'cq_match': cq_match,
        'keywords_coverage': keywords_coverage,
        'contaminated': contaminated,
        'section': metadata.get('Section', 'unknown'),
        'content_preview': content[:100] + '...',
    }


def run_rag_validation(chunks_file: str) -> None:
    """
    RAG検証を実行
    """
    import sys

    print(f"""
╔══════════════════════════════════════════════════════════╗
║  RAG精度検証 - cancer_survivor_guidelines.pdf          ║
║  コンタミなし、CQ厳格分離の確認                        ║
╚══════════════════════════════════════════════════════════╝
    """)

    # ChromaDB構築
    print("【Step 1】ChromaDB構築中...")
    try:
        from build_and_search_chromadb import parse_chunks_file
        chunks = parse_chunks_file(chunks_file)
        print(f"  ✅ {len(chunks)}件のチャンクを読み込み")
    except Exception as e:
        print(f"  ❌ エラー: {e}")
        return

    client, collection = build_chromadb(chunks)

    # 検証実行
    print("\n【Step 2】検証用Q&Aで検索テスト...")
    results_summary = {
        'total_cases': len(VALIDATION_CASES),
        'cq_match_count': 0,
        'no_contamination_count': 0,
        'keyword_coverage_avg': 0.0,
        'details': []
    }

    for case_idx, case in enumerate(VALIDATION_CASES, 1):
        print(f"\n  [{case_idx}/{len(VALIDATION_CASES)}] {case['query'][:50]}...")

        results = search_chromadb(collection, case['query'], cq_filter=case['cq'], top_k=3)

        if not results:
            print(f"    ⚠️  検索結果なし")
            continue

        top_result = results[0]
        eval_result = evaluate_retrieval(top_result, case)

        results_summary['details'].append({
            'query': case['query'],
            'cq': case['cq'],
            'evaluation': eval_result,
        })

        # スコア集計
        if eval_result['cq_match']:
            results_summary['cq_match_count'] += 1
        if not eval_result['contaminated']:
            results_summary['no_contamination_count'] += 1
        results_summary['keyword_coverage_avg'] += eval_result['keywords_coverage']

        # 結果表示
        status = "✅" if (eval_result['cq_match'] and not eval_result['contaminated']) else "⚠️"
        print(f"    {status} CQ一致: {eval_result['cq_match']}, "
              f"コンタミ: {eval_result['contaminated']}, "
              f"キーワード: {eval_result['keywords_coverage']:.1%}")
        print(f"       セクション: {eval_result['section']}")

    # サマリー
    results_summary['keyword_coverage_avg'] /= max(1, len(VALIDATION_CASES))

    print(f"""
╔══════════════════════════════════════════════════════════╗
║  検証結果サマリー                                      ║
╚══════════════════════════════════════════════════════════╝

  総テストケース数: {results_summary['total_cases']}
  CQ一致率: {results_summary['cq_match_count']}/{results_summary['total_cases']} ({100*results_summary['cq_match_count']/results_summary['total_cases']:.0f}%)
  コンタミなし率: {results_summary['no_contamination_count']}/{results_summary['total_cases']} ({100*results_summary['no_contamination_count']/results_summary['total_cases']:.0f}%)
  キーワードカバレッジ平均: {results_summary['keyword_coverage_avg']:.1%}

  判定: """, end='')

    if (results_summary['cq_match_count'] == results_summary['total_cases'] and
            results_summary['no_contamination_count'] == results_summary['total_cases']):
        print("🟢 PASS - RAG精度良好")
    elif (results_summary['cq_match_count'] >= len(VALIDATION_CASES) * 0.8):
        print("🟡 MARGINAL - 改善推奨")
    else:
        print("🔴 FAIL - 根本的な改善が必要")

    # JSON出力
    output_json = "rag_validation_results.json"
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(results_summary, f, ensure_ascii=False, indent=2)
    print(f"\n  詳細: {output_json}")


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="RAG精度検証")
    parser.add_argument("--chunks-file", required=True, help="pdf_chunks.json")
    args = parser.parse_args()

    run_rag_validation(args.chunks_file)
