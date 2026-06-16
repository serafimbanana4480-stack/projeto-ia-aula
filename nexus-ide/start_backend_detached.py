import subprocess, time, os, sys

PROJECT = r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide"
PYTHON = r"C:\Users\rodri\AppData\Local\Programs\Python\Python312\python.exe"
PIDFILE = os.path.join(PROJECT, "backend.pid")

if os.path.exists(PIDFILE):
    with open(PIDFILE) as f:
        old = f.read().strip()
    if old.isdigit():
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", old],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(2)

proc = subprocess.Popen(
    [PYTHON, os.path.join(PROJECT, "run.py")],
    cwd=PROJECT,
    stdout=open(os.path.join(PROJECT, "logs", "restart.log"), "a+b"),
    stderr=subprocess.STDOUT,
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    close_fds=True,
)
with open(PIDFILE, "w") as f:
    f.write(str(proc.pid))
print("started pid", proc.pid)
