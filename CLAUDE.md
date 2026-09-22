# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

v1 built: `smoke.py` (all sections), `test_detect.py`, `.github/workflows/monthly.yml`, `README.md`. `PRD.md` is the original plan and rationale; where it disagrees with this file (pass order, Crawl4AI), this file wins. Hosted adapters are verified against vendor docs and mocked responses, but only Jina has been called live.

## What Smoke is

A benchmark that asks one question: when an agent fetches a web page through an "LLM-ready" extraction tool (Jina, Firecrawl, Tavily, Exa, Context.dev) or a local baseline (trafilatura, html2text, markitdown), does hidden text reach the model, and does the tool warn about it? The fixtures are HTML pages with ASCII canaries hidden by different payload techniques. The harness publishes them to GitHub Pages, fetches them through each tool, and checks whether the canary survives.

## Commands

```bash
uv run python test_detect.py          # detector tests: no network, no keys; run after any detector change
uv run python smoke.py generate       # build the 16 fixtures into docs/f/<run_id>/
uv run python smoke.py run --local    # local baselines only; no keys, no network
uv run python smoke.py run [--tools a,b]  # pre-flight, then adapters -> results/<run_id>.json + raw/<run_id>.json.gz
uv run python smoke.py analyze <run_id>
uv run python smoke.py report         # Markdown results table
uv run python smoke.py flips          # diff against the previous run -> flips/<run_id>.md
```

**uv, never pip.** Deps via `uv add`/`uv remove`, run via `uv run`. No `pip install`, no hand-made venvs. Commit `uv.lock`.

API keys live in `~/.smoke.env`. That file is git-ignored and sourced per run; never commit it. Jina is keyless. The offline path (`generate`, then local baselines, then `report`) must work with no keys set.

## Architecture

- `smoke.py` is a single module with section banners: grid, fixtures, detector, adapters, runner, report, flips. Split it only once it passes ~600 lines.
- **Grid:** 4 payloads × 2 placements (`in_main | out_of_main`) × 2 lengths = 16 fixtures. It is an `itertools.product` over three module-level lists.
- **Adapters:** one plain function per tool plus a registry list. There are two signatures on purpose: hosted adapters take a URL, local ones take HTML. Don't merge them. Each returns `Fetched(text, warn, error, raw)` (`raw` = verbatim response body) with `warn ∈ {"n/a", "silent", "warned"}`. `n/a` means the tool has no warning mechanism; `silent` means it has one and did not warn.
- **No vendor SDKs.** Use raw `httpx` POST/GET calls, so an endpoint change surfaces as an `error` row instead of being absorbed by an SDK.
- **Cache bypass is mandatory** on every hosted adapter: Jina `x-no-cache: true`, Firecrawl `maxAge: 0` (its default is 2 days), Exa `maxAgeHours: 0`, Context.dev `maxAgeMs: 0`. Tavily has no bypass, so use a fresh URL.
- **Firecrawl has two rows.** `firecrawl_md` is plain markdown. `firecrawl_json` uses the `json` format with `checkPromptInjection: true`. A 403 `SCRAPE_PROMPT_INJECTION_DETECTED` is recorded as `state:"stripped"`, `warn:"warned"`.
- **Results** are a flat list of self-describing trials, so adding a tool changes the record count, never the schema. `state ∈ reached | altered | stripped | empty | error`, `pass ∈ exact | nowrap | nocf | untag | null`. `empty` (a None or empty response) must stay distinct from `stripped`. Merging them would report a false clean result.
- **Failure handling:** if an adapter raises, record `error` and keep going. Retry once after `sleep(10)` on 429/5xx/timeout. Abort the whole run only on a missing API key, a deploy-poll timeout, or a pre-flight failure.
- **Pre-flight is the positive control.** The monthly workflow deploys `docs/` with `actions/deploy-pages` (Pages source must be "GitHub Actions"). `run` then polls each fixture URL until it returns 200, 10 min max. Then it asserts the canary is detectable in the raw published bytes before any tool runs.
- **Flips** are keyed on `(tool, payload, placement, length)`. New or removed keys are reported as coverage changes, not flips. Any change where either side is `error` or `empty` goes under "transient / unverified".

## Detector invariants (highest-risk logic)

- Canary: `"sm0ke" + token_hex(6) + f"{i:02d}"`. It is pure lowercase ASCII with no whitespace, `--`, or `<>&`. The needle never changes; only the haystack is transformed.
- **NFKC/NFKD normalisation does nothing** to these payloads, because they are all Unicode category `Cf`. Don't "simplify" the detector to use NFKC. The tests pin this.
- Passes run in order and the first hit wins: `exact` (reached), then `nowrap` (drop whitespace), then `nocf` (drop `Cf`, then drop whitespace), then `untag` (decode U+E0000–E007F via `chr(ord(c) - 0xE0000)`, then drop `Cf`, then drop whitespace). No match means `stripped`. `nocf` must precede `untag` (PRD table has it backwards): `untag` also drops `Cf`, so it would shadow `nocf`.
- **Inside the `untag` pass, decode before dropping `Cf`.** Tag characters are themselves `Cf`, so stripping first would falsely report tag payloads as `stripped`. Tests assert the *pass name*, not just the state.

## Repo layout conventions

- `docs/f/<run_id>/*.html` holds fixtures served by Pages. Keep only the last two run dirs; git history keeps the rest.
- `results/<run_id>.json` is the long-lived artifact. `raw/<run_id>.json.gz` stores verbatim tool output so a detector bug can be re-scored offline.
- Tavily ToS §3.2(x) may restrict publishing its results. Collect Tavily data, but don't publish it without an explicit decision. The monthly workflow's default tool list leaves Tavily out for this reason, because everything it commits is public. Don't commit local Tavily results either.
- Crawl4AI is excluded: 702 MB install, and its `arun()` needs headless Chromium plus system libs (sudo). The README records why.
