#!/usr/bin/env python3
"""The Daily Butler — static site generator.

Reads (from the primary the-daily-butler project + the Butler corpus):
  - ~/AI/the-daily-butler/episodes/<date>--<slug>/episode.json
  - .../06-publish/podcast.json (historical published episodes)
  - .../06-publish/podcast-receipt.json (native published episodes)
  - .../06-publish/storyboard.json or 04-video/drafts/storyboard.json
  - ~/books/butler-saints/butler-complete.md (the source text)

Generates the full static site into the repo ROOT (committed so Vercel deploys):
  index.html, archive/, about/, episode/<date>/, reader/<MM-DD>/, css/, js/,
  sitemap.xml, robots.txt, 404.html

The reader is year-independent (keyed by MM-DD); the Butler text for a calendar
day is the same every year. Episode pages (year-specific) link to their MM-DD
reader page.

Run:
  python3 build/build.py                  # local build, no R2 upload
  python3 build/build.py --upload-art     # also push new hero art to R2 (public)
"""
import os, re, sys, json, datetime, html, hashlib, subprocess, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # repo root (output dir)
DAILY_BUTLER = os.path.abspath(os.path.expanduser(
    os.environ.get("DAILY_BUTLER_REPO", "~/AI/the-daily-butler")
))
CORPUS = os.path.abspath(os.path.expanduser(
    os.environ.get("BUTLER_CORPUS", "~/books/butler-saints/butler-complete.md")
))
UPLOAD_ART = "--upload-art" in sys.argv

R2_HOST = "feed.thedailybutler.com"
SITE = "thedailybutler.com"
CHANNEL = "UC9hSyqTY9oUQh1bRQjeO-TA"
YOUTUBE = f"https://www.youtube.com/channel/{CHANNEL}"
SUBSCRIBE = {
    "apple": "https://podcasts.apple.com/search?term=The+Daily+Butler",
    "spotify": "https://open.spotify.com/search/The%20Daily%20Butler",
    "r2": "https://feed.thedailybutler.com/feed.xml",
}

MONTHS = ["January","February","March","April","May","June","July","August",
          "September","October","November","December"]
MONTH_NUM = {m: i+1 for i, m in enumerate(MONTHS)}
MONTH_SLUG = {m: m.lower() for m in MONTHS}
MONTH_ABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def e(s):  # html escape
    return html.escape(s, quote=True)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


# ---------------------------------------------------------------- corpus
def clean_paragraph(raw):
    """Join wrapped lines within a paragraph; return a tidy text block."""
    raw = raw.replace("\u00a0", " ")
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\s*\n\s*", " ", raw)     # wrapped line -> space
    return raw.strip()


def split_reflection(body_paras):
    """Pull the trailing 'Reflection' out of a list of paragraphs.

    Returns (body_paras, reflection_text|None)."""
    for i, p in enumerate(body_paras):
        m = re.match(r"(?i)^\*{0,2}\s*Reflection\*{0,2}\s*[.:—-]?\s*(.*)$", p)
        if m:
            refl = m.group(1).strip()
            # the reflection may span following paragraphs
            for j in range(i+1, len(body_paras)):
                refl = (refl + " " + body_paras[j]).strip()
            return body_paras[:i], refl or None
    return body_paras, None


def parse_corpus():
    """Return an ordered list of 366 day dicts:
       {mmdd, month_num, day, month, month_slug, label,
        entries:[{name, is_person, paras:[...], reflection:str|None}]}"""
    src = open(CORPUS).read()
    # find all day sections: "## Month D." up to the next "## "
    days = []
    for m in re.finditer(r"^##\s+([A-Z][a-z]+)\s+(\d{1,2})\.\s*\n(.*?)(?=^##\s+|\Z)",
                         src, re.M | re.S):
        month, day = m.group(1), int(m.group(2))
        section = m.group(3)
        # split into entries on "### "
        entries = []
        for em in re.finditer(r"^###\s+(.+?)\s*\n(.*?)(?=^###\s+|\Z)",
                              section, re.M | re.S):
            name = clean_paragraph(em.group(1)).rstrip(".")
            body_raw = em.group(2)
            paras = [clean_paragraph(p) for p in re.split(r"\n\s*\n", body_raw)]
            paras = [p for p in paras if p]
            paras, refl = split_reflection(paras)
            if not paras and not refl:
                continue
            is_person = bool(re.match(r"^(st|sts|ss|saint|saints|blessed|venerable)\b", name, re.I))
            entries.append({"name": name, "is_person": is_person,
                            "paras": paras, "reflection": refl})
        if not entries:
            continue
        mn = MONTH_NUM[month]
        mmdd = f"{mn:02d}-{day:02d}"
        days.append({
            "mmdd": mmdd, "month_num": mn, "day": day, "month": month,
            "month_slug": MONTH_SLUG[month],
            "label": f"{day} {month}",
            "entries": entries,
        })
    days.sort(key=lambda d: (d["month_num"], d["day"]))
    return days


# ---------------------------------------------------------------- episodes
def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


