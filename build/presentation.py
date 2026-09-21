"""Editorial templates for the Daily Butler website. No network requests at render time."""
import datetime as dt
import html
import json
import math
import re


def esc(value):
    return html.escape(str(value), quote=True)


def title_case(value):
    # The corpus uses capitals for names. Preserve the full identity and all feast names.
    value = re.sub(r"\bST\.?\s+", "Saint ", value, flags=re.I)
    words = value.split()
    return " ".join((w.lower() if i and w.lower() in {"of", "the", "and", "in", "on", "within"} else w.title()) if w.isupper() else w for i, w in enumerate(words))


def name(ep):
    return title_case(" & ".join(ep["saints"]) or ep["title"])


def date_label(value):
    return dt.date.fromisoformat(value).strftime("%-d %B %Y")


def duration(ep):
    seconds = round(ep.get("duration_s") or 0)
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds else "Full reading"


ICONS = {
    "play": '<path d="m9 5 11 7-11 7z"/>',
    "arrow": '<path d="M4 12h15m-6-6 6 6-6 6"/>',
    "book": '<path d="M12 5v15M12 5C9 3 5 3 2 4v15c3-1 7-1 10 1 3-2 7-2 10-1V4c-3-1-7-1-10 1Z"/>',
    "headphones": '<path d="M4 14v-3a8 8 0 0 1 16 0v3M4 13h3v8H4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2Zm16 0h-3v8h3a2 2 0 0 0 2-2v-4a2 2 0 0 0-2-2Z"/>',
    "youtube": '<rect x="2" y="5" width="20" height="14" rx="4"/><path d="m10 9 5 3-5 3z"/>',
    "spotify": '<circle cx="12" cy="12" r="10"/><path d="M6 9c4-2 9-1 12 1M7 12c3-1 7-1 10 1M8 15c3-1 5 0 7 1"/>',
    "rss": '<circle cx="5" cy="19" r="1"/><path d="M4 11a9 9 0 0 1 9 9M4 4a16 16 0 0 1 16 16"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
}


def icon(key):
    return f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[key]}</svg>'


class Site:
    def __init__(self, episodes, days, host, youtube, subscriptions):
        self.episodes, self.days = episodes, days
        self.host, self.youtube, self.subscriptions = host, youtube, subscriptions
        self.day_map = {day["mmdd"]: day for day in days}
        self.ep_map = {ep["mmdd"]: ep for ep in episodes}
        self.today = dt.date.today().strftime("%m-%d")

    def platform_links(self):
        return f'''<div class="platforms">
          <a href="{esc(self.youtube)}">{icon('youtube')}YouTube</a>
          <a href="{esc(self.subscriptions['apple'])}">{icon('headphones')}Apple Podcasts</a>
          <a href="{esc(self.subscriptions['spotify'])}">{icon('spotify')}Spotify</a>
          <a href="{esc(self.subscriptions['r2'])}">{icon('rss')}RSS feed</a>
        </div>'''

    def wrap(self, title, description, body, path="/", active="", image="/assets/channel-banner.webp", schema=None):
        nav = "".join(f'<a href="{url}"'+(' aria-current="page"' if active == key else '')+f'>{label}</a>'
                      for url, label, key in [("/", "Home", "home"), ("/archive/", "Episodes", "episodes"),
                                              ("/reader/", "The reader", "reader"), ("/about/", "Our story", "about")])
        image = f"https://{self.host}{image}" if image.startswith("/") else image
        schema_html = '<script type="application/ld+json">'+json.dumps(schema).replace("<", "\\u003c")+'</script>' if schema else ''
        return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · The Daily Butler</title><meta name="description" content="{esc(description)}">
