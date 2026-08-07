"""Reproducao minima do modelo de execucao do NEXUS:
estado de sessao + tarefa longa da IA guardados EM MEMORIA,
servidor arrancado com --reload sobre a arvore do projeto."""
import asyncio, os
from fastapi import FastAPI

app = FastAPI()
RUNS: dict[str, int] = {}          # <- estado da sessao/tarefa: so em memoria

async def _long_ai_task(run_id: str):
    for i in range(1, 31):         # 30s de "trabalho da IA"
        await asyncio.sleep(1)
        RUNS[run_id] = i

@app.post("/start")
async def start():
    RUNS["run-1"] = 0
    asyncio.create_task(_long_ai_task("run-1"))
    return {"started": True, "pid": os.getpid()}

@app.get("/status")
async def status():
    return {"pid": os.getpid(), "runs": RUNS}