def _existing_episode_file(episode_dir, value):
    """Resolve an episode-relative path without allowing it to escape the repo."""
    if not value:
        return None
    candidate = os.path.realpath(os.path.join(episode_dir, str(value)))
    project = os.path.realpath(DAILY_BUTLER)
    if candidate != project and not candidate.startswith(project + os.sep):
        return None
    return candidate if os.path.isfile(candidate) else None


def _imported_asset(episode_dir, storyboard_asset):
    """Map an imported legacy storyboard path to its new immutable destination."""
    manifest = read_json(os.path.join(episode_dir, "06-publish", "import-manifest.json"), {})
    wanted = str(storyboard_asset or "").replace("\\", "/")
    wanted_name = os.path.basename(wanted)
    for record in manifest.get("files", []):
        source = str(record.get("source") or "").replace("\\", "/")
        if source == wanted or source.endswith("/" + wanted) or os.path.basename(source) == wanted_name:
            resolved = _existing_episode_file(episode_dir, record.get("destination"))
            if resolved:
                return resolved
    return None


def _indexed_asset(episode_dir, asset_id=None, asset_path=None):
    index = read_json(os.path.join(episode_dir, "02-images", "index.json"), {})
    wanted_name = os.path.basename(str(asset_path or ""))
    approved_fallback = None
    for record in index.get("assets", []):
        if record.get("status") != "approved":
            continue
        resolved = _existing_episode_file(episode_dir, record.get("file"))
        if not resolved:
            continue
        if approved_fallback is None:
            approved_fallback = resolved
        if asset_id and asset_id in (record.get("id"), record.get("sha256")):
            return resolved
        if wanted_name and os.path.basename(str(record.get("file") or "")) == wanted_name:
            return resolved
    return approved_fallback


def hero_art(episode_dir, date_str):
    """Return the first approved storyboard image and its stable R2 object key."""
    storyboard = None
    for relative in (
        os.path.join("06-publish", "storyboard.json"),
        os.path.join("04-video", "drafts", "storyboard.json"),
    ):
        storyboard = read_json(os.path.join(episode_dir, relative))
        if storyboard:
            break

    first = ((storyboard or {}).get("shots") or [{}])[0]
    asset_path = first.get("source_path") or first.get("asset")
    local = _existing_episode_file(episode_dir, asset_path)
    if not local and asset_path:
        local = _existing_episode_file(DAILY_BUTLER, asset_path)
    if not local and asset_path:
        local = _imported_asset(episode_dir, asset_path)
    if not local:
        local = _indexed_asset(episode_dir, first.get("asset_id"), asset_path)
    if not local:
        return None
    return local, f"art/{date_str}.jpg"


def _published_item(episode_dir):
    """Load the canonical public podcast item for native or imported episodes."""
    receipt = read_json(os.path.join(episode_dir, "06-publish", "podcast-receipt.json"), {})
    item = receipt.get("item") if isinstance(receipt, dict) else None
    if isinstance(item, dict):
        return item, receipt
    historical = read_json(os.path.join(episode_dir, "06-publish", "podcast.json"))
    if isinstance(historical, dict):
        return historical, {}
    return None, {}


def load_episodes():
    eps = []
    ep_root = os.path.join(DAILY_BUTLER, "episodes")
    if not os.path.isdir(ep_root):
        return eps
    for d in sorted(os.listdir(ep_root)):
        if not re.match(r"^\d{4}-\d{2}-\d{2}(?:--.+)?$", d):
            continue
        episode_dir = os.path.join(ep_root, d)
        if not os.path.isdir(episode_dir):
            continue
        metadata = read_json(os.path.join(episode_dir, "episode.json"), {})
        item, receipt = _published_item(episode_dir)
        if not item or metadata.get("hold") is True or item.get("hold") is True:
            continue
        date = item.get("date") or metadata.get("date") or d[:10]
        try:
            dt = datetime.date.fromisoformat(date)
        except (TypeError, ValueError):
            continue
        ha = hero_art(episode_dir, date)
        channels = metadata.get("channels") or {}
        podcast_channel = channels.get("podcast") or {}
        youtube_channel = channels.get("youtube") or {}
        video_id = item.get("video_id") or youtube_channel.get("video_id")
        mp3_url = receipt.get("audio_url") or podcast_channel.get("audio_url")
        saints = item.get("saints") or []
        if not saints and metadata.get("saint"):
            saints = [metadata["saint"]]
        eps.append({
            "date": date,
            "mmdd": f"{dt.month:02d}-{dt.day:02d}",
            "month_num": dt.month,
            "title": item.get("title") or metadata.get("title") or date,
            "saints": saints,
            "video_id": video_id,
            "mp3_url": mp3_url or f"https://{R2_HOST}/mp3/{date}.mp3",
            "art_url": (f"https://{R2_HOST}/{ha[1]}" if ha else None),
            "art_local": (ha[0] if ha else None),
            "description": item.get("description", ""),
            "pub_date": item.get("pub_date") or receipt.get("verified_at", ""),
            "duration_s": item.get("duration_s", 0),
        })
    eps.sort(key=lambda x: x["date"])
    return eps


