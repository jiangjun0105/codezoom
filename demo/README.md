# Codezoom demo site

A static site that shows one repository, Auto-GPT v0.4.7 from `run_auto_gpt`, as a
zoomable flowchart with a question box on every node. It needs no backend and no key.

## Run it

Requires Node 20 or newer.

```bash
cd demo
npm install
npm run dev        # http://localhost:5173
```

## Build it

```bash
npm run build      # type-checks, then writes the static site to demo/dist
npm run preview    # serves demo/dist locally
```

`dist/` is plain HTML, CSS and JS. Any static host can serve it.

## Deploy to junbot.dev (Vercel)

**As a subdomain (simplest), e.g. `codezoom.junbot.dev`:**

1. In Vercel, create a project from this repository and set **Root Directory** to `demo`.
   `vercel.json` already declares the Vite build and the `dist` output.
2. Add the domain under Project → Settings → Domains.

**As a subpath, e.g. `junbot.dev/codezoom`:**

1. Deploy the project as above, with the environment variable `DEMO_BASE=/codezoom/`
   so asset URLs carry the prefix.
2. In this project's `vercel.json`, strip the prefix:
   `"rewrites": [{ "source": "/codezoom/:path*", "destination": "/:path*" }]`
3. In the main junbot.dev project, forward the path to this deployment:
   `"rewrites": [{ "source": "/codezoom/:path*", "destination": "https://<this-deployment>/codezoom/:path*" }]`

If the name changes, only `DEMO_BASE` and those two rewrites change. Nothing in the
source hard-codes the path.

## Optional live mode

By default every answer is pre-computed and shipped with the page. Live mode sends
typed questions to a model through `api/ask.ts`, a serverless function. Suggested
questions keep using their pre-computed answers either way.

Set these on the server (Vercel → Settings → Environment Variables), never in the
client and never in git:

| Variable | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | The model key. Read only inside the function. |
| `CODEZOOM_LIVE=1` | Switches the endpoint on. Without it the function answers `{"live": false}`. |
| `CODEZOOM_MODEL` | Optional. Defaults to `claude-haiku-5-5`. |
| `CODEZOOM_DAILY_CAP` | Optional. Requests per day per function instance, default 400. |

Locally: `cp .env.example .env.local`, fill in the key, `npm run dev`. The dev server
mounts the same function at `/api/ask`.

The endpoint is public once enabled. It caps question length, throttles per IP and per
day (in memory, so best effort), and gives the model only this repository's data. Set a
spend limit on the key as well.

## Layout

```
../codezoom/             2023 pipeline dumps → src/data/graph.json (see NOTES.md)
src/data/graph.json      generated: nodes, links, code, function summaries
src/data/authored.ts     answers to the whole-program questions
src/lib/graph.ts         accessors over the graph, scope and breadcrumb rules
src/lib/layout.ts        chart layout: dagre, column wrapping, the Level-0 grid
src/lib/answers.ts       answers derived from the data, question matching
src/lib/ask.ts           the ask flow: pre-computed, or live when available
src/components/Canvas    pan, zoom, level transitions, path highlighting
api/ask.ts               optional live mode (Vercel Function)
```

See [NOTES.md](NOTES.md) for what is generated and what is hand-written.
