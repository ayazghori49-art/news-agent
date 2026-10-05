"""
News Agent — agentic loop for SerpApi India Hackathon 2026 (AI Agents track).

Ek conversational research agent: user ka sawaal aata hai, agent plan karke
SerpApi se multi-search chalata hai, sources compare karke Gemini se Hinglish
jawab synthesize karta hai. Har step ka trace UI ko wapas milta hai.

Loop (REAL code, naatak nahi):
    1. PLAN       Gemini 2 targeted queries banata hai (news + web angle).
                  Key nahi hai -> rule-based keyword fallback.
    2. SEARCH     Har planned query apne tool pe chalti hai:
                    news_search -> google_news engine (sort_by_date)
                    web_search  -> google engine
                  google_news fail -> 1 retry -> phir google + tbs=qdr:d backup.
                  Har failure pe friendly message, kabhi crash nahi.
    3. COMPARE    dedupe (link/title), recency + relevance rank, top 7 sources.
    4. SYNTHESIZE Gemini: 3-5 line Hinglish jawab, har claim pe [n] citation.
                  Key nahi hai -> templated jawab (sample data se).
    5. TRACE      planned queries, searches, compare stats -> API response me.

Params lock (research finding): plan step SIRF query string banata hai, baaki
params fixed hain: {"gl": "in", "hl": "en", "num": 8}.

Quota note: har successful SerpApi call = 1 credit (free plan 250/month).
Plan max 2 queries banata hai; searches per-query cache hote hain.

app.py ka shared plumbing reuse hota hai (exceptions, sanitize, cache,
sample data, Gemini caller) — circular import se bachne ke liye ye module
sirf tab import hota hai jab /api/chat route pehli baar hit hota hai
(app.py me function-level import), tab tak app module poori tarah loaded hai.

AI-assisted development disclosure: Built with AI assistance (Muse Spark agent).
"""
import json
import logging
import re
import time
from datetime import datetime, timezone

import requests

import config
from app import (
    SerpApiAuthError,
    SerpApiError,
    SerpApiQuotaError,
    SerpApiTransientError,
    _gemini_generate,
    cache_get,
    cache_put,
    load_sample_news,
    sanitize,
)

log = logging.getLogger("newsagent")

# ------------------------------------------------- locked params (finding #2)
DEFAULT_PARAMS = {"gl": "in", "hl": "en", "num": 8}  # plan step inhe touch nahi karta
NEWS_ENGINE = "google_news"
WEB_ENGINE = "google"
NEWS_SORT = {"sort_by_date": "1"}       # finding #5: latest news pehle
WEB_DATE_BACKUP = {"tbs": "qdr:d"}      # finding #4: news fail ka backup