# ---------------------------------------------------------------- html helpers
def meta_tags(title, desc, url, image=None, extra=None):
    og_type = extra.get("type", "website")
    bits = [
        f'<meta charset="utf-8">',
        f'<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<title>{e(title)}</title>',
        f'<meta name="description" content="{e(desc)}">',
        f'<link rel="canonical" href="{url}">',
        f'<meta property="og:type" content="{og_type}">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(desc)}">',
        f'<meta property="og:url" content="{url}">',
        f'<meta property="og:site_name" content="The Daily Butler">',
        f'<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{e(title)}">',
        f'<meta name="twitter:description" content="{e(desc)}">',
        f'<link rel="icon" href="/favicon.png" type="image/png">',
        f'<link rel="apple-touch-icon" href="/apple-touch-icon.png">',
    ]
    if image:
        bits.append(f'<meta property="og:image" content="{image}">')
        bits.append(f'<meta name="twitter:image" content="{image}">')
    if extra.get("schema"):
        bits.append(f'<script type="application/ld+json">{extra["schema"]}</script>')
    return "\n".join(bits)


def _active(url):
    if "/archive/" in url or "/episode/" in url: return "archive"
    if "/about/" in url: return "about"
    return "home"


def header(active=""):
    def a(href, label, act=False):
        cls = ' class="active"' if act else ""
        return f'<a href="{href}"{cls}>{label}</a>'
    links = [a("/", "Home", active == "home"),
             a("/archive/", "Episodes", active == "archive"),
             a("/about/", "About", active == "about"),
             f'<a class="btn" href="/subscribe/">Subscribe</a>']
    return f"""
<header class="site-header">
  <div class="container nav">
    <a class="brand" href="/"><span class="sun"></span><b class="chrome">THE DAILY</b>&nbsp;<b class="chrome">BUTLER</b></a>
    <nav class="nav-links">
      {''.join(links)}
    </nav>
  </div>
</header>"""


def footer():
    return f"""
<footer class="site-footer">
  <div class="container">
    <div>© {datetime.date.today().year} The Daily Butler. The text from <a href="https://www.sacred-texts.com/chr/butler/butler-toc.htm">Butler's Lives of the Saints</a> (Benziger 1894) is public domain. Narration &amp; production © The Daily Butler.</div>
    <div>
      <a href="/archive/">Episodes</a> · <a href="/about/">About</a> ·
      <a href="{SUBSCRIBE['r2']}">RSS</a> · <a href="https://www.youtube.com/@thedailybutler">YouTube</a>
    </div>
  </div>
</footer>"""


def newsletter_form():
    return f"""
<section>
  <div class="container">
    <div class="news">
      <div>
        <h3>Each morning's life, in your inbox</h3>
        <p>A short note with the day's saint and a link to the full reading. No ads, no spam — just the reading.</p>
      </div>
      <form data-newsletter>
        <input type="email" placeholder="you@example.com" required aria-label="Email address">
        <button class="btn" type="submit">Subscribe</button>
        <span data-status aria-live="polite"></span>
      </form>
    </div>
  </div>
</section>"""


def subscribe_strip(center=False):
    cls = "subs center" if center else "subs"
    return f"""
<div class="{cls}">
  <a href="{SUBSCRIBE['apple']}"><svg viewBox="0 0 24 24"><path d="M16.5 3c.1 1.1-.3 2.2-.9 3-.8.9-2.1 1.4-3.2 1.2-.1-1 .4-2.1 1-2.9.7-.9 2-1.4 3.1-1.3z"/><path d="M12.7 6.4C12 5.9 11.2 5.7 10.4 5.7c-.9 0-1.8.4-2.4 1.1-.6.7-.9 1.7-.9 2.7 0 2 1.6 3.7 3.5 3.7.1 0 .2 0 .4 0-.1.4 0 .8.2 1.1.3.3.7.4 1.2.4.7 0 1.2-.4 1.6-1 .6.2 1.2.3 1.9.3.5 0 .9 0 1.4-.1.2-.4.4-.9.5-1.4 1-.6 1.6-1.7 1.6-2.9 0-2.2-1.9-4-4.2-4-.9 0-1.7.3-2.4.8z"/></svg> Apple</a>
  <a href="{SUBSCRIBE['spotify']}"><svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 100 20 10 10 0 000-20zm4.6 14.4c-.2.3-.6.4-.9.2-2.4-1.5-5.5-1.8-9-1-.4.1-.7-.1-.8-.4 0-.4.1-.7.5-.8 3.8-.9 7.2-.5 9.9 1.1.3.2.4.6.2.9zm1.2-3c-.2.4-.7.5-1.1.3-2.8-1.7-6.9-2.2-10.2-1.3-.5.1-.9-.1-1-.5-.1-.5.1-.9.6-1 3.7-1 8.2-.4 11.4 1.5.4.2.5.7.3 1zm.1-3.1c-3.3-2-8.7-2.2-12.5-1.2-.6.1-1.1-.2-1.3-.7-.1-.6.2-1.1.7-1.3 4.3-1.2 10.2-.9 14 1.4.5.3.6 1 .3 1.5-.3.5-1 .6-1.3.3z"/></svg> Spotify</a>
  <a href="{SUBSCRIBE['r2']}"><svg viewBox="0 0 24 24"><path d="M4 4h4v16H4zM10 4h2v16h-2zM16 4h4v16h-4z"/></svg> RSS</a>
  <a href="https://www.youtube.com/@thedailybutler"><svg viewBox="0 0 24 24"><path d="M23 7.5c-.2-1.5-1.1-2.4-2.6-2.6C18.6 4.6 12 4.6 12 4.6s-6.6 0-8.4.3C2.1 5.1 1.2 6 1 7.5.7 9.3.7 12 .7 12s0 2.7.3 4.5c.2 1.5 1.1 2.4 2.6 2.6 1.8.3 8.4.3 8.4.3s6.6 0 8.4-.3c1.5-.2 2.4-1.1 2.6-2.6.3-1.8.3-4.5.3-4.5s0-2.7-.3-4.5zM9.8 15.3V8.7l5.7 3.3-5.7 3.3z"/></svg> YouTube</a>
</div>"""


