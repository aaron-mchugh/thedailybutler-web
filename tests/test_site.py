"""Check the complete generated site and preservation of the source text."""
import html
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'build'))
import build


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
    def handle_starttag(self, tag, attrs):
        self.urls.extend(value for key, value in attrs if key in ('src', 'href') and value)


class PublishedSiteTests(unittest.TestCase):
    def test_public_contact_and_about_copy(self):
        page = (ROOT / 'about/index.html').read_text()
        self.assertIn('mailto:info@thedailybutler.com', page)
        self.assertNotIn('@gmail.com', page)
        self.assertNotIn('Ron Gelinas', page)
        self.assertNotIn('Satisfied (Original Mix)', page)

    def test_footer_uses_purple_logo(self):
        for page in (ROOT / 'index.html', ROOT / 'about/index.html',
                     ROOT / 'reader/01-01/index.html'):
            footer = page.read_text().split('<footer class="site-footer">', 1)[1]
            self.assertIn('/assets/channel-logo-purple.webp', footer)
            self.assertNotIn('/assets/channel-logo.webp', footer)

    def test_internal_destinations_exist(self):
        files = [ROOT / 'index.html', ROOT / '404.html']
        for folder in ('about', 'subscribe', 'archive', 'reader', 'episode'):
            files.extend((ROOT / folder).rglob('*.html'))
        self.assertGreater(len(files), 380)
        for file in files:
            parser = Links()
            parser.feed(file.read_text())
            for url in parser.urls:
                if not url.startswith('/') or url.startswith('//'):
                    continue
                path = ROOT / unquote(urlsplit(url).path).lstrip('/')
                if path.is_dir():
                    path /= 'index.html'
                with self.subTest(page=str(file.relative_to(ROOT)), link=url):
                    self.assertTrue(path.is_file())

    def test_reader_preserves_complete_corpus(self):
        for day in build.parse_corpus():
            page = (ROOT / f'reader/{day["mmdd"]}/index.html').read_text()
            for entry in day['entries']:
                for paragraph in entry['paras'] + ([entry['reflection']] if entry['reflection'] else []):
                    with self.subTest(date=day['mmdd']):
                        self.assertIn(html.escape(paragraph, quote=True), page)


if __name__ == '__main__':
    unittest.main()
