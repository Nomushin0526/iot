# 留守番電話 詐欺判定データセット構築パイプライン

Raspberry Pi 5 上で動かす軽量テキスト分類器（詐欺・不審=1 / 正常=0）の学習データを作る。

## 実行手順

```bash
pip install -r requirements.txt
cd scripts
python 01_fetch_hf_data.py          # HF英語データ → data/raw/hf_en_data.jsonl (各ラベル250件)
python 02_create_seed_data.py       # 手書きシード → data/raw/seed_data.jsonl (65件, 8カテゴリ)
python 03_generate_synthetic.py     # LLMで水増し → data/processed/synthetic.jsonl (不足分のみ)
python 04_augment_noise.py          # ASRノイズ30% + 統合 + 層化分割
```

### ローカルLLM（Ollama, 無料）で生成する場合

Raspberry Pi + Thonny での手順は [RASPBERRY_PI.md](RASPBERRY_PI.md)。
APIキーが無く Ollama が起動していれば、引数なしでも自動で Ollama を使う。

```bash
ollama pull gemma3:12b
python 03_generate_synthetic.py --backend ollama --model gemma3:12b
```

`OLLAMA_HOST`（既定 `http://localhost:11434`）で別マシンのOllamaも指定できる。
小型モデルは「〇〇様」「XXXX」のような伏せ字を出しがちなので、該当する出力は自動で捨てている。
`--categories refund_scam,relative_scam` のように対象カテゴリを絞れるので、
カテゴリやモデルを分けて生成し、文体の偏りを減らすこともできる。

`03` は `OPENAI_API_KEY` → `ANTHROPIC_API_KEY` → `GEMINI_API_KEY` の順で見つかったものを使う。
モデルは `--model` または `OPENAI_MODEL` / `ANTHROPIC_MODEL` / `GEMINI_MODEL` で変更可能。
10件ずつ生成して追記するので、中断しても再実行すれば続きから生成する。
キーが無い場合は `--backend template`（オフラインのテンプレ生成）で全工程を通せるが、
**テンプレ生成データは簡単すぎ（文字n-gram+ロジスティック回帰で val 100%）なので学習には使わないこと**。
テンプレ版を作り直す場合は `data/processed/synthetic.jsonl` を消してからLLMで再生成する。

## 出力

| ファイル | 内容 |
|---|---|
| `data/dataset.jsonl` | ノイズ付与後の全2,000件 |
| `data/train.jsonl` / `data/val.jsonl` | 80/20、label×categoryで層化分割 |
| `data/processed/all_clean.jsonl` | ノイズ付与前の統合データ |

スキーマ: `{"id", "text", "label", "category", "language", "source"}`。
ASRノイズを付与した行は `source` の末尾に `+asr_noise`。

## 構成比（目標値）

- label 1 (1,000): HF 250 + シード 37 + 合成 713（auto_voice_gov / intl_scam_zh_en / refund_scam / fake_police_billing / relative_scam を均等）
- label 0 (1,000): HF 250 + シード 28 + 合成 722（normal_auto_voice / normal_business / normal_personal を均等）
- 負例の約10%ずつを英語・中国語にして「中国語＝詐欺」の短絡学習を防いでいる
- ノイズは label×language ごとに同率(30%)で付与（ノイズの有無とラベルが相関しないように）

## ノイズの種類 (04)

句読点の全削除 / セグメント境界のスペース / 漢字→ひらがな / 同音異義語（口座→講座, 期限→機嫌 等）/
数字表記の揺れ（1番→一番, 1を→位置を）/ フィラー挿入 / 句の繰り返し / 録音の途中切れ /
Whisperの定番幻覚フレーズ（「ご視聴ありがとうございました」「字幕由Amara.org社区提供」等）/ 英語の同音語・小文字化 / 中国語の同音字。

## 注意点

- HFの `hf_telemarketing`（営業電話）は元データで正常(0)扱い。用途によっては不審扱いに変えるか除外を検討。
- HFデータは対話の caller 発話を連結して作っているため、真の留守電より会話的な文が混ざる。
- 評価用には、合成データとは別に実際の留守電の文字起こしを少数でも用意することを強く推奨。

## データの出典

- `data/raw/hf_en_data.jsonl`: [BothBosu/scam-dialogue](https://huggingface.co/datasets/BothBosu/scam-dialogue)（Apache-2.0）から抽出・整形
- `data/raw/seed_data.jsonl`: 本リポジトリで手書きした架空のシード（人名・番号・金額はすべて架空）
- `data/processed/` と `data/{dataset,train,val}.jsonl` は生成物のためリポジトリには含めない（03・04で再生成）
