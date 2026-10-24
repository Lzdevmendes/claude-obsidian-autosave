# claude-obsidian-autosave

Salva toda conversa do Claude Code no Obsidian, sozinho. Inclui o `/clear`:
o hook `SessionEnd` exporta a sessão inteira antes do contexto ser apagado.

Auto-save every Claude Code chat to an Obsidian vault, including on `/clear`
(a `SessionEnd` hook exports the full session before the context is wiped).

## O que gera

```
<cofre>/Claude/
  Projetos/<projeto>/2026-10-24_corrigir-bug-no-login_abc12345.md   conversa legível
  Projetos/<projeto>.md                                             índice do projeto
  Tópicos/bug.md ...                                                índice por assunto
  Sessões/<projeto>/<id>.jsonl.gz                                   backup bruto
```

Cada nota tem frontmatter (`tags`, `projeto`, `data`, `sessao`), título tirado
da primeira mensagem real, arquivos alterados e as ferramentas chamadas.
O grafo do Obsidian ganha uma cor por tópico e destaque para as sessões de hoje.

## Instalar

Requer Python 3.8+ e Claude Code.

```
git clone https://github.com/Lzdevmendes/claude-obsidian-autosave
cd claude-obsidian-autosave/skills/obsidian-autosave
python scripts/install.py --vault "C:/Users/voce/Documents/MeuCofre" --backfill
```

Ou copie `skills/obsidian-autosave` para `~/.claude/skills/` e peça ao Claude:
"ative o obsidian-autosave".

| Flag | Efeito |
|---|---|
| `--vault` | cofre do Obsidian (padrão `~/Documents/SecondBrain`) |
| `--subdir` | subpasta no cofre (padrão `Claude`) |
| `--backfill` | exporta todo o histórico existente agora |
| `--schedule` | rede de segurança horária (Windows: `schtasks`; outros: imprime a linha do cron) |
| `--uninstall` | remove hook e agendamento; notas ficam |

Variáveis `OBSIDIAN_VAULT`, `OBSIDIAN_SUBDIR` e `CLAUDE_CONFIG_DIR` têm
prioridade sobre o `config.json`.

O instalador faz backup em `settings.json.bak` e preserva os outros hooks.

## Escopo

Só Claude Code. Codex, Gemini CLI e Copilot usam outros formatos de sessão e
não são cobertos. PRs com exportadores são bem-vindos.

## Licença

MIT
