#!/usr/bin/env python3
"""Varre todas as sessões (.jsonl) do Claude Code, exporta cada uma para markdown
no Obsidian (organizadas por projeto), arquiva o .jsonl bruto comprimido como
backup, e reconstrói o índice de cada projeto.

Idempotente: pula sessões já exportadas cujo .jsonl não mudou desde a última vez.
Reexecutável a qualquer momento como rede de segurança (ex: sessões que travaram
antes do hook de fim de sessão rodar).

Uso: backfill.py [--force]
"""
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

HOME = os.path.expanduser("~")
CLAUDE_HOME = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude")
PROJECTS_DIR = os.path.join(CLAUDE_HOME, "projects")
# Cofre do Obsidian e subpasta onde as conversas ficam.
# Prioridade: variável de ambiente > config.json (gravado pelo install.py) > padrão.
_cfg = {}
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"), encoding="utf-8") as _f:
        _cfg = json.load(_f)
except Exception:
    pass
VAULT_ROOT = os.environ.get("OBSIDIAN_VAULT") or _cfg.get("vault") or os.path.join(HOME, "Documents", "SecondBrain")
SUBDIR = os.environ.get("OBSIDIAN_SUBDIR") or _cfg.get("subdir") or "Claude"
VAULT = os.path.join(VAULT_ROOT, SUBDIR)
PROJETOS_DIR = os.path.join(VAULT, "Projetos")
SESSOES_DIR = os.path.join(VAULT, "Sessões")
TOPICOS_DIR = os.path.join(VAULT, "Tópicos")
OBSIDIAN_DIR = os.path.join(VAULT_ROOT, ".obsidian")
EXPORTER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "export.py")

HOJE_COLOR_RGB = 16766720  # dourado — marca as sessões salvas no dia atual

TAG_COLORS = {
    "bug": 15158332, "deploy": 3447003, "ui": 10181046, "auth": 1752220,
    "database": 15105570, "performance": 15844367, "docs": 8359053,
    "config": 9268835, "seguranca": 12597547, "mobile": 15483002,
    "api": 3066993, "refactor": 6056896, "infra": 4545124,
}

FORCE = "--force" in sys.argv


def sanitize(name):
    name = re.sub(r"[\\/:*?\"<>|]", "-", name).strip()
    return name or "Geral"


def find_jsonl_files():
    if not os.path.isdir(PROJECTS_DIR):
        return
    for entry in os.scandir(PROJECTS_DIR):
        if not entry.is_dir():
            continue
        for f in os.scandir(entry.path):
            if f.is_file() and f.name.endswith(".jsonl"):
                yield f.path


