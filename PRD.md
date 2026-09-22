# Smoke — v1 implementation plan

## Context

`PRD.md` defines Smoke: a benchmark answering one question — **when an agent fetches a web page through an "LLM-ready" extraction tool, does hidden text reach the model, and does the tool warn?** Prior work covers open-source loaders and full RAG pipelines; nobody tracks the hosted tools agents actually plug in. Target: repo + first results table + README in one weekend.

The project is greenfield — `PRD.md` and nothing else, not yet a git repo.

Research this session surfaced **five findings that invalidate PRD assumptions**. The plan below corrects for each; they are the reason this isn't a straight read-the-PRD-and-build.

| # | Finding | Consequence |
|---|---|---|
| 1 | **NFKC/NFKD strips none of the payloads** — all are Unicode category `Cf` and round-trip unchanged (verified empirically) | The PRD's "exact + normalised" matching would silently under-detect. Detector needs `Cf`-stripping + tag-block decoding. **The single highest-risk piece of logic in the project.** |
| 2 | **Crawl4AI is not hosted** — cloud API is unreleased closed beta | Moves to baselines *(your decision)* |
| 3 | **Firecrawl's `checkPromptInjection` is on the paid `json`/LLM-extract path, default off** — returns HTTP 403 `SCRAPE_PROMPT_INJECTION_DETECTED` | Answers the PRD's open question. Firecrawl needs **two rows**, not a policy call |
| 4 | **`fetch-guard` is a poor positive control** — 1 star, nothing since 2026-03, URL-only, CLI-only, no JSON output, detection claims unvalidated | Dropped from the grid; replaced by a pre-flight raw-HTML assertion |
| 5 | **Cache defaults are worse than assumed** — Firecrawl `maxAge` defaults to **2 days** | Fresh-URL-per-run is not enough; every adapter passes an explicit no-cache param |

Plus: Tavily ToS §3.2(x) restricts disclosing "performance information or analysis" — **measure now, decide publishing later** *(your decision)*.

## Decisions locked

- **Environment:** migrate to WSL2 / Ubuntu before starting
- **Crawl4AI:** reclassified to the baselines row
- **Tavily:** include in the harness; publishing decision deferred until the data exists
- **Tool selection** driven by one criterion from `awesome-ai-web-search`: *does it accept an arbitrary caller-supplied URL and return that page's content?*

---

## Step 0 — WSL2 migration (brief; WSL2 already running)

**Keep the project on the Linux filesystem (`~/projects`), not `/mnt/c`** — `/mnt/c` is slow for many small files and mangles permissions, and this project's whole payload surface is exotic Unicode that Windows cp1252 console handling will corrupt.

```bash
sudo apt update && sudo apt install -y gh python3 build-essential
curl -LsSf https://astral.sh/uv/install.sh | sh
mkdir -p ~/projects/Smoke && cd ~/projects/Smoke
cp /mnt/c/Users/philipp.hunold/projects/Smoke/PRD.md .
git init && gh auth login
```

Then restart the Claude Code session inside WSL so the working directory is `~/projects/Smoke`. Keys go in `~/.smoke.env` (git-ignored, sourced per run) — never committed.

---

## Scope — v1 grid

**Hosted (the story).** Five vendors; Crawl4AI's slot goes to Context.dev, which is hosted, has the best free tier (1,000 credits/month, no card) and a documented cache-bypass knob.

| Row | Call | Text at | Cache bypass |
|---|---|---|---|
| `jina` | `GET https://r.jina.ai/<url>`, keyless, `Accept: application/json` | `data.content` | header `x-no-cache: true` |
| `firecrawl_md` | `POST api.firecrawl.dev/v2/scrape` | `data.markdown` | `maxAge: 0` **(default is 2 days)** |
| `firecrawl_json` | same + `json` format, `checkPromptInjection: true` | — | `maxAge: 0` |
| `tavily` | `POST api.tavily.com/extract` | `results[].raw_content` | none — fresh URL only |
| `exa` | `POST api.exa.ai/contents`, `x-api-key` | `results[].text` | `maxAgeHours: 0` |
| `context_dev` | `POST api.context.dev/v1/web/scrape` | `markdown.data` | `maxAgeMs: 0` |

**Baselines (local, HTML-string in).** One plain GET fetches the HTML; the same bytes feed all of these: `trafilatura.extract(html, output_format="markdown")` (returns `str | None`), `html2text.html2text(html)`, `markitdown` via `convert_stream(io.BytesIO(html_bytes), stream_info=StreamInfo(mimetype="text/html", extension=".html", charset="utf-8"))` — **binary stream required** — and Crawl4AI, included only if it installs cleanly.

**Stretch, after the core loop works** (~12 lines each): Olostep (`POST /v1/scrapes`, also returns `html_content`), Linkup (`POST /v1/fetch`; note `renderJs` defaults false).

**Excluded, with reasons for the README:** Brave Search API and SearXNG are query-only — they cannot accept a fixture URL at all. JigsawStack has no full-page markdown mode. All SERP APIs (SerpApi, Serper, SearchApi, DataForSEO, TalorData) are out by the same criterion. *This is itself a finding: most "AI web search tools for agents" are search, not extraction.*

**Grid: 4 payloads × 2 placements × 2 lengths = 16 fixtures.** This halves the PRD's grid — it drops the 4-placement axis to `in_main | out_of_main`. Rationale: stripping is structural, not positional; the only positional thing that moves results is whether boilerplate removal engages, which is exactly in-main vs out-of-main. It's an `itertools.product` over three module-level lists, so restoring the full axis after run 1 is a one-line edit.

---

## Architecture

