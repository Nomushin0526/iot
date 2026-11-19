"""判定結果の保存。

- data/check_log.csv … 評価用 (文字起こし本文は入れない)。label 列は後で手で 1(詐欺)/0(正常) を記入する
- data/results.jsonl … 画面表示用の詳細 (文字起こしを含むので Git に入れない)
"""
import csv
import json
import threading

from . import config
from .number_check import mask

LOG_FIELDS = [
    "time", "id", "source", "number_masked", "number_kind", "number_score", "content_score",
    "content_backend", "risk", "level", "notified", "language", "audio_sec", "transcribe_sec",
    "whisper_model", "total_sec", "transcript_chars", "label",
]
_lock = threading.Lock()


def append(result: dict) -> None:
    with _lock:
        config.LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
        new = not config.LOG_CSV.exists()
        with config.LOG_CSV.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
            if new:
                w.writeheader()
            w.writerow({
                "time": result["time"], "id": result["id"], "source": result["source"],
                "number_masked": mask(result.get("number", "")), "number_kind": result.get("number_kind", ""),
                "number_score": result.get("number_score", ""), "content_score": result.get("content_score", ""),
                "content_backend": result.get("content_backend", ""), "risk": result["risk"], "level": result["level"],
                "notified": int(bool(result.get("notified"))), "language": result.get("language", ""),
                "audio_sec": result.get("audio_sec", ""), "transcribe_sec": result.get("transcribe_sec", ""),
                "whisper_model": result.get("whisper_model", ""), "total_sec": result.get("total_sec", ""),
                "transcript_chars": len(result.get("transcript", "")), "label": "",
            })
        with config.RESULTS_JSONL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")


def recent(n: int = 20) -> list[dict]:
    if not config.RESULTS_JSONL.exists():
        return []
    with config.RESULTS_JSONL.open(encoding="utf-8") as f:
        lines = f.readlines()[-n:]
    return [json.loads(l) for l in reversed(lines) if l.strip()]


def update_notified(result_id: str) -> None:
    """手動通知した結果を results.jsonl に反映 (小さいファイルなので全体を書き直す)。"""
    with _lock:
        if not config.RESULTS_JSONL.exists():
            return
        rows = [json.loads(l) for l in config.RESULTS_JSONL.read_text(encoding="utf-8").splitlines() if l.strip()]
        for r in rows:
            if r["id"] == result_id:
                r["notified"] = True
        config.RESULTS_JSONL.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
