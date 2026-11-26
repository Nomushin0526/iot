"""学習済みの軽量分類器 (scam_voicemail/scripts/05_train_classifier.py で作る) で内容を判定する。

モデルは models/scam_clf.joblib。Pi の中で完結し、1件数ミリ秒で判定できる。
"""
import threading

from . import config

_model = None
_lock = threading.Lock()


def available() -> bool:
    return config.CLASSIFIER_MODEL.exists()


def load() -> dict:
    global _model
    with _lock:
        if _model is None:
            import joblib
            _model = joblib.load(config.CLASSIFIER_MODEL)
            print(f"[classifier] loaded {config.CLASSIFIER_MODEL.name} "
                  f"(trained {_model.get('trained_at')}, n={_model.get('n_train')})")
        return _model


def predict(text: str, top_k: int = 5) -> tuple[float, list[str]]:
    """詐欺である確率 (0〜1) と、詐欺側に効いた文字列 (上位) を返す。"""
    pipe = load()["pipeline"]
    score = float(pipe.predict_proba([text])[0, 1])
    tfidf, clf = pipe.named_steps["tfidf"], pipe.named_steps["clf"]
    x = tfidf.transform([text])
    names = tfidf.get_feature_names_out()
    contrib = sorted(((x[0, j] * clf.coef_[0, j], names[j]) for j in x.nonzero()[1]), reverse=True)
    top = [n.strip() for c, n in contrib if c > 0 and len(n.strip()) >= 2][:top_k]
    return score, top
