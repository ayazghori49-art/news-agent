"""
News Agent v3 — SerpApi India Hackathon 2026 (AI Agents track).

Conversational AI research agent: user chat me sawaal poochta hai, agent
PLAN -> SEARCH -> COMPARE -> SYNTHESIZE ka real loop chalata hai
(agent.py), har step ka trace UI ko dikhata hai.

Tools: news_search (google_news engine, sort_by_date) aur web_search
(google engine). Params locked: {"gl": "in", "hl": "en", "num": 8}.
Bina keys ke sample mode me chalta hai — demo kabhi nahi toot-ta, aur
koi bhi route kabhi HTTP 500 nahi deta (hamesha JSON payload).

API contract v3:
    POST /api/chat                  {"message": "...", "session_id": "..."}
                                    -> {"answer", "sources[]", "trace", "cached",
                                        "session_id", "error"?}
    GET /api/news?topic=ai|startups|tech   (legacy news endpoint, kept)
    GET /api/search?q=<query>              (legacy custom search, kept)
    GET /api/topics                        topic map
    GET /health                            status + agent + cache + uptime detail

Sab config config.py me hai. Keys sirf env vars se aati hain.

AI-assisted development disclosure: Built with AI assistance (Muse Spark agent).
"""
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, render_template, request

import config

# ------------------------------------------------------------------ logging
# Format EXACT: "%(asctime)s %(levelname)s %(name)s: %(message)s", INFO level.
# Kabhi bhi API key log mat karna — SerpApi calls "bina key ke" log hote hain.
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("ainews")

app = Flask(__name__, template_folder=".")

START_TIME = time.monotonic()  # /health uptime ke liye

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_PATH = os.path.join(BASE_DIR, "sample_news.json")


# ------------------------------------------------------------------- cache
# Shared store: "topic:<key>" aur "search:<normalized query>" ->
# (timestamp, payload). 2-hour TTL, max 50 entries (LRU-ish eviction).
_cache: dict = {}


def cache_get(key: str):
    """Fresh cached payload do, ya None. Expired entry turant hatao."""
    entry = _cache.get(key)
    if entry is None:
        return None
    timestamp, payload = entry
    if time.time() - timestamp < config.CACHE_TTL_SECONDS:
        return payload
    _cache.pop(key, None)
    return None


def cache_put(key: str, payload: dict) -> None:
    """Payload store karo; 50 entries cross hon to sabse purani nikalo."""
    if key in _cache:
        _cache[key] = (time.time(), payload)
        return
    if len(_cache) >= config.MAX_CACHE_ENTRIES:
        oldest = min(_cache, key=lambda k: _cache[k][0])
        _cache.pop(oldest, None)
        log.info(
            "Cache full (%d entries) — evicted oldest entry %r",
            config.MAX_CACHE_ENTRIES,
            oldest,
        )
    _cache[key] = (time.time(), payload)


# ------------------------------------------------------------------ secrets
# api_key=... pattern logs/errors se strip karne ke liye. requests ke
# exception messages me kabhi-kabhi poora URL (api_key samet) aa jata hai,
# isliye har bahar jaane wali error string isse guzarti hai.
_API_KEY_PATTERN = re.compile(r"api_key=[^&\s'\"]*", re.IGNORECASE)


# ------------------------------------------------------- conversations
# Session-based memory: session_id -> recent exchanges
# [{"role": "user"|"assistant", "content": str}]. Follow-up sawaalon ke
# liye pichle 6-8 exchanges yaad rehte hain (config.AGENT_MAX_HISTORY).
_conversations: dict[str, list[dict]] = {}


def _prune_conversations() -> None:
    """Session dict cap cross ho to sabse purane sessions nikalo."""
    while len(_conversations) > config.AGENT_MAX_SESSIONS:
        oldest = next(iter(_conversations))
        _conversations.pop(oldest, None)


def sanitize(text) -> str:
    """Error/log strings se API key ke tukde hatao."""
    if not isinstance(text, str):
        text = str(text)
    return _API_KEY_PATTERN.sub("api_key=[REDACTED]", text)


