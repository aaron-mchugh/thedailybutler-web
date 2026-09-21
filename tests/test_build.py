import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path


BUILD_PATH = Path(__file__).parents[1] / "build" / "build.py"
SPEC = importlib.util.spec_from_file_location("daily_butler_site_build", BUILD_PATH)
site_build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site_build)

ASSETS_PATH = Path(__file__).parents[1] / "build" / "assets.py"
ASSETS_SPEC = importlib.util.spec_from_file_location("daily_butler_site_assets", ASSETS_PATH)
site_assets = importlib.util.module_from_spec(ASSETS_SPEC)
ASSETS_SPEC.loader.exec_module(site_assets)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class EpisodeLoadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.original_project = site_build.DAILY_BUTLER
        site_build.DAILY_BUTLER = str(self.project)

    def tearDown(self):
        site_build.DAILY_BUTLER = self.original_project
        self.temp.cleanup()

    def test_loads_native_receipt_and_native_storyboard(self):
        episode = self.project / "episodes" / "2026-09-17--st-lambert"
        image = episode / "02-images" / "approved" / "lambert.jpg"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"image")
        write_json(episode / "episode.json", {
            "date": "2026-09-17",
            "status": "published",
            "hold": False,
            "channels": {"youtube": {"video_id": "youtube-id"}},
        })
        write_json(episode / "06-publish" / "podcast-receipt.json", {
            "verified_at": "2026-09-17T00:00:00Z",
            "audio_url": "https://media.example/episode.mp3",
            "item": {
                "date": "2026-09-17",
                "title": "17 September — Saint Lambert",
                "saints": ["Saint Lambert"],
                "duration_s": 120,
                "hold": False,
            },
        })
        write_json(episode / "04-video" / "drafts" / "storyboard.json", {
            "shots": [{"source_path": "02-images/approved/lambert.jpg"}],
        })

        episodes = site_build.load_episodes()

        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["video_id"], "youtube-id")
        self.assertEqual(episodes[0]["mp3_url"], "https://media.example/episode.mp3")
        self.assertEqual(episodes[0]["art_local"], str(image))

    def test_loads_verified_split_native_manifest_and_receipt(self):
        episode = self.project / "episodes" / "2026-09-21--st-matthew"
        write_json(episode / "episode.json", {
            "date": "2026-09-21",
            "status": "published",
            "hold": False,
            "channels": {"youtube": {"video_id": "youtube-id"}},
        })
        write_json(episode / "06-publish" / "podcast.json", {
            "date": "2026-09-21",
            "guid": "tdb-2026-09-21",
            "title": "21 September — Saint Matthew",
            "saints": ["Saint Matthew"],
            "duration_s": 121,
            "hold": False,
        })
        write_json(episode / "06-publish" / "podcast-receipt.json", {
            "status": "published",
            "verified_at": "2026-09-21T11:44:18Z",
            "audio_url": "https://media.example/2026-09-21.mp3",
            "guid": "tdb-2026-09-21",
        })

        episodes = site_build.load_episodes()

        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["date"], "2026-09-21")
        self.assertEqual(episodes[0]["video_id"], "youtube-id")
        self.assertEqual(episodes[0]["mp3_url"], "https://media.example/2026-09-21.mp3")

    def test_split_native_manifest_requires_matching_published_receipt(self):
        for day, status, receipt_guid in (
            ("19", "pending", "tdb-2026-09-19"),
            ("20", "published", "tdb-another-episode"),
        ):
            episode = self.project / "episodes" / f"2026-09-{day}--native"
            write_json(episode / "episode.json", {
                "date": f"2026-09-{day}", "status": "published", "hold": False,
            })
            write_json(episode / "06-publish" / "podcast.json", {
                "date": f"2026-09-{day}", "guid": f"tdb-2026-09-{day}", "hold": False,
            })
            write_json(episode / "06-publish" / "podcast-receipt.json", {
                "status": status,
                "verified_at": "2026-09-21T11:44:18Z",
                "audio_url": f"https://media.example/2026-09-{day}.mp3",
                "guid": receipt_guid,
            })

        self.assertEqual(site_build.load_episodes(), [])

    def test_resolves_imported_storyboard_and_excludes_holds(self):
        published = self.project / "episodes" / "2026-09-01--st-giles"
        imported = published / "02-images" / "approved" / "digest--giles.png"
        imported.parent.mkdir(parents=True)
        imported.write_bytes(b"image")
        write_json(published / "episode.json", {
            "date": "2026-09-01", "status": "historical_published", "hold": False,
        })
        write_json(published / "06-publish" / "podcast.json", {
            "date": "2026-09-01", "title": "Saint Giles", "saints": ["Saint Giles"],
        })
        write_json(published / "06-publish" / "storyboard.json", {
            "shots": [{"asset": "assets/saints/st_giles/giles.png"}],
        })
        write_json(published / "06-publish" / "import-manifest.json", {
            "files": [{
                "source": "/legacy/assets/saints/st_giles/giles.png",
                "destination": "02-images/approved/digest--giles.png",
            }],
        })

        held = self.project / "episodes" / "2026-09-02--held"
        write_json(held / "episode.json", {"date": "2026-09-02", "hold": True})
        write_json(held / "06-publish" / "podcast.json", {
            "date": "2026-09-02", "title": "Held episode", "hold": False,
        })

        episodes = site_build.load_episodes()

        self.assertEqual([item["date"] for item in episodes], ["2026-09-01"])
        self.assertEqual(episodes[0]["art_local"], str(imported))

    def test_draft_manifest_unverified_receipt_and_missing_hold_are_excluded(self):
        for day, meta, receipt in (
            ('18', {'hold': False, 'status': 'draft'}, {}),
            ('19', {'hold': False}, {'item': {'date': '2026-09-19'}}),
            ('20', {}, {'item': {'date': '2026-09-20'}, 'verified_at': 'now', 'audio_url': 'https://example.test/audio'}),
        ):
            episode = self.project / 'episodes' / f'2026-09-{day}--draft'
            write_json(episode / 'episode.json', meta)
            write_json(episode / '06-publish/podcast.json', {'date': f'2026-09-{day}'})
            write_json(episode / '06-publish/podcast-receipt.json', receipt)
        self.assertEqual(site_build.load_episodes(), [])

    def test_missing_production_source_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            site_build.load_episodes()

    def test_uses_reviewed_delivery_thumbnail_with_matching_digest(self):
        episode = self.project / "episodes" / "2026-09-21--st-matthew"
        thumbnail = episode / "05-thumbnail" / "final" / "thumbnail_yt.png"
        thumbnail.parent.mkdir(parents=True)
        thumbnail.write_bytes(b"approved thumbnail")
        digest = hashlib.sha256(thumbnail.read_bytes()).hexdigest()
        meta = {"thumbnail": {
            "delivery_file": "05-thumbnail/final/thumbnail_yt.png",
            "delivery_sha256": digest,
            "reviewed_at": "2026-09-21T09:21:12Z",
            "reviewer": "Aaron",
        }}

        self.assertEqual(site_assets.approved_thumbnail(episode, meta), thumbnail)

    def test_rejects_delivery_thumbnail_with_mismatched_digest(self):
        episode = self.project / "episodes" / "2026-09-21--st-matthew"
        thumbnail = episode / "05-thumbnail" / "final" / "thumbnail_yt.png"
        thumbnail.parent.mkdir(parents=True)
        thumbnail.write_bytes(b"different thumbnail")
        meta = {"thumbnail": {
            "delivery_file": "05-thumbnail/final/thumbnail_yt.png",
            "delivery_sha256": "0" * 64,
            "reviewed_at": "2026-09-21T09:21:12Z",
            "reviewer": "Aaron",
        }}

        self.assertIsNone(site_assets.approved_thumbnail(episode, meta))

    def test_withdrawn_pages_and_art_removed_without_touching_other_files(self):
        removed = ('episode/2026-09-18/index.html', 'assets/art-2026-09-18.webp',
                   'assets/episode-2026-09-18-small.webp')
        kept = ('episode/2026-09-17/index.html', 'episode/2026-09-18/notes.txt',
                'assets/channel-logo.webp', 'assets/episode-2026-09-17.webp')
        for relative in removed + kept:
            path = self.project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture')
        site_build.prune_episode_outputs(self.project, {'2026-09-17'})
        for relative in removed:
            self.assertFalse((self.project / relative).exists())
        for relative in kept:
            self.assertTrue((self.project / relative).exists())


if __name__ == "__main__":
    unittest.main()