# ------------------------------------------------- raw call (1 call = 1 credit)
def _serpapi_call(engine: str, query: str, extra_params: dict | None = None) -> dict:
    """
    Ek raw SerpApi call. Locked DEFAULT_PARAMS + engine + query + extra.
    Retry YAHAAN nahi hota — tool-level policy news_search me hai.
    Raises: SerpApiAuthError / SerpApiQuotaError / SerpApiTransientError / SerpApiError.
    API key kabhi log nahi hoti.
    """
    if not config.SERPAPI_KEY:
        raise SerpApiAuthError("SerpApi API key is not configured")

    params = dict(DEFAULT_PARAMS)
    params.update({"engine": engine, "q": query, "api_key": config.SERPAPI_KEY})
    if extra_params:
        params.update(extra_params)

    log.info("Agent SerpApi call: engine=%s q=%r (key hidden)", engine, query)
    try:
        resp = requests.get(
            config.SERPAPI_URL, params=params, timeout=config.SERPAPI_TIMEOUT_SECONDS
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise SerpApiTransientError(f"network/timeout: {sanitize(exc)}")
    except requests.RequestException as exc:
        raise SerpApiError(f"request failed: {sanitize(exc)}")

    status = resp.status_code
    if status in (401, 403):
        raise SerpApiAuthError(f"SerpApi rejected the API key (HTTP {status})")
    if status == 429:
        raise SerpApiQuotaError("SerpApi monthly quota finished")
    if 500 <= status < 600:
        raise SerpApiTransientError(f"SerpApi HTTP {status}")
    if status != 200:
        raise SerpApiError(f"SerpApi HTTP {status}: {sanitize(resp.text[:200])}")
    return resp.json()


def _parse_items(raw_list: list) -> list[dict]:
    """news_results ya organic_results -> clean compact item dicts."""
    items = []
    for r in raw_list:
        title = (r.get("title") or "").strip()
        if not title:
            continue
        source = r.get("source") or {}
        source_name = source.get("name", "") if isinstance(source, dict) else str(source)
        items.append(
            {
                "title": title,
                "link": r.get("link", ""),
                "source": source_name,
                "date": r.get("date", ""),
                "iso_date": r.get("iso_date", ""),
                "snippet": r.get("snippet", "") or "",
            }
        )
    return items


# ------------------------------------------------- TOOL 1: news_search (finding #1)
def news_search(query: str) -> tuple[list[dict], dict]:
    """
    Sirf google_news engine pe chalti hai (sort_by_date=1).
    Policy: fail -> 1 retry -> phir backup: web_search(query, tbs=qdr:d).
    Returns (items, tool_trace). Hard failure pe raise (caller sample fallback karta hai).
    """
    trace = {
        "tool": "news_search",
        "engine": NEWS_ENGINE,
        "query": query,
        "hits": 0,
        "credits": 0,
        "fallback_used": False,
    }
    data = None
    try:
        data = _serpapi_call(NEWS_ENGINE, query, NEWS_SORT)
        trace["credits"] = 1
    except SerpApiTransientError as exc:
        log.warning("news_search transient fail, 1 retry: %s", sanitize(exc))
        try:
            data = _serpapi_call(NEWS_ENGINE, query, NEWS_SORT)
            trace["credits"] = 1
        except SerpApiTransientError as exc2:
            log.warning("news_search retry bhi fail — backup web_search: %s",
                        sanitize(exc2))
            items, fb_trace = web_search(query, tbs="qdr:d")
            trace["fallback_used"] = True
            trace["credits"] = fb_trace["credits"]
            trace["hits"] = len(items)
            return items, trace
    # SerpApiAuthError / SerpApiQuotaError / SerpApiError yahin se raise honge

    items = _parse_items((data or {}).get("news_results") or [])
    items = items[: config.AGENT_RESULTS_PER_TOOL]
    trace["hits"] = len(items)
    return items, trace


# ------------------------------------------------- TOOL 2: web_search (finding #1)
def web_search(query: str, tbs: str | None = None) -> tuple[list[dict], dict]:
    """
    Sirf google engine pe chalti hai. tbs optional (backup me "qdr:d" aata hai).
    Returns (items, tool_trace). Failure pe raise.
    """
    trace = {
        "tool": "web_search",
        "engine": WEB_ENGINE,
        "query": query,
        "hits": 0,
        "credits": 0,
    }
    data = _serpapi_call(WEB_ENGINE, query, {"tbs": tbs} if tbs else None)
    trace["credits"] = 1
    items = _parse_items(data.get("organic_results") or [])
    items = items[: config.AGENT_RESULTS_PER_TOOL]
    trace["hits"] = len(items)
    return items, trace


def _compact_item(it: dict) -> dict:
    """Raw sample item -> compact shape (source dict se name nikalo)."""
    src = it.get("source") or {}
    name = src.get("name", "") if isinstance(src, dict) else str(src)
    return {
        "title": it.get("title", ""),
        "link": it.get("link", ""),
        "source": name,
        "date": it.get("date", ""),
        "iso_date": it.get("iso_date", ""),
        "snippet": it.get("snippet") or "",
    }


# ------------------------------------------------- sample-mode search
def _sample_search(tool: str, query: str) -> list[dict]:
    """Bina key / failure pe: sample data me keyword relevance se top items."""
    tokens = _keywords(query)
    items = load_sample_news(config.AGENT_RESULTS_PER_TOOL * 2)
    scored = []
    for it in items:
        text = (it.get("title", "") + " " + (it.get("snippet") or "")).lower()
        score = sum(1 for t in tokens if t in text) if tokens else 0
        scored.append((score, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [_compact_item(it) for _, it in scored[: config.AGENT_RESULTS_PER_TOOL]]


# ------------------------------------------------- STEP 1: PLAN
_STOPWORDS = {
    "kya", "hai", "ka", "ki", "ke", "ko", "me", "mein", "se", "par", "aur",
    "ya", "toh", "batao", "bataiye", "bataye", "news", "samachar", "aaj",
    "kal", "latest", "taaza", "taza", "mujhe", "mere", "mera", "iske",
    "uske", "iska", "uska", "ye", "wo", "woh", "kaise", "kab", "kyun",
    "kahan", "kitna", "raha", "rahe", "rahi", "rahen", "hoga", "hogi", "honge",
    "hota", "hote", "hoti", "kar", "karke", "kiya", "kiye", "the", "a", "an",
    "is", "are", "was", "what", "when",
    "why", "how", "where", "in", "of", "on", "for", "to", "latest", "today",
    "about", "tell", "me", "give", "some", "any", "update", "updates",
}


def _keywords(text: str) -> list[str]:
    """Message se meaningful keywords nikalo (Hindi + English)."""
    toks = re.findall(r"[a-zA-Z0-9\u0900-\u097F]+", (text or "").lower())
    return [t for t in toks if t not in _STOPWORDS and len(t) > 2]


def _plan_fallback(message: str) -> list[dict]:
    """Gemini key nahi hai / fail hua: rule-based 2 queries (1 news + 1 web)."""
    kw = _keywords(message)[:5] or ["AI", "news"]
    base = " ".join(kw)
    return [
        {"tool": "news_search", "query": base, "angle": "news"},
        {"tool": "web_search", "query": f"{base} India", "angle": "web"},
    ]


def _plan_with_gemini(message: str, history: list[dict]) -> list[dict] | None:
    """Gemini se max 3 targeted queries. Parse fail / error -> None."""
    ctx = ""
    if history:
        last = history[-2:]
        ctx = "Recent conversation: " + " | ".join(
            f"{m['role']}: {m['content'][:120]}" for m in last
        )
    prompt = (
        "Tum ek research agent ka planner ho. User ka sawaal neeche hai "
        "(Hinglish ho sakta hai).\n"
        f"Sawaal: \"{message}\"\n{ctx}\n\n"
        "Kaam: SerpApi pe chalane layak MAX 3 targeted search queries banao — "
        "kam se kam 1 news angle (tool: news_search) aur 1 web angle "
        "(tool: web_search). Follow-up sawaal ho to conversation context use karo.\n"
        "Sirf JSON array return karo, koi extra text nahi. Queries English me, "
        "3-6 shabd ki:\n"
        '[{"tool":"news_search","query":"...","angle":"news"},'
        ' {"tool":"web_search","query":"...","angle":"web"}]'
    )
    last_exc = None
    for model in config.GEMINI_MODELS[:2]:
        try:
            raw = _gemini_generate(model, prompt)
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(cleaned)
            if not isinstance(parsed, list) or not parsed:
                continue
            queries = []
            for q in parsed[:3]:
                if not isinstance(q, dict):
                    continue
                tool = q.get("tool")
                query = (q.get("query") or "").strip()
                if tool in ("news_search", "web_search") and query:
                    queries.append(
                        {"tool": tool, "query": query[:80],
                         "angle": q.get("angle") or tool}
                    )
            if queries:
                log.info("Plan via Gemini (%s): %d queries", model, len(queries))
                return queries
        except Exception as exc:
            last_exc = exc
            log.warning("Plan via %s fail: %s", model, sanitize(exc)[:120])
    log.warning("Gemini plan fail (%s) — rule fallback",
                sanitize(last_exc)[:120] if last_exc else "parse")
    return None


def plan_queries(message: str, history: list[dict]) -> tuple[list[dict], str]:
    """
    STEP 1 — PLAN. Returns (planned_queries, plan_source).
    planned_queries: [{"tool": "news_search"|"web_search", "query": str, "angle": str}]
    """
    if config.GEMINI_API_KEY:
        queries = _plan_with_gemini(message, history)
        if queries:
            return queries, "gemini"
    return _plan_fallback(message), "rules"


# ------------------------------------------------- STEP 2: SEARCH
def _friendly_search_error(exc: Exception) -> str:
    if isinstance(exc, SerpApiAuthError):
        return ("SerpApi key me issue hai — is sawaal ka jawab sample data "
                "se de rahe hain.")
    if isinstance(exc, SerpApiQuotaError):
        return ("Is mahine ka SerpApi quota khatm ho gaya — sample data se "
                "jawab de rahe hain.")
    return ("Search abhi nahi ho paaya — sample data se jawab de rahe hain.")


def run_search(pq: dict) -> tuple[list[dict], dict]:
    """
    STEP 2 — SEARCH. Ek planned query apne tool pe chalao.
    Per-query cache (quota bachao). Key missing / failure -> sample fallback.
    Returns (items, search_trace).
    """
    tool, query = pq["tool"], pq["query"]
    engine = NEWS_ENGINE if tool == "news_search" else WEB_ENGINE

    cache_key = f"agentsearch:{tool}:{query.lower().strip()}"
    cached = cache_get(cache_key)
    if cached is not None:
        trace = dict(cached["trace"])
        trace["cached"] = True
        log.info("Agent search cache hit: %s %r", tool, query)
        return list(cached["items"]), trace

    items, trace = [], {
        "tool": tool, "engine": engine, "query": query,
        "hits": 0, "credits": 0, "cached": False, "mode": "live",
    }
    if config.SERPAPI_KEY:
        try:
            if tool == "news_search":
                items, trace = news_search(query)
            else:
                items, trace = web_search(query)
            trace["cached"] = False
        except SerpApiError as exc:
            trace["error"] = _friendly_search_error(exc)
            trace["mode"] = "sample"
            items = _sample_search(tool, query)
            trace["hits"] = len(items)
    else:
        trace["mode"] = "sample"
        items = _sample_search(tool, query)
        trace["hits"] = len(items)

    cache_put(cache_key, {"items": items, "trace": trace})
    return items, trace


# ------------------------------------------------- STEP 3: COMPARE
def _recency_score(date_str: str) -> float:
    """iso_date ya 'MM/DD/YYYY, HH:MM AM' -> 0..1 (taaza = zyada)."""
    if not date_str:
        return 0.2
    try:
        dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(str(date_str), "%m/%d/%Y, %I:%M %p")
            dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return 0.2
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
    return 1.0 / (1.0 + days)


def compare_sources(
    items: list[dict], query_keywords: list[str], limit: int = None
) -> list[dict]:
    """
    STEP 3 — COMPARE. Dedupe (same link/title hatao), phir
    recency + relevance se rank karke top N sources chuno.
    """
    limit = limit or config.AGENT_SOURCES_LIMIT
    seen_links, seen_titles, unique = set(), set(), []
    for it in items:
        link_key = re.sub(r"^https?://(www\.)?", "",
                          (it.get("link") or "").lower()).rstrip("/")
        title_key = re.sub(r"[^a-z0-9]", "", (it.get("title") or "").lower())[:60]
        if (link_key and link_key in seen_links) or \
           (title_key and title_key in seen_titles):
            continue
        if link_key:
            seen_links.add(link_key)
        if title_key:
            seen_titles.add(title_key)
        unique.append(it)

    scored = []
    for it in unique:
        text = (it.get("title", "") + " " + (it.get("snippet") or "")).lower()
        relevance = (
            sum(1 for k in query_keywords if k in text) / len(query_keywords)
            if query_keywords else 0.0
        )
        recency = _recency_score(it.get("iso_date") or it.get("date"))
        scored.append((0.6 * relevance + 0.4 * recency, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored[:limit]]


# ------------------------------------------------- STEP 4: SYNTHESIZE
def _compact_sources(sources: list[dict]) -> str:
    """Finding #3: Gemini ko raw JSON nahi — compact list (title/link/source/date/snippet)."""
    lines = []
    for i, s in enumerate(sources, 1):
        lines.append(
            f"[{i}] {s.get('title', '')}\n"
            f"    source: {s.get('source', '')} | date: {s.get('date', '')}\n"
            f"    snippet: {(s.get('snippet') or '')[:220]}\n"
            f"    link: {s.get('link', '')}"
        )
    return "\n".join(lines)


def _synthesize_with_gemini(
    message: str, sources: list[dict], history: list[dict]
) -> str:
    """Gemini: compact sources se 3-5 line Hinglish jawab + [n] citations."""
    ctx = ""
    if history:
        last_user = next((m["content"] for m in reversed(history)
                          if m.get("role") == "user"), "")
        if last_user and last_user != message:
            ctx = f"Pichla sawaal tha: \"{last_user[:120]}\" (follow-up ho sakta hai).\n"
    prompt = (
        "Tum ek Hinglish news research agent ho. User ka sawaal aur neeche "
        "numbered sources (title/link/source/date/snippet) diye hain.\n"
        f"{ctx}Sawaal: \"{message}\"\n\n"
        "SOURCES:\n" + _compact_sources(sources) + "\n\n"
        "Kaam: 3-5 line ka jawab do — Roman-script Hinglish, simple "
        "WhatsApp-style tone. Har claim/fact ke saath uska source number "
        "[1], [2] lagao. Sources me jo NAHI hai wo mat jodo, andaza mat lagao. "
        "Sirf jawab ka text do, sources ki list mat do (wo alag se dikhegi)."
    )
    last_exc = None
    for model in config.GEMINI_MODELS[:2]:
        try:
            text = _gemini_generate(model, prompt)
            log.info("Synthesize via Gemini (%s)", model)
            return text.strip()
        except Exception as exc:
            last_exc = exc
            log.warning("Synthesize via %s fail: %s", model, sanitize(exc)[:120])
    raise RuntimeError(f"Gemini synthesize fail: {sanitize(last_exc)[:120]}")


def _synthesize_template(message: str, sources: list[dict]) -> str:
    """Gemini key nahi hai: sample sources se templated Hinglish jawab."""
    if not sources:
        return ("Is sawaal pe abhi koi fresh source nahi mila — thoda aur "
                "specific pooch ke dekho, jaise \"AI startups India funding\".")
    lines = [f"**{message.strip()}** — yeh raha latest update:"]
    for i, s in enumerate(sources[:4], 1):
        core = (s.get("snippet") or s.get("title", "")).strip()
        src = f" ({s.get('source', '')})" if s.get("source") else ""
        lines.append(f"• {core}{src} [{i}]")
    lines.append("Neeche sources ki list se full detail padh sakte ho.")
    return "\n".join(lines)


# ------------------------------------------------- full loop
def run_agent(message: str, history: list[dict]) -> dict:
    """
    STEP 1-5 ka full agentic loop. Returns:
    {"answer", "sources": [{title, link, source}],
     "trace": {planned_queries, searches, sources_compared, sources_picked,
               mode, plan_source, synthesize_source},
     "notice" (optional friendly message)}
    Kabhi raise nahi karta — har failure pe graceful degradation.
    """
    trace = {
        "planned_queries": [],
        "searches": [],
        "sources_compared": 0,
        "sources_picked": 0,
        "mode": "live" if config.SERPAPI_KEY else "sample",
        "plan_source": "rules",
        "synthesize_source": "template",
    }
    notice = None

    try:
        # 1. PLAN
        planned, plan_source = plan_queries(message, history)
        trace["planned_queries"] = planned
        trace["plan_source"] = plan_source

        # 2. SEARCH
        all_items = []
        for pq in planned:
            items, search_trace = run_search(pq)
            trace["searches"].append(search_trace)
            all_items.extend(items)
            if search_trace.get("error") and not notice:
                notice = search_trace["error"]
        trace["sources_compared"] = len(all_items)

        # 3. COMPARE
        keywords = _keywords(message)
        if not keywords:
            keywords = _keywords(" ".join(p["query"] for p in planned))
        picked = compare_sources(all_items, keywords)
        trace["sources_picked"] = len(picked)

        # 4. SYNTHESIZE (compact sources -> finding #3)
        if picked and config.GEMINI_API_KEY:
            try:
                answer = _synthesize_with_gemini(message, picked, history)
                trace["synthesize_source"] = "gemini"
            except Exception as exc:
                log.warning("Gemini synthesize fail, template: %s",
                            sanitize(exc)[:120])
                answer = _synthesize_template(message, picked)
        else:
            answer = _synthesize_template(message, picked)

        sources = [
            {"title": s.get("title", ""), "link": s.get("link", ""),
             "source": s.get("source", "")}
            for s in picked
        ]
    except Exception as exc:  # STEP 5 ka guard — loop kabhi crash nahi karta
        log.exception("run_agent unexpected failure")
        answer = ("Agent ko kuch dikkat aa gayi — dobara try karo. "
                  f"({sanitize(exc)[:80]})")
        sources = []
        notice = notice or "Temporary issue — dobara try karein."

    result = {"answer": answer, "sources": sources, "trace": trace}
    if notice:
        result["notice"] = notice
    return result