<link rel="canonical" href="https://{self.host}{path}"><meta name="theme-color" content="#14131e">
<meta property="og:title" content="{esc(title)} · The Daily Butler"><meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="https://{self.host}{path}"><meta property="og:type" content="website"><meta property="og:image" content="{esc(image)}">
<meta property="og:site_name" content="The Daily Butler"><meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.png"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="preload" href="/assets/fonts/cormorant-regular.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/css/site.css?v=heritage-1">{schema_html}
<noscript><style>@media(max-width:850px){{.menu-toggle{{display:none}}.masthead{{height:auto;flex-wrap:wrap;padding-block:15px}}.nav-links{{display:flex;position:static;flex-wrap:wrap;padding:0;gap:18px;border:0}}}}</style></noscript></head>
<body class="page-{active or 'general'}"><a class="skip" href="#main">Skip to content</a>
<header class="site-header"><div class="container masthead">
  <a class="brand" href="/" aria-label="The Daily Butler home"><img src="/assets/channel-logo.webp" alt="" width="70" height="70"><span>The Daily Butler<small>THE LIVES OF THE SAINTS</small></span></a>
  <button class="menu-toggle" type="button" aria-controls="primary-nav" aria-expanded="false" data-nav-toggle>Menu <span aria-hidden="true">☰</span></button>
  <nav id="primary-nav" class="nav-links" aria-label="Main navigation">{nav}<a href="/subscribe/" class="nav-follow">Follow the readings {icon('arrow')}</a></nav>
</div></header>
<main id="main">{body}</main>
<footer class="site-footer"><div class="container"><div class="footer-top">
  <a class="brand" href="/"><img src="/assets/channel-logo-purple.webp" alt="" width="70" height="70" loading="lazy"><span>The Daily Butler<small>A SAINT A DAY, READ ALOUD.</small></span></a>
  <div class="footer-links"><a href="/archive/">Episodes</a><a href="/reader/">The reader</a><a href="/about/">Our story</a><a href="/subscribe/">Listen &amp; follow</a></div>
