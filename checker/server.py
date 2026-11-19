"""受信サーバー + ハードウェア制御。

  POST /check        iPhoneショートカットから音声(file)と番号(number)を受け取って判定
  GET  /             判定結果の画面 (根拠の語句を赤くハイライト)
  GET  /api/results  直近の結果 (JSON)
  POST /notify/{id}  画面から手動でSlack通知

起動: リポジトリ直下で `python run_server.py` (Thonnyなら run_server.py を開いて実行)
"""
import html
import re
import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from . import config, logbook, notify
from .pipeline import run_check
from .risk import LEVEL_JA


# ---------------------------------------------------------------- ハードウェア
class Hardware:
    """パネル表示・通知ボタン・キーパッドをまとめて管理する。"""

    def __init__(self, real: bool):
        from . import hardware as hw
        if not real:
            hw.use_mock_pins()
        self.hw = hw
        self.panel = hw.Panel()
        self.button = hw.NotifyButton(on_press=self.manual_notify, on_hold=self.reset)
        self.keypad = hw.Keypad(on_key=self.on_key)
        self.buffer = ""
        self.last_result: dict | None = None
        self.keypad.start()
        self.panel.show_char("-")  # 起動完了の合図

    # --- 表示
    def show_result(self, result: dict):
        self.last_result = result
        self.panel.show_risk(result["risk"])

    def reset(self):
        """ボタン長押し: 表示を消す。"""
        self.buffer = ""
        self.last_result = None
        self.panel.clear()
        self.panel.show_char("-")
        print("[button] reset")

    def manual_notify(self):
        """ボタン短押し: 最後の結果を家族に通知。"""
        r = self.last_result
        if r is None:
            print("[button] 通知する結果がありません")
            return
        ok, info = notify.send_slack(notify.build_message(r, manual=True))
        print(f"[button] manual notify -> {ok} ({info})")
        if ok:
            logbook.update_notified(r["id"])
            r["notified"] = True
            # 送信できたことを青く一瞬光らせて知らせる
            self.panel.set_color("blue")
            threading.Timer(0.5, lambda: self.panel.show_risk(r["risk"])).start()

    # --- キーパッド: 数字を打って # で判定、* でクリア、D で1文字消す、A は「+」
    def on_key(self, key: str):
        if key.isdigit() or key == "A":
            self.buffer += "+" if key == "A" else key
            self.panel.show_char(key if key.isdigit() else "P")
            self.panel.set_color("blue")
        elif key == "D":
            self.buffer = self.buffer[:-1]
            self.panel.show_char(self.buffer[-1] if self.buffer and self.buffer[-1].isdigit() else "-")
        elif key == "*":
            self.buffer = ""
            if self.last_result:
                self.panel.show_risk(self.last_result["risk"])
            else:
                self.panel.clear()
                self.panel.show_char("-")
        elif key == "#":
            number, self.buffer = self.buffer, ""
            if not number:
                return
            print(f"[keypad] check number ({len(number)} digits)")
            threading.Thread(target=self._check_number, args=(number,), daemon=True).start()
        elif key == "B" and self.last_result:  # 最後の結果をもう一度表示
            self.panel.show_risk(self.last_result["risk"])
        print(f"[keypad] {key}  buffer={'*' * len(self.buffer)}")

    def _check_number(self, number: str):
        self.panel.busy()
        try:
            self.show_result(run_check(number=number, source="keypad"))
        except Exception as e:
            print(f"[keypad] error: {e}")
            self.panel.error()

    def close(self):
        self.keypad.close()
        self.button.close()
        self.panel.close()


HW: Hardware | None = None