def archive_raw(jsonl_path, project, session_id):
    dest_dir = os.path.join(SESSOES_DIR, sanitize(project))
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{session_id}.jsonl.gz")
    if os.path.exists(dest) and not FORCE:
        if os.path.getmtime(dest) >= os.path.getmtime(jsonl_path):
            return dest
    with open(jsonl_path, "rb") as fin, gzip.open(dest, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    return dest


def parse_note(path):
    """Lê o frontmatter YAML + cabeçalho de uma nota de sessão exportada."""
    info = {"tags": [], "projeto": "", "data": "", "sessao": "", "inicio": "", "resumo": "", "titulo": ""}
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    in_front = False
    for i, line in enumerate(lines):
        if i == 0 and line.strip() == "---":
            in_front = True
            continue
        if in_front:
            if line.strip() == "---":
                in_front = False
                continue
            if line.startswith("tags:"):
                raw = line.split("tags:", 1)[1].strip().strip("[]")
                info["tags"] = [t.strip() for t in raw.split(",") if t.strip()]
            elif line.startswith("projeto:"):
                info["projeto"] = line.split("projeto:", 1)[1].strip()
            elif line.startswith("data:"):
                info["data"] = line.split("data:", 1)[1].strip()
            elif line.startswith("sessao:"):
                info["sessao"] = line.split("sessao:", 1)[1].strip()
            continue
        if not info["titulo"] and line.startswith("# "):
            info["titulo"] = line[2:].strip()
        elif line.startswith("**Início:**"):
            info["inicio"] = line.split("**Início:**", 1)[1].strip()
        elif line.startswith("**Resumo:**"):
            info["resumo"] = line.split("**Resumo:**", 1)[1].strip()
        elif line.startswith("---"):
            break
    return info


def rebuild_project_index(project):
    proj_dir = os.path.join(PROJETOS_DIR, sanitize(project))
    if not os.path.isdir(proj_dir):
        return
    rows = []
    for fname in sorted(os.listdir(proj_dir)):
        if not fname.endswith(".md"):
            continue
        info = parse_note(os.path.join(proj_dir, fname))
        info["file"] = fname
        rows.append(info)
    rows.sort(key=lambda r: r["inicio"], reverse=True)

    index_path = os.path.join(PROJETOS_DIR, f"{sanitize(project)}.md")
    lines = [f"# Projeto — {project}", ""]
    lines.append(f"{len(rows)} sessão(ões) do Claude Code registradas neste projeto.")
    lines.append("")
    lines.append("| Início | Título | Tópicos | Sessão |")
    lines.append("|---|---|---|---|")
    for r in rows:
        link = f"[[Projetos/{sanitize(project)}/{r['file']}|abrir]]"
        titulo = (r["titulo"] or r["resumo"]).replace("|", "\\|")
        tags = " ".join(f"#{t}" for t in r["tags"])
        lines.append(f"| {r['inicio']} | {titulo} | {tags} | {link} |")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def rebuild_topic_indices():
    """Reconstrói Claude/Tópicos/<tag>.md cruzando sessões de todos os projetos."""
    if not os.path.isdir(PROJETOS_DIR):
        return {}
    tag_map = {}
    for proj_name in sorted(os.listdir(PROJETOS_DIR)):
        proj_dir = os.path.join(PROJETOS_DIR, proj_name)
        if not os.path.isdir(proj_dir):
            continue
        for fname in sorted(os.listdir(proj_dir)):
            if not fname.endswith(".md"):
                continue
            info = parse_note(os.path.join(proj_dir, fname))
            for tag in info["tags"]:
                tag_map.setdefault(tag, []).append({
                    "projeto": proj_name, "file": fname,
                    "inicio": info["inicio"], "resumo": info["titulo"] or info["resumo"],
                })

    os.makedirs(TOPICOS_DIR, exist_ok=True)
    for tag, rows in tag_map.items():
        rows.sort(key=lambda r: r["inicio"], reverse=True)
        lines = [f"# Tópico — #{tag}", ""]
        lines.append(f"{len(rows)} sessão(ões) marcadas com #{tag}, de todos os projetos.")
        lines.append("")
        lines.append("| Início | Projeto | Título | Sessão |")
        lines.append("|---|---|---|---|")
        for r in rows:
            link = f"[[Projetos/{r['projeto']}/{r['file']}|abrir]]"
            resumo = r["resumo"].replace("|", "\\|")
            lines.append(f"| {r['inicio']} | {r['projeto']} | {resumo} | {link} |")
        with open(os.path.join(TOPICOS_DIR, f"{tag}.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    master = ["# Tópicos", "", "Sessões agrupadas por assunto, cruzando todos os projetos.", ""]
    for tag in sorted(tag_map):
        master.append(f"- [[Tópicos/{tag}.md|#{tag}]] ({len(tag_map[tag])})")
    with open(os.path.join(TOPICOS_DIR, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(master) + "\n")
    return tag_map


def update_color_groups():
    """Atualiza os grupos de cor do grafo: uma cor por tópico + 'Hoje' em destaque
    (dourado) por cima, apontando sempre para a data atual."""
    graph_path = os.path.join(OBSIDIAN_DIR, "graph.json")
    if not os.path.isdir(OBSIDIAN_DIR):
        return
    cfg = {}
    if os.path.isfile(graph_path):
        try:
            with open(graph_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

    groups = cfg.get("colorGroups", [])
    by_rgb = {g.get("color", {}).get("rgb"): g for g in groups if isinstance(g, dict)}

    for tag, rgb in TAG_COLORS.items():
        query = f"tag:#{tag}"
        if rgb in by_rgb:
            by_rgb[rgb]["query"] = query
        else:
            groups.append({"query": query, "color": {"a": 1, "rgb": rgb}})
            by_rgb[rgb] = groups[-1]

    today = datetime.now().strftime("%Y-%m-%d")
    hoje_query = f'path:"{SUBDIR}/Projetos" path:"{today}"'
    if HOJE_COLOR_RGB in by_rgb:
        g = by_rgb[HOJE_COLOR_RGB]
        groups.remove(g)
        g["query"] = hoje_query
        groups.append(g)
    else:
        groups.append({"query": hoje_query, "color": {"a": 1, "rgb": HOJE_COLOR_RGB}})

    cfg["colorGroups"] = groups
    cfg.setdefault("collapse-color-groups", False)

    os.makedirs(OBSIDIAN_DIR, exist_ok=True)
    with open(graph_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main():
    files = sorted(find_jsonl_files(), key=lambda p: os.path.getmtime(p))
    total = len(files)
    exported = 0
    skipped = 0
    failed = 0
    touched_projects = set()

    print(f"Encontradas {total} sessões (.jsonl) em {PROJECTS_DIR}")

    for jsonl_path in files:
        session_id = os.path.splitext(os.path.basename(jsonl_path))[0]

        try:
            with open(jsonl_path, encoding="utf-8", errors="replace") as f:
                first_line = f.readline()
            first = json.loads(first_line) if first_line.strip() else {}
        except Exception:
            first = {}

        tmp_out = os.path.join(tempfile.gettempdir(), f"obsidian_export_{session_id}.md")
        try:
            result = subprocess.run(
                [sys.executable, EXPORTER, jsonl_path, tmp_out],
                capture_output=True, text=True, timeout=300,
            )
        except subprocess.TimeoutExpired:
            print(f"  [TIMEOUT] {session_id}")
            failed += 1
            continue

        if result.returncode != 0:
            print(f"  [ERRO] {session_id}: {result.stderr.strip()[:200]}")
            failed += 1
            continue

        try:
            meta = json.loads(result.stdout.strip().splitlines()[-1])
        except Exception:
            print(f"  [ERRO metadata] {session_id}")
            failed += 1
            continue

        project = sanitize(meta.get("project") or "Geral")
        start = (meta.get("start") or "")[:10] or "sem-data"
        slug = sanitize(meta.get("slug") or "sessao")
        final_dir = os.path.join(PROJETOS_DIR, project)
        os.makedirs(final_dir, exist_ok=True)
        final_path = os.path.join(final_dir, f"{start}_{slug}_{session_id[:8]}.md")

        if os.path.exists(final_path) and not FORCE:
            if os.path.getmtime(final_path) >= os.path.getmtime(jsonl_path):
                os.remove(tmp_out)
                skipped += 1
                touched_projects.add(project)
                continue

        shutil.move(tmp_out, final_path)
        archive_raw(jsonl_path, project, session_id)
        touched_projects.add(project)
        exported += 1
        print(f"  [OK] {project}/{os.path.basename(final_path)}  ({meta.get('n_user')} msgs)")

    for project in touched_projects:
        rebuild_project_index(project)

    tag_map = rebuild_topic_indices()
    update_color_groups()

    print()
    print(f"Total: {total} | exportadas: {exported} | já atualizadas: {skipped} | falhas: {failed}")
    print(f"Projetos atualizados: {', '.join(sorted(touched_projects)) or '(nenhum)'}")
    print(f"Tópicos: {', '.join(sorted(tag_map)) or '(nenhum)'}")


if __name__ == "__main__":
    main()
