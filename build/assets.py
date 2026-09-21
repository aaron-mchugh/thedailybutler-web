"""Publish small, local derivatives of the channel's existing approved artwork."""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageOps


def approved_thumbnail(episode_dir, meta):
    """Resolve an explicitly reviewed thumbnail without trusting an unchecked path."""
    episode_dir = Path(episode_dir).resolve()

    def checked(record, file_key, sha_key, *, status_key=None, expected_status=None):
        if not isinstance(record, dict) or not record.get(file_key):
            return None
        if status_key and record.get(status_key) != expected_status:
            return None
        candidate = (episode_dir / record[file_key]).resolve()
        if not candidate.is_relative_to(episode_dir) or not candidate.is_file():
            return None
        expected_sha = record.get(sha_key)
        if expected_sha and hashlib.sha256(candidate.read_bytes()).hexdigest() != expected_sha:
            return None
        return candidate

    legacy = (meta.get("draft_render") or {}).get("thumbnail_candidate") or {}
    selected = checked(legacy, "file", "sha256", status_key="review_status",
                       expected_status="approved_and_published")
    if selected:
        return selected

    review = meta.get("thumbnail_review") or {}
    selected = checked(review, "file", "sha256", status_key="status", expected_status="approved")
    if selected:
        return selected

    delivery = meta.get("thumbnail") or {}
    if delivery.get("reviewed_at") and delivery.get("reviewer") and delivery.get("delivery_sha256"):
        selected = checked(delivery, "delivery_file", "delivery_sha256")
        if selected:
            return selected
    if delivery.get("reviewed_at") and delivery.get("reviewer") and delivery.get("master_sha256"):
        selected = checked(delivery, "master_file", "master_sha256")
        if selected:
            return selected

    # Retain the original convention for imported/legacy approved finals.
    for extension in ("png", "jpg", "jpeg", "webp"):
        final = episode_dir / f"05-thumbnail/final/thumbnail.{extension}"
        if final.is_file():
            return final
    return None


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
        thumb = approved_thumbnail(episode_dir, meta)
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
