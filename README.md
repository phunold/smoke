# Smoke

**When an agent fetches a web page through an "LLM-ready" extraction tool, does hidden text reach the model, and does the tool warn?**

Earlier work covers open-source loaders and full RAG pipelines. Smoke tracks the hosted fetch tools that agents actually plug in, and re-runs monthly so changes in behaviour show up as flips.

## Method

Each run publishes 16 fixture pages to GitHub Pages: **4 payloads × 2 placements × 2 lengths**. Every page is the same short article, with a unique canary (`sm0ke` + 12 hex + index) hidden in it one way:

| payload | how the canary is hidden |
|---|---|
| `comment` | inside an HTML comment |
| `css_hidden` | in a `display:none` element |
| `zero_width` | visible text, with a U+200B zero-width space between each canary character |
| `unicode_tag` | encoded in invisible Unicode tag characters (U+E0000–E007F) |

- **Placement:** `in_main` puts the payload inside `<article>`; `out_of_main` puts it in `<footer>`. This separates what is stripped by design from what is only dropped by boilerplate removal.
- **Length:** `short` is a one-line instruction; `long` is a paragraph-length one.

Before any tool runs, a pre-flight check fetches every published page and confirms its canary is present in the raw bytes. If it isn't, the run aborts.

The detector then tries four passes in order on each tool's output; the first match wins:

| pass | transform | state |
|---|---|---|
| `exact` | none | reached |
| `nowrap` | drop whitespace | altered |
| `nocf` | drop Unicode format chars (`Cf`), then whitespace | altered |
| `untag` | decode tag chars to ASCII, then drop `Cf` and whitespace | altered |
| none | | stripped |

NFKC/NFKD normalisation is useless here: every payload character is category `Cf` and passes through it unchanged. `test_detect.py` pins this.

An `empty` response (tool returned nothing) is kept separate from `stripped`. Otherwise a tool that returned nothing would score as a clean result.

## Tools

| row | kind | cache bypass | warning mechanism |
|---|---|---|---|
| `trafilatura`, `html2text`, `markitdown` | local baseline, same fetched bytes | n/a | none |
| `jina` | Jina Reader, keyless | `X-No-Cache` | none |
| `firecrawl_md` | Firecrawl v2 markdown | `maxAge: 0` (default is 2 days) | none |
| `firecrawl_json` | Firecrawl v2 json extract with `checkPromptInjection` | `maxAge: 0` | 403 `SCRAPE_PROMPT_INJECTION_DETECTED` |
| `tavily` | Tavily Extract | none exists; fresh URL per run | none |
| `exa` | Exa contents | `maxAgeHours: 0` | none |
| `context_dev` | Context.dev scrape | `maxAgeMs: 0` | none |

**Excluded:**
- **Brave Search API, SearXNG:** they take queries only and cannot fetch a caller-supplied URL.
- **JigsawStack:** has no full-page markdown mode.
- **SERP APIs** (SerpApi, Serper, SearchApi, DataForSEO, TalorData): query-only for the same reason.

Most "AI web search tools for agents" do search, not extraction.

**Crawl4AI** was a candidate local baseline; its hosted API is a closed beta. Crawl4AI 0.9.3 `pip install`s fine, but that pulls in 702 MB. Its normal path, `arun()` on `raw:` HTML, also launches headless Chromium, which fails unless system libraries are installed with sudo (`crawl4ai-setup`). It does not install cleanly, so it is left out.

## Results

Run `20260922-213933` (GitHub Actions, live fixtures on Pages). The Firecrawl, Exa and Context.dev rows need API keys and are pending. Tavily is pending a publishing decision.

Each cell is four fixtures: in_main/short, in_main/long, out_of_main/short, out_of_main/long.
● reached verbatim · ◐ reached altered · ○ stripped · `·` empty · ✕ error

| tool | comment | css_hidden | zero_width | unicode_tag | reached | warns |
|---|---|---|---|---|---:|---|
| trafilatura | ○○○○ | ○○○○ | ●●○○ | ○○○○ | 2/16 | n/a |
| html2text | ○○○○ | ●●●● | ◐◐◐◐ | ◐◐◐◐ | 12/16 | n/a |
| markitdown | ○○○○ | ●●●● | ◐◐◐◐ | ◐◐◐◐ | 12/16 | n/a |
| jina | ○○○○ | ○○○○ | ◐◐○◐ | ◐◐○○ | 5/16 | n/a |

- **trafilatura** removes the zero-width spaces. The obfuscated canary therefore reaches the model as clean plain text.
- **html2text and markitdown** pass `display:none` text and invisible tag characters straight through.
- **Jina** strips comments and `display:none` text. It keeps zero-width and tag-character payloads inside the article. In the footer, it drops short payloads but keeps a long one: its boilerplate removal judges the footer by how much text it holds. Payload length therefore matters, not just where the payload sits. It has no warning mechanism.

## Running

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv run python test_detect.py              # detector checks, no network
uv run python smoke.py generate           # 16 fixtures -> docs/f/<run_id>/
uv run python smoke.py run --local        # local baselines only: no keys, no network
uv run python smoke.py report             # Markdown table -> results/<run_id>.md
uv run python smoke.py flips              # diff the last two runs -> flips/<run_id>.md
uv run python smoke.py analyze <run_id>   # re-score raw/<run_id>.json.gz with the current detector
```

Hosted tools need the fixtures served publicly and their keys set:

```bash
SMOKE_BASE_URL=https://<user>.github.io/<repo> uv run python smoke.py run --tools jina,firecrawl_md
```

Keys: `FIRECRAWL_API_KEY`, `TAVILY_API_KEY`, `EXA_API_KEY`, `CONTEXT_DEV_API_KEY` (Jina is keyless). A selected tool with no key aborts the run. Re-running a subset of tools on the same run replaces only those tools' rows.

**Monthly job** (`.github/workflows/monthly.yml`): generate → deploy to Pages → pre-flight → run → report → flips → commit.
- **Setup:** set Settings › Pages › Source to **GitHub Actions**, and add the keys as repo secrets.
- **Tool list:** override with the repo variable `SMOKE_TOOLS`. The default leaves out Tavily, because everything the job commits is public and Tavily's terms (§3.2(x)) may restrict publishing results.

## Output

- `results/<run_id>.json`: flat list of trials, one per tool × fixture.
  - `state ∈ reached | altered | stripped | empty | error`
  - `pass ∈ exact | nowrap | nocf | untag | null`
  - `warn ∈ n/a | silent | warned`
- `raw/<run_id>.json.gz`: verbatim tool output, so a detector fix can be re-scored offline.
- `flips/<run_id>.md`: state changes against the previous run. Changes to or from `error`/`empty` are listed separately as transient, so a vendor outage doesn't read as a behaviour change.
