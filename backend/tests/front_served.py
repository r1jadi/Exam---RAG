import subprocess, sys, time, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8124"], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
try:
    for i in range(30):
        time.sleep(2)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8124/", timeout=5) as r:
                body = r.read()
                print("root:", r.status, len(body), body[:80])
                assert b"Study Assistant" in body or b"root" in body or b"html" in body.lower()
                break
        except Exception as e:
            print("wait", i, str(e)[:80])
    else:
        raise SystemExit("no root")
    print("FRONT-SERVED OK")
finally:
    proc.terminate()
    try: proc.wait(timeout=15)
    except Exception: proc.kill()