# ---------------------------------------------------------------- pages
def page_wrap(title, desc, body, url, image=None, schema=None):
    schema_json = None
    if schema:
        schema_json = json.dumps(schema, separators=(",", ":"))
    og = {"schema": schema_json, "type": "website"}
    return f"""<!doctype html>
<html lang="en">
<head>
{meta_tags(title, desc, url, image, og)}
<link rel="stylesheet" href="/css/site.css">
<link rel="preconnect" href="https://www.youtube.com">
</head>
<body>
{header(_active(url))}
<main>
{body}
</main>
{footer()}
<script src="/js/site.js" defer></script>
</body>
</html>
"""


def ep_card(ep, reader_path):
    art = f'<img src="{ep["art_url"]}" alt="{e(ep["saints"][0] if ep["saints"] else "The Daily Butler")}" loading="lazy">' if ep["art_url"] else ""
    date_lbl = datetime.date.fromisoformat(ep["date"]).strftime("%-d %B %Y")
    saint = e(ep["saints"][0]) if ep["saints"] else e(ep["title"])
    q = e(" ".join(ep["saints"] + [ep["title"], ep["date"]]))
    return f"""
<article class="card" data-ep-card data-q="{q}" data-month="{ep['month_num']:02d}">
  <a class="thumb" href="/episode/{ep['date']}/" aria-hidden="true">{art}<span class="date">{date_lbl}</span></a>
  <div class="body">
    <a class="saint" href="/episode/{ep['date']}/">{saint}</a>
    <span class="meta">Episode · {date_lbl}</span>
    <a class="read-link" href="/reader/{ep['mmdd']}/">Read the full text →</a>
  </div>
</article>"""


