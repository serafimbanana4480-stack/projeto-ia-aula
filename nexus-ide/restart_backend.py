import subprocess, time, sys, os

PROJECT = r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide"
PYTHON = r"C:\Users\rodri\AppData\Local\Programs\Python\Python312\python.exe"
PIDFILE = os.path.join(PROJECT, "backend.pid")


def main():
    old_pid = None
    if os.path.exists(PIDFILE):
        with open(PIDFILE) as f:
            txt = f.read().strip()
        if txt.isdigit():
            old_pid = int(txt)

    if old_pid:
        print(f"Killing old backend PID {old_pid}")
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(old_pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(2)

    print("Starting new backend...")
    proc = subprocess.Popen(
        [PYTHON, os.path.join(PROJECT, "run.py")],
        cwd=PROJECT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    print(f"New backend PID: {proc.pid}")
    with open(PIDFILE, "w") as f:
        f.write(str(proc.pid))
    time.sleep(4)

    import requests, urllib.request

    try:
        r = urllib.request.urlopen("http://localhost:8000/health", timeout=5)
        print("Backend health:", r.status, r.read().decode())
    except Exception as e:
        print("Backend not ready yet:", e)


if __name__ == "__main__":
    main()
