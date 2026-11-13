"""
Google News -> Telegram channel bot
- Fetches news from Google News (RSS) for your keywords
- Mixes topics: takes the newest item from each keyword in turn
- Posts one by one with a random 1-2 min gap
- Then waits a random 30-60 min before the next round of 5
- Skips anything already posted and news older than MAX_AGE_HOURS

Install:  pip install feedparser requests
Run once (GitHub Actions):  python bot.py --once   (add --force to skip the 30-60 min wait)
"""

import os, sys, json, time, html, re, random
from datetime import datetime
from urllib.parse import quote
import feedparser, requests

# ===== SETTINGS =====
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")                      # stored in GitHub Secrets, never in code
CHAT_ID   = os.getenv("TG_CHAT_ID") or "-1004311851712"       # Market Pulse News
KEYWORDS  = ["gold price", "forex market", "bitcoin price", "federal reserve"]  # your topics
LANG, COUNTRY = "en", "US"         # e.g. "mk","MK" for Macedonian news

POSTS_PER_ROUND = 5
POST_GAP_SEC    = (60, 120)        # random gap between posts: 1-2 min
ROUND_GAP_MIN   = (30, 60)         # random gap between rounds: 30-60 min
MAX_AGE_HOURS   = 12               # ignore older news
SEEN_FILE = "seen.json"
STATE_FILE = "state.json"         # remembers when the next round is allowed
# ====================


def load_seen():
    try:
        return set(json.load(open(SEEN_FILE)))
    except Exception:
        return set()

def save_seen(seen):
    json.dump(list(seen)[-3000:], open(SEEN_FILE, "w"))

def load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {}

def save_state(state):
    json.dump(state, open(STATE_FILE, "w"))

def fetch_news(keyword):
    url = (f"https://news.google.com/rss/search?q={quote(keyword)}"
           f"&hl={LANG}&gl={COUNTRY}&ceid={COUNTRY}:{LANG}")
    feed = feedparser.parse(url)
    cutoff = time.time() - MAX_AGE_HOURS * 3600
    items = []
    for e in feed.entries:
        ts = time.mktime(e.published_parsed) if e.get("published_parsed") else 0
        if ts < cutoff:
            continue
        title = e.title
        source = e.get("source", {}).get("title", "")
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        items.append({"id": e.link, "title": title, "source": source,
                      "link": e.link, "ts": ts, "keyword": keyword})
    items.sort(key=lambda x: x["ts"], reverse=True)   # newest first
    return items

def format_post(item):
    t = html.escape(item["title"])
    src = html.escape(item["source"] or "Google News")
    tag = "#" + re.sub(r"\W+", "", item["keyword"].title())
    lines = [f"📰 <b>{t}</b>", "",
             f"🗞 {src}", f"🔗 <a href=\"{item['link']}\">Read more</a>", "", tag]
    return "\n".join(lines)

def send(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": False}
    for attempt in range(1, 4):
        try:
            r = requests.post(url, json=payload, timeout=30)
            if r.ok:
                return True
            print("  Telegram error:", r.text)
            if r.status_code == 429:   # Telegram says slow down
                wait = r.json().get("parameters", {}).get("retry_after", 10)
                time.sleep(wait)
                continue
            return False
        except requests.RequestException as ex:
            print(f"  network error (try {attempt}/3): {ex}")
            time.sleep(10 * attempt)
    return False

def pick_round(seen):
    """Newest unseen items, taking turns between topics: gold, forex, bitcoin, fed, gold..."""
    queues = {kw: [i for i in fetch_news(kw) if i["id"] not in seen] for kw in KEYWORDS}
    picks, used_titles = [], set()
    while len(picks) < POSTS_PER_ROUND and any(queues.values()):
        for kw in KEYWORDS:
            while queues[kw]:
                item = queues[kw].pop(0)
                key = item["title"].lower()
                if key in used_titles:        # same story under two topics
                    continue
                picks.append(item)
                used_titles.add(key)
                break
            if len(picks) >= POSTS_PER_ROUND:
                break
    return picks

def run_round():
    seen = load_seen()
    picks = pick_round(seen)
    print(f"[{datetime.now():%H:%M}] round start: {len(picks)} new items")
    for n, item in enumerate(picks, 1):
        if send(format_post(item)):
            seen.add(item["id"])
            save_seen(seen)
            print(f"  posted {n}/{len(picks)}: {item['title'][:70]}")
        if n < len(picks):
            gap = random.randint(*POST_GAP_SEC)
            print(f"  next post in {gap}s")
            time.sleep(gap)

if __name__ == "__main__":
    if not BOT_TOKEN:
        sys.exit("TG_BOT_TOKEN is not set")

    if "--once" in sys.argv:
        # Started every ~10 min by cron-job.org. Only posts when the random
        # 30-60 min gap since the last round has passed (or when forced).
        force = "--force" in sys.argv
        state = load_state()
        now = time.time()
        if not force and now < state.get("next_after", 0):
            mins = int((state["next_after"] - now) / 60) + 1
            print(f"Not time yet - next round in about {mins} min")
            sys.exit(0)
        run_round()
        gap = random.randint(*ROUND_GAP_MIN)
        save_state({"last_round": now, "next_after": now + gap * 60})
        print(f"Next round in about {gap} min")
        sys.exit(0)

    while True:                         # local/Colab mode: run forever
        run_round()
        wait = random.randint(*ROUND_GAP_MIN)
        print(f"Next round in {wait} min\n")
        time.sleep(wait * 60)