def render_home(eps, days):
    today = datetime.date.today()
    today_mmdd = f"{today.month:02d}-{today.day:02d}"
    latest = eps[-1] if eps else None
    recent = list(reversed(eps[-6:]))

    # latest "listen now"
    if latest:
        latest_date = datetime.date.fromisoformat(latest["date"]).strftime("%-d %B %Y")
        listen = f"""
<section>
  <div class="container">
    <h2 class="sec">Listen now</h2>
    <div class="listen">
      <img class="art" src="{latest['art_url'] or f'https://{R2_HOST}/cover.jpg'}" alt="">
      <div>
        <h3>{e(latest['saints'][0] if latest['saints'] else latest['title'])}</h3>
        <p class="sub">{latest_date} · the full reading</p>
        <audio controls preload="metadata" src="{latest['mp3_url']}"></audio>
        <div class="mt0" style="margin-top:12px">
          <a class="btn" href="/episode/{latest['date']}/">Watch the episode</a>
          <a class="btn ghost" href="/reader/{latest['mmdd']}/">Read the full text</a>
        </div>
      </div>
    </div>
  </div>
</section>"""
    else:
        listen = ""

    cards = "".join(ep_card(x, f"/reader/{x['mmdd']}/") for x in recent)

    body = f"""
<section class="hero">
  <div class="container">
    <div class="kicker">The lives of the saints · every morning</div>
    <h1><span class="small">THE DAILY</span><span class="chrome">BUTLER</span></h1>
    <p class="tag">A saint a day, read aloud. Each morning, the life appointed to that date in
      Butler's Lives of the Saints (the 1894 edition, public domain) — read in full, with a
      short reflection and a look ahead at tomorrow.</p>
    <div class="actions">
      <a class="btn" href="{SUBSCRIBE['apple']}">Subscribe on Apple</a>
      <a class="btn ghost" href="https://www.youtube.com/@thedailybutler">Watch on YouTube</a>
    </div>
    <div style="margin-top:22px">{subscribe_strip(center=True)}</div>
  </div>
</section>
{listen}
<section>
  <div class="container">
    <h2 class="sec">Recent episodes</h2>
    <div class="grid ep">{cards}</div>
    <p style="margin-top:16px"><a class="btn ghost" href="/archive/">All episodes →</a></p>
  </div>
</section>
<section>
  <div class="container">
    <h2 class="sec">Read the full text</h2>
    <p class="muted" style="max-width:640px">Every episode is drawn from the complete, public-domain text of
      <a href="https://www.sacred-texts.com/chr/butler/butler-toc.htm">Butler's Lives of the Saints</a>.
      Read <a href="/reader/{today_mmdd}/">today's life</a> in full, or browse the whole calendar.</p>
    <p style="margin-top:14px"><a class="btn" href="/reader/{today_mmdd}/">Today's reading →</a></p>
  </div>
</section>
{newsletter_form()}
"""
    schema = {
        "@context": "https://schema.org",
        "@type": "Podcast",
        "name": "The Daily Butler",
        "url": f"https://{SITE}/",
        "description": "A saint a day, read aloud from Butler's Lives of the Saints (1894, public domain).",
        "image": f"https://{R2_HOST}/cover.jpg",
        "episode": [
            {k: v for k, v in {
                "@type": "PodcastEpisode",
                "name": x["title"],
                "url": f"https://{SITE}/episode/{x['date']}/",
                "datePublished": x["pub_date"] or x["date"],
                "audio": {"@type": "MediaObject", "contentUrl": x["mp3_url"]},
                "video": ({"@type": "MediaObject",
                           "contentUrl": f"https://youtu.be/{x['video_id']}"}
                          if x["video_id"] else None),
            }.items() if v is not None}
            for x in eps[-10:]
        ],
    }
    return page_wrap("The Daily Butler — a saint a day, read aloud",
                     "A saint a day, read aloud. Each morning, the life appointed to that date in Butler's Lives of the Saints (1894, public domain), read in full with a short reflection.",
                     body, f"https://{SITE}/", f"https://{R2_HOST}/cover.jpg",
                     schema)


def render_episode(ep, eps, day_lookup):
    dt = datetime.date.fromisoformat(ep["date"])
    date_lbl = dt.strftime("%A, the %-d of %B %Y")
    idx = [i for i, x in enumerate(eps) if x["date"] == ep["date"]]
    i = idx[0] if idx else -1
    prev = eps[i-1] if i > 0 else None
    nxt = eps[i+1] if i < len(eps)-1 else None
    saint = e(ep["saints"][0]) if ep["saints"] else e(ep["title"])
    image = ep["art_url"] or f"https://{R2_HOST}/cover.jpg"

    video = (f'<div class="video"><iframe src="https://www.youtube-nocookie.com/embed/{ep["video_id"]}" '
             f'title="{e(ep["title"])}" allow="accelerated playback; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" '
             f'allowfullscreen loading="lazy"></iframe></div>') if ep["video_id"] else ""
    youtube_cta = (f'<a class="btn ghost" href="https://youtu.be/{ep["video_id"]}" '
                   f'style="margin-left:8px">Watch on YouTube</a>') if ep["video_id"] else ""

    notes = e(ep["description"]) if ep["description"] else ""

    def nav_link(other, side):
        if not other:
            return ('<a href="#" style="visibility:hidden"><span class="lab">'
                    f"{'← Previous' if side == 'prev' else 'Next →'}"
                    '</span><div class="ttl">—</div></a>')
        s = other["saints"][0] if other["saints"] else other["title"]
        lab = "← Previous" if side == "prev" else "Next →"
        align = "text-align:right" if side == "next" else ""
        return (f'<a href="/episode/{other["date"]}/" style="{align}">'
                f'<span class="lab">{lab}</span><div class="ttl">{e(s)}</div></a>')

    body = f"""
<div class="ep-hero">
  <div class="container">
    <div class="crumbs"><a href="/">Home</a> · <a href="/archive/">Episodes</a> · {date_lbl}</div>
    <div class="ep-head">
      <img class="art" src="{image}" alt="{saint}">
      <div>
        <div class="date">{date_lbl}</div>
        <h1 class="chrome">{saint}</h1>
        <p class="lead">Episode · the full reading of the life appointed to this day in Butler's Lives of the Saints.</p>
        <div class="mt0" style="margin-top:16px">{subscribe_strip()}</div>
      </div>
    </div>
  </div>
</div>
<section>
  <div class="container">
    {video}
    <audio controls preload="metadata" style="width:100%;margin:8px 0 24px" src="{ep['mp3_url']}"></audio>
    <div class="notes">{notes}</div>
    <p style="margin-top:22px">
      <a class="btn" href="/reader/{ep['mmdd']}/">Read the full text →</a>
      {youtube_cta}
    </p>
    <div class="nav-ep">
      {nav_link(prev, 'prev')}
      {nav_link(nxt, 'next')}
    </div>
  </div>
</section>
"""
    schema = {
        "@context": "https://schema.org",
        "@type": "PodcastEpisode",
        "name": ep["title"],
        "url": f"https://{SITE}/episode/{ep['date']}/",
        "datePublished": ep["pub_date"] or ep["date"],
        "duration": f"PT{int(ep['duration_s']//60)}M{int(ep['duration_s']%60)}S" if ep["duration_s"] else None,
        "image": image,
        "audio": {"@type": "MediaObject", "contentUrl": ep["mp3_url"], "encodingFormat": "audio/mpeg"},
        "video": {"@type": "MediaObject", "contentUrl": f"https://youtu.be/{ep['video_id']}"} if ep["video_id"] else None,
        "about": {"@type": "Thing", "name": saint},
    }
    schema = {k: v for k, v in schema.items() if v is not None}
    return page_wrap(ep["title"], f"The full reading of {saint} — {date_lbl}.", body,
                     f"https://{SITE}/episode/{ep['date']}/", image, schema)


