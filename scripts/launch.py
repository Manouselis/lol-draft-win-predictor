"""Launch the local service or open an existing instance, without exposing configuration."""
import threading
import time
import urllib.request
import webbrowser

URL = "http://127.0.0.1:8765"


def healthy():
    try:
        with urllib.request.urlopen(URL + "/api/health", timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


if healthy():
    webbrowser.open(URL)
    print("League Draft Lab is already running at " + URL)
else:
    def open_when_ready():
        for _ in range(100):
            if healthy():
                webbrowser.open(URL)
                return
            time.sleep(.2)
    threading.Thread(target=open_when_ready, daemon=True).start()
    import uvicorn
    uvicorn.run("loldraft.api:create_app", factory=True, host="127.0.0.1", port=8765, access_log=False)