# --------------------------------------------------------------- exceptions
class SerpApiError(Exception):
    """Base: SerpApi se kuch bhi gadbad."""


class SerpApiAuthError(SerpApiError):
    """401/403 — key galat, expired ya missing. Retry ka koi fayda nahi."""


class SerpApiQuotaError(SerpApiError):
    """429 — free quota (250/month) khatm. Retry ka koi fayda nahi."""


class SerpApiTransientError(SerpApiError):
    """Timeout / network / 5xx — retry layak."""


# ----------------------------------------------------------------- serpapi
def serpapi_get(query: str) -> dict:
    """
    SerpApi search.json pe GET. Transient failures pe 2 retries,
    exponential backoff 1s -> 2s.

    Raises:
        SerpApiAuthError      401/403 (bad key) — no retry
        SerpApiQuotaError     429 (quota over) — no retry
        SerpApiTransientError timeout/network/5xx — retried, phir raise

    API key kabhi log nahi hoti.
    """
    if not config.SERPAPI_KEY:
        raise SerpApiAuthError("SerpApi API key is not configured")

    params = {
        "engine": config.SERPAPI_ENGINE,
        "q": query,
        "gl": config.SERPAPI_GEO,
        "hl": config.SERPAPI_LANG,
        "so": config.SERPAPI_SORT_BY_DATE,
        "api_key": config.SERPAPI_KEY,
    }

    attempts = config.SERPAPI_RETRIES + 1
    last_exc: SerpApiError | None = None

    for attempt in range(attempts):
        try:
            log.info(
                "SerpApi request: engine=%s q=%r (attempt %d/%d)",
                config.SERPAPI_ENGINE,
                query,
                attempt + 1,
                attempts,
            )
            resp = requests.get(
                config.SERPAPI_URL,
                params=params,
                timeout=config.SERPAPI_TIMEOUT_SECONDS,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = SerpApiTransientError(f"network/timeout: {sanitize(exc)}")
            log.warning("SerpApi network failure (attempt %d): %s",
                        attempt + 1, sanitize(last_exc))
        except requests.RequestException as exc:
            # Non-retryable request-level failure (URL me key ho sakti hai -> sanitize)
            raise SerpApiError(f"request failed: {sanitize(exc)}")

        else:
            status = resp.status_code
            if status in (401, 403):
                log.warning("SerpApi auth failure (HTTP %d) — API key issue", status)
                raise SerpApiAuthError(
                    f"SerpApi rejected the API key (HTTP {status})"
                )
            if status == 429:
                log.warning("SerpApi quota exhausted (HTTP 429)")
                raise SerpApiQuotaError("SerpApi monthly quota finished")
            if 500 <= status < 600:
                last_exc = SerpApiTransientError(f"SerpApi HTTP {status}")
                log.warning("SerpApi server error HTTP %d (attempt %d)",
                            status, attempt + 1)
            elif status != 200:
                raise SerpApiError(
                    f"SerpApi HTTP {status}: {sanitize(resp.text[:200])}"
                )
            else:
                log.info("SerpApi success for q=%r", query)
                return resp.json()

        # Yahan aaye matlab retryable failure hui
        if attempt < config.SERPAPI_RETRIES:
            delay = config.SERPAPI_BACKOFF_BASE_SECONDS * (2 ** attempt)  # 1s, 2s
            log.info("SerpApi retry in %ds ...", delay)
            time.sleep(delay)

    log.warning("SerpApi gave up after %d attempts for q=%r", attempts, query)
    raise last_exc or SerpApiTransientError("SerpApi failed after retries")


def fetch_live_news(query: str, limit: int = config.NEWS_ITEM_LIMIT) -> list[dict]:
    """SerpApi news_results ko clean item dicts me badlo. Failure pe raise."""
    data = serpapi_get(query)
    results = data.get("news_results") or []
    items = []
    for r in results[:limit]:
        title = (r.get("title") or "").strip()
        if not title:
            continue  # bina title ke card bekaar hai
        source = r.get("source") or {}
        # source OBJECT hota hai {name, icon, authors} — string assume mat karo
        if isinstance(source, dict):
            source_name = source.get("name", "")
            source_icon = source.get("icon", "")
        else:
            source_name, source_icon = str(source), ""
        items.append(
            {
                "position": r.get("position"),
                "title": title,
                "link": r.get("link", ""),
                "source": source_name,
                "source_icon": source_icon,
                "date": r.get("date", ""),
                "iso_date": r.get("iso_date", ""),
                "thumbnail": r.get("thumbnail", ""),
                "snippet": r.get("snippet", ""),  # guaranteed nahi — defensive
            }
        )
    if not items:
        raise SerpApiError("SerpApi returned no usable news_results")
    return items


# ------------------------------------------------------------------ sample
def load_sample_news(limit: int = config.NEWS_ITEM_LIMIT) -> list[dict]:
    """Realistic sample data — demo kabhi break nahi hota. is_sample tag samet."""
    try:
        with open(SAMPLE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = (data.get("news_results") or [])[:limit]
        for it in items:
            it["is_sample"] = True
        log.info("Sample fallback: serving %d sample items", len(items))
        return items
    except Exception as exc:  # last-resort guard — kabhi raise mat karo
        log.error("sample_news.json unreadable: %s", sanitize(exc))
        return []


# ------------------------------------------------------------------ gemini
def _gemini_generate(model: str, prompt: str) -> str:
    """Single Gemini call. Non-200 pe raise taaki caller fallback kar sake."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": config.GEMINI_TEMPERATURE,
            "maxOutputTokens": config.GEMINI_MAX_TOKENS,
        },
    }
    resp = requests.post(
        url,
        headers={"x-goog-api-key": config.GEMINI_API_KEY,
                 "Content-Type": "application/json"},
        json=body,
        timeout=config.GEMINI_TIMEOUT_SECONDS,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Gemini {model} HTTP {resp.status_code}: {sanitize(resp.text[:200])}"
        )
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def summarize_batch(headlines: list[str]) -> list[str]:
    """
    Ek batched Gemini call: 5-8 headlines -> 1-2 line Hinglish summaries.
    Model ladder: flash-lite -> 2.5-flash -> 2.0-flash, 429 pe backoff.
    Total failure pe har headline ke liye "Summary unavailable".
    Kabhi raise nahi karta.
    """
    fallback = [config.SUMMARY_UNAVAILABLE] * len(headlines)
    if not config.GEMINI_API_KEY:
        return fallback

    numbered = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(headlines))
    prompt = (
        "Neeche AI/tech news ki headlines hain. Har headline ke liye 1-2 line ki "
        "short summary likho — Hinglish (Roman script, jaise WhatsApp pe likhte hain), "
        "simple aur interesting tone me. Sirf JSON array of strings return karo, "
        "koi extra text nahi. Example: [\"summary1\", \"summary2\"]\n\n" + numbered
    )

    for model in config.GEMINI_MODELS:
        for attempt in range(config.GEMINI_ATTEMPTS_PER_MODEL):
            try:
                raw = _gemini_generate(model, prompt)
                cleaned = raw.strip()
                if cleaned.startswith("```"):  # ```json fences strip karo
                    cleaned = cleaned.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
                parsed = json.loads(cleaned)
                if isinstance(parsed, list) and parsed:
                    summaries = [str(s) for s in parsed]
                    while len(summaries) < len(headlines):
                        summaries.append(config.SUMMARY_UNAVAILABLE)
                    return summaries[: len(headlines)]
            except Exception as exc:
                msg = sanitize(exc)
                if "429" in msg and attempt < config.GEMINI_ATTEMPTS_PER_MODEL - 1:
                    time.sleep(2 ** attempt)  # 429 -> exponential backoff
                    continue
                log.error("Gemini %s failed (attempt %d): %s",
                          model, attempt, msg[:150])
                break  # non-429: agle model pe jao
    return fallback


# ---------------------------------------------------------------- pipeline
def build_payload(topic, query, items, live, error=None) -> dict:
    """API contract v2 ka standard payload. error sirf failure pe."""
    payload = {
        "topic": topic,
        "query": query,
        "live": live,
        "cached": False,  # cache hit pe caller True karta hai
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "items": items,
    }
    if error:
        payload["error"] = error
    return payload


def failure_payload(topic, query, message: str) -> dict:
    """Kabhi-500-nahi guard: khaali items + friendly error, HTTP 200 ke sath."""
    return build_payload(topic, query, [], live=False, error=message)


def get_news_payload(cache_key: str, topic, query: str) -> dict:
    """
    News pipeline: cache -> SerpApi (retry) -> Gemini summaries -> cache.
    Kabhi raise nahi karta — SerpApi failure pe sample fallback + error note.
    """
    cached = cache_get(cache_key)
    if cached is not None:
        payload = dict(cached)
        payload["cached"] = True
        log.info("Cache hit: %r", cache_key)
        return payload

    live, error = True, None
    try:
        items = fetch_live_news(query)
    except SerpApiAuthError:
        log.warning("Sample fallback for q=%r: API key issue", query)
        items = load_sample_news()
        live = False
        error = ("Live news unavailable — SerpApi key me issue hai. "
                 "Demo ke liye sample headlines dikha rahe hain.")
    except SerpApiQuotaError:
        log.warning("Sample fallback for q=%r: quota exhausted", query)
        items = load_sample_news()
        live = False
        error = ("Live news unavailable — is mahine ka SerpApi quota khatm ho gaya. "
                 "Sample headlines dikha rahe hain.")
    except SerpApiError as exc:
        log.warning("Sample fallback for q=%r: %s", query, sanitize(exc))
        items = load_sample_news()
        live = False
        error = ("Live news abhi nahi mil pa rahi — sample headlines dikha rahe hain. "
                 "Thodi der baad retry karein.")

    headlines = [it.get("title", "") for it in items]
    summaries = summarize_batch(headlines)
    for it, summary in zip(items, summaries):
        it["summary"] = summary

    payload = build_payload(topic, query, items, live, error)
    cache_put(cache_key, payload)
    return payload


# ------------------------------------------------------------- validation
def validate_query(raw) -> tuple[str | None, str | None]:
    """
    /api/search ka q validate karo. Returns (clean_query, None) ya
    (None, friendly_error_message). Gibberish = koi readable text nahi.
    """
    q = (raw or "").strip()
    if not q:
        return None, "Search karne ke liye kuch type karein — box khaali hai."
    collapsed = " ".join(q.split())  # extra whitespace hatao
    if len(collapsed) > config.MAX_QUERY_CHARS:
        return None, (
            f"Query bahut lambi hai — {config.MAX_QUERY_CHARS} characters "
            "ke andar rakhein."
        )
    if not any(ch.isalnum() for ch in collapsed):
        return None, ("Query me koi readable text nahi hai — "
                      "please sahi shabd type karein.")
    return collapsed, None


# ----------------------------------------------------------------- routes
@app.route("/")
def index():
    return render_template("chat.html")


def _chat_error(message: str, session_id: str, http_code: int = 200):
    """Friendly validation error — kabhi 500 nahi, hamesha JSON."""
    return jsonify({
        "answer": "",
        "sources": [],
        "trace": {},
        "cached": False,
        "session_id": session_id,
        "error": message,
    }), http_code


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """
    POST /api/chat — conversational agent loop.
    Body: {"message": "...", "session_id": "..."}.
    Empty/invalid message -> friendly validation error (HTTP 200, kabhi 500 nahi).
    Response: {"answer", "sources": [{title, link, source}], "trace",
               "cached", "session_id", "notice"?}.
    """
    session_id = ""
    try:
        body = request.get_json(silent=True) or {}
        raw = body.get("message", "")
        session_id = body.get("session_id") or ""

        if not isinstance(raw, str) or not raw.strip():
            return _chat_error(
                "Kuch type to karo — sawaal khaali hai 🙂", session_id or uuid.uuid4().hex
            )
        message = " ".join(raw.split())
        if len(message) > config.AGENT_MAX_MESSAGE_CHARS:
            return _chat_error(
                f"Sawaal thoda chhota rakho — "
                f"{config.AGENT_MAX_MESSAGE_CHARS} characters ke andar.",
                session_id or uuid.uuid4().hex,
            )
        if not isinstance(session_id, str) or not re.fullmatch(r"[0-9a-f]{32}", session_id):
            session_id = uuid.uuid4().hex  # naya session

        # Full-answer cache (message-level) — quota bachao
        cache_key = f"agentchat:{message.lower()}"
        cached_payload = cache_get(cache_key)

        history = _conversations.get(session_id, [])
        if cached_payload is not None:
            result = dict(cached_payload)
            result["cached"] = True
            log.info("Agent answer cache hit: %r", message[:60])
        else:
            # agent.py ka lazy import — circular import se bachne ke liye.
            # Is point tak app module poori tarah loaded hai.
            from agent import run_agent
            result = run_agent(message, history)
            result["cached"] = False
            cache_put(cache_key, result)

        # Conversation memory update (trim to last N exchanges)
        history = history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": result.get("answer", "")},
        ]
        _conversations[session_id] = history[-config.AGENT_MAX_HISTORY:]
        _prune_conversations()

        result["session_id"] = session_id
        return jsonify(result)
    except Exception:  # kabhi 500 nahi — hamesha JSON payload
        log.exception("Unhandled error in /api/chat")
        return _chat_error(
            "Kuch gadbad ho gayi — dobara try karo.",
            session_id if re.fullmatch(r"[0-9a-f]{32}", session_id or "")
            else uuid.uuid4().hex,
        )


@app.route("/api/news")
def api_news():
    """GET /api/news?topic=ai|startups|tech — contract v2, behavior same as v1."""
    try:
        topic = (request.args.get("topic") or "ai").strip() or "ai"
        query = config.TOPICS.get(topic, config.TOPICS["ai"])
        return jsonify(get_news_payload(f"topic:{topic}", topic, query))
    except Exception as exc:  # kabhi 500 nahi — hamesha JSON payload
        log.exception("Unhandled error in /api/news")
        return jsonify(failure_payload(
            None, "ai", "News load nahi ho paayi — please retry karein."
        )), 200


@app.route("/api/search")
def api_search():
    """GET /api/search?q=<query> — custom user search, SerpApi google_news
    engine pe, date-sort. Validation fail -> items=[] + friendly error, HTTP 200."""
    try:
        raw = request.args.get("q", "")
        query, err = validate_query(raw)
        if err:
            log.info("Search rejected: q=%r", raw[:60])
            return jsonify(failure_payload(None, raw.strip()[:60], err)), 200
        normalized = query.lower()  # cache key normalize: lowercase+strip
        return jsonify(get_news_payload(f"search:{normalized}", None, query))
    except Exception as exc:  # kabhi 500 nahi — hamesha JSON payload
        log.exception("Unhandled error in /api/search")
        return jsonify(failure_payload(
            None, (request.args.get("q") or "")[:60],
            "Search me kuch gadbad hui — please dobara try karein."
        )), 200


@app.route("/api/topics")
def api_topics():
    return jsonify({"topics": config.TOPICS})


@app.route("/health")
def health():
    """Detailed health: version, agent, key status, cache stats, uptime."""
    return jsonify({
        "status": "ok",
        "version": config.APP_VERSION,
        "agent": {
            "mode": "live" if config.SERPAPI_KEY else "sample",
            "tools": ["news_search (google_news)", "web_search (google)"],
            "conversations": len(_conversations),
        },
        "serpapi_configured": bool(config.SERPAPI_KEY),
        "gemini_configured": bool(config.GEMINI_API_KEY),
        "cache": {
            "entries": len(_cache),
            "ttl_seconds": config.CACHE_TTL_SECONDS,
        },
        "uptime_seconds": int(time.monotonic() - START_TIME),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=False)