def render_reader(day, days, eps_by_mmdd):
    idx = days.index(day)
    prev = days[idx-1] if idx > 0 else days[-1]      # wrap: before Jan 1 → Dec 31
    nxt = days[idx+1] if idx < len(days)-1 else days[0]  # wrap: after Dec 31 → Jan 1
    ep = eps_by_mmdd.get(day["mmdd"])
    saints = [x["name"] for x in day["entries"] if x["is_person"]]
    saints_lbl = e(", ".join(saints[:4]) + ("…" if len(saints) > 4 else "")) if saints else e(day["label"])

    def entry_html(en):
        name = e(en["name"])
        paras = ""
        # dropcap only on non-person entries (people begin "St." — a 1-letter
        # dropcap would split the abbreviation awkwardly)
        use_dropcap = not en["is_person"] and en["paras"]
        for pi, p in enumerate(en["paras"]):
            if pi == 0 and use_dropcap and len(p) > 3:
                first = p[:1]
                rest = p[1:]
                paras += f'<p><span class="dropcap">{e(first)}</span>{e(rest)}</p>'
            else:
                paras += f'<p>{e(p)}</p>'
        refl = f'<div class="reflection"><span class="lab">Reflection.</span> {e(en["reflection"])}</div>' if en["reflection"] else ""
        return f'<div class="entry"><span class="saint">{name}</span>{paras}{refl}</div>'

    entries = "".join(entry_html(en) for en in day["entries"])
    ep_name = ep["saints"][0] if (ep and ep["saints"]) else "this episode"
    listen_cta = (f'<a class="btn" href="/episode/{ep["date"]}">▶ Listen to {e(ep_name)}</a>'
                  if ep else "")

    body = f"""
<div class="reader-wrap">
  <div class="container">
    <div class="reader-head">
      <div class="kicker">Butler's Lives of the Saints · 1894</div>
      <h1 class="chrome">{e(day['label'])}</h1>
      <div class="saints">{saints_lbl}</div>
    </div>
    <div class="pane">{entries}</div>
    <p class="center" style="margin-top:16px;color:var(--dim);font-size:13px">Text: {e(day['label'])} — Alban Butler, <i>The Lives of the Saints</i> (Benziger 1894, public domain).</p>
    <div class="reader-nav">
      <a href="/reader/{prev['mmdd']}/"><span class="lab">← Previous day</span><div class="ttl">{e(prev['label'])}</div></a>
      <a href="/reader/{nxt['mmdd']}/" style="text-align:right"><span class="lab">Next day →</span><div class="ttl">{e(nxt['label'])}</div></a>
    </div>
    {listen_cta and f'<div class="center"><a class="listen-cta btn" href="/episode/{ep["date"]}/">▶ Listen to this episode</a></div>'}
  </div>
</div>
"""
    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": f"{day['label']} — The Lives of the Saints",
        "datePublished": f"{datetime.date.today().year}-{'%02d' % day['month_num']}-{'%02d' % day['day']}",
        "author": {"@type": "Person", "name": "Alban Butler"},
        "about": {"@type": "Thing", "name": ", ".join(saints)},
        "description": f"The life(s) appointed to {day['label']} in Butler's Lives of the Saints (1894).",
    }
    return page_wrap(f"{day['label']} · The Daily Butler",
                     f"The full text appointed to {day['label']} in Butler's Lives of the Saints (1894, public domain).",
                     body, f"https://{SITE}/reader/{day['mmdd']}/",
                     f"https://{R2_HOST}/cover.jpg", schema)


