# 残りの作業の手順（モデル・評価・通知）

ハードウェアと詐欺チェッカー本体は完成済み。残りは次の5つ。上から順にやるのがおすすめ。

| # | 作業 | 誰が | かかる時間 |
|---|---|---|---|
| 1 | 学習データを Gemma で作る | Claude（クラウド側で実行中） | 数時間（待つだけ） |
| 2 | 本番のモデルを学習する | ラズパイで1コマンド | 数秒 |
| 3 | 評価用の音声を集める・録音する | 自分 | 1〜2時間 |
| 4 | 3つの判定方式を評価・比較する | ラズパイで1コマンドずつ | 数分〜数十分 |
| 5 | Slack 通知・iPhone ショートカットを設定する | 自分 | 30分 |

コマンドはすべてラズパイのターミナルで実行する（Thonny の「ツール → システムシェルを開く」でもよい）。

---

## 1. 学習データを Gemma で作る（待つだけ）

- 今の仮モデルは、テンプレートで作った簡単すぎるデータで学習している（val の正解率が100%になり実力が測れない）
- Claude 側で gemma3:4b を使って 1,435件の合成データを作り直している
- できたら `scam_voicemail/data/` の `train.jsonl` / `val.jsonl` などを `main` に入れる → 手順2へ

## 2. 本番のモデルを学習する

データが `main` に入ったと連絡が来たら実行する。

**① 仮のデータを消す**（消さないと `git pull` が「同じ名前のファイルがある」で止まる）

```bash
cd ~/iot/scam_voicemail/data && rm -f train.jsonl val.jsonl dataset.jsonl processed/*.jsonl
```

**② 取り込んで学習する**

```bash
cd ~/iot && git pull && cd scam_voicemail/scripts && ~/iot-venv/bin/python 05_train_classifier.py
```

- 最後に `saved -> .../models/scam_clf.joblib` と出れば完成
- 途中に出る「正解率・検出率・誤検知率・カテゴリ別」は合成データでの成績（参考値。本当の実力は手順4で測る）
- サーバー（`run_server.py`）を起動し直すと新しいモデルに切り替わる

## 3. 評価用の音声を集める・録音する

合成データでの成績は高めに出るので、**実際の音声**で測る。詐欺・正常それぞれ **10件ずつ以上**あると評価らしくなる。

### 3-1. 置き場所

```bash
mkdir -p ~/iot/data/eval_audio
```

音声ファイルは `~/iot/data/eval_audio/` に入れる（Git には入らない設定）。

### 3-2. 詐欺の音声（県警の公開音声）

- 茨城・滋賀・長野・京都・静岡などの県警が「詐欺電話の犯人の声」を公開している
- **使う前に各ページの利用条件を確認**し、出典をメモしておく（発表資料に書く）
- 多くは犯人と被害者の会話なので、できれば**犯人の声の部分だけ**を切り出す（留守電に近づけるため）
- mp3 / m4a / wav どれでもよい

### 3-3. 正常な留守電（自分で読み上げて録音）

iPhone の「ボイスメモ」で録音すると m4a になる。下の台本を、留守電を残すつもりで普通の速さで読む（「えーと」などが入ってもよい）。

| ファイル名 | 台本 |
|---|---|
| normal_01.m4a | こちらはさくら歯科クリニックです。明日午後3時のご予約の確認のお電話です。ご変更の場合は診療時間内にお電話ください。 |
| normal_02.m4a | ヤマト運輸です。お荷物をお届けに伺いましたがご不在でした。再配達は不在票の番号かウェブサイトからお願いします。 |
| normal_03.m4a | 東京ガスです。来週火曜日の午前中に定期点検に伺います。ご都合が悪い場合ははがきの番号までご連絡ください。 |
| normal_04.m4a | お世話になっております。みずほ銀行の木村です。先日のお申し込みの書類で確認したい点がございます。お手すきの際にご連絡ください。 |
| normal_05.m4a | もしもし、お母さんだけど。えーと、週末そっちに行く件、土曜のお昼ぐらいに着くと思うから。また電話するね。 |
| normal_06.m4a | あ、もしもし田中です。来週の飲み会のお店決まったから、あとでLINEで送っとくね。じゃあね。 |
| normal_07.m4a | ひまわり小学校の担任の井上です。明日の遠足の持ち物の件でお伝えしたいことがあります。学校までお電話いただけますか。 |
| normal_08.m4a | 市立中央病院です。検査結果がそろいましたので、次回の外来でご説明します。予約の変更は予約センターまでお願いします。 |
| normal_09.m4a | もしもし、おれおれ、健太だけど。昨日借りた傘を返したいんだけど、今日の夜は家にいる？あとで連絡ちょうだい。 |
| normal_10.m4a | こちらは市役所の防災課です。明日、地域の防災訓練を行います。詳しくは市のホームページをご覧ください。 |

normal_09 は「おれおれ」で始まるが中身は普通の連絡（オレオレ詐欺と見分けられるかのテスト）。
normal_10 は役所を名乗るがお金の話がない（還付金詐欺と見分けられるかのテスト）。

**iPhone からラズパイへ送る方法**（どれか1つ）

