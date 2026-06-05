"""
sr_stage3_legacy_integration.py — 段階 3: 旧ガイドライン統合

以下を実装：
  1. 旧ガイドラインから文献を抽出
  2. 新規 PubMed 検索結果と統合
  3. 同じ SR パイプラインで処理
  4. 新旧ガイドラインの比較分析
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum


class EvidenceSource(Enum):
    """エビデンスの出所"""
    LEGACY_GUIDELINE = "旧ガイドライン"
    NEW_PUBMED_SEARCH = "新規 PubMed 検索"
    SUPPLEMENTARY_PDF = "補足 PDF"


@dataclass
class LegacyCitation:
    """旧ガイドラインからの引用"""
    pmid: str
    doi: str
    author: str
    year: int
    title: str
    source_page: int
    recommendation_context: str  # どの推奨で引用されたか
    quality_rating: Optional[str] = None  # 旧ガイドラインでの評価


@dataclass
class IntegratedEvidence:
    """統合されたエビデンス"""
    pmid: str
    original_source: EvidenceSource
    legacy_data: Optional[LegacyCitation] = None
    new_data: Optional[Dict[str, Any]] = None
    combined_rob2: Optional[Dict[str, Any]] = None
    status: str = "Active"  # Active, Superseded, Enhanced


class Stage3LegacyIntegrator:
    """旧ガイドライン統合エンジン"""

    def __init__(self, output_dir: str = "./sr_output/stage3"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.legacy_citations: Dict[str, LegacyCitation] = {}
        self.new_evidence: Dict[str, Dict[str, Any]] = {}
        self.integrated_evidence: Dict[str, IntegratedEvidence] = {}

    def extract_legacy_citations(self, legacy_data: List[Dict[str, Any]]) -> None:
        """旧ガイドラインから引用を抽出"""
        print("[段階 3A] 旧ガイドラインから引用を抽出中...")

        for item in legacy_data:
            pmid = item.get("pmid", "")
            if pmid:
                legacy_citation = LegacyCitation(
                    pmid=pmid,
                    doi=item.get("doi", ""),
                    author=item.get("author", ""),
                    year=item.get("year", 0),
                    title=item.get("title", ""),
                    source_page=item.get("page", 0),
                    recommendation_context=item.get("context", ""),
                    quality_rating=item.get("quality", None)
                )
                self.legacy_citations[pmid] = legacy_citation

        print(f"  ✅ {len(self.legacy_citations)} 件の旧引用を抽出")

    def add_new_evidence(self, pmid: str, evidence_data: Dict[str, Any]) -> None:
        """新規エビデンスを追加"""
        self.new_evidence[pmid] = evidence_data

    def integrate_evidence(self) -> Dict[str, IntegratedEvidence]:
        """エビデンスを統合"""
        print("[段階 3B] エビデンスを統合中...")

        # 旧ガイドラインの引用をベースに統合
        for pmid, legacy_citation in self.legacy_citations.items():
            if pmid in self.new_evidence:
                # 新旧両方にある場合：Enhanced
                status = "Enhanced"
            else:
                # 旧のみ：Active（新規検索で再評価が必要）
                status = "Active"

            integrated = IntegratedEvidence(
                pmid=pmid,
                original_source=EvidenceSource.LEGACY_GUIDELINE,
                legacy_data=legacy_citation,
                new_data=self.new_evidence.get(pmid),
                status=status
            )
            self.integrated_evidence[pmid] = integrated

        # 新規のみの場合も追加
        for pmid, new_data in self.new_evidence.items():
            if pmid not in self.integrated_evidence:
                integrated = IntegratedEvidence(
                    pmid=pmid,
                    original_source=EvidenceSource.NEW_PUBMED_SEARCH,
                    new_data=new_data,
                    status="New"
                )
                self.integrated_evidence[pmid] = integrated

        print(f"  ✅ {len(self.integrated_evidence)} 件のエビデンスを統合")
        return self.integrated_evidence

    def generate_integration_summary(self) -> str:
        """統合レポートを生成"""
        summary = f"""# 旧ガイドライン統合レポート

**統合日**: {datetime.now().isoformat()}

---

## サマリー

- **旧ガイドラインからの引用**: {len(self.legacy_citations)}
- **新規 PubMed 検索**: {len([e for e in self.integrated_evidence.values() if e.original_source == EvidenceSource.NEW_PUBMED_SEARCH])}
- **統合済みエビデンス**: {len(self.integrated_evidence)}

### ステータス別集計

"""

        status_counts = {}
        for evidence in self.integrated_evidence.values():
            status = evidence.status
            status_counts[status] = status_counts.get(status, 0) + 1

        for status, count in status_counts.items():
            summary += f"- {status}: {count}\n"

        summary += """

---

## 詳細分析

### Enhanced（新旧両方で評価）

"""

        enhanced_list = [e for e in self.integrated_evidence.values() if e.status == "Enhanced"]
        for evidence in enhanced_list:
            summary += f"""
**PMID {evidence.pmid}** - {evidence.legacy_data.author if evidence.legacy_data else 'N/A'}
- 旧評価: {evidence.legacy_data.quality_rating if evidence.legacy_data else 'N/A'}
- 新評価: {evidence.new_data.get('rob2', 'N/A') if evidence.new_data else 'N/A'}
- 推奨文脈: {evidence.legacy_data.recommendation_context if evidence.legacy_data else 'N/A'}

"""

        summary += """

### Active（旧ガイドラインから）