def render_archive(eps):
    months = []
    for m in range(1, 13):
        if any(x["month_num"] == m for x in eps):
            months.append(f'<option value="{m:02d}">{MONTHS[m-1]}</option>')
    cards = "".join(ep_card(x, f"/reader/{x['mmdd']}/") for x in reversed(eps))
    total = len(eps)
    body = f"""
<section style="padding-top:40px">
  <div class="container">
    <h1 class="chrome" style="font-size:clamp(32px,6vw,56px)">Episodes</h1>
    <p class="muted">Every episode, most recent first. Search by saint or date, or filter by month.</p>
    <div class="search">
      <input data-archive-search type="search" placeholder="Search saints (e.g. giles, stephen)…" aria-label="Search episodes">
      <select data-archive-month aria-label="Filter by month">
        <option value="">All months</option>
        {''.join(months)}
      </select>
    </div>
    <div class="count" data-archive-count>{total} episodes</div>
    <div class="grid ep">{cards}</div>
  </div>
</section>
"""
    return page_wrap("Episodes · The Daily Butler",
                     f"All episodes of The Daily Butler — {total} and counting. Search by saint or date.",
                     body, f"https://{SITE}/archive/", f"https://{R2_HOST}/cover.jpg")


def render_about():
    body = f"""
<section style="padding-top:44px">
  <div class="container prose">
    <h1 class="chrome">About The Daily Butler</h1>
    <p><strong>The Daily Butler</strong> is a daily reading of the lives of the saints — one a day,
       every morning. Each episode reads, in full, the life appointed to that date in
       <em>Butler's Lives of the Saints</em>, followed by a short reflection and a look ahead
       at tomorrow.</p>
    <h2>The source text</h2>
    <p>The readings are drawn from the complete, proofread text of Alban Butler's
       <em>The Lives of the Saints</em> — the Benziger Brothers edition of 1894, which is in the
       public domain. Butler (1711–1773) was an English Benedictine who spent most of his life in
       the East Indies; his work remains one of the great English-language books of the saints.</p>
    <p>Butler's calendar is the traditional one (pre-1969), so the days follow the old liturgical
       assignments — the same calendar most of the world kept for centuries. The full text for every
       day is free to read on this site, <a href="/reader/01-01/">a day at a time</a>.</p>
    <h2>How it's made</h2>
    <p>Every episode is a video and a podcast: a short intro, the full reading over the day's
       artwork, a music bed, and a sign-off. New episodes are published each morning. The show has
       no ads, no commentary, and no sponsors — just the reading.</p>
    <h2>Listen &amp; follow</h2>
    <p>The podcast is available on <a href="{SUBSCRIBE['apple']}">Apple Podcasts</a>,
       <a href="{SUBSCRIBE['spotify']}">Spotify</a>, and <a href="{SUBSCRIBE['r2']}">the open RSS feed</a>.
       Video is on <a href="https://www.youtube.com/@thedailybutler">YouTube</a>.</p>
    <h2>Get each morning's life by email</h2>
    <p><a class="btn" href="/subscribe/">Subscribe to the newsletter</a></p>
    <h2>Contact</h2>
    <p><a href="mailto:aaron.mchugh@gmail.com">aaron.mchugh@gmail.com</a></p>
  </div>
</section>
"""
    return page_wrap("About · The Daily Butler",
                     "What The Daily Butler is, where the source text comes from, and how each episode is made.",
                     body, f"https://{SITE}/about/", f"https://{R2_HOST}/cover.jpg")


def render_subscribe(eps):
    latest = eps[-1] if eps else None
    body = f"""
<section style="padding-top:44px">
  <div class="container">
    <div class="reader-head">
      <div class="kicker">Newsletter</div>
      <h1 class="chrome" style="font-size:clamp(30px,6vw,52px)">Each morning's life, in your inbox</h1>
      <p class="muted" style="max-width:560px;margin:10px auto 0">A short note with the day's saint and a link to the full
        reading. No ads, no spam — just the reading, every morning.</p>
    </div>
    <div class="news" style="max-width:640px;margin:24px auto">
      <div>
        <h3>Subscribe</h3>
        <p>Delivered by <a href="https://resend.com">Resend</a>. Unsubscribe any time.</p>
      </div>
      <form data-newsletter>
        <input type="email" placeholder="you@example.com" required aria-label="Email address">
        <button class="btn" type="submit">Subscribe</button>
        <span data-status aria-live="polite"></span>
      </form>
    </div>
    <div class="center" style="margin-top:24px">
      <p class="muted">Prefer a podcast app?</p>
      <div style="margin-top:10px">{subscribe_strip(center=True)}</div>
    </div>
  </div>
</section>
"""
    return page_wrap("Subscribe · The Daily Butler",
                     "Get each morning's saint and a link to the full reading by email.",
                     body, f"https://{SITE}/subscribe/", f"https://{R2_HOST}/cover.jpg")


def render_404():
    body = f"""
<section style="padding-top:80px;text-align:center">
  <div class="container">
    <h1 class="chrome" style="font-size:clamp(48px,10vw,96px)">404</h1>
    <p class="muted">That page has wandered off into the desert.</p>
    <p style="margin-top:18px"><a class="btn" href="/">Back to The Daily Butler</a></p>
  </div>
</section>
"""
    return page_wrap("Not found · The Daily Butler", "Page not found.", body, f"https://{SITE}/404")


