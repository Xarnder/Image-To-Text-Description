"""Double-click entry point. Starts one local server, then opens the user's browser."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent


def app_running(url):
    try:
        with urllib.request.urlopen(url + "/api/health", timeout=2) as response:
            return json.load(response).get("app") == "local-image-captioner"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    url = "http://127.0.0.1:" + str(config["port"])
    if not app_running(url):
        python = Path(config["python_executable"])
        if not python.is_file():
            raise RuntimeError("The Python runtime was moved. Update python_executable in config.json.")
        (ROOT / "data").mkdir(exist_ok=True)
        with (ROOT / "data" / "server.log").open("ab") as output:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            process = subprocess.Popen([str(python), "-s", "-u", str(ROOT / "app.py")],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                creationflags=flags, start_new_session=os.name != "nt")
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if app_running(url):
                break
            if process.poll() is not None:
                raise RuntimeError("The app could not start. Check data/server.log. Port "
                                   + str(config["port"]) + " may already be in use.")
            time.sleep(0.25)
        else:
            raise RuntimeError("Startup is taking longer than expected. Check data/server.log and open " + url)
    print("Caption Studio is ready: " + url)
    if not args.no_browser:
        webbrowser.open(url, new=2)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Could not launch Caption Studio: " + str(error), file=sys.stderr)
        sys.exit(1)
