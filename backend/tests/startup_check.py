import subprocess, sys, time, urllib.request, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
proc = subprocess.Popen([sys.executable or "py", "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8123"],
                        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
try:
    ok = False
    for i in range(40):
        time.sleep(2)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8123/api/health", timeout=5) as r:
                print("health:", r.status, r.read()[:200])
                ok = True
                break
        except Exception as e:
            print("wait...", i, str(e)[:100])
    assert ok, "backend did not start"
    with urllib.request.urlopen("http://127.0.0.1:8123/api/system/status", timeout=30) as r:
        s = json.loads(r.read())
        print("ollama:", s["ollama_available"], "chat_ready:", s["chat_model_ready"], "embed_ready:", s["embed_model_ready"])
        assert s["ollama_available"] and s["chat_model_ready"] and s["embed_model_ready"]
    with urllib.request.urlopen("http://127.0.0.1:8123/api/documents", timeout=15) as r:
        print("docs:", r.read()[:200])
    print("STARTUP OK")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except Exception:
        proc.kill()
