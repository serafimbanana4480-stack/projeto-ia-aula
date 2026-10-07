"""NX-20261006-A1 — snapshot reversivel da arvore de trabalho suja.

Porquê: o checkout tem ~735 entradas alteradas com autoria nao estabelecida, e a maioria dos
ficheiros relevantes e UNTRACKED (git diff nao os ve, logo nao ha rollback via git). Antes de
qualquer edicao, este script grava metadados + SHA256 em streaming para que qualquer alteracao
feita a partir daqui possa ser revertida com exactidao (I-2, I-9, I-11).

Nao escreve nada no repo. Nao faz rede. Nao le secrets (.env e ignorado explicitamente).
Custo: metadata + hashing. Sem alocacao de disco significativa.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(r"C:\Users\rodri\Desktop\nexus")
OUT = REPO / "nexus-ide/docs/auditorias/_run/2026-10-06/NX-20261006-A1/baseline/manifest.jsonl"
MAX_HASH_BYTES = 64 * 1024 * 1024  # acima disto: metadados + motivo, sem hash
SECRET_NAMES = {".env", ".env.local", "credentials.json", "secrets.json", ".npmrc", ".pypirc"}


def sha256(path: Path) -> tuple[str | None, str | None]:
    """Return (hash, reason_skipped)."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, f"stat falhou: {exc}"
    if size > MAX_HASH_BYTES:
        return None, f"demasiado grande para hashing ({size} bytes)"
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError as exc:
        return None, f"leitura falhou: {exc}"
    return h.hexdigest(), None


def main() -> int:
    raw = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=REPO, capture_output=True, text=True, errors="replace",
    ).stdout

    # -z: "<XY> <path>\0" ; renamesLEM "XY <a>\0<b>\0"
    fields = [f for f in raw.split("\0") if f]
    entries = []
    i = 0
    while i < len(fields):
        field = fields[i]
        if len(field) < 4:
            i += 1
            continue
        code, path_str = field[:2], field[3:]
        dest = None
        if code[0] in ("R", "C") and i + 1 < len(fields):
            dest = fields[i + 1]
            i += 1
        i += 1
        full = REPO / path_str
        rec = {
            "code": code,
            "path": path_str,
            "is_dir": full.is_dir(),
            "size": None,
            "mtime": None,
            "sha256": None,
            "hash_skipped_reason": None,
            "secret_excluded": False,
            "rename_dest": dest,
        }
        if dest:
            rec["rename_dest"] = dest
        if full.name in SECRET_NAMES or full.suffix in {".pem", ".key", ".p12"}:
            rec["secret_excluded"] = True
            rec["hash_skipped_reason"] = "segredo: conteudo e hash NAO registados (I-5)"
        elif full.is_file():
            st = full.stat()
            rec["size"] = st.st_size
            rec["mtime"] = st.st_mtime
            rec["sha256"], rec["hash_skipped_reason"] = sha256(full)
        else:
            rec["hash_skipped_reason"] = "nao e ficheiro (removido)"
        entries.append(rec)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for rec in entries:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    hashed = sum(1 for r in entries if r["sha256"])
    skipped = sum(1 for r in entries if r["hash_skipped_reason"] and not r["sha256"])
    secrets = sum(1 for r in entries if r["secret_excluded"])
    tracked = sum(1 for r in entries if r["code"] != "??")
    print(f"entradas no manifesto : {len(entries)}")
    print(f"  tracked alterados    : {tracked}")
    print(f"  untracked            : {len(entries) - tracked}")
    print(f"  com SHA256           : {hashed}")
    print(f"  sem hash (motivo)    : {skipped}")
    print(f"  segredos excluidos   : {secrets}")
    print(f"escrito em            : {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())