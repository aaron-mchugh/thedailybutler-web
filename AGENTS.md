# The Daily Butler website — operating rules

- This is the public website, deployed from GitHub `aaron-mchugh/thedailybutler-web`
  `main` to Vercel at https://thedailybutler.com. Cloudflare supplies DNS/email routing
  and podcast R2 storage, not website hosting.
- `../the-daily-butler` is the production source of truth for episodes, final publication
  receipts, approved artwork, thumbnails and canonical branding. Never publish media,
  clear holds, or change production approvals from a website sync.
- Work on templates in `build/presentation.py`, styling in `build/css/site.css`, and
  behavior in `build/js/site.js`; regenerate HTML rather than editing generated pages.
- After a successful, explicitly approved media publication and final receipt updates,
  run `daily-butler sync-website --episode YYYY-MM-DD` from the production repo.
  For artwork/metadata corrections to already published episodes, use `sync-website`
  without `--episode`. See `README.md` for setup and recovery.
- `build/sync.py` requires a clean website `main` matching its approved GitHub remote.
  It builds/tests in a temporary checkout, commits only generated output, pushes without
  force, then checks the release marker and actual page bytes on the live domain.
  Never bypass a failing test, overwrite local edits, or deploy source/credential files.
- A failed website update does not undo media publication. Retry website sync only;
  never re-upload a video/podcast to repair the website. Inspect the production repo's
  `var/website-sync/latest.json` and episode `06-publish/website-receipt.json`.
- Only unheld episodes with verified native podcast receipts or canonical imported
  historical publication metadata belong on the site. Remove stale generated pages and
  generated episode art when an episode is withdrawn/held; preserve production originals.
- Public contact is `info@thedailybutler.com`. Never put a personal email on the site.
  Use the original purple-background logo in the footer. Music credits belong to their
  individual episodes; About must not promise a particular artist or permanent track.
