"""Public content fidelity, privacy, versioning and deployment contract."""
import copy
import hashlib
import html
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))
import build
import content
import sync
import assets


class ContentAssetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "website"
        self.project = Path(self.temporary.name) / "production"
        for folder in (self.root / "build/brand", self.project / "assets/brand"):
            folder.mkdir(parents=True)
        for name in ("banner.png", "podcast-cover-1400.jpg", "logo.png"):
            Image.new("RGB", (64, 64), "purple").save(self.project / "assets/brand" / name)
        Image.new("RGB", (64, 64), "purple").save(self.root / "build/brand/channel-logo.webp")

    def test_cached_assets_are_reused_but_corrupt_derivatives_are_repaired(self):
        assets.prepare_assets(self.root, self.project, [])
        target = self.root / "assets/channel-banner.webp"
        original = target.read_bytes()
        with patch.object(Image.Image, "save", side_effect=AssertionError("Unnecessary re-encode")):
            assets.prepare_assets(self.root, self.project, [])
        target.write_bytes(b"corrupt derivative")
        assets.prepare_assets(self.root, self.project, [])
        self.assertEqual(target.read_bytes(), original)

    def test_square_artwork_must_match_published_hash_and_stay_in_episode(self):
        episode = self.project / "episodes/2026-09-26--saints"
        episode.mkdir(parents=True)
        (episode / "episode.json").write_text("{}")
        artwork = episode / "published.jpg"
        Image.new("RGB", (64, 64), "gold").save(artwork)
        ep = {"date": "2026-09-26", "source_dir": str(episode),
              "podcast_art_file": "published.jpg", "podcast_art_sha256": "0" * 64}
        with self.assertRaisesRegex(ValueError, "digest differs"):
            assets.prepare_assets(self.root, self.project, [ep])
        ep["podcast_art_sha256"] = hashlib.sha256(artwork.read_bytes()).hexdigest()
        assets.prepare_assets(self.root, self.project, [ep])
        self.assertEqual(len(ep["square_artwork"]), 2)
        ep["podcast_art_file"] = "../../assets/brand/logo.png"
        with self.assertRaisesRegex(ValueError, "missing"):
            assets.prepare_assets(self.root, self.project, [ep])


class PublicContentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "assets").mkdir()
        Image.new("RGB", (64, 64), "purple").save(self.root / "assets/cover.webp")
        self.days = build.parse_corpus()
        self.episode = {
            "date": "2026-09-26", "mmdd": "09-26", "guid": "tdb-2026-09-26",
            "title": "26 September — Saints Cyprian and Justina", "saints": ["Saints Cyprian and Justina"],
            "pub_date": "2026-09-25T20:00:00+00:00", "duration_s": 162.5,
            "audio_bytes": 12345, "audio_sha256": "a" * 64,
            "mp3_url": "https://feed.thedailybutler.com/mp3/2026-09-26.mp3",
            "description": "Full notes\n\nMusic\nArtist: Example\nTrack: Example",
            "thumbnail": "/assets/cover.webp", "square_artwork": ["/assets/cover.webp"],
            "video_id": None, "source_dir": "/private/production", "art_local": "/private/art.png",
            "approvals": {"private": "must not escape"},
        }

    def generate(self, episodes=None):
        return content.write_content(self.root, [self.episode] if episodes is None else episodes,
                                     self.days, build.SITE, build.YOUTUBE, build.SUBSCRIBE)

    def test_only_public_fields_are_exported_and_credits_are_preserved(self):
        self.generate()
        raw = (self.root / "content/v1/catalog.json").read_text()
        episode = json.loads(raw)["episodes"][0]
        self.assertEqual(episode["notes"], self.episode["description"])
        self.assertEqual(episode["id"], self.episode["guid"])
        self.assertIsNone(episode["video"])
        for private in ("source_dir", "art_local", "/private/", "approvals"):
            self.assertNotIn(private, raw)
        self.assertIn("?v=" + "a" * 64, episode["audio"]["url"])

    def test_versions_are_deterministic_independent_of_presentation(self):
        original = self.generate()
        (self.root / "index.html").write_text("different presentation")
        self.assertEqual(original, self.generate())
        self.episode["description"] += "\nCorrection"
        changed = self.generate()
        self.assertNotEqual(original["content_version"], changed["content_version"])
        self.assertEqual(original["documents"]["reader"], changed["documents"]["reader"])

    def test_full_reader_and_stable_text_anchors(self):
        document = content.reader_document(self.days, build.SITE)
        for source, reading in zip(self.days, document["readings"]):
            for entry, exported in zip(source["entries"], reading["entries"]):
                self.assertEqual(entry["paras"], [p["text"] for p in exported["paragraphs"]])
                self.assertEqual(entry["reflection"], (exported["reflection"] or {}).get("text"))
        changed = copy.deepcopy(self.days)
        changed[0]["entries"][0]["paras"].insert(0, "New introductory paragraph.")
        updated = content.reader_document(changed, build.SITE)
        old = document["readings"][0]["entries"][0]["paragraphs"]
        new = updated["readings"][0]["entries"][0]["paragraphs"][1:]
        self.assertEqual(old, new)

    def test_multiple_years_can_reference_the_same_reading(self):
        second = dict(self.episode, guid="tdb-2027-09-26", date="2027-09-26")
        self.generate([self.episode, second])
        episodes = json.loads((self.root / "content/v1/catalog.json").read_text())["episodes"]
        self.assertEqual(len(episodes), 2)
        self.assertEqual(episodes[0]["reading_id"], episodes[1]["reading_id"])

    def test_duplicate_identifiers_and_incomplete_calendar_fail(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            self.generate([self.episode, self.episode])
        self.days[-1] = self.days[0]
        with self.assertRaisesRegex(ValueError, "366-day"):
            self.generate()

    def test_withdrawal_replaces_the_authoritative_catalogue(self):
        before = self.generate()
        after = self.generate([])
        self.assertNotEqual(before["content_version"], after["content_version"])
        self.assertEqual(json.loads((self.root / "content/v1/catalog.json").read_text())["episodes"], [])


class GeneratedContentTests(unittest.TestCase):
    def test_schema_hashes_and_website_parity(self):
        directory = ROOT / "content/v1"
        schema = json.loads((ROOT / "build/content.schema.json").read_text())
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        manifest = json.loads((directory / "manifest.json").read_text())
        validator.validate(manifest)
        self.assertEqual(manifest["content_version"], content.digest(content.encode(manifest["documents"])))
        for name, ref in manifest["documents"].items():
            data = (directory / f"{name}.json").read_bytes()
            self.assertEqual(ref["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(ref["bytes"], len(data))
            validator.validate(json.loads(data))
        catalog = json.loads((directory / "catalog.json").read_text())
        marker = json.loads((ROOT / "site-version.json").read_text())
        self.assertEqual(marker["app_content_version"], manifest["content_version"])
        self.assertEqual(sorted(e["date"] for e in catalog["episodes"]), marker["episode_dates"])
        for ep in catalog["episodes"]:
            page = (ROOT / f"episode/{ep['date']}/index.html").read_text()
            self.assertIn(html.escape(ep["display_title"], quote=True), page)
            self.assertIn(html.escape(ep["audio"]["url"].split("?v=")[0], quote=True), page)
            for shape in ("landscape", "square"):
                for image in ep["artwork"][shape]:
                    path = ROOT / image["url"].split("/assets/", 1)[1].split("?", 1)[0]
                    data = (ROOT / "assets" / path.name).read_bytes()
                    self.assertEqual(image["sha256"], hashlib.sha256(data).hexdigest())
        reader = json.loads((directory / "reader.json").read_text())
        for day in reader["readings"]:
            page = (ROOT / f"reader/{day['calendar_day']}/index.html").read_text()
            for entry in day["entries"]:
                for block in entry["paragraphs"] + ([entry["reflection"]] if entry["reflection"] else []):
                    self.assertIn(html.escape(block["text"], quote=True), page)

    def test_allowlist_is_narrow(self):
        for name in ("manifest", "catalog", "reader", "site", "schema"):
            self.assertTrue(sync.allowed_output(f"content/v1/{name}.json"))
        for name in ("content/v1/private.json", "content/v1/.env", "content/v1/../../secret.json", "content/v2/catalog.json"):
            self.assertFalse(sync.allowed_output(name))
