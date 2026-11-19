"""faster-whisper による文字起こし (Pi の中で実行。音声は外部に出さない)。"""
import re
import threading
import time
from dataclasses import dataclass

from . import config

# 無音区間などで Whisper が出しがちな定番の幻覚フレーズ (判定を狂わせるので除く)
HALLUCINATIONS = [
    "ご視聴ありがとうございました", "チャンネル登録よろしくお願いします", "字幕由Amara.org社区提供",
    "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目", "Thank you for watching", "Thanks for watching",
]


@dataclass
class Transcript:
    text: str
    language: str
    language_prob: float
    audio_sec: float
    elapsed_sec: float   # 文字起こしにかかった時間 (Pi 5 での計測用)
    model: str


_model = None
_model_lock = threading.Lock()


def get_model():
    """初回だけモデルを読み込む (Pi 5 で small は数秒〜十数秒)。"""
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            t = time.time()
            _model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
            print(f"[whisper] loaded '{config.WHISPER_MODEL}' in {time.time() - t:.1f}s")
        return _model


def clean(text: str) -> str:
    for h in HALLUCINATIONS:
        text = text.replace(h, "")
    return re.sub(r"\s+", " ", text).strip()


def transcribe(path: str) -> Transcript:
    model = get_model()
    t = time.time()
    segments, info = model.transcribe(
        path,
        language=config.WHISPER_LANGUAGE or None,  # None で自動判定 (国際電話の英語・中国語に対応)
        beam_size=1,          # Pi では速度優先
        vad_filter=True,      # 無音を飛ばして幻覚を減らす
        condition_on_previous_text=False,
    )
    text = "".join(s.text for s in segments)  # ジェネレーターなのでここで実際に処理が走る
    return Transcript(
        text=clean(text),
        language=info.language,
        language_prob=round(info.language_probability, 3),
        audio_sec=round(info.duration, 1),
        elapsed_sec=round(time.time() - t, 1),
        model=config.WHISPER_MODEL,
    )
