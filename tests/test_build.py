import importlib.util
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
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
            "channels": {"youtube": {"video_id": "youtube-id", "privacy": "public"}},
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
            "channels": {"youtube": {"video_id": "youtube-id", "privacy": "public"}},
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

    def published_fixture(self, *, pub_date="2026-09-21T00:00:00Z", video=None):
        episode = self.project / "episodes/2026-09-21--saint"
        write_json(episode / "episode.json", {
            "date": "2026-09-21", "hold": False, "status": "scheduled",
            "channels": {"youtube": video or {}},
        })
        write_json(episode / "06-publish/podcast.json", {
            "date": "2026-09-21", "guid": "tdb-2026-09-21", "pub_date": pub_date,
        })
        write_json(episode / "06-publish/podcast-receipt.json", {
            "status": "published", "verified_at": "2026-09-20T00:00:00Z",
            "guid": "tdb-2026-09-21", "audio_url": "https://example.test/audio.mp3",
        })
        return episode

    def test_future_audio_is_not_exported_even_with_verified_upload(self):
        self.published_fixture(pub_date="2099-09-21T04:00:00+08:00")
        self.assertEqual(site_build.load_episodes(now=datetime(2026, 9, 26, tzinfo=timezone.utc)), [])

    def test_scheduled_video_needs_elapsed_slot_and_public_readback(self):
        self.published_fixture(video={"video_id": "abcdefghijk", "privacy": "private",
                                      "publish_at": "2026-09-22T00:00:00Z"})
        checks = []
        def verify(video_id):
            checks.append(video_id)
            return True
        before = site_build.load_episodes(now=datetime(2026, 9, 21, 12, tzinfo=timezone.utc), verify_video=verify)
        self.assertIsNone(before[0]["video_id"])
        self.assertEqual(checks, [])
        after = datetime(2026, 9, 23, tzinfo=timezone.utc)
        self.assertIsNone(site_build.load_episodes(now=after)[0]["video_id"])
        self.assertIsNone(site_build.load_episodes(now=after, verify_video=lambda _: False)[0]["video_id"])
        self.assertEqual(site_build.load_episodes(now=after, verify_video=verify)[0]["video_id"], "abcdefghijk")

    def test_corrupt_publication_data_aborts_instead_of_withdrawing(self):
        episode = self.published_fixture()
        (episode / "06-publish/podcast.json").write_text("{corrupt")
        with self.assertRaisesRegex(RuntimeError, "source JSON"):
            site_build.load_episodes()

    def test_missing_episode_is_not_an_authorized_withdrawal(self):
        episode = self.published_fixture()
        output = self.project / "website"
        write_json(output / "site-version.json", {"episode_dates": ["2026-09-21"]})
        (episode / "06-publish/podcast-receipt.json").unlink()
        with self.assertRaisesRegex(RuntimeError, "explicit hold"):
            site_build.validate_withdrawals(output, site_build.load_episodes())
        write_json(episode / "episode.json", {"date": "2026-09-21", "hold": True})
        site_build.validate_withdrawals(output, [])
        (episode / "06-publish/podcast-receipt.json").write_text("{corrupt")
        site_build.validate_withdrawals(output, site_build.load_episodes())

    def test_naive_timestamp_is_rejected(self):
        self.published_fixture(pub_date="2026-09-21T04:00:00")
        with self.assertRaisesRegex(RuntimeError, "timestamp"):
            site_build.load_episodes()

    def test_embedded_receipt_cannot_override_failed_status_or_guid_mismatch(self):
        episode = self.published_fixture()
        for status, guid in (("failed", "tdb-2026-09-21"), ("published", "wrong-episode")):
            write_json(episode / "06-publish/podcast-receipt.json", {
                "status": status, "guid": guid, "verified_at": "2026-09-21T00:00:00Z",
                "audio_url": "https://example.test/audio.mp3",
                "item": {"date": "2026-09-21", "guid": "tdb-2026-09-21"},
            })
            self.assertEqual(site_build.load_episodes(), [])

    def test_malformed_receipt_type_aborts_build(self):
        episode = self.published_fixture()
        write_json(episode / "06-publish/podcast-receipt.json", [])
        with self.assertRaisesRegex(RuntimeError, "receipt must be an object"):
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

    def test_uses_verified_master_when_delivery_was_reencoded(self):
        episode = self.project / "episodes" / "2026-09-20--st-eustachius"
        final = episode / "05-thumbnail" / "final"
        final.mkdir(parents=True)
        (final / "thumbnail_yt.png").write_bytes(b"reencoded delivery")
        master = final / "thumbnail-master-2k.png"
        master.write_bytes(b"approved master")
        meta = {"thumbnail": {
            "delivery_file": "05-thumbnail/final/thumbnail_yt.png",
            "delivery_sha256": "0" * 64,
            "master_file": "05-thumbnail/final/thumbnail-master-2k.png",
            "master_sha256": hashlib.sha256(master.read_bytes()).hexdigest(),
            "reviewed_at": "2026-09-20T07:56:44Z",
            "reviewer": "Aaron",
        }}

        self.assertEqual(site_assets.approved_thumbnail(episode, meta), master)

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
