"""
AI News Digest v2 — central configuration.

Sab tunables ek jagah: timeouts, limits, retry policy, topics, models.
app.py isi module se import karta hai.

Secrets SIRF environment variables se aate hain — kabhi hard-code mat
karna, kabhi commit mat karna:

    SERPAPI_KEY     SerpApi API key  (serpapi.com, free plan 250/month)
    GEMINI_API_KEY  Gemini API key   (aistudio.google.com)

Keys missing hon to app sample mode me chalti rehti hai (demo kabhi
nahi toot-ta).
"""
import os


# ------------------------------------------------------------------ secrets
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()


# --------------------------------------------------------------------- app
APP_VERSION = "3.0.0"  # News Agent — AI Agents track


# -------------------------------------------------------------------- agent
AGENT_MAX_HISTORY = 8            # session me yaad rakhne wale exchanges
AGENT_MAX_SESSIONS = 200         # server-side session dict cap
AGENT_SOURCES_LIMIT = 7          # compare step: top N sources
AGENT_RESULTS_PER_TOOL = 8       # har tool se max items (num=8 se match)
AGENT_MAX_MESSAGE_CHARS = 500    # /api/chat message length limit


# -------------------------------------------------------------------- cache
CACHE_TTL_SECONDS = 2 * 60 * 60   # 2 hours — topics aur custom search dono
MAX_CACHE_ENTRIES = 50            # cap cross ho to sabse purani entry nikalo


# ------------------------------------------------------------------ serpapi
SERPAPI_URL = "https://serpapi.com/search.json"
SERPAPI_ENGINE = "google_news"
SERPAPI_TIMEOUT_SECONDS = 25
SERPAPI_RETRIES = 2                    # pehle attempt ke baad 2 retries
SERPAPI_BACKOFF_BASE_SECONDS = 1       # exponential: 1s -> 2s
SERPAPI_GEO = "in"                     # gl: India results
SERPAPI_LANG = "en"                    # hl: English
SERPAPI_SORT_BY_DATE = "1"             # so=1: freshest news pehle
NEWS_ITEM_LIMIT = 8                    # har response me max items


# ------------------------------------------------------------------- gemini
GEMINI_MODELS = [                      # fallback ladder, best pehle
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]
GEMINI_TIMEOUT_SECONDS = 30
GEMINI_MAX_TOKENS = 400
GEMINI_TEMPERATURE = 0.3
GEMINI_ATTEMPTS_PER_MODEL = 3
SUMMARY_UNAVAILABLE = "Summary unavailable"


# ------------------------------------------------------------------- search
MAX_QUERY_CHARS = 100                  # /api/search?q= length limit


# ------------------------------------------------------------------- topics
TOPICS = {
    "ai": "artificial intelligence",
    "startups": "AI startups India",
    "tech": "technology news India",
}


# ------------------------------------------------------------------- server
PORT = int(os.environ.get("PORT") or 5000)
