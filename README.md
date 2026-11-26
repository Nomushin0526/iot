# iot — 留守電の詐欺チェッカー (Raspberry Pi 5)

知らない番号からの留守番電話を、聞く前に「電話番号」と「話の内容」から判定し、
LED・7セグ・バーグラフで本人に、Slack で家族に知らせる装置。設計メモは [CLAUDE.md](CLAUDE.md)。

| ディレクトリ | 内容 |
|---|---|
| [`checker/`](checker/) | 本体（受信サーバー・文字起こし・判定・ハード制御・通知・ログ・評価） |
| `run_server.py` | 起動用（Thonny でこれを開いて実行） |
| `data/blacklist.csv` | 危険番号リスト |
| `deploy/fraud-checker.service` | 自動起動用 systemd サービス |
| `tests/` | PC で動くテスト（GPIO は模擬ピン） |
| [`scam_voicemail/`](scam_voicemail/) | 内容判定モデル用データセットの構築パイプライン |
| [`docs/NEXT_STEPS.md`](docs/NEXT_STEPS.md) | **残りの作業の手順**（モデルの学習・評価用データ・評価・Slack・iPhone） |

## 処理の流れ

```
iPhone ショートカット ─(m4a + 番号, POST /check)─▶ Raspberry Pi
  文字起こし (faster-whisper, Pi内)  → 番号判定 (blacklist.csv + ルール)
  → 内容判定 (LLM / Ollama / キーワード。外部送信前に名前・番号を伏せる)
  → 危険度 0〜9 → 7セグ・バーグラフ・RGB LED → しきい値以上で Slack
  → data/check_log.csv に記録
キーパッド: 番号を打って # → 番号だけで判定 / * クリア / D 1文字消す / A は「+」/ B 最後の結果を再表示
ボタン: 短押し → 最後の結果を家族に通知 / 2秒長押し → 表示リセット
```

危険度: 0〜3 安全(緑) / 4〜6 注意(黄) / 7〜9 危険(赤)。
内容 75% + 番号 25% で重み付けし、内容スコアそのものを下限とする（話がはっきり詐欺なら番号に関係なく危険）。
危険番号リストに一致した場合は最低でも 8。

## ラズパイでのセットアップ

```bash
cd ~/iot && git pull
# gpiozero / lgpio は OS 付属のものを使うので --system-site-packages を付けて venv を作る
python3 -m venv --system-site-packages ~/iot-venv
~/iot-venv/bin/pip install -r requirements.txt
cp .env.example .env      # 必要な値を書き込む (Slack の URL など)
```

以前 `--system-site-packages` なしで `~/iot-venv` を作った場合は、`rm -rf ~/iot-venv` してから作り直す。
Thonny のインタープリターは `~/iot-venv/bin/python3` を指定する（手順は `scam_voicemail/RASPBERRY_PI.md` の手順5）。

起動: Thonny で `run_server.py` を開いて実行（または `~/iot-venv/bin/python run_server.py`）。
7セグに「-」が出れば準備完了。初回は Whisper モデルのダウンロードに数分かかる。
結果画面: 同じネットワークの PC やスマホで `http://<ラズパイのIP>:8000/`（IP は `hostname -I` で確認）。

### 内容判定のバックエンド

`.env` の `CONTENT_BACKEND=auto` のとき、次の順で使えるものを選ぶ。

1. `ANTHROPIC_API_KEY` があれば Claude
2. `OPENAI_API_KEY` があれば OpenAI
3. Ollama が起動していれば Gemma（無料・Pi内で完結。ただし1件に数十秒〜数分）
4. どれも無ければキーワード判定

LLM が失敗した場合もキーワード判定に自動で切り替わる。外部に送るのは名前・番号・メールを伏せたテキストのみ。
自分や家族の名前は `MASK_NAMES` に書いておくと必ず伏せる。

## iPhone ショートカット「詐欺チェック」の作り方

1. ショートカット App →「＋」→ 名前を「詐欺チェック」にする
2. 下の「i」(詳細) →「共有シートに表示」をオン、受け付ける入力を「ファイル」(と「メディア」) にする
3. アクション「入力を要求」: 種類「数字」または「テキスト」、プロンプト「かけてきた電話番号」
4. アクション「URLの内容を取得」
   - URL: `http://<ラズパイのIP>:8000/check`
   - 方法: POST、本文を要求: **フォーム**
   - フィールド追加: `file` = 種類「ファイル」・値「ショートカットの入力」
   - フィールド追加: `number` = 種類「テキスト」・値「入力された値」
   - (`.env` に `CHECK_TOKEN` を設定した場合) `token` = 種類「テキスト」・値に同じ文字列
5. アクション「辞書の値を取得」: キー `message`、辞書「URLの内容」
6. アクション「結果を表示」: 「辞書の値」

使い方: 電話 App の留守番電話 → メッセージを開く → 共有ボタン →「詐欺チェック」→ 番号を入力。

- iPhone と Pi は同じ Wi-Fi に接続する。大学の Wi-Fi は端末同士の通信を遮断していることが多いので、
  デモでは iPhone のインターネット共有 (テザリング) に Pi をつなぐと確実
- 文字起こしに時間がかかってショートカットがタイムアウトしても、Pi 側の判定と LED 表示・Slack 通知は続行される

## 評価

```bash
# 判定ログ: data/check_log.csv の label 列に 1(詐欺)/0(正常) を記入してから
python -m checker.evaluate --log data/check_log.csv
# 評価セット (CSV 列: audio,text,number,label,category。audio はCSVからの相対パス可)
python -m checker.evaluate --csv data/eval_set.csv
# テキストデータセットで内容判定だけ
python -m checker.evaluate --jsonl scam_voicemail/data/val.jsonl --backend keyword
```

正解率・検出率・誤検知率・混同行列と、しきい値ごとの検出率/誤検知率を表示する。
ログには文字起こし時間 (`transcribe_sec`) も記録しているので、Pi 5 での処理時間もここで集計される。

## 自動起動 (systemd)

`deploy/fraud-checker.service` の `User` とパスを自分の環境に合わせてから:

```bash
sudo cp deploy/fraud-checker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fraud-checker
journalctl -u fraud-checker -f      # ログを見る
```

Thonny で起動するときは、先に `sudo systemctl stop fraud-checker` で止める（GPIO とポートが重なるため）。

## テスト (PC でも可)

```bash
pip install -r requirements.txt pytest httpx gpiozero
python -m pytest tests -q
```

## プライバシー

- 音声はPi内で文字起こしし、判定後に削除する (`KEEP_AUDIO=1` で保存)
- `data/check_log.csv` には文字起こし本文を入れず、番号も先頭以外を伏せる。本文は `data/results.jsonl` (Git 管理外)
- Slack には番号を伏せて送る (`SLACK_SHOW_NUMBER=1` で全桁)