# ---------------------------------------------------------------- sitemap / robots
def render_sitemap(eps, days):
    urls = [f"https://{SITE}/", f"https://{SITE}/archive/",
            f"https://{SITE}/about/", f"https://{SITE}/subscribe/"]
    for x in eps:
        urls.append(f"https://{SITE}/episode/{x['date']}/")
    for d in days:
        urls.append(f"https://{SITE}/reader/{d['mmdd']}/")
    body = "\n".join(f"  <url><loc>{u}</loc></url>" for u in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}\n</urlset>\n'


def render_robots():
    return f"""User-agent: *
Allow: /

Sitemap: https://{SITE}/sitemap.xml
"""


# ---------------------------------------------------------------- R2 art upload
def upload_art_to_r2(eps):
    creds = dict(os.environ)
    for env_file in (
        os.path.expanduser("~/.config/the-daily-butler/runtime.env"),
        os.path.join(DAILY_BUTLER, ".env"),
    ):
        if not os.path.exists(env_file):
            continue
        with open(env_file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    creds.setdefault(key.strip(), value.strip().strip('"').strip("'"))

    required = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
    use_s3 = all(creds.get(key) for key in required)
    bucket = creds.get("R2_BUCKET", "thedailybutler")
    s3 = None
    if use_s3:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 is required for environment-based R2 uploads") from exc
        acct = creds["R2_ACCOUNT_ID"]
        s3 = boto3.client("s3", endpoint_url=f"https://{acct}.r2.cloudflarestorage.com",
                          aws_access_key_id=creds["R2_ACCESS_KEY_ID"],
                          aws_secret_access_key=creds["R2_SECRET_ACCESS_KEY"],
                          region_name="auto")
    else:
        try:
            auth = subprocess.run(
                ["npx", "--yes", "wrangler", "whoami"],
                check=True, capture_output=True, text=True,
            )
            if "not authenticated" in (auth.stdout + auth.stderr).lower():
                raise RuntimeError("Wrangler is not authenticated")
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            missing = [key for key in required if not creds.get(key)]
            raise RuntimeError(
                "R2 upload needs either `npx wrangler login` or these environment "
                f"variables: {', '.join(missing)}"
            ) from exc
        except RuntimeError as exc:
            missing = [key for key in required if not creds.get(key)]
            raise RuntimeError(
                "R2 upload needs either `npx wrangler login` or these environment "
                f"variables: {', '.join(missing)}"
            ) from exc

    for ep in eps:
        if not ep["art_local"]:
            continue
        key = f"art/{ep['date']}.jpg"
        size = os.path.getsize(ep["art_local"])
        ext = os.path.splitext(ep["art_local"])[1].lower()
        content_type = "image/png" if ext == ".png" else "image/jpeg"
        if s3:
            try:
                if s3.head_object(Bucket=bucket, Key=key)["ContentLength"] == size:
                    print(f"  = {key} (already uploaded)")
                    continue
            except Exception:
                pass
            s3.upload_file(ep["art_local"], bucket, key, ExtraArgs={
                "ContentType": content_type,
                "CacheControl": "public, max-age=604800, immutable",
            })
        else:
            subprocess.run([
                "npx", "--yes", "wrangler", "r2", "object", "put",
                f"{bucket}/{key}", "--file", ep["art_local"],
                "--content-type", content_type,
                "--cache-control", "public, max-age=604800, immutable",
                "--remote", "--force",
            ], check=True)
        print(f"  + art/{ep['date']}.jpg")


# ---------------------------------------------------------------- main
def main():
    print("Parsing corpus…")
    days = parse_corpus()
    print(f"  {len(days)} day-sections")

    print("Loading episodes…")
    eps = load_episodes()
    print(f"  {len(eps)} episodes: {[x['date'] for x in eps]}")

    eps_by_mmdd = {x["mmdd"]: x for x in eps}
    day_lookup = {d["mmdd"]: d for d in days}

    os.makedirs(os.path.join(ROOT, "css"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "js"), exist_ok=True)

    # copy css/js sources
    for sub in ("css", "js"):
        srcdir = os.path.join(ROOT, "build", sub)
        for f in os.listdir(srcdir):
            with open(os.path.join(srcdir, f)) as fh:
                open(os.path.join(ROOT, sub, f), "w").write(fh.read())

    def write(rel, content):
        path = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(content)
        return path

    write("index.html", render_home(eps, days))
    write("404.html", render_404())
    write("archive/index.html", render_archive(eps))
    write("about/index.html", render_about())
    write("subscribe/index.html", render_subscribe(eps))
    write("sitemap.xml", render_sitemap(eps, days))
    write("robots.txt", render_robots())

    for ep in eps:
        write(f"episode/{ep['date']}/index.html", render_episode(ep, eps, day_lookup))

    for d in days:
        write(f"reader/{d['mmdd']}/index.html", render_reader(d, days, eps_by_mmdd))

    print(f"Generated: 1 home, 1 archive, 1 about, 1 subscribe, {len(eps)} episodes, {len(days)} reader pages")

    if UPLOAD_ART:
        print("Uploading hero art to R2…")
        upload_art_to_r2(eps)

    print("Done.")


if __name__ == "__main__":
    main()