```
smoke.py                 # grid, fixtures, detector, adapters, runner, report, flips
test_detect.py           # the runnable check — no network, no keys
pyproject.toml           # uv: httpx, trafilatura, html2text, markitdown
docs/f/<run_id>/*.html   # fixtures served by GitHub Pages
results/<run_id>.json    # long-lived artifact
raw/<run_id>.json.gz     # verbatim tool output, so a detector bug is re-scored offline
flips/<run_id>.md
.github/workflows/monthly.yml
```

One module with section banners; split only past ~600 lines. Subcommands: `generate`, `run`, `analyze <run_id>`, `report`, `flips`.

**Adapters: a plain function per tool + a registry list.** Two signatures, not one — hosted takes a URL, local takes HTML; forcing them into one shape would be a lie. Each returns a `Fetched(text, warn, error, meta)` where `warn ∈ {"n/a", "silent", "warned"}` — this one field distinguishes *"no warning mechanism exists"* from *"mechanism existed and stayed silent"*, which is the PRD's actual question.

**Skip the vendor SDKs** (`firecrawl-py`, `tavily-python`, `exa-py`). Each wraps a single POST; raw `httpx` gives ~12-line adapters, one error taxonomy, three fewer pinned deps. An endpoint change then surfaces as an `error` row rather than being absorbed — the right failure mode for a monitoring harness.

**Results JSON: a flat list of self-describing trials**, so adding or removing a tool changes the record count, never the schema. `state ∈ reached | altered | stripped | empty | error`, `pass ∈ exact | nowrap | nocf | untag | null`. **`empty` is deliberately distinct from `stripped`** — `trafilatura` returning `None` or Tavily returning 200 with both arrays empty means we learned nothing, and collapsing that into "stripped" is precisely the false clean bill of health this project exists to avoid.

---

## The detector (highest-risk logic)

Canary: `"sm0ke" + token_hex(6) + f"{i:02d}"` — pure ASCII (tag-block encoding only covers 0x00–0x7F), no `--` (illegal in HTML comments), no `<>&`, no whitespace, lowercase. **The needle is invariant under every transform, so only the haystack is transformed.**

Four ordered passes on the haystack, first hit wins; the pass name is the recorded evidence:

| pass | transform | → state |
|---|---|---|
| `exact` | identity | reached |
| `nowrap` | delete whitespace | altered |
| `untag` | `chr(ord(c) - 0xE0000)` for U+E0000–E007F, then drop `Cf`, then whitespace | altered |
| `nocf` | drop `Cf`, then whitespace | altered |
| — | no match | stripped |

**Ordering is load-bearing: tag characters are themselves `Cf`.** Strip `Cf` before decoding the tag block and every tag-payload cell reports "stripped" — a silent false exoneration of the vendor. `test_detect.py` pins this by asserting the *pass name*, not just the state.

---

## Implementation order

1. **Detector + `test_detect.py`** — no network, no keys. Get this right first; everything downstream trusts it.
2. **Fixture generator + local baselines** → a real `results.json` offline. **Working demo exists at this point.**
3. **Report + flip detection**, against that local JSON.
4. **Publish `docs/`** — one push for all 16 fixtures (Pages soft-limits 10 builds/hour), then poll each URL until HTTP 200 before any tool call.
5. **Hosted adapters, one at a time, Jina first** (keyless — no signup to get the first hosted row working).
6. **Monthly GitHub Action.**

**Failure handling, proportionate:** adapter raises → record `state:"error"`, continue; never abort. One retry after `sleep(10)` on 429/5xx/timeout — a `for attempt in (1, 2)`, not a framework. Firecrawl-json 403 `SCRAPE_PROMPT_INJECTION_DETECTED` → `state:"stripped"`, `warn:"warned"`. **Aborts the run:** missing API key, deploy-poll timeout, or pre-flight failure.

**Flip detection** keys on `(tool, payload, placement, length)`. Tool churn is structural, not a flip — new keys go under "new coverage", dropped under "removed". Any change where either side is `error`/`empty` goes under a separate "transient / unverified" heading, so a vendor outage never reads as a behaviour change.

---

## Verification

- `uv run python test_detect.py` — asserts, no network. Must cover: zero-width-interleaved canary → `altered/nocf` (not `stripped`); tag-encoded canary → `altered/untag` **asserting the pass name** (this is the assertion that catches the `Cf`-ordering bug); `NFKC(zw_canary)` → still `altered`, pinning the verified fact that normalisation changes nothing so a future "just use NFKC" simplification regresses loudly; negatives — absent canary and `canary[:-1]` → `stripped`.
- **Pre-flight = the real positive control.** After the push, GET each fixture URL and assert the canary is detectable in the raw published bytes. If it isn't there before any tool touches it, the run is garbage — abort. This replaces `fetch-guard`, for free.
- End-to-end offline: `generate` → local baselines only → `report` produces a Markdown table with no API keys set.
- Then one hosted tool (Jina, keyless) end-to-end before wiring the rest.

## Deferred past v1

Olostep + Linkup (stretch rows), `fetch-guard`, concurrency, retries beyond the single one, PDF/DOCX, model-behaviour tests, MCP pipes. Fixture dirs: keep only the last two `docs/f/<run_id>/` per commit — git history retains the rest, and `results/` is the actual artifact.

## Open items to chase before first publication

- Exa ToS — served as a PDF that couldn't be parsed this session; check `exa.ai/terms-of-service` manually
- Context.dev ToS §8 has a generic "don't compete with us" clause — read before publishing
- Tavily — the §3.2(x) publishing decision, once the data exists
- Linkup caching behaviour (undocumented) if the stretch row gets built
