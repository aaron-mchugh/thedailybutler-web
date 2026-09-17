"""Publish small, local derivatives of the channel's existing approved artwork."""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageOps


def prepare_assets(root, project, episodes):
    root, project = Path(root), Path(project)
    output = root / "assets"
    output.mkdir(exist_ok=True)
    provenance = []

    def image(source, name, width, notes=None):
        source = Path(source)
        destination = output / f"{name}.webp"
        with Image.open(source) as original:
            picture = ImageOps.exif_transpose(original).convert("RGBA" if original.mode == "RGBA" else "RGB")
            picture.thumbnail((width, width * 2), Image.Resampling.LANCZOS)
            picture.save(destination, "WEBP", quality=86, method=6)
        source_label = ("production/" + source.relative_to(project).as_posix()
                        if source.is_relative_to(project)
                        else "website/" + source.relative_to(root).as_posix())
        provenance.append({"asset": destination.name, "source": source_label,
                           "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                           "provenance": notes or "Existing channel artwork; resized and encoded for the website."})
        return f"/assets/{destination.name}"

    image(project / "assets/brand/banner.png", "channel-banner", 1920,
          "Aaron-selected Butler Library banner, qa-v4, 17 September 2026.")
    image(project / "assets/brand/podcast-cover-1400.jpg", "podcast-cover", 640)
    image(project / "assets/brand/logo.png", "channel-logo-purple", 240,
          "Canonical channel logo with its original purple background, used in the footer.")
    # A retained derivative of the exact transparent mark used in the banner.
    # No ongoing dependency on the read-only legacy production repository.
    mark = root / "build/brand/channel-logo.webp"
    image(mark, "channel-logo", 360, "Canonical transparent logo; see build/brand/README.md for original provenance.")
    for episode in episodes:
        episode_dir = Path(episode["source_dir"])
        meta = json.loads((episode_dir / "episode.json").read_text())
        candidate = (meta.get("draft_render") or {}).get("thumbnail_candidate") or {}
        thumb = None
        if candidate.get("review_status") == "approved_and_published" and candidate.get("file"):
            candidate_path = (episode_dir / candidate["file"]).resolve()
            if candidate_path.is_relative_to(episode_dir.resolve()) and candidate_path.is_file():
                thumb = candidate_path
        for extension in ("png", "jpg", "jpeg", "webp"):
            final = episode_dir / f"05-thumbnail/final/thumbnail.{extension}"
            if thumb is None and final.is_file():
                thumb = final
        if thumb:
            episode["thumbnail"] = image(thumb, f"episode-{episode['date']}", 960)
            image(thumb, f"episode-{episode['date']}-small", 480)
        if episode.get("art_local"):
            index_path = episode_dir / "02-images/index.json"
            index = json.loads(index_path.read_text()) if index_path.exists() else {}
            record = next((a for a in index.get("assets", [])
                           if (episode_dir / a.get("file", "")).resolve() == Path(episode["art_local"]).resolve()), {})
            episode["image_source"] = record.get("source_url")
            episode["image_credit"] = record.get("notes", "")
            episode["art_url"] = image(episode["art_local"], f"art-{episode['date']}", 960, record)
        episode.setdefault("thumbnail", episode.get("art_url") or "/assets/podcast-cover.webp")
    # Keep provenance with build sources, including original attribution/review records.
    (root / "build/asset-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
