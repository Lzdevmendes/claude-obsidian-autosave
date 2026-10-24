#!/usr/bin/env python3
"""Hook de SessionEnd do Claude Code: exporta a sessão inteira pro Obsidian.

Lê o JSON do hook via stdin (precisa de transcript_path), roda o exportador,
guarda o markdown em Claude/Projetos/<projeto>/, arquiva o .jsonl bruto
comprimido em Claude/Sessões/<projeto>/ e reconstrói o índice do projeto.

Disparado uma única vez por sessão (evento SessionEnd, não Stop — Stop dispara
a cada resposta e não serve pra isso).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill import (  # noqa: E402
    sanitize, archive_raw, rebuild_project_index, rebuild_topic_indices,
    update_color_groups, PROJETOS_DIR, EXPORTER,
)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    transcript_path = data.get("transcript_path")
    session_id = data.get("session_id", "sessao")
    if not transcript_path or not os.path.isfile(transcript_path):
        return 0

    tmp_out = os.path.join(tempfile.gettempdir(), f"obsidian_export_{session_id}.md")
    result = subprocess.run(
        [sys.executable, EXPORTER, transcript_path, tmp_out],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0 or not os.path.exists(tmp_out):
        sys.stderr.write(f"session_end: falha ao exportar {session_id}: {result.stderr[:300]}\n")
        return 0

    try:
        meta = json.loads(result.stdout.strip().splitlines()[-1])
    except Exception:
        meta = {"project": "Geral", "start": ""}

    project = sanitize(meta.get("project") or "Geral")
    start = (meta.get("start") or "")[:10] or "sem-data"
    slug = sanitize(meta.get("slug") or "sessao")
    final_dir = os.path.join(PROJETOS_DIR, project)
    os.makedirs(final_dir, exist_ok=True)
    final_path = os.path.join(final_dir, f"{start}_{slug}_{session_id[:8]}.md")

    shutil.move(tmp_out, final_path)
    archive_raw(transcript_path, project, session_id)
    rebuild_project_index(project)
    rebuild_topic_indices()
    update_color_groups()
    return 0


if __name__ == "__main__":
    sys.exit(main())
