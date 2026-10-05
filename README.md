# News Agent 🤖

**SerpApi India Hackathon 2026 — AI Agents track · Solo entry by Ayaz Gori**

Ek conversational AI research agent: chat me sawaal poochho, agent **plan karke
SerpApi se multi-search chalata hai, sources compare karke Hinglish jawab
synthesize karta hai** — har step ka trace UI me dikhta hai ("Agent trace").

## Agent architecture

```
                ┌─────────────┐
                │    User     │  "AI agents India me kya ho raha hai?"
                └──────┬──────┘
                       ▼
                ┌─────────────┐
                │    PLAN     │  Gemini: 2 targeted queries banata hai
                │             │  (1 news angle + 1 web angle)
                │             │  Key nahi hai → rule-based keyword fallback
                └──────┬──────┘
                       ▼
         ┌──────────────────────────┐
         │          SEARCH          │  Locked params: gl=in, hl=en, num=8
         │ news_search → google_news│  (sort_by_date=1, latest pehle)
         │ web_search  → google     │  google_news fail → 1 retry →
         └──────────────┬───────────┘  → backup: google + tbs=qdr:d
                        ▼
                 ┌─────────────┐
                 │   COMPARE   │  dedupe (link/title) → recency +
                 │             │  relevance rank → top 7 sources
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐
                 │ SYNTHESIZE  │  Gemini: 3-5 line Hinglish jawab,
                 │             │  har claim pe [1][2] citation.
                 │             │  Sirf compact sources milte hain
                 │             │  (title/link/source/date/snippet) —
                 │             │  raw SerpApi JSON nahi (token saving).
                 │             │  Key nahi hai → templated jawab.
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐
                 │   ANSWER    │  jawab + sources + agent trace (chat UI)
                 └─────────────┘
```

## Loop steps (detail)

1. **PLAN** — `agent.plan_queries()`: user ka sawaal + recent conversation
   context Gemini ko milta hai → max 2-3 targeted search queries
   (tool, query, angle). Gemini key missing/fail → keyword-based fallback.
2. **SEARCH** — `agent.news_search()` / `agent.web_search()`: har planned
   query apne fixed engine pe chalti hai (`google_news` + `sort_by_date`,
   `google`). Per-query 2-hr cache. Har successful call = 1 SerpApi credit
   (free plan 250/month) — isliye plan 2 queries se zyada nahi banata.
   `google_news` fail → 1 retry → backup `web_search(tbs=qdr:d)`.
3. **COMPARE** — `agent.compare_sources()`: duplicate links/titles hatao,
   recency (iso_date) + query-relevance se score karke top 7 chuno.
4. **SYNTHESIZE** — Gemini ko sirf compact source list milti hai → 3-5 line
   Hinglish jawab, har fact ke saath `[n]` citation. Gemini key nahi hai →
   sample data se templated jawab.
5. **TRACE** — `planned_queries`, `searches` (tool/engine/query/hits/credits),
   `sources_compared`, `mode` (live|sample) → API response me wapas, UI me
   expandable "Agent trace".

## What it does

- **Chat UI** (mobile-first, dark): user right-blue bubbles, agent left-cards,
  typing indicator ("plan → search → compare"), har jawab ke neeche
  expandable **Agent trace**, source links ki list, input box + send.
- **Conversation memory**: session-based (server-side dict, browser cookie/
  localStorage uuid), pichle 8 exchanges yaad — follow-up sawaal context
  samajhte hain.
- **Sample mode**: bina keys ke agent poora loop sample data pe chalata hai
  (scripted trace ke saath) — demo kabhi nahi toot-ta, header me ● SAMPLE badge.
- **Quota-safe**: per-query search cache (2h), per-message answer cache, plan
  max 2 queries.
- Legacy JSON endpoints (`/api/news`, `/api/search`, `/api/topics`) ab bhi
  available hain (quick tools ke liye).
- Keys **sirf env vars** me (`SERPAPI_KEY`, `GEMINI_API_KEY`) — code/repo me
  kabhi hardcode nahi.

## Quick start (local)

```bash
cd serpapi-hackathon
pip install -r requirements.txt
cp .env.example .env        # fill in your keys (optional — app runs without them)
python app.py               # -> http://localhost:5000
```

Then open `http://localhost:5000` (mobile browser works too).

### API keys

| Key | Where to get it | Free tier |
|---|---|---|
| `SERPAPI_KEY` | [serpapi.com](https://serpapi.com) → sign up → Dashboard → API Key | 250 searches/month |
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) → Get API key | generous free quota |

Without keys the app runs in **sample mode** (header shows ● SAMPLE).

## API

- `POST /api/chat` — body `{"message": "...", "session_id": "..."}` →
  `{"answer": "...", "sources": [{"title","link","source"}],
   "trace": {"planned_queries": [...], "searches": [{"tool","engine","query","hits": n}],
             "sources_compared": n, "sources_picked": n, "mode": "live"|"sample",
             "plan_source": "gemini"|"rules", "synthesize_source": "gemini"|"template"},
   "cached": bool, "session_id": "..."}`
  - Empty message → friendly validation error (kabhi HTTP 500 nahi).
- `GET /` — chat UI
- `GET /api/news?topic=ai|startups|tech` — legacy news endpoint
- `GET /api/search?q=...` — legacy custom search
- `GET /api/topics` — topic presets
- `GET /health` — version, agent (mode/tools/conversations), key status, cache stats, uptime

**Reliability:** koi bhi route kabhi HTTP 500 nahi deta — SerpApi timeout
(retry + backoff), bad key, quota exhaustion, bad queries sab friendly JSON
messages + sample-data fallback ke saath handle hote hain.

## Deploy on Render (free)

1. Push this folder to a **public GitHub repo**.
2. [render.com](https://render.com) → New → **Web Service** → connect the repo.
3. Render auto-detects `render.yaml` (or set manually):
   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2`
   - Plan: **Free**
4. Environment tab → add `SERPAPI_KEY` and `GEMINI_API_KEY` (values secret).
5. Deploy → done.

## Tech stack

Python · Flask · SerpApi (`google_news` + `google` engines) · Google Gemini
(2.5-flash-lite) · gunicorn

## AI-tools disclosure

> **Built with AI assistance — Muse Spark agent.** Code, design and documentation
> were produced by an AI coding agent under the direction of Ayaz Gori
> (human entry, solo).

## License

MIT — see [LICENSE](LICENSE).
