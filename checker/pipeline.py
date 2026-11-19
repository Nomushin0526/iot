"""判定の流れ: 文字起こし → 番号判定 → 内容判定 → 危険度 → (通知) → ログ。

ハードウェアに依存しないので、評価スクリプトやPCでのテストからも呼べる。
"""
import threading
import time
import uuid
from datetime import datetime

from . import config, logbook, notify
from .content_check import check_content
from .number_check import check_number, load_blacklist
from .risk import combine, level

_lock = threading.Lock()  # Whisper は同時に1件ずつ (Pi のCPU・メモリを使い切るため)


def run_check(audio_path: str | None = None, number: str = "", source: str = "api",
              text: str | None = None, auto_notify: bool = True, save: bool = True,
              content_backend: str | None = None) -> dict:
    """audio_path か text のどちらか (または両方なし=番号のみ) を受け取り、結果の dict を返す。"""
    with _lock:
        t0 = time.time()
        result = {
            "id": uuid.uuid4().hex[:8],
            "time": datetime.now().isoformat(timespec="seconds"),
            "source": source,
            "number": number,
        }

        if audio_path:
            from .transcribe import transcribe
            tr = transcribe(audio_path)
            text = tr.text
            result.update(language=tr.language, language_prob=tr.language_prob, audio_sec=tr.audio_sec,
                          transcribe_sec=tr.elapsed_sec, whisper_model=tr.model)
            print(f"[whisper] {tr.audio_sec}s audio -> {tr.elapsed_sec}s ({tr.model}, {tr.language})")
        result["transcript"] = text or ""

        nr = check_number(number, load_blacklist(config.BLACKLIST_CSV))
        result.update(number=nr.number, number_score=nr.score, number_reasons=nr.reasons, number_kind=nr.kind)

        if text is not None:
            cr = check_content(text, content_backend)
            result.update(content_score=cr.score, phrases=cr.phrases, content_reasons=cr.reasons,
                          content_backend=cr.backend, content_error=cr.error)
            content_score = cr.score
        else:
            content_score = None  # 番号のみ (キーパッド入力)

        risk = combine(nr.score, content_score, blacklisted=nr.kind == "blacklist")
        result.update(risk=risk, level=level(risk), notified=False)

        if auto_notify and risk >= config.NOTIFY_THRESHOLD:
            ok, info = notify.send_slack(notify.build_message(result))
            result["notified"] = ok
            result["notify_info"] = info
        result["total_sec"] = round(time.time() - t0, 1)

        if save:
            logbook.append(result)
        return result
