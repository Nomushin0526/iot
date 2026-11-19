"""設定。環境変数またはリポジトリ直下の .env から読む (APIキー等はコードに書かない)。"""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _load_dotenv(path: Path) -> None:
    """依存を増やさないための最小の .env 読み込み (KEY=VALUE 形式, # はコメント)。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), _parse_value(value))  # 既に設定済みの環境変数を優先


def _parse_value(value: str) -> str:
    """値を取り出す。引用符で囲まれていなければ行末の「 # コメント」を取り除く。"""
    value = value.strip()
    if value[:1] in ('"', "'"):
        end = value.find(value[0], 1)
        return value[1:end] if end != -1 else value[1:]
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


_load_dotenv(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# --- サーバー
HOST = env("HOST", "0.0.0.0")
PORT = env_int("PORT", 8000)
CHECK_TOKEN = env("CHECK_TOKEN")  # 設定するとリクエストに同じトークンが必要になる

# --- ハードウェア (0 にするとGPIOを使わずPCでも動く)
USE_HARDWARE = env_bool("USE_HARDWARE", True)

# --- 文字起こし
WHISPER_MODEL = env("WHISPER_MODEL", "small")  # tiny / base / small
WHISPER_LANGUAGE = env("WHISPER_LANGUAGE", "")  # 空=自動判定, "ja" で日本語固定

# --- 内容判定: auto / anthropic / openai / ollama / keyword
CONTENT_BACKEND = env("CONTENT_BACKEND", "auto")
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL", "claude-opus-5-5")
OPENAI_MODEL = env("OPENAI_MODEL", "gpt-4.1-mini")
OLLAMA_MODEL = env("OLLAMA_MODEL", "")  # 空なら入っている Gemma を自動選択
OLLAMA_HOST = env("OLLAMA_HOST", "http://localhost:11434")
MASK_NAMES = [n for n in env("MASK_NAMES").split(",") if n.strip()]  # 外部送信前に伏せる名前

# --- 通知
SLACK_WEBHOOK_URL = env("SLACK_WEBHOOK_URL")
NOTIFY_THRESHOLD = env_int("NOTIFY_THRESHOLD", 7)  # 危険度がこれ以上で自動通知
SLACK_SHOW_NUMBER = env_bool("SLACK_SHOW_NUMBER", False)  # True で番号を伏せずに送る

# --- ファイル
BLACKLIST_CSV = Path(env("BLACKLIST_CSV", str(DATA / "blacklist.csv")))
LOG_CSV = Path(env("LOG_CSV", str(DATA / "check_log.csv")))
RESULTS_JSONL = Path(env("RESULTS_JSONL", str(DATA / "results.jsonl")))
UPLOAD_DIR = Path(env("UPLOAD_DIR", str(DATA / "uploads")))
KEEP_AUDIO = env_bool("KEEP_AUDIO", False)  # False なら判定後に音声を削除
