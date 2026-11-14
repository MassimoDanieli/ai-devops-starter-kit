# ai-devops-starter-kit v2

Strumenti IA per CI/CD che non dipendono da un singolo fornitore: **review delle PR**, **proposte di test**, **changelog** e **triage SonarQube**. Lo stesso codice gira con Anthropic, OpenAI o un modello sul tuo hardware (llama.cpp, vLLM, Ollama, LM Studio: qualsiasi server compatibile OpenAI).

*English summary at the bottom.*

## Perché una v2

La v1 (luglio 2025) e i prototipi da cui nasceva (`cubo-ai-pipeline`, `ci-ai-testgen`, `ai-devops-demo`, `ai-code-quality-notifier`) chiamavano `gpt-3.5-turbo` o `gpt-4` scritti nel codice. OpenAI li ha spenti il **23 ottobre 2026** e da allora non funzionano più. Due usavano anche `openai.ChatCompletion`, che non esiste più dalla versione 1.0 dell'SDK.

La v2 raccoglie tutto in un pacchetto solo e cambia l'approccio:

| | 2025 | v2 |
|---|---|---|
| Modello | scritto nel codice | `AI_PROVIDER` + `AI_MODEL` da variabili d'ambiente |
| Fornitore | solo OpenAI | Anthropic, OpenAI, server locale |
| Input della review | file interi, uno alla volta | diff della PR con contesto |
| Output | prosa in Markdown | JSON con schema imposto (file, riga, gravità, fix) |
| Rumore | commenti su tutto | solo problemi reali; lista vuota se va tutto bene |
| Commenti sulla PR | uno nuovo a ogni run | uno solo, aggiornato |
| Changelog | ultimi 10 commit, appeso in fondo | commit dall'ultimo tag, formato Keep a Changelog, PR invece di push su main |
| SonarQube | file "recenti" simulati, email | storia git reale, codice attorno all'issue, fix proposto, commento sulla PR |
| Test | Streamlit, `max_tokens=800` | file di test eseguibili per i file cambiati, mai sovrascritti |

## Installazione

```bash
pip install "aikit[all] @ git+https://github.com/MassimoDanieli/ai-devops-starter-kit@main"
```

`[anthropic]` o `[openai]` se ti serve un solo SDK. Il modo locale usa l'SDK `openai`.

## Configurazione

| Variabile | Valori | Note |
|---|---|---|
| `AI_PROVIDER` | `anthropic` (default), `openai`, `local` | |
| `AI_MODEL` | id del modello | obbligatorio per `openai` e `local`; per Anthropic c'è un default |
| `AI_BASE_URL` | es. `http://nero.lan:8080/v1` | solo `local` |
| `AI_API_KEY` | | solo se il server locale la chiede |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | | chiavi dei fornitori |
| `AI_LANGUAGE` | es. `Italian` | lingua dell'output (default inglese) |

`aikit doctor` mostra la configurazione risolta.

Il kit non indovina gli id dei modelli OpenAI o locali: è esattamente quello che ha rotto la v1.

## Comandi

```bash
aikit review    --base origin/main [--fail-on critical] [--context CLAUDE.md] [--comment]
aikit testgen   --base origin/main [--write ai-tests/] [--comment]
aikit changelog [--version v1.2.0] [--dry-run]
aikit sonar     --report sonar.json [--days 7] [--fail-threshold 3] [--comment]
```

Tutti accettano `--out FILE` e `--language`. In GitHub Actions l'output finisce anche nel job summary.

### Con un modello locale

```bash
export AI_PROVIDER=local AI_MODEL=bonsai-2-27b AI_BASE_URL=http://nero.lan:8080/v1
aikit review --base origin/main
```

Il codice non lascia la tua rete: è il modo giusto per repository che non possono andare verso API esterne. Per server senza decodifica vincolata dallo schema, il kit estrae il JSON anche se arriva dentro un blocco di codice o con una frase davanti, e ne verifica la struttura.

## Workflow riutilizzabili

In `.github/workflows/`:

- `ai-review.yml` · review della PR, commento aggiornato in place, `fail-on` opzionale
- `ai-testgen.yml` · proposte di test come commento + artifact
- `ai-changelog.yml` · su un tag `v*`, apre una PR con la voce del changelog
- `ai-sonar-triage.yml` · issue BLOCKER/CRITICAL nei file cambiati di recente, con fix proposti

Esempio pronto da copiare: [`examples/use-the-kit.yml`](examples/use-the-kit.yml). Basta un secret, `ANTHROPIC_API_KEY`.

```yaml
jobs:
  review:
    permissions: { contents: read, pull-requests: write }
    uses: MassimoDanieli/ai-devops-starter-kit/.github/workflows/ai-review.yml@main
    with:
      language: Italian
      fail-on: critical
    secrets: inherit
```

Le PR da fork vengono saltate (i secret non sono disponibili). Senza chiave il job scrive una notice e non fallisce.

### Alternativa agentica

[`examples/claude-code-review.yml`](examples/claude-code-review.yml) usa l'action ufficiale `anthropics/claude-code-action`: invece di una chiamata singola gira un agente nel repo, che apre i file collegati, lancia i test e verifica le proprie affermazioni prima di commentare. Costa di più per PR, rende meglio su modifiche grandi o sottili, e risponde alle menzioni `@claude`.

Quando usare cosa:
- **`ai-review.yml`**: ogni PR, costo prevedibile, funziona anche con un modello locale.
- **Claude Code**: PR importanti, refactoring, o quando vuoi chiedere `@claude correggi questo` direttamente nella PR.

## Sviluppo

```bash
pip install -e ".[dev]"
pytest -q        # nessuna chiamata di rete: i test usano un client finto
ruff check . && ruff format --check .
```

La CI fa girare i test su Python 3.10 e 3.13 e poi usa il kit per fare la review delle sue stesse PR.

## Struttura

```
aikit/
  client.py     client unico: anthropic | openai | local, output strutturato
  review.py     review del diff
  testgen.py    proposte di test
  changelog.py  changelog Keep a Changelog
  sonar.py      triage SonarQube (ex ai-code-quality-notifier)
  gitutil.py    diff, commit, tag
  github.py     commento sulla PR (crea o aggiorna)
```

---

## English summary

Provider-agnostic AI helpers for CI/CD: PR review on the diff with structured findings, test proposals for changed files, Keep-a-Changelog entries from commits since the last tag, and SonarQube triage with proposed fixes. Choose the backend with `AI_PROVIDER` (`anthropic`, `openai`, `local`) and `AI_MODEL`; `local` talks to any OpenAI-compatible server so code never leaves your network. Reusable GitHub workflows live in `.github/workflows/`; see `examples/use-the-kit.yml`. v1 hard-coded `gpt-3.5-turbo` / `gpt-4`, both shut down by OpenAI on 23 October 2026.

MIT © Massimo Danieli