"""

        active_list = [e for e in self.integrated_evidence.values() if e.status == "Active"]
        for evidence in active_list[:5]:  # 最初の 5 つ
            summary += f"""
**PMID {evidence.pmid}** - {evidence.legacy_data.author if evidence.legacy_data else 'N/A'} ({evidence.legacy_data.year if evidence.legacy_data else '?'})
- 旧推奨文脈: {evidence.legacy_data.recommendation_context if evidence.legacy_data else 'N/A'}
- 新データ: 未評価（要再審査）

"""

        if len(active_list) > 5:
            summary += f"... 他 {len(active_list) - 5} 件\n"

        summary += """

### New（新規 PubMed 検索）

"""

        new_list = [e for e in self.integrated_evidence.values() if e.status == "New"]
        for evidence in new_list[:5]:
            summary += f"**PMID {evidence.pmid}** - {evidence.new_data.get('author', 'N/A') if evidence.new_data else 'N/A'}\n"

        if len(new_list) > 5:
            summary += f"... 他 {len(new_list) - 5} 件\n"

        summary += """

---

## 推奨事項

1. **Enhanced エビデンス**の新旧評価の比較
   - 旧ガイドラインでの評価が現在も妥当か確認
   - 新規データで更新が必要か判断

2. **Active エビデンス**の再評価
   - 旧ガイドラインの理由を確認
   - 新しい RoB2 で評価

3. **New エビデンス**の統合
   - 新規検索結果を既存の推奨に組み込む
   - 推奨の更新が必要か判断

---

"""

        return summary

    def generate_comparison_analysis(self) -> str:
        """新旧ガイドラインの比較分析"""
        comparison = f"""# 新旧ガイドラインの比較分析

**分析日**: {datetime.now().isoformat()}

---

## エビデンスベースの変化

### 旧ガイドラインのエビデンス
- 総引用数: {len(self.legacy_citations)}
- 平均発行年: {sum(c.year for c in self.legacy_citations.values()) / max(1, len(self.legacy_citations)):.0f}

### 新規検索のエビデンス
- 新規エビデンス数: {len([e for e in self.integrated_evidence.values() if e.status == 'New'])}
- 強化されたエビデンス: {len([e for e in self.integrated_evidence.values() if e.status == 'Enhanced'])}

---

## 推奨への影響

| 推奨レベル | 旧ガイドライン | 新統合版 | 変化 |
|---|---|---|---|
| 強い推奨 | ? | ? | ? |
| 弱い推奨 | ? | ? | ? |
| 条件付き推奨 | ? | ? | ? |
| 推奨しない | ? | ? | ? |

---

## 主な変化

1. エビデンスレベルの向上/低下
2. 新規重要研究の追加
3. 推奨強度の変更の可能性

---

"""

        return comparison

    def save_all_outputs(self) -> None:
        """全て の出力を保存"""
        # 統合サマリー
        summary = self.generate_integration_summary()
        summary_file = self.output_dir / "Integration_Summary.md"
        summary_file.write_text(summary, encoding="utf-8")
        print(f"✅ 統合レポート: {summary_file}")

        # 比較分析
        comparison = self.generate_comparison_analysis()
        comparison_file = self.output_dir / "Comparison_Analysis.md"
        comparison_file.write_text(comparison, encoding="utf-8")
        print(f"✅ 比較分析: {comparison_file}")

        # JSON 形式の統合データ
        integrated_json = {
            "analysis_date": datetime.now().isoformat(),
            "summary": {
                "legacy_citations": len(self.legacy_citations),
                "new_evidence": len([e for e in self.integrated_evidence.values() if e.original_source == EvidenceSource.NEW_PUBMED_SEARCH]),
                "integrated_total": len(self.integrated_evidence)
            },
            "evidence": {
                pmid: {
                    "status": e.status,
                    "original_source": e.original_source.value,
                    "legacy": asdict(e.legacy_data) if e.legacy_data else None,
                    "new": e.new_data
                }
                for pmid, e in self.integrated_evidence.items()
            }
        }
        json_file = self.output_dir / "Integrated_Evidence.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(integrated_json, f, ensure_ascii=False, indent=2)
        print(f"✅ 統合データ JSON: {json_file}")


def main():
    """サンプル実行"""
    integrator = Stage3LegacyIntegrator()

    # サンプル：旧ガイドラインの引用
    legacy_data = [
        {
            "pmid": "12345678",
            "doi": "10.1234/example1",
            "author": "Smith J",
            "year": 2019,
            "title": "Original exercise study",
            "page": 45,
            "context": "CQ1: 運動の推奨強度に関連",
            "quality": "Moderate"
        },
        {
            "pmid": "87654321",
            "doi": "10.1234/example2",
            "author": "Johnson M",
            "year": 2018,
            "title": "Safety of exercise in cancer",
            "page": 52,
            "context": "安全性に関する重要な研究",
            "quality": "Low"
        }
    ]

    integrator.extract_legacy_citations(legacy_data)

    # 新規検索結果
    new_data = {
        "12345678": {
            "author": "Smith J et al",
            "year": 2024,
            "evidence": "Meta-analysis",
            "rob2": "Some concerns"
        },
        "11111111": {
            "author": "New Author",
            "year": 2023,
            "evidence": "RCT",
            "rob2": "Low"
        }
    }

    for pmid, data in new_data.items():
        integrator.add_new_evidence(pmid, data)

    # 統合実行
    integrator.integrate_evidence()

    # 出力を保存
    integrator.save_all_outputs()

    # サマリーを表示
    print("\n" + integrator.generate_integration_summary())


if __name__ == "__main__":
    main()
