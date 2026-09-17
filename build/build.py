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
    with open(CORPUS, encoding="utf-8") as corpus_file:
        src = corpus_file.read()
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
    if isinstance(item, dict) and receipt.get("verified_at") and receipt.get("audio_url"):
        return item, receipt
    historical = read_json(os.path.join(episode_dir, "06-publish", "podcast.json"))
    metadata = read_json(os.path.join(episode_dir, "episode.json"), {})
    if isinstance(historical, dict) and metadata.get("status") == "historical_published":
        return historical, {}
    return None, {}


def load_episodes():
    eps = []
    ep_root = os.path.join(DAILY_BUTLER, "episodes")
    if not os.path.isdir(ep_root):
        raise RuntimeError(f"Production episode directory is missing: {ep_root}")
    for d in sorted(os.listdir(ep_root)):
        if not re.match(r"^\d{4}-\d{2}-\d{2}(?:--.+)?$", d):
            continue
        episode_dir = os.path.join(ep_root, d)
        if not os.path.isdir(episode_dir):
            continue
        metadata = read_json(os.path.join(episode_dir, "episode.json"), {})
        item, receipt = _published_item(episode_dir)
        if not item or metadata.get("hold") is not False or item.get("hold") is True:
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
            "source_dir": episode_dir,
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




# ---------------------------------------------------------------- sitemap / robots
def render_sitemap(eps, days):
    urls = [f"https://{SITE}/", f"https://{SITE}/archive/", f"https://{SITE}/reader/",
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
def prune_episode_outputs(root, live_dates):
    """Remove only generated pages/art belonging to withdrawn episode dates."""
    from pathlib import Path
    root = Path(root)
    for page in (root / 'episode').glob('*/index.html'):
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', page.parent.name) and page.parent.name not in live_dates:
            page.unlink()
    for asset in (root / 'assets').glob('*.webp'):
        match = re.fullmatch(r'(?:episode|art)-(\d{4}-\d{2}-\d{2})(?:-small)?\.webp', asset.name)
        if match and match[1] not in live_dates:
            asset.unlink()


def main():
    from assets import prepare_assets
    from presentation import Site
    print("Parsing corpus…")
    days = parse_corpus()
    if len(days) != 366:
        raise RuntimeError("Refusing to build without the complete 366-day corpus")
    print(f"  {len(days)} day-sections")

    print("Loading episodes…")
    eps = load_episodes()
    print(f"  {len(eps)} episodes: {[x['date'] for x in eps]}")

    prepare_assets(ROOT, DAILY_BUTLER, eps)
    site = Site(eps, days, SITE, YOUTUBE, SUBSCRIBE)

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

    write("index.html", site.home())
    write("404.html", site.not_found())
    write("archive/index.html", site.archive())
    write("about/index.html", site.about())
    write("subscribe/index.html", site.subscribe())
    write("reader/index.html", site.calendar())
    write("sitemap.xml", render_sitemap(eps, days))
    write("robots.txt", render_robots())

    for ep in eps:
        write(f"episode/{ep['date']}/index.html", site.episode(ep))

    for d in days:
        write(f"reader/{d['mmdd']}/index.html", site.reader(d))

    # Remove only generated episode pages/art for withdrawn or newly held episodes.
    # Never recursively delete directories or touch production media.
    from pathlib import Path
    live_dates = {ep['date'] for ep in eps}
    prune_episode_outputs(ROOT, live_dates)

    # A deterministic public marker allows sync to verify the exact generated release.
    public_files = [Path(ROOT) / name for name in ('index.html', '404.html', 'sitemap.xml', 'robots.txt')]
    for folder in ('about', 'archive', 'subscribe', 'episode', 'reader', 'assets', 'css', 'js'):
        public_files.extend(p for p in (Path(ROOT) / folder).rglob('*') if p.is_file())
    digest = hashlib.sha256()
    for path in sorted(public_files):
        digest.update(path.relative_to(ROOT).as_posix().encode() + b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    write('site-version.json', json.dumps({'schema_version': 1, 'content_sha256': digest.hexdigest(),
          'episode_dates': sorted(live_dates)}, indent=2) + '\n')

    print(f"Generated: 1 home, 1 archive, 1 about, 1 subscribe, {len(eps)} episodes, {len(days)} reader pages")

    if UPLOAD_ART:
        print("Uploading hero art to R2…")
        upload_art_to_r2(eps)

    print("Done.")


if __name__ == "__main__":
    main()