</div><div class="footer-bottom"><p>Butler’s <i>Lives of the Saints</i> · Benziger Brothers, 1894 · Public-domain text</p><p>© {dt.date.today().year} The Daily Butler. Narration &amp; production.</p></div></div></footer>
<script src="/js/site.js?v=heritage-1" defer></script>
<script>window.va=window.va||function(){{(window.vaq=window.vaq||[]).push(arguments)}}</script>
<script src="/_vercel/insights/script.js" defer></script></body></html>'''

    def player(self, ep):
        return f'''<div class="audio-player" data-player>
          <audio controls preload="none" src="{esc(ep['mp3_url'])}" aria-label="Listen to {esc(name(ep))}"></audio>
          <div class="player-controls" hidden>
            <button class="play-button" data-play type="button" aria-label="Play reading">{icon('play')}</button>
            <div class="player-track"><div class="player-label"><span data-player-label>Listen to the full reading</span><span class="player-time"><span data-time>0:00</span> / <span data-duration>{duration(ep)}</span></span></div>
            <input data-seek type="range" min="0" max="100" step="0.1" value="0" aria-label="Seek through reading" aria-valuetext="0:00"></div>
            <button class="speed-button" data-speed type="button" aria-label="Playback speed: 1 times">1×</button>
          </div><p class="player-error" data-player-error role="status" hidden>Audio could not load. <a href="{esc(ep['mp3_url'])}">Open the audio file</a>.</p>
        </div>'''

    def thumb(self, ep, eager=False):
        src = ep['thumbnail']
        srcset = f' srcset="/assets/episode-{ep["date"]}-small.webp 480w, {src} 960w" sizes="(max-width: 640px) 100vw, (max-width: 1000px) 50vw, 33vw"' if src.startswith('/assets/episode-') else ''
        return f'<img src="{esc(src)}"{srcset} alt="{esc(name(ep))} — episode artwork" width="960" height="540" loading="{"eager" if eager else "lazy"}">'

    def card(self, ep):
        return f'''<article class="episode-card" data-ep-card data-q="{esc(name(ep)+' '+ep['date']+' '+date_label(ep['date']))}" data-month="{ep['month_num']:02d}">
          <a class="card-image" href="/episode/{ep['date']}/" tabindex="-1" aria-hidden="true">{self.thumb(ep)}<span class="duration">{duration(ep)}</span></a>
          <div class="card-meta"><time datetime="{ep['date']}">{date_label(ep['date'])}</time><span>Full reading</span></div>
          <h3><a href="/episode/{ep['date']}/">{esc(name(ep))}</a></h3>
          <a class="text-link card-listen" href="/episode/{ep['date']}/">Listen &amp; watch {icon('arrow')}</a>
        </article>'''

    def follow(self):
        return f'''<section class="follow-section"><div class="container follow-inner"><div><p class="eyebrow">MAKE TIME FOR THE READING</p><h2>A daily companion.</h2><p>At home, on a walk, or on the way to work.<br>Follow The Daily Butler wherever you listen.</p></div><div>{self.platform_links()}<a class="quiet-link" href="/subscribe/">All ways to follow {icon('arrow')}</a></div></div></section>'''

    def home(self):
        latest = self.episodes[-1] if self.episodes else None
        feature = ''
        if latest:
            day = self.day_map.get(latest['mmdd'])
            opening = day['entries'][0]['paras'][0] if day else ''
            opening = opening[:225].rsplit(' ', 1)[0] + '…' if len(opening) > 225 else opening
            feature = f'''<section class="section latest-section"><div class="container">
              <div class="section-heading"><p class="eyebrow">THE LATEST READING</p><time datetime="{latest['date']}">{date_label(latest['date'])}</time></div>
              <div class="featured-episode"><a class="featured-image" href="/episode/{latest['date']}/">{self.thumb(latest, True)}<span class="image-action">{icon('play')} Watch the episode <span>{duration(latest)}</span></span></a>
              <div class="featured-copy"><h2><a href="/episode/{latest['date']}/">{esc(name(latest))}</a></h2><p class="excerpt">{esc(opening)}</p>
              {self.player(latest)}<a class="text-link" href="/reader/{latest['mmdd']}/">Read the original text {icon('arrow')}</a></div></div></div></section>'''
        cards = ''.join(self.card(ep) for ep in reversed(self.episodes[-7:-1]))
        body = f'''<div class="channel-banner"><img src="/assets/channel-banner.webp" alt="The Daily Butler — Butler’s Lives of the Saints. Complete traditional readings, daily. Saints Stephen, Rosalia, Nicholas of Tolentino and Cloud surround the channel’s library banner." width="1920" height="1080" fetchpriority="high"></div>
          <section class="introduction"><div class="container intro-grid"><div><p class="eyebrow">THE DAILY BUTLER</p><h1>The lives of the saints,<br><em>read in full.</em></h1></div>
          <div class="intro-copy"><p>One day at a time, through Butler’s <i>Lives of the Saints</i>. Complete traditional readings and reflections, brought to life through narration and sacred art.</p><div class="actions"><a class="button" href="{'/episode/'+latest['date']+'/' if latest else '/archive/'}">{icon('headphones')} Listen to the latest</a><a class="text-link" data-today href="/reader/{self.today}/">Today’s text {icon('arrow')}</a></div></div></div></section>
          <div class="platform-strip"><div class="container"><span class="eyebrow">WATCH. LISTEN. RETURN DAILY.</span>{self.platform_links()}</div></div>
          {feature}
          <section class="section recent-section"><div class="container"><div class="section-heading"><div><p class="eyebrow">FROM THE ARCHIVE</p><h2>More lives to discover</h2></div><a class="text-link" href="/archive/">All episodes {icon('arrow')}</a></div><div class="episode-grid">{cards}</div></div></section>
          <section class="library-section"><div class="container library-grid"><div class="library-title"><span class="edition-number">1894</span><p class="eyebrow">THE BENZIGER EDITION</p><h2>A place for<br><em>quiet reading.</em></h2></div><div class="library-copy"><p class="lead">The complete text. Every day of the year.</p><p>Read the lives and reflections at your own pace. Our online reader follows the calendar of the 1894 edition, with a page for every date.</p><div class="actions"><a class="button button-gold" href="/reader/">{icon('book')} Open the reader</a><a class="text-link" data-today href="/reader/{self.today}/">Read today’s life {icon('arrow')}</a></div><p class="fine-print">Freely available · No account needed</p></div></div></section>
          {self.follow()}'''
        return self.wrap('The lives of the saints, read in full', 'Daily readings from Butler’s Lives of the Saints. Watch, listen, and explore the complete 1894 text.', body, active='home', schema={"@context":"https://schema.org", "@type":"PodcastSeries", "name":"The Daily Butler", "url":f"https://{self.host}/", "webFeed":self.subscriptions['r2']})

    def archive(self):
        months = sorted({ep['month_num'] for ep in self.episodes})
        options = ''.join(f'<option value="{m:02d}">{dt.date(2024,m,1):%B}</option>' for m in months)
        body = f'''<section class="page-heading container"><p class="eyebrow">THE EPISODE COLLECTION</p><h1>A life for every day.</h1><p>Explore the saints, their stories, and the reflections they leave us.<br>Watch or listen to each reading in full.</p></section>
          <section class="container archive-content"><div class="archive-toolbar"><label class="search-box">{icon('search')}<input type="search" data-archive-search placeholder="Search by saint or date" aria-label="Search episodes"></label><label class="month-filter"><span>Browse</span><select data-archive-month aria-label="Filter episodes by month"><option value="">All months</option>{options}</select></label></div>
          <div class="collection-meta"><span data-archive-count role="status">{len(self.episodes)} episodes</span><span>NEWEST FIRST</span></div><div class="episode-grid">{''.join(self.card(ep) for ep in reversed(self.episodes))}</div>
          <div class="empty-state" data-empty hidden><h2>No readings found.</h2><p>Try another saint’s name or clear your filters.</p><button class="button" data-reset>Clear filters</button></div></section>{self.follow()}'''
        return self.wrap('Episodes', 'Browse the Daily Butler episode archive by saint or date.', body, '/archive/', 'episodes')

    def episode(self, ep):
        idx = self.episodes.index(ep)
        day = self.day_map.get(ep['mmdd'])
        reflection = next((entry['reflection'] for entry in day['entries'] if entry['reflection']), None) if day else None
        video = ''
        if ep['video_id']:
            video = f'''<div class="video-player" data-video="{esc(ep['video_id'])}" data-title="{esc(name(ep))}"><a class="video-launch" href="https://www.youtube.com/watch?v={esc(ep['video_id'])}">{self.thumb(ep, True)}<span class="video-play">{icon('play')}<span>Watch the reading</span></span></a></div>'''
        else:
            video = f'<div class="video-player">{self.thumb(ep, True)}</div>'
        notes = ''.join(f'<p>{esc(p)}</p>' for p in ep['description'].split('\n\n') if p.strip())
        refl = f'<aside class="episode-reflection"><p class="eyebrow">FROM TODAY’S REFLECTION</p><blockquote>{esc(reflection)}</blockquote><a class="text-link" href="/reader/{ep["mmdd"]}/">Read the full text {icon("arrow")}</a></aside>' if reflection else ''
        related = [x for x in self.episodes[max(0,idx-3):idx]]
        body = f'''<section class="container episode-heading"><a class="back-link" href="/archive/">← All episodes</a><p class="eyebrow"><time datetime="{ep['date']}">{date_label(ep['date'])}</time> <span>·</span> {duration(ep)} MIN</p><h1>{esc(name(ep))}</h1><p>A complete reading from Butler’s <i>Lives of the Saints</i>.</p></section>
          <section class="container episode-layout"><div>{video}{self.player(ep)}<div class="episode-actions"><a class="text-link" href="/reader/{ep['mmdd']}/">{icon('book')} Read this day’s text</a><a class="quiet-link" href="{esc(ep['mp3_url'])}">Open audio file ↗</a></div>
          <details class="episode-notes"><summary>Episode notes &amp; credits</summary><div>{notes}<p>Episode artwork and thumbnail: The Daily Butler. Original artwork provenance is retained with the channel’s production archive.</p></div></details></div>{refl}</section>
{('<section class="section container"><div class="section-heading"><h2>Earlier readings</h2><a class="text-link" href="/archive/">The full archive '+icon('arrow')+'</a></div><div class="episode-grid">'+''.join(self.card(x) for x in reversed(related))+'</div></section>') if related else ''}
          {self.follow()}'''
        schema = {"@context":"https://schema.org", "@type":"PodcastEpisode", "name":name(ep), "datePublished":ep['date'], "url":f"https://{self.host}/episode/{ep['date']}/", "audio":{"@type":"AudioObject","contentUrl":ep['mp3_url']}}
        return self.wrap(name(ep), f"Listen to the full reading for {date_label(ep['date'])}.", body, f"/episode/{ep['date']}/", 'episodes', ep['thumbnail'], schema)

    def calendar(self):
        months, sections = [], []
        for number in range(1,13):
            label = dt.date(2024,number,1).strftime('%B')
            months.append(f'<a href="#month-{number}">{label}</a>')
            links = ''.join(f'<a class="calendar-day" href="/reader/{d["mmdd"]}/"><span class="day-number">{d["day"]:02d}</span><span>{esc("; ".join(title_case(x["name"]) for x in d["entries"]))}</span>{icon("arrow")}</a>' for d in self.days if d['month_num']==number)
            sections.append(f'<section class="calendar-month" id="month-{number}"><div class="month-heading"><span>{number:02d}</span><h2>{label}</h2><a class="quiet-link" href="#months">Back to months ↑</a></div><div class="calendar-list">{links}</div></section>')
        body = f'''<section class="page-heading container"><p class="eyebrow">BUTLER’S LIVES OF THE SAINTS · 1894</p><h1>The reading room.</h1><p>Lives of faith, arranged by day.<br>Open today’s reading, or find a date in the calendar.</p><a class="button" data-today href="/reader/{self.today}/">{icon('book')} Read today’s life</a></section>
          <div class="container calendar-layout"><nav class="month-index" id="months" aria-label="Reading months"><p class="eyebrow">THE CALENDAR</p>{''.join(months)}<p class="fine-print">Dates follow the traditional calendar of the source edition.</p></nav><div>{''.join(sections)}</div></div>'''
        return self.wrap('The reading room', 'The complete 1894 Butler calendar. Read every saint’s life and reflection, freely, by date.', body, '/reader/', 'reader')

    def reader(self, day):
        idx = self.days.index(day)
        previous, following = self.days[idx-1], self.days[(idx+1)%len(self.days)]
        ep = self.ep_map.get(day['mmdd'])
        entries = []
        for entry in day['entries']:
            paragraphs = ''.join(f'<p>{esc(p)}</p>' for p in entry['paras'])
            reflection = f'<aside class="reading-reflection"><h3>Reflection</h3><p>{esc(entry["reflection"])}</p></aside>' if entry['reflection'] else ''
            entries.append(f'<section class="reading-entry"><h2>{esc(title_case(entry["name"]))}</h2>{paragraphs}{reflection}</section>')
        minutes = max(1, math.ceil(sum(len(' '.join(x['paras']).split()) for x in day['entries'])/200))
        listen = f'<a href="/episode/{ep["date"]}/" class="text-link">{icon("headphones")} Listen to this reading</a>' if ep else '<span>THE COMPLETE ORIGINAL TEXT</span>'
        body = f'''<div class="reader-toolbar container"><a class="back-link" href="/reader/">← The reading room</a><div class="reader-tools"><span>Text size</span><button data-font="smaller" aria-label="Smaller text">A−</button><button data-font="larger" aria-label="Larger text">A+</button></div></div>
          <article class="reading"><header class="reading-heading"><p class="eyebrow">BUTLER’S LIVES OF THE SAINTS</p><h1>{esc(day['label'])}</h1><p>Benziger Brothers, 1894 <span>·</span> {minutes} min read</p></header>
          <div class="reading-listen">{listen}</div><div class="reading-body">{''.join(entries)}</div>
          <p class="source-note">From <i>Lives of the Saints</i>, Benziger Brothers, 1894. Public-domain text. Dates follow this edition’s traditional calendar.</p>
          <nav class="reading-nav" aria-label="Daily readings"><a href="/reader/{previous['mmdd']}/"><span>← PREVIOUS DAY</span><strong>{esc(previous['label'])}</strong></a><a href="/reader/{following['mmdd']}/"><span>NEXT DAY →</span><strong>{esc(following['label'])}</strong></a></nav></article>'''
        return self.wrap(f"{day['label']} — {title_case(day['entries'][0]['name'])}", f"The complete lives and reflection for {day['label']} in Butler’s Lives of the Saints.", body, f"/reader/{day['mmdd']}/", 'reader')

    def about(self):
        body = f'''<section class="page-heading container"><p class="eyebrow">OUR STORY</p><h1>An old tradition.<br><em>A daily reading.</em></h1><p>The Daily Butler brings the lives of the saints<br>into the ordinary rhythm of the day.</p></section>
          <div class="container about-banner"><img src="/assets/channel-banner.webp" alt="The Daily Butler’s illustrated library banner" width="1920" height="1080"></div>
          <div class="container about-layout"><aside><p class="eyebrow">THE DAILY BUTLER</p><p>Complete readings.<br>Sacred art.<br>Time for reflection.</p><a class="text-link" href="/subscribe/">Follow along {icon('arrow')}</a></aside><div class="prose"><h2>A saint a day, read aloud.</h2><p>Each episode follows the day’s entry in the Benziger Brothers’ 1894 edition of Butler’s <i>Lives of the Saints</i>. The reading includes the lives and the reflection appointed to that date.</p><p>You can watch the reading with sacred artwork, listen as a podcast, or open the original text here on the website.</p><h2>The book behind the readings.</h2><p>Alban Butler was an English Catholic priest whose work gathered the lives of the saints for generations of readers. The Daily Butler uses the 1894 Benziger edition, a collection arranged for daily reading throughout the year.</p><p>We follow the dates in that edition. These do not always match the dates in today’s liturgical calendar. The source text is in the public domain, and the complete calendar is freely available in <a href="/reader/">our reading room</a>.</p><p class="source-note">Sources: <a href="https://www.newadvent.org/cathen/03090a.htm">Alban Butler, Catholic Encyclopedia</a> · <a href="https://www.sacred-texts.com/chr/butler/butler-toc.htm">The 1894 text</a></p><h2>The sound of the reading.</h2><p>Each episode pairs narration with sacred imagery and a quiet musical accompaniment. Music and artwork credits can be found in each episode’s notes.</p><h2>Get in touch.</h2><p>For questions about the readings or the channel, write to <a href="mailto:info@thedailybutler.com">info@thedailybutler.com</a>.</p></div></div>{self.follow()}'''
        return self.wrap('Our story', 'About The Daily Butler and the 1894 edition of Butler’s Lives of the Saints.', body, '/about/', 'about')

    def subscribe(self):
        body = f'''<section class="container follow-page"><div class="podcast-cover"><img src="/assets/podcast-cover.webp" width="640" height="640" alt="The Daily Butler podcast cover"></div><div><p class="eyebrow">LISTEN &amp; FOLLOW</p><h1>Make room<br>for a daily reading.</h1><p class="lead">Follow The Daily Butler on your favourite platform, and return to the lives of the saints each day.</p>{self.platform_links()}<p class="fine-print">Apple Podcasts and Spotify links open a search for The Daily Butler. You can also add the RSS feed directly to your podcast app.</p><div class="email-note"><h2>Prefer to read?</h2><p>The full text is always here. No signup needed.</p><a class="text-link" href="/reader/">Visit the reading room {icon('arrow')}</a></div></div></section>'''
        return self.wrap('Listen & follow', 'Follow The Daily Butler on YouTube, Apple Podcasts, Spotify, or RSS.', body, '/subscribe/', 'follow')

    def not_found(self):
        return self.wrap('Page not found', 'Find your way back to The Daily Butler.', '<section class="page-heading container error-page"><p class="eyebrow">PAGE NOT FOUND · 404</p><h1>Let’s turn back a page.</h1><p>This reading may have moved, or the address may be incomplete.</p><div class="actions"><a class="button" href="/">Return home</a><a class="text-link" href="/reader/">Browse the calendar →</a></div></section>', '/404')
