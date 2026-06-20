import os
import sys
import socket
import subprocess
import threading
import time
import webview

PORT = 8501
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app.py")

CLEAN_ENV = {
    "HOME": "/Users/tsunemi",
    "USER": "tsunemi",
    "LOGNAME": "tsunemi",
    "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    "PATH": "/Library/Frameworks/Python.framework/Versions/3.10/bin:/usr/local/bin:/usr/bin:/bin",
    "LANG": "en_US.UTF-8",
    "__CF_USER_TEXT_ENCODING": os.environ.get("__CF_USER_TEXT_ENCODING", "0x1F5:0x1:0xE"),
    "TERM": "xterm-256color",
}


def _start_streamlit():
    subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", APP_PATH,
            "--server.headless=true",
            f"--server.port={PORT}",
            "--server.address=localhost",
            "--browser.gatherUsageStats=false",
        ],
        env=CLEAN_ENV,
        cwd=BASE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_port(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("localhost", PORT), timeout=1):
                return True
        except OSError:
            time.sleep(0.4)
    return False


if __name__ == "__main__":
    threading.Thread(target=_start_streamlit, daemon=True).start()

    if not _wait_for_port():
        print("エラー: Streamlit の起動がタイムアウトしました")
        sys.exit(1)

    window = webview.create_window(
        title="株式ポートフォリオ管理",
        url=f"http://localhost:{PORT}",
        width=1440,
        height=900,
        min_size=(900, 600),
        resizable=True,
    )
    webview.start()
