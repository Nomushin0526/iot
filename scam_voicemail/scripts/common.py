"""共通ユーティリティ: パス定義・JSONL入出力・スキーマ検証"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"

SCHEMA_KEYS = ("id", "text", "label", "category", "language", "source")
LANGS = {"ja", "en", "zh"}


def validate(rec: dict) -> dict:
    missing = [k for k in SCHEMA_KEYS if k not in rec]
    if missing:
        raise ValueError(f"missing keys {missing}: {rec}")
    if rec["label"] not in (0, 1):
        raise ValueError(f"bad label: {rec}")
    if rec["language"] not in LANGS:
        raise ValueError(f"bad language: {rec}")
    if not isinstance(rec["text"], str) or not rec["text"].strip():
        raise ValueError(f"empty text: {rec}")
    return {k: rec[k] for k in SCHEMA_KEYS}


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def write_jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(validate(r), ensure_ascii=False) + "\n")


def append_jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(validate(r), ensure_ascii=False) + "\n")
        f.flush()
