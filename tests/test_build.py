import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


BUILD_PATH = Path(__file__).parents[1] / "build" / "build.py"
SPEC = importlib.util.spec_from_file_location("daily_butler_site_build", BUILD_PATH)
site_build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site_build)


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


if __name__ == "__main__":
    unittest.main()