- Google ドライブ等に上げてラズパイのブラウザでダウンロードし、`~/iot/data/eval_audio/` に移す
- USB メモリ経由でコピーする

### 3-4. 一覧表（CSV）を作る

ひな形をコピーして編集する。

```bash
cp ~/iot/data/eval_set.example.csv ~/iot/data/eval_set.csv
```

列の意味:

| 列 | 内容 |
|---|---|
| audio | 音声ファイル（`eval_audio/ファイル名`。CSV からの相対パス） |
| text | 音声が無いときだけ、文字で書く（audio があれば空でよい） |
| number | かかってきた番号（分からなければ空。詐欺音声は国際電話や 050 など想定の番号でもよい） |
| label | 1 = 詐欺、0 = 正常 |
| category | 種類のメモ（refund / police / relative / normal_auto / normal_personal など） |

## 4. 3つの判定方式を評価・比較する

同じ評価データで、内容判定の方式だけを変えて比べる。サーバー（`run_server.py`）は止めてから実行する。

```bash
cd ~/iot && ~/iot-venv/bin/python -m checker.evaluate --csv data/eval_set.csv --backend classifier
```

```bash
cd ~/iot && ~/iot-venv/bin/python -m checker.evaluate --csv data/eval_set.csv --backend keyword
```

```bash
cd ~/iot && ~/iot-venv/bin/python -m checker.evaluate --csv data/eval_set.csv --backend ollama
```

- 出力: 正解率・**検出率**（詐欺を詐欺と言えた割合）・**誤検知率**（正常を詐欺と言った割合）・混同行列・しきい値ごとの表
- ollama（Gemma）は1件に数十秒〜数分かかる。20件なら30分程度見ておく
- 文字起こし（Whisper）も毎回走るので、その時間も含まれる

**発表用のまとめ方（例）**

| 方式 | 正解率 | 検出率 | 誤検知率 | 1件あたりの時間 |
|---|---|---|---|---|
| 学習モデル | | | | |
| Gemma (Ollama) | | | | |
| キーワード | | | | |

「速さ」と「精度」のどちらを取るかを数字で示せる。

**実際に使ったときのログでも評価できる**: iPhone から判定したものは `data/check_log.csv` に記録される。
`label` 列に 1 / 0 を書き込んでから次を実行する。

```bash
cd ~/iot && ~/iot-venv/bin/python -m checker.evaluate --log data/check_log.csv
```

## 5. Slack 通知・iPhone ショートカット

### 5-1. Slack 通知

**Bot トークン（`xoxb-...`）を持っている場合はこちらが早い**: `~/iot/.env` に次の2行を書く。

```
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL=C...
```

- `SLACK_CHANNEL` はチャンネル ID（Slack でチャンネル名を右クリック →「チャンネル詳細を表示」の一番下）
- Bot をそのチャンネルに招待しておく（チャンネルで `/invite @Botの名前`）
- Bot に `chat:write` 権限が必要（アプリ設定の「OAuth & Permissions」）
- 書いたら下の 6. のテスト送信へ。失敗したときは原因と直し方が表示される

**Webhook を使う場合**:

1. Slack で家族用のワークスペース（またはチャンネル）を用意する
2. https://api.slack.com/apps →「Create New App」→「From scratch」→ アプリ名（例: 詐欺チェッカー）とワークスペースを選ぶ
3. 左メニュー「Incoming Webhooks」→ オンにする →「Add New Webhook to Workspace」→ 通知先のチャンネルを選ぶ
4. 表示された `https://hooks.slack.com/services/...` をコピーする（**この URL は人に見せない・Git に入れない**）
5. ラズパイの `~/iot/.env` に書く

   ```
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
   ```

6. テスト送信する（サーバーを起動しなくてよい）

   ```bash
   cd ~/iot && ~/iot-venv/bin/python -m checker.notify
   ```

   最後に `送信成功 (HTTP 200)` と出て、Slack にテストのメッセージが届けば完成

7. 本番の動作: サーバーを起動し直し、判定したあとに通知ボタンを短く押すと、その結果が Slack に届く

危険度 7 以上で自動通知される（`.env` の `NOTIFY_THRESHOLD` で変更可）。

### 5-2. iPhone ショートカット

作り方はリポジトリ直下の `README.md` の「iPhone ショートカット『詐欺チェック』の作り方」を参照。

- iPhone とラズパイを同じ Wi-Fi につなぐ（ラズパイの IP は `hostname -I` で確認）
- 大学の Wi-Fi は端末同士の通信を遮断していることが多い → デモでは iPhone のテザリングにラズパイをつなぐ

---

## 困ったとき

| 症状 | 対処 |
|---|---|
| `git pull` で「untracked working tree files would be overwritten」 | 手順2の①（仮のデータを消す）を実行してからもう一度 |
| `[classifier] ...failed` と出てキーワード判定になる | `models/scam_clf.joblib` が無い → 手順2の②を実行 |
| 評価で `label (1/0) が記入された行がありません` | CSV / ログの label 列に 1 か 0 を書く |
| 表示が残ったまま消えない | サーバーは Thonny のシェルで Ctrl+C で止める。残ったら `python3 hw_test.py off` |
