"""
sr_pdf_advanced_parser.py — PDF 高度パーサ（SoF 表・RoB2 抽出版）

cancer_survivor_guidelines.pdf から以下を抽出：
  1. SoF 表（GRADE standard）→ HTML で出力
  2. RoB2 評価シート（7 ドメイン全て）
  3. メタデータ（PMID, DOI, CQ）
  4. SR 中間ファイル（テーブル形式）

仕様：
  - RoB2: 7 ドメイン（Selection Bias, Performance Bias, Detection Bias,
           Attrition Bias, Reporting Bias, Other Bias, Overall）
  - SoF: Outcome, Studies, Participants, Effect, Certainty
  - メタデータ: PMID/DOI ベース
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

import pdfplumber


@dataclass
class ROB2Domain:
    """RoB2 評価（1 ドメイン）"""
    domain_name: str  # e.g., "Selection Bias"
    risk_level: str  # "Low", "Some concerns", "High", "Not applicable"
    justification: str  # 根拠
    page_number: int


@dataclass
class ROB2Evaluation:
    """RoB2 評価シート（1 論文）"""
    pmid: str
    doi: str
    author: str
    year: int
    title: str
    domains: List[ROB2Domain]
    overall_risk: str  # "Low", "Some concerns", "High"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pmid": self.pmid,
            "doi": self.doi,
            "author": self.author,
            "year": self.year,
            "title": self.title,
            "domains": [asdict(d) for d in self.domains],
            "overall_risk": self.overall_risk,
        }


@dataclass
class SoFRow:
    """SoF 表の 1 行"""
    outcome: str
    n_studies: int
    n_participants: int
    effect_estimate: str  # e.g., "MD 2.5 (1.2 to 3.8)"
    certainty_of_evidence: str  # GRADE: "High", "Moderate", "Low", "Very low"
    comments: str


class PDFAdvancedParser:
    """cancer_survivor_guidelines.pdf 高度パーサ"""

    def __init__(self, pdf_path: str):
        self.pdf_path = Path(pdf_path)
        self.pages_content = []
        self.rob2_evaluations: List[ROB2Evaluation] = []
        self.sof_tables: Dict[str, List[SoFRow]] = {}
        self.metadata: Dict[str, Any] = {}

    def parse(self) -> None:
        """PDF をパース"""
        print(f"[パース開始] {self.pdf_path}")

        with pdfplumber.open(str(self.pdf_path)) as pdf:
            print(f"  総ページ数: {len(pdf.pages)}")

            # ページごとにテキスト抽出
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text()
                self.pages_content.append({
                    "page": page_num,
                    "text": text,
                    "tables": page.extract_tables() or []
                })

                if page_num % 20 == 0:
                    print(f"  進捗: {page_num}/{len(pdf.pages)}")

        print(f"✅ PDF パース完了")

    def extract_metadata(self) -> Dict[str, Any]:
        """メタデータ抽出（CQ, 発行年等）"""
        print("[メタデータ抽出中...]")

        # 全ページから CQ を検索
        cq_set = set()
        for page_info in self.pages_content[:10]:  # 最初の 10 ページから検索
            text = page_info["text"]
            cq_matches = re.findall(r"CQ\s*(\d+)", text, re.IGNORECASE)
            cq_set.update(cq_matches)

        # CQ ごとに詳細を抽出
        cq_details = {}
        for cq_num in sorted(cq_set):
            # CQ に関する記述を検索
            for page_info in self.pages_content[:50]:
                text = page_info["text"]
                if f"CQ{cq_num}" in text or f"CQ {cq_num}" in text:
                    # CQ の内容（次の 200 文字）
                    pattern = rf"CQ\s*{cq_num}[^\n]{{0,150}}"
                    match = re.search(pattern, text)
                    if match:
                        cq_details[f"CQ{cq_num}"] = match.group(0)
                    break

        self.metadata = {
            "cqs": sorted(list(cq_set)),
            "cq_details": cq_details,
            "total_pages": len(self.pages_content),
            "extraction_date": str(Path(self.pdf_path).stat().st_mtime),
        }

        print(f"  発見された CQ: {len(cq_set)} 個")
        for cq in sorted(list(cq_set)):
            print(f"    CQ{cq}: {cq_details.get(f'CQ{cq}', 'Details not found')[:80]}")

        return self.metadata

    def extract_rob2_evaluations(self) -> List[Dict[str, Any]]:
        """RoB2 評価シート抽出（7 ドメイン全て）"""
        print("\n[RoB2 評価抽出中...]")

        rob2_list: List[ROB2Evaluation] = []
        rob2_section_pattern = r"(Risk of Bias|バイアス|評価シート)"

        for page_info in self.pages_content:
            page_num = page_info["page"]
            text = page_info["text"]

            # RoB2 セクションかどうか判定
            if not re.search(rob2_section_pattern, text, re.IGNORECASE):
                continue

            # 著者・PMID を抽出
            author_match = re.search(r"([A-Z][a-z]+\s+[A-Z]\.)", text)
            pmid_match = re.search(r"PMID:?\s*(\d+)", text)
            doi_match = re.search(r"DOI:?\s*([^\s]+)", text)
            year_match = re.search(r"(\d{4})", text)

            if not pmid_match:
                continue

            pmid = pmid_match.group(1)
            doi = doi_match.group(1) if doi_match else "N/A"
            author = author_match.group(1) if author_match else "Unknown"
            year = int(year_match.group(1)) if year_match else 0
            title = self._extract_title(text, page_num)

            # 7 ドメイン抽出
            domains = self._extract_7_domains(text, page_num)

            # overall risk を算出
            risk_levels = [d.risk_level for d in domains if d.risk_level != "Not applicable"]
            if "High" in risk_levels:
                overall_risk = "High"
            elif "Some concerns" in risk_levels:
                overall_risk = "Some concerns"
            else:
                overall_risk = "Low"

            rob2 = ROB2Evaluation(
                pmid=pmid,
                doi=doi,
                author=author,
                year=year,
                title=title,
                domains=domains,
                overall_risk=overall_risk,
            )
            rob2_list.append(rob2)

        print(f"  抽出された論文数: {len(rob2_list)}")
        self.rob2_evaluations = rob2_list

        return [r.to_dict() for r in rob2_list]

    def _extract_7_domains(self, text: str, page_num: int) -> List[ROB2Domain]:
        """RoB2 の 7 ドメイン抽出"""
        domain_names = [
            "Selection Bias",
            "Performance Bias",
            "Detection Bias",
            "Attrition Bias",
            "Reporting Bias",
            "Other Bias",
            "Overall",
        ]

        domains: List[ROB2Domain] = []

        for domain in domain_names:
            # ドメイン名を探す
            pattern = rf"{domain}.*?(Low|Some concerns|High|Not applicable)"
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)

            if match:
                risk_level = match.group(1)
                # 根拠を抽出（最大 200 文字）
                start_idx = match.end()
                justification = text[start_idx:start_idx+200].split("\n")[0].strip()
            else:
                risk_level = "Not applicable"
                justification = ""

            domains.append(ROB2Domain(
                domain_name=domain,
                risk_level=risk_level,
                justification=justification,
                page_number=page_num,
            ))

        return domains

    def _extract_title(self, text: str, page_num: int) -> str:
        """タイトルを抽出"""
        lines = text.split("\n")
        for line in lines:
            if len(line) > 20 and len(line) < 300:
                return line.strip()
        return f"Page {page_num} Study"

    def extract_sof_tables(self) -> Dict[str, List[Dict[str, Any]]]:
        """SoF 表抽出"""
        print("\n[SoF 表抽出中...]")

        sof_dict: Dict[str, List[SoFRow]] = {}
        sof_section_pattern = r"(Summary of Findings|SoF|エビデンス総体)"

        for page_info in self.pages_content:
            page_num = page_info["page"]
            tables = page_info["tables"]

            # テーブルがあるページかチェック
            if not tables:
                continue

            for table in tables:
                # テーブル構造を分析
                rows = self._parse_table_as_sof(table, page_num)
                if rows:
                    cq = f"CQ_{page_num}"
                    sof_dict[cq] = rows

        print(f"  抽出された SoF 表: {len(sof_dict)} 個")
        self.sof_tables = sof_dict

        return {
            cq: [asdict(row) for row in rows]
            for cq, rows in sof_dict.items()
        }

    def _parse_table_as_sof(self, table: List[List[str]], page_num: int) -> List[SoFRow]:
        """テーブルを SoF 形式でパース"""
        if not table or len(table) < 2:
            return []

        rows: List[SoFRow] = []
        headers = [h for h in table[0] if h]  # None を除外

        if not headers:
            return []

        # ヘッダから列を特定
        outcome_col = self._find_column(headers, ["Outcome", "アウトカム"])
        studies_col = self._find_column(headers, ["Studies", "論文数"])
        certainty_col = self._find_column(headers, ["Certainty", "確実性"])

        if outcome_col is None:
            return []

        for row_data in table[1:]:
            if len(row_data) <= outcome_col or not row_data[outcome_col]:
                continue

            outcome = row_data[outcome_col] if outcome_col < len(row_data) else ""
            n_studies = len(re.findall(r"\d+", row_data[studies_col])) if studies_col and studies_col < len(row_data) else 0
            certainty = row_data[certainty_col] if certainty_col and certainty_col < len(row_data) else "Unknown"

            rows.append(SoFRow(
                outcome=outcome,
                n_studies=n_studies,
                n_participants=0,
                effect_estimate="",
                certainty_of_evidence=certainty,
                comments="",
            ))

        return rows

    def _find_column(self, headers: List[str], keywords: List[str]) -> Optional[int]:
        """キーワードから列番号を検索"""
        for col_idx, header in enumerate(headers):
            for keyword in keywords:
                if keyword.lower() in header.lower():
                    return col_idx
        return None

    def generate_sof_html(self, cq: str, output_file: str = None) -> str:
        """SoF 表を GRADE standard HTML で生成"""
        if cq not in self.sof_tables:
            return "<p>SoF table not found</p>"

        rows = self.sof_tables[cq]

        html = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #000; padding: 8px; text-align: left; }
    th { background-color: #f0f0f0; }
    .high { background-color: #d4edda; }
    .moderate { background-color: #fff3cd; }
    .low { background-color: #f8d7da; }
    .very-low { background-color: #f5c6cb; }
</style>
</head>
<body>
<h2>Summary of Findings (SoF) Table</h2>
<table>
<thead>
<tr>
<th>Outcome</th>
<th>No. of Studies</th>
<th>No. of Participants</th>
<th>Effect Estimate</th>
<th>Certainty of Evidence</th>
<th>Comments</th>
</tr>
</thead>
<tbody>
"""

        for row in rows:
            certainty_class = row.certainty_of_evidence.lower().replace(" ", "-")
            html += f"""<tr>
<td>{row.outcome}</td>
<td>{row.n_studies}</td>
<td>{row.n_participants if row.n_participants > 0 else '-'}</td>
<td>{row.effect_estimate if row.effect_estimate else '-'}</td>
<td class="{certainty_class}">{row.certainty_of_evidence}</td>
<td>{row.comments if row.comments else '-'}</td>
</tr>
"""

        html += """</tbody>
</table>
</body>
</html>
"""

        if output_file:
            Path(output_file).write_text(html, encoding="utf-8")
            print(f"✅ SoF HTML: {output_file}")

        return html

    def save_all_to_json(self, output_dir: str = "./sr_output") -> None:
        """全ての抽出結果を JSON に保存"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # RoB2
        rob2_file = output_path / "rob2_evaluations.json"
        with open(rob2_file, "w", encoding="utf-8") as f:
            json.dump(
                [r.to_dict() for r in self.rob2_evaluations],
                f,
                ensure_ascii=False,
                indent=2
            )
        print(f"✅ {rob2_file}")

        # SoF
        sof_file = output_path / "sof_tables.json"
        with open(sof_file, "w", encoding="utf-8") as f:
            sof_data = {
                cq: [asdict(row) for row in rows]
                for cq, rows in self.sof_tables.items()
            }
            json.dump(sof_data, f, ensure_ascii=False, indent=2)
        print(f"✅ {sof_file}")

        # メタデータ
        metadata_file = output_path / "pdf_metadata.json"
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)
        print(f"✅ {metadata_file}")

        # HTML (SoF)
        for cq in self.sof_tables.keys():
            html_file = output_path / f"sof_table_{cq}.html"
            self.generate_sof_html(cq, str(html_file))


def main():
    import argparse

    parser = argparse.ArgumentParser(description="PDF 高度パーサ（SoF・RoB2 抽出）")
    parser.add_argument("--pdf", required=True, help="PDF ファイルパス")
    parser.add_argument("--output-dir", default="./sr_output")
    args = parser.parse_args()

    parser_obj = PDFAdvancedParser(args.pdf)
    parser_obj.parse()
    parser_obj.extract_metadata()
    parser_obj.extract_rob2_evaluations()
    parser_obj.extract_sof_tables()
    parser_obj.save_all_to_json(args.output_dir)

    print("\n✅ 全ての抽出が完了しました")


if __name__ == "__main__":
    main()