def _warm_up_whisper():
    try:
        from .transcribe import get_model
        get_model()
    except Exception as e:
        print(f"[whisper] warm-up failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global HW
    try:
        HW = Hardware(real=config.USE_HARDWARE)
        print(f"[hw] ready ({'GPIO' if config.USE_HARDWARE else 'mock pins'})")
    except Exception as e:  # 配線・権限の問題があってもサーバー自体は動かす
        print(f"[hw] disabled: {type(e).__name__}: {e}")
        HW = None
        if config.USE_HARDWARE:
            from . import hardware as hw
            busy = hw.find_busy_pins()
            for b in busy:
                print(f"[hw]   使用中: {b}")
            if busy:
                print("[hw]   hw_test.py や前回のサーバーが動いていないか確認してください "
                      "(ps aux | grep python)")
    threading.Thread(target=_warm_up_whisper, daemon=True).start()
    yield
    if HW:
        HW.close()


app = FastAPI(title="留守電 詐欺チェッカー", lifespan=lifespan)


def _auth(token: str | None):
    if config.CHECK_TOKEN and token != config.CHECK_TOKEN:
        raise HTTPException(status_code=401, detail="token が違います")


# ---------------------------------------------------------------- API
@app.post("/check")
def check(
    file: UploadFile | None = File(None),
    number: str = Form(""),
    token: str = Form(""),
    x_token: str | None = Header(None),
):
    """iPhoneショートカット「URLの内容を取得」(方法: POST, 本文: フォーム) から呼ぶ。"""
    _auth(x_token or token)
    audio_path = None
    if file is not None and file.filename:
        config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        suffix = Path(file.filename).suffix or ".m4a"
        audio_path = config.UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
        with audio_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)

    if HW:
        HW.panel.busy()
    try:
        result = run_check(audio_path=str(audio_path) if audio_path else None, number=number,
                           source="iphone" if audio_path else "api")
    except Exception as e:
        if HW:
            HW.panel.error()
        print(f"[check] error: {type(e).__name__}: {e}")
        return JSONResponse({"error": str(e), "message": "判定に失敗しました"}, status_code=500)
    finally:
        if audio_path and not config.KEEP_AUDIO:
            audio_path.unlink(missing_ok=True)
    if HW:
        HW.show_result(result)

    message = f"危険度 {result['risk']}/9（{LEVEL_JA[result['level']]}）"
    if result.get("content_reasons"):
        message += "\n" + " / ".join(result["content_reasons"][:3])
    if result["notified"]:
        message += "\n家族に通知しました"
    return {"message": message, **{k: result.get(k) for k in (
        "id", "risk", "level", "notified", "number_reasons", "content_score", "content_reasons",
        "phrases", "transcribe_sec", "total_sec")}}


@app.get("/api/results")
def results(n: int = 20):
    return logbook.recent(n)


@app.post("/notify/{result_id}")
def notify_manual(result_id: str, token: str = Form(""), x_token: str | None = Header(None)):
    _auth(x_token or token)
    r = next((r for r in logbook.recent(200) if r["id"] == result_id), None)
    if r is None:
        raise HTTPException(404, "結果が見つかりません")
    ok, info = notify.send_slack(notify.build_message(r, manual=True))
    if ok:
        logbook.update_notified(result_id)
    return {"ok": ok, "info": info}


# ---------------------------------------------------------------- 画面
def highlight(text: str, phrases: list[str]) -> str:
    out = html.escape(text)
    for p in sorted(set(phrases), key=len, reverse=True):
        ep = html.escape(p)
        if ep:
            out = re.sub(re.escape(ep), lambda m: f"<mark>{m.group(0)}</mark>", out)
    return out


PAGE = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="5">
<title>留守電チェッカー</title><style>
body{{font-family:sans-serif;margin:0;padding:16px;background:#f4f4f5;color:#18181b}}
h1{{font-size:20px;margin:0 0 12px}}
.card{{background:#fff;border-radius:10px;padding:14px 16px;margin-bottom:12px;border-left:8px solid #ccc}}
.green{{border-color:#16a34a}}.yellow{{border-color:#eab308}}.red{{border-color:#dc2626}}
.risk{{font-size:28px;font-weight:bold}} .meta{{color:#71717a;font-size:13px}}
.text{{margin:8px 0;line-height:1.7;white-space:pre-wrap}}
mark{{background:#fecaca;color:#b91c1c;font-weight:bold;padding:0 2px;border-radius:3px}}
button{{padding:6px 12px;border-radius:6px;border:1px solid #a1a1aa;background:#fff;cursor:pointer}}
</style></head><body><h1>留守電 詐欺チェッカー</h1>{cards}</body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    cards = []
    for r in logbook.recent(10):
        reasons = " / ".join(r.get("number_reasons", []) + r.get("content_reasons", []))
        notified = "通知済み" if r.get("notified") else (
            f'<form method="post" action="/notify/{r["id"]}" style="display:inline">'
            f'<button>家族に通知</button></form>')
        transcript = highlight(r.get("transcript", ""), r.get("phrases", [])) or "<span class=meta>(音声なし)</span>"
        cards.append(
            f'<div class="card {r["level"]}"><div class="risk">危険度 {r["risk"]}/9 {LEVEL_JA[r["level"]]}</div>'
            f'<div class="meta">{html.escape(r["time"])} ・ {html.escape(r["source"])} ・ '
            f'{html.escape(r.get("content_backend", "番号のみ"))} ・ 処理 {r.get("total_sec", "-")}秒</div>'
            f'<div class="text">{transcript}</div><div class="meta">{html.escape(reasons)}</div>'
            f'<div style="margin-top:8px">{notified}</div></div>')
    return PAGE.format(cards="".join(cards) or "<p>まだ結果がありません</p>")
