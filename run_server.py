"""詐欺チェッカーを起動する (Thonny ではこのファイルを開いて「実行」)。

ブラウザで http://<ラズパイのIPアドレス>:8000/ を開くと結果画面が見られる。
停止は Thonny の「停止」ボタン (または Ctrl+C)。
"""
import uvicorn

from checker import config

if __name__ == "__main__":
    uvicorn.run("checker.server:app", host=config.HOST, port=config.PORT)
