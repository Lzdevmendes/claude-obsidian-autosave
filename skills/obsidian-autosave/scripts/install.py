#!/usr/bin/env python3
"""Instala o autosave Claude Code -> Obsidian.

Copia os scripts para <CLAUDE_HOME>/obsidian-autosave/, grava config.json e
registra o hook SessionEnd em settings.json (idempotente, preserva o resto).
SessionEnd dispara no fim de toda sessão, inclusive no /clear.

Uso:
  install.py [--vault CAMINHO] [--subdir Claude] [--schedule] [--backfill]
  install.py --uninstall
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLAUDE_HOME = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
DEST = os.path.join(CLAUDE_HOME, "obsidian-autosave")
SETTINGS = os.path.join(CLAUDE_HOME, "settings.json")
SCRIPTS = ("export.py", "backfill.py", "session_end.py")
MARKER = "obsidian-autosave"
TASK = "ClaudeObsidianAutosave"


def load_settings():
    if not os.path.isfile(SETTINGS):
        return {}
    with open(SETTINGS, encoding="utf-8") as f:
        return json.load(f)


def save_settings(cfg):
    os.makedirs(CLAUDE_HOME, exist_ok=True)
    if os.path.isfile(SETTINGS):
        shutil.copy2(SETTINGS, SETTINGS + ".bak")
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")


def strip_hook(cfg):
    groups = cfg.get("hooks", {}).get("SessionEnd", [])
    kept = []
    for g in groups:
        g["hooks"] = [h for h in g.get("hooks", []) if MARKER not in h.get("command", "")]
        if g["hooks"]:
            kept.append(g)
    if kept:
        cfg["hooks"]["SessionEnd"] = kept
    elif "SessionEnd" in cfg.get("hooks", {}):
        del cfg["hooks"]["SessionEnd"]


def quote(p):
    return f'"{p}"'


def install(args):
    os.makedirs(DEST, exist_ok=True)
    for name in SCRIPTS:
        shutil.copy2(os.path.join(HERE, name), os.path.join(DEST, name))
    conf = {}
    if args.vault:
        conf["vault"] = os.path.abspath(os.path.expanduser(args.vault))
    if args.subdir:
        conf["subdir"] = args.subdir
    if conf:
        with open(os.path.join(DEST, "config.json"), "w", encoding="utf-8") as f:
            json.dump(conf, f, indent=2, ensure_ascii=False)

    cfg = load_settings()
    strip_hook(cfg)
    cmd = f"{quote(sys.executable)} {quote(os.path.join(DEST, 'session_end.py'))}"
    cfg.setdefault("hooks", {}).setdefault("SessionEnd", []).append(
        {"hooks": [{"type": "command", "command": cmd}]}
    )
    save_settings(cfg)
    print(f"hook SessionEnd registrado em {SETTINGS}")

    if args.schedule:
        schedule()
    if args.backfill:
        subprocess.run([sys.executable, os.path.join(DEST, "backfill.py")], check=False)


def schedule():
    backfill = os.path.join(DEST, "backfill.py")
    if os.name == "nt":
        # pythonw evita janela de console piscando a cada execução.
        py = sys.executable
        pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
        if os.path.isfile(pyw):
            py = pyw
        subprocess.run(
            ["schtasks", "/Create", "/F", "/TN", TASK, "/SC", "HOURLY",
             "/TR", f'{quote(py)} {quote(backfill)}'],
            check=False,
        )
    else:
        print("agende manualmente (cron): 0 * * * * " + f"{quote(sys.executable)} {quote(backfill)}")


def uninstall():
    cfg = load_settings()
    strip_hook(cfg)
    if cfg.get("hooks") == {}:
        del cfg["hooks"]
    save_settings(cfg)
    shutil.rmtree(DEST, ignore_errors=True)
    if os.name == "nt":
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK], check=False)
    print("removido (notas no cofre foram mantidas)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vault", help="pasta do cofre do Obsidian (padrão: ~/Documents/SecondBrain)")
    ap.add_argument("--subdir", help="subpasta dentro do cofre (padrão: Claude)")
    ap.add_argument("--schedule", action="store_true", help="agenda o backfill de segurança a cada hora")
    ap.add_argument("--backfill", action="store_true", help="exporta agora todo o histórico existente")
    ap.add_argument("--uninstall", action="store_true")
    args = ap.parse_args()
    uninstall() if args.uninstall else install(args)


if __name__ == "__main__":
    main()
