#!/usr/bin/env python3
"""Converte um transcript .jsonl do Claude Code em markdown legível para o Obsidian.

Uso: export.py <transcript.jsonl> <saida.md> [--project NOME]

Escreve o markdown em <saida.md> e imprime no stdout uma linha JSON com metadados
{"project": "...", "cwd": "...", "session_id": "...", "start": "...", "end": "...",
 "summary": "...", "n_user": N, "n_files": N} para o script que chama consumir.
"""
import json
import sys
import os
import re
from datetime import datetime, timezone

MAX_TOOL_INPUT = 300
MAX_BLOCK_CHARS = 20_000
MAX_TOTAL_CHARS = 400_000

TAG_RULES = {
    "bug": [r"\bbug\b", r"\berro\b", r"travand", r"travad", r"corrig", r"quebrou",
            r"não funciona", r"nao funciona", r"crash", r"falha", r"congela",
            r"não (?:está|esta) (?:funcionando|deixando|abrindo|carregando)",
            r"não consigo", r"nao consigo", r"não deixa", r"nao deixa",
            r"\bproblema\b", r"conserta", r"\barruma", r"resolve isso"],
    "deploy": [r"deploy", r"\bbuild\b", r"produção", r"producao", r"vercel", r"publicar",
               r"release", r"pipeline", r"\bci/?cd\b"],
    "ui": [r"\bui\b", r"\bux\b", r"design", r"layout", r"interface", r"componente",
           r"estilo", r"\bcss\b", r"tailwind", r"figma", r"tela"],
    "auth": [r"login", r"autentic", r"\bsenha\b", r"\btoken\b", r"oauth", r"cadastro",
             r"\botp\b"],
    "database": [r"banco de dados", r"supabase", r"\bsql\b", r"migration", r"\bquery\b",
                 r"\btabela\b", r"postgres"],
    "performance": [r"performance", r"\blento\b", r"otimiz", r"\bcache\b", r"memória ram",
                     r"memoria ram"],
    "docs": [r"document", r"\breadme\b"],
    "config": [r"config", r"instal", r"\bsetup\b", r"ambiente", r"variável de ambiente",
               r"variavel de ambiente", r"\.env\b"],
    "seguranca": [r"seguran", r"vulnerab", r"\bsecurity\b", r"exploit", r"pentest",
                   r"\bcve\b"],
    "mobile": [r"react native", r"\bexpo\b", r"\bandroid\b", r"\bios\b", r"\bmobile\b"],
    "api": [r"\bapi\b", r"endpoint", r"webhook", r"\brest\b"],
    "refactor": [r"refator", r"reorganiz"],
    "infra": [r"\bdocker\b", r"servidor", r"nginx", r"\bvps\b", r"systemd", r"\bcron\b"],
}
TAG_RULES = {k: [re.compile(p, re.IGNORECASE) for p in v] for k, v in TAG_RULES.items()}


def derive_tags(blob):
    tags = []
    for tag, patterns in TAG_RULES.items():
        if any(p.search(blob) for p in patterns):
            tags.append(tag)
    return tags


def cap_block(text):
    if len(text) <= MAX_BLOCK_CHARS:
        return text
    cortado = len(text) - MAX_BLOCK_CHARS
    return (
        text[:MAX_BLOCK_CHARS]
        + f"\n\n…[bloco truncado — {cortado:,} caracteres cortados; "
        "conteúdo completo no backup bruto em Claude/Sessões/]".replace(",", ".")
    )


def fmt_time(iso):
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso


def short(v, n=MAX_TOOL_INPUT):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


def tool_use_line(block):
    name = block.get("name", "Tool")
    inp = block.get("input", {}) or {}
    key_fields = ["file_path", "command", "path", "pattern", "url", "query", "prompt"]
    for k in key_fields:
        if k in inp:
            return f"- 🔧 **{name}** `{short(inp[k])}`"
    if inp:
        first_key = next(iter(inp))
        return f"- 🔧 **{name}** `{first_key}={short(inp[first_key])}`"
    return f"- 🔧 **{name}**"


def slugify(text, max_words=8, max_len=60):
    import unicodedata
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    words = [w for w in text.split() if w][:max_words]
    slug = "-".join(words)[:max_len].strip("-")
    return slug or "sessao"


SYSTEM_WRAPPER_RE = re.compile(
    r"^<(local-command-caveat|command-name|command-message|command-args|"
    r"system-reminder|user-prompt-submit-hook|pasted_content)\b", re.IGNORECASE)


def is_system_wrapper(text):
    return bool(SYSTEM_WRAPPER_RE.match((text or "").strip()))


def extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text", ""))
        return "\n".join(parts)
    return ""


