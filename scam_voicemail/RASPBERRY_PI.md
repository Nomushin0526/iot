# Raspberry Pi 5 + Thonny で合成データを生成する手順

ターミナル（メニュー → アクセサリ → LXTerminal、または Thonny の「ツール → システムシェルを開く」）で
コマンドを実行し、Python スクリプトは Thonny で実行する。

## 0. ラズパイの状態を確認

```bash
uname -m          # aarch64 なら OK（armv7l = 32bit OS は Ollama 非対応）
free -h           # Mem の total でメモリ量を確認 → 手順3のモデル選びに使う
df -h ~           # 空きディスク。モデル1つで 3〜8GB 使う
```

## 1. Ollama があるか確認

```bash
ollama --version
```

- `ollama version is 0.x.x` と出る → 入っている。手順2は飛ばして下の起動確認へ
- `command not found` → 入っていない。手順2へ

起動確認:

```bash
curl http://localhost:11434/api/version
```

`{"version":"..."}` が返れば起動中。`Connection refused` なら `sudo systemctl start ollama` を実行してから再確認。

## 2. Ollama をインストール（無い場合のみ）

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

インストール後は自動で起動し、再起動後も自動起動する。手順1の起動確認をもう一度行う。

## 3. Gemma モデルをダウンロード

メモリ量（手順0の `free -h`）で選ぶ:

| メモリ | モデル | 備考 |
|---|---|---|
| 8GB | `gemma3:4b` | 日本語がやや不自然になることがある |
| 16GB | `gemma3:12b` | 自然な日本語。ただし4bの数倍遅い |

```bash
ollama pull gemma3:4b
ollama run gemma3:4b "留守番電話のメッセージを1つ書いて"
```

返事が出れば OK（`/bye` で抜ける）。

## 4. コードを取得

```bash
cd ~
git clone -b ollama-backend https://github.com/Nomushin0526/iot.git
```

## 5. Python 環境を作って Thonny に設定

Raspberry Pi OS ではシステムの Python に直接 pip install できないため、専用の環境（venv）を作る。
ラズパイで必要なパッケージは `openai` だけ（Ollama との通信に使う。OpenAI に課金はされない）。

```bash
python3 -m venv ~/iot-venv
~/iot-venv/bin/pip install openai
```

Thonny で:
1. 「ツール」→「オプション」→「インタープリター」タブ
   （英語表示なら Tools → Options → Interpreter）
2. 種類で「ローカル Python 3」を選ぶ
3. 「Python実行ファイル」に `/home/<ユーザー名>/iot-venv/bin/python3` を指定して OK
   （`<ユーザー名>` はターミナルで `whoami` を実行すると分かる）
4. 下のシェル欄に `>>> import openai` と打ってエラーが出なければ成功

## 6. 合成データを生成（03）

1. Thonny で `~/iot/scam_voicemail/scripts/03_generate_synthetic.py` を開く
2. 緑の「実行」ボタン（F5）
3. `backend = llm:ollama:gemma3:4b` と表示され、数分ごとに `[batch 1] ...` が増えていけば正常

- 引数は不要。APIキーが無く Ollama が起動していれば自動で Ollama を使い、入っているモデルのうち
  一番大きい Gemma（12b → 4b の順）を選ぶ
- **まず1バッチの所要時間を見る。** 必要なのはおよそ150〜250バッチなので、全体の時間を見積もれる
- 「停止」ボタン（Ctrl+F2）でいつでも止めてよい。もう一度「実行」すれば続きから生成する
- 長時間フル稼働するので、アクティブクーラー推奨。温度は `vcgencmd measure_temp` で確認（80℃超で性能低下）

## 7. ノイズ付与と分割（04）

03 が `synthetic total = 1435` と表示して終わったら、Thonny で
`~/iot/scam_voicemail/scripts/04_augment_noise.py` を開いて実行。数秒で終わり、カテゴリ別の件数表が出る。

出力:
- `~/iot/scam_voicemail/data/train.jsonl`（1,600件）
- `~/iot/scam_voicemail/data/val.jsonl`（400件）
- `~/iot/scam_voicemail/data/dataset.jsonl`（全2,000件）

## 困ったとき

| 症状 | 対処 |
|---|---|
| `Ollamaに接続できません` | `sudo systemctl start ollama` |
| `モデル ... が未インストールです` | 表示された `ollama pull ...` を実行 |
| `llama-server process has terminated: signal: killed` | メモリ不足。小さいモデルにする（自動でリトライはする） |
| `ModuleNotFoundError: No module named 'openai'` | 手順5の Thonny インタープリター設定を確認 |
| 生成をやり直したい | `data/processed/synthetic.jsonl` を削除してから 03 を実行 |
