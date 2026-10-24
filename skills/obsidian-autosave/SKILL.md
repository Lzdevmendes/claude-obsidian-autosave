---
name: obsidian-autosave
description: Salva automaticamente toda conversa do Claude Code em um cofre do Obsidian, organizada por projeto e tópico. Dispara no /clear e no fim de qualquer sessão. Use quando o usuário pedir para ativar, instalar, verificar ou remover o salvamento automático de chats no Obsidian.
---

# obsidian-autosave

Registra um hook `SessionEnd` no Claude Code. `/clear` encerra a sessão atual,
então o hook roda também nele: o histórico inteiro é exportado antes de o
contexto ser limpo.

## Ativar

1. Descubra o cofre. Pergunte ao usuário o caminho se não for informado. Padrão: `~/Documents/SecondBrain`.
2. Rode, a partir da pasta desta skill:

```
python scripts/install.py --vault "<caminho do cofre>" --backfill
```

Flags: `--subdir NOME` (padrão `Claude`), `--schedule` (backfill horário, rede de segurança), `--backfill` (exporta o histórico já existente).

3. Confirme que `settings.json` em `~/.claude/` contém o hook `SessionEnd` apontando para `obsidian-autosave/session_end.py`.
4. Teste: encerre uma sessão com `/clear` e verifique se surgiu uma nota em `<cofre>/Claude/Projetos/<projeto>/`.

## Verificar

- Hook presente em `settings.json` e arquivos em `~/.claude/obsidian-autosave/`.
- Notas recentes: `<cofre>/Claude/Projetos/*/AAAA-MM-DD_*.md`.
- Falhas aparecem no stderr do hook como `session_end: falha ao exportar`.

## Remover

```
python scripts/install.py --uninstall
```

Notas já salvas no cofre são mantidas.

## Estrutura gerada

- `Claude/Projetos/<projeto>/<data>_<titulo>_<id8>.md`: conversa completa, ferramentas usadas, arquivos alterados.
- `Claude/Projetos/<projeto>.md`: índice por projeto.
- `Claude/Tópicos/<tag>.md`: índice por assunto (bug, deploy, ui, auth, ...).
- `Claude/Sessões/<projeto>/<id>.jsonl.gz`: transcript bruto comprimido.

## Limites

Cobre só o Claude Code. Outras ferramentas (Codex, Gemini CLI, Copilot) guardam
sessões em formatos próprios e não são exportadas por esta skill.
