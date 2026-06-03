# RAG → RC-1/RC-5生成 → RAG再現性評価プロトコル

## 1. 入力とゴールドデータ
ゴールドデータはCQ単位でJSON化する。最低限、`cq`、`pico.P/I/C/O`、`recommendation_direction`、`recommendation_strength`、`evidence_certainty`、`recommendation_text`、`etd_judgments`、`references`を持たせる。採用文献はPMIDまたはDOIを正規化して評価する。

## 2. 生成パイプライン
1. p129-p146のエビデンス評価シート・エビデンス総体、p147以降の定性的システマティックレビュー、本文の推奨・作成経過をチャンク化する。
2. EtD項目をCQ単位に構造化し、各チャンクのメタデータに`etd_metadata`として付与する。
3. ChromaDBでRAG検索を行い、CQ別にPICO、エビデンス総体、定性的SR、益害、価値観・負担、合意形成の各アスペクトを検索する。
4. Bedrock APIでRC-1草案とRC-5推奨作成過程を生成する。
5. 生成物から評価用構造化JSONを抽出する。

## 3. 評価項目と指標
| 評価項目 | 指標 |
|---|---|
| CQ抽出 | 完全一致率 |
| PICO抽出 | P/I/C完全一致率、O再現率・F1 |
| 推奨方向 | 一致率 |
| 推奨の強さ | 一致率 |
| エビデンスの強さ | 一致率 |
| 推奨文 | 意味的一致率、BLEU系補助指標 |
| EtD判断 | 項目別一致率 |
| 採用文献リスト | PMID/DOIベースF1 |
| 推奨作成経過 | 内容妥当性、事実整合性、根拠なし記述率 |
| 専門家評価 | 「使用可能」判定率 |

## 4. 合格基準
| 項目 | 合格基準 |
|---|---:|
| CQ抽出 | 100% |
| PICO抽出 | P/I/Cは90%以上、Oは80%以上 |
| 推奨方向 | 100% |
| 推奨の強さ | 90%以上 |
| エビデンスの強さ | 90%以上 |
| 採用文献リスト | PMID/DOIベースで90%以上 |
| EtD主要項目 | 80%以上 |
| 根拠なし記述 | 5%未満 |
| 専門家による「使用可能」判定 | 80%以上 |

## 5. 実行例
```bash
python minds_rag_generator_fixed.py \
  --cq CQ1 \
  --input_file data/metadata/cancer_chunks_etd.jsonl \
  --output_dir results/generations \
  --bedrock_model_id "$BEDROCK_MODEL_ID"

python minds_rag_evaluator.py \
  --gold gold/CQ1_gold.json \
  --pred results/generations/CQ1_prediction_structured.json \
  --prediction_text results/generations/CQ1_RC5_process.md \
  --retrieval_trace results/retrievals/CQ1_retrieval_trace.json \
  --semantic \
  --fact_check \
  --expert_csv expert/CQ1_usability.csv \
  --output results/evaluation/CQ1_evaluation_report.json
```

## 6. 実装上の注意
Fact consistencyは、文字列一致だけでは不十分なため、RAG取得チャンクを根拠としてLLM-as-judgeで「根拠なし記述」を抽出する。ただし、最終判定には専門家レビューを併用する。BLEUは語順・表層一致の補助指標であり、推奨文の合否主指標は意味的一致率と専門家判定に置く。
