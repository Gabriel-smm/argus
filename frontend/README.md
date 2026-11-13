This is the [assistant-ui](https://github.com/assistant-ui/assistant-ui) starter project for LangGraph. It ships a minimal Ollama-backed agent (`backend/agent.ts`) plus a Next.js chat UI that streams from it.

## Getting Started

1. Set up the pipeline's Python environment, from the repository root (see the [root README](../README.md)):

   ```bash
   python3.12 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

   The Laya service loads the fine-tuned checkpoint from `models/laya-rf-modes` in the repository root. **Run Laya** fails with a message naming that path when the folder is missing.

2. Copy the env template:

   ```bash
   cp .env.example .env.local
   ```

   Required:
   - Ollama running locally (`ollama serve`), with the model from `OLLAMA_MODEL` already pulled. Defaults to `qwen2.5:14b` at `http://127.0.0.1:11434`. Use the same model the pipeline loads: it keeps that one in GPU memory, and a small GPU cannot hold a second.

   Optional:
   - `OLLAMA_HOST` / `OLLAMA_MODEL` — override the local server or model id
   - `OLLAMA_NUM_CTX` — a larger context window for the chat
   - `PIPELINE_API_URL` — where the Laya service listens, `http://127.0.0.1:8000` by default
   - `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` — tracing
   - `LANGCHAIN_API_KEY` — only needed when pointing `LANGGRAPH_API_URL` at LangGraph Platform (cloud)

3. Install deps and run the web app, the LangGraph backend and the Laya service together:

   ```bash
   npm install
   npm run dev
   ```

   - `localhost:3000` — Next.js app
   - `localhost:2024` — LangGraph dev server (serves the `agent` graph)
   - `localhost:8000` — Laya service (`pipeline/server.py`)

   Run them individually with `npm run dev:frontend`, `npm run dev:backend` and `npm run dev:pipeline`.

## Using it

The quickest way in is **Scan the area** on the front page: it plays a built-in scene (`SCENES` in `pipeline/server.py`, today the 17 sample campus signals), sweeps the spectrum while Laya and the site check run, then shows the site report. A badge says it is demo data, not a live radio. The Scan page is always what opens: after a reload it does not jump to an earlier result, but offers a **See last result** link. The sweep stays on screen for at least one full pass (`SCAN_MIN_MS` in `hooks/use-analysis.ts`), even when the result is quicker. To demo a real capture, point the scene's `data` at a file made with `python -m pipeline.ingest`.

During the sweep each dot is colored by the site check (red needs a closer look, amber unknown, green normal), the newest one is named as a likely match ("Looks like Wi-Fi or Bluetooth", "Possible drone", "Something on GPS", "Mystery signal"), and a **Heard so far** list grows underneath. These come from `GET /scene`, which runs the site check up front: it is plain rules, so it needs no GPU. With reduced motion turned on in the system settings, there is no sweep: all the dots and the list appear at once.

The globe button at the top right switches the scan page, the site report and the chat between **English, Español and Français**. The choice is kept in the browser. Fixed text is translated from a dictionary in `lib/i18n.ts`, with no online service. The chat model is told the language through the run config (`configurable.language`, read in `backend/agent.ts`) and keeps all its guardrails. The detailed reason and "Next" text from `data/context/bands.csv` stay in English for now, and the report says so.

To use your own files instead:

1. In the Library, open **Knowledge** and add a Laya questions file, such as `data/data-full.json`.
2. Open **Data** and add observations, such as `data/observations-full.jsonl`. JSON lists and one-object-per-line files both work.
3. Each file is checked as it is added. One that is not valid JSON, or sits in the wrong tab, says so under its name and cannot be picked.
4. Press **Run Laya**. Chat is paused while Laya has the GPU. Only the first 100 rows of the data file are classified. Asking the chat to analyze the remaining rows, or a different number, runs Laya on that slice and summarizes it.
5. When the Library shows **Active**, ask the chat about the result. It answers from Laya's output only, and says so when the answer is not there.

Above the chat, a **site report** shows the site check at a glance: one verdict (normal / mostly normal / needs a closer look), a red-yellow-green bar, what is in the air in everyday words, the signals to look at first with what to check next, and follow-up questions built from the result. It is computed by the Laya service (`build_site_report` in `pipeline/context.py`), not by the chat model, so it appears as soon as a run finishes and always matches the numbers.

**Package for HQ**, on the report card, saves the result as one file, `argus-packet-<site>-<date-time>.json`, so it can be carried offline (USB stick, shared drive) for further analysis. It holds the site and its coordinates, where the data came from (the demo badge for the built-in scene, so demo data is never mistaken for a real recording), the versions of the band table, site profile and model, the verdict, the counts and every signal with its reason and what to check next, worst first. A sha256 fingerprint of the contents is added; its first 8 characters show on screen. At HQ, **Open a packet** on the front page checks the fingerprint and shows the same report card under a banner naming the packet, when it was made and where. A packet whose contents were changed after it was made is refused. The fingerprint catches accidental or casual changes; it is not a signature, so it cannot prove who made the packet. Opening a packet is view-only: it does not replace this computer's result, and the chat keeps answering about that. Making and opening packets happens entirely in the browser (`lib/packet.ts`, tested with `npm test`); nothing is sent anywhere.

**Clear**, or removing a file the result came from, drops the result. It otherwise survives a page reload, until the Laya service restarts.

## Project layout

```
app/                    Next.js App Router pages
app/api/[..._path]/     proxy to the LangGraph server
app/api/pipeline/       proxy to the Laya service
backend/agent.ts        LangGraph graph exported as `graph`
components/library.tsx  file upload, checks and the Run control
components/site-report.tsx  the site report card above the chat
components/scan-hero.tsx    the front page: Scan button and spectrum sweep
components/language-menu.tsx  the language button, and passing the language to the chat
hooks/use-analysis.ts   run state shared by the Library and the chat
lib/i18n.ts             English, Spanish and French text for the scan page and site report
lib/packet.ts           the field-to-HQ packet: build, fingerprint, open, check (tests next to it)
components/packet.tsx   Package for HQ, Open a packet, and the opened packet view
langgraph.json          LangGraph CLI config (graph id, node version, env file)
```

`app/assistant.tsx` builds the runtime with `useStreamRuntime({ assistantId, apiUrl })` from `@assistant-ui/react-langchain`, which wraps `useStream` from `@langchain/react`. It uses the websocket transport: over SSE, replies never arrive in Firefox.

On every turn `backend/agent.ts` reads the current result from the Laya service and puts it in the system prompt, so a new run is picked up by the next message.

## Deployment security

The bundled proxy rejects browser requests marked same-site or cross-site so the local starter works without exposing `LANGCHAIN_API_KEY` to the client. For clients without Fetch Metadata, reverse proxies must preserve the public scheme and host in the request URL for the `Origin` fallback. Request-context checks are not user authentication. Before deploying with a cloud API key, require your application session in `app/api/[..._path]/route.ts` and apply a durable rate limit.