def main():
    if len(sys.argv) < 3:
        print("uso: export.py <transcript.jsonl> <saida.md> [--project NOME]", file=sys.stderr)
        sys.exit(1)
    transcript_path = sys.argv[1]
    out_path = sys.argv[2]
    project_override = None
    if "--project" in sys.argv:
        project_override = sys.argv[sys.argv.index("--project") + 1]

    session_id = None
    cwd = None
    start_ts = None
    end_ts = None
    first_user_text = None
    title_source_text = None
    files_touched = set()
    body_lines = []
    n_user_turns = 0
    body_chars = 0
    total_truncated = False
    tag_blob_parts = []
    TAG_BLOB_TURNS = 3

    def add(*lines):
        nonlocal body_chars, total_truncated
        if total_truncated:
            return
        chunk = "\n".join(lines)
        body_chars += len(chunk)
        body_lines.extend(lines)
        if body_chars > MAX_TOTAL_CHARS:
            body_lines.append(
                f"\n\n---\n\n**⚠️ Nota truncada em {MAX_TOTAL_CHARS:,} caracteres "
                "— conversa muito longa. Conteúdo completo no backup bruto em "
                "Claude/Sessões/.**".replace(",", ".")
            )
            total_truncated = True

    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue

                if session_id is None:
                    session_id = d.get("sessionId") or d.get("session_id")
                if cwd is None and d.get("cwd"):
                    cwd = d["cwd"]
                ts = d.get("timestamp")
                if ts:
                    if start_ts is None:
                        start_ts = ts
                    end_ts = ts

                t = d.get("type")
                if t == "user":
                    msg = d.get("message", {})
                    content = msg.get("content")
                    text = extract_text(content) if not isinstance(content, str) else content
                    if isinstance(content, str) and content.strip():
                        n_user_turns += 1
                        if first_user_text is None:
                            first_user_text = content.strip()
                        if title_source_text is None and not is_system_wrapper(content):
                            title_source_text = content.strip()
                        if len(tag_blob_parts) < TAG_BLOB_TURNS:
                            tag_blob_parts.append(content.strip())
                        add(f"\n### 🧑 Você — {fmt_time(ts)}\n", cap_block(content.strip()))
                    elif isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text" and c.get("text", "").strip():
                                n_user_turns += 1
                                if first_user_text is None:
                                    first_user_text = c["text"].strip()
                                if title_source_text is None and not is_system_wrapper(c["text"]):
                                    title_source_text = c["text"].strip()
                                if len(tag_blob_parts) < TAG_BLOB_TURNS:
                                    tag_blob_parts.append(c["text"].strip())
                                add(f"\n### 🧑 Você — {fmt_time(ts)}\n", cap_block(c["text"].strip()))
                elif t == "assistant":
                    msg = d.get("message", {})
                    content = msg.get("content")
                    if isinstance(content, list):
                        text_parts = []
                        tool_lines = []
                        for c in content:
                            if not isinstance(c, dict):
                                continue
                            ctype = c.get("type")
                            if ctype == "text" and c.get("text", "").strip():
                                text_parts.append(c["text"].strip())
                            elif ctype == "tool_use":
                                tool_lines.append(tool_use_line(c))
                                inp = c.get("input", {}) or {}
                                fp = inp.get("file_path") or inp.get("path")
                                if fp and c.get("name") in ("Write", "Edit", "NotebookEdit"):
                                    files_touched.add(fp)
                        if text_parts:
                            add(f"\n### 🤖 Claude — {fmt_time(ts)}\n", cap_block("\n".join(text_parts)))
                        if tool_lines:
                            add("", *tool_lines)
    except FileNotFoundError:
        print(f"arquivo não encontrado: {transcript_path}", file=sys.stderr)
        sys.exit(1)

    GENERIC_DIRNAMES = {
        "frontend", "backend", "src", "app", "web", "api", "client", "server",
        "mobile", "web-app", "webapp", "site", "docs", "packages", "apps",
    }

    project = project_override
    if not project:
        base = (cwd or "").rstrip("/\\")
        if not base or os.path.normcase(base) == os.path.normcase(os.path.expanduser("~")):
            project = "Geral"
        else:
            leaf = os.path.basename(base)
            if leaf.lower() in GENERIC_DIRNAMES:
                parent = os.path.basename(os.path.dirname(base))
                project = f"{parent}-{leaf}" if parent else leaf
            else:
                project = leaf

    summary = (first_user_text or "(sem mensagem inicial)").replace("\n", " ")
    if len(summary) > 140:
        summary = summary[:140] + "…"

    titulo_src = (title_source_text or first_user_text or "").replace("\n", " ").strip()
    titulo = titulo_src[:90].strip()
    if titulo and len(titulo_src) > 90:
        titulo = titulo.rsplit(" ", 1)[0] + "…"
    titulo = titulo[0].upper() + titulo[1:] if titulo else "Sessão sem título"

    slug = slugify(titulo_src or project)

    tag_blob = " ".join(tag_blob_parts)
    tags = derive_tags(tag_blob)
    date_only = (start_ts or "")[:10]

    frontmatter = ["---"]
    frontmatter.append(f"tags: [{', '.join(tags)}]" if tags else "tags: []")
    frontmatter.append(f"projeto: {project}")
    frontmatter.append(f"data: {date_only}")
    frontmatter.append(f"sessao: {session_id or ''}")
    frontmatter.append("---")

    header = []
    header.append(f"# {titulo}")
    header.append("")
    header.append(f"*{project} · {date_only}*")
    header.append("")
    header.append(f"**Diretório:** `{cwd or 'desconhecido'}`")
    header.append(f"**Sessão:** `{session_id or 'desconhecida'}`")
    header.append(f"**Início:** {fmt_time(start_ts)}")
    header.append(f"**Fim:** {fmt_time(end_ts)}")
    header.append(f"**Mensagens do usuário:** {n_user_turns}")
    header.append(f"**Resumo:** {summary}")
    if files_touched:
        header.append("")
        header.append("**Arquivos alterados:**")
        for fp in sorted(files_touched):
            header.append(f"- `{fp}`")
    header.append("")
    header.append("---")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(frontmatter))
        f.write("\n")
        f.write("\n".join(header))
        f.write("\n")
        f.write("\n".join(body_lines))
        f.write("\n")

    meta = {
        "project": project,
        "cwd": cwd,
        "session_id": session_id,
        "start": start_ts,
        "end": end_ts,
        "summary": summary,
        "titulo": titulo,
        "slug": slug,
        "n_user": n_user_turns,
        "files": sorted(files_touched),
        "tags": tags,
    }
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
