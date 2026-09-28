# Public content v1

This is a static, read-only content API generated alongside the website. Production
remains the source of truth; the website and app are consumers. No database, account,
API key or separate mobile publishing step is required for daily public content.

## Public documents

All URLs begin with `https://thedailybutler.com/content/v1/`.

| File | Contents |
| --- | --- |
| `manifest.json` | Schema version, content revision, counts and document hashes/sizes/URLs |
| `catalog.json` | Complete currently eligible episode catalogue, newest first |
| `reader.json` | All 366 calendar days with complete text, reflections and edition details |
| `site.json` | Show identity, contact address, edition details and public follow links |
| `schema.json` | JSON Schema 2020-12 for the four public document kinds |

`build/content.schema.json` is the source contract. Its public copy is for developer
tooling; apps ship a reviewed schema rather than downloading executable validation
logic. Only explicit public fields are exported. Private paths, approvals, provider
credentials and production state are never part of this API. Episode notes retain
their full original credits. About currently remains a canonical web link; it is not
yet a structured native page in this first milestone.

## Identities and revisions

- An episode ID is its podcast GUID, normally `tdb-YYYY-MM-DD`. Historical records
  without a GUID use that same deterministic date form. Titles and slugs are not IDs.
- A reading ID is `butler-benziger-1894-en:MM-DD`. Many annual episodes may reference
  the same reading. February 29 is always present, including in non-leap years.
- Paragraph/reflection IDs include the reading ID, block kind, text hash and duplicate
  occurrence. Inserting a different paragraph does not change existing anchors.
  Text edits create new anchors. Identical duplicate paragraphs cannot be distinguished
  across reordering; annotations must not be silently moved to changed text.
- Per-record revisions hash the canonical record before adding its `revision` field.
  Document hashes cover the **exact UTF-8 bytes**, including the final newline.
- `content_version` is SHA-256 of the document descriptor map, serialized as compact
  sorted-key JSON with a final newline. It changes with public content, not a CSS edit.
- `site-version.json` records this as `app_content_version`; its separate
  `content_sha256` also covers generated website presentation files.

Select Today's reading using the visitor's local month/day, not a UTC ISO date slice.
Publication timestamps are timezone-aware instants; the production slot is separate
from the visitor's calendar. The traditional 1894 calendar is not silently remapped
to a modern liturgical calendar.

## Safe refresh and offline operation

1. Open the last verified snapshot, falling back to the app's bundled snapshot.
2. Fetch the manifest on launch, foreground or explicit refresh. If its content
   revision is unchanged, no documents need downloading.
3. Download only changed documents. Reuse an unchanged reader across daily releases.
4. Verify supported schema version, document address, byte count and SHA-256; validate
   the schema, complete calendar, unique IDs and episode-to-reading relationships.
5. Commit the complete snapshot atomically. Keep user bookmarks, playback positions
   and annotations in independent storage keyed by stable IDs.

A Vercel deployment can switch during requests. Retry once from a fresh manifest when
hashes do not match; otherwise retain the prior snapshot. Never clear the current
catalogue because a request failed or returned invalid JSON. The app's TypeScript
consumer implements these rules; native storage and crypto adapters remain to be added.

The full catalogue is authoritative, not append-only. A valid new catalogue removes
withdrawn episodes from visible content. An offline device learns about withdrawals
on its next successful refresh; this is not remote erasure. Native download management
must reconcile removed/corrected media separately and preserve personal bookmarks.
Bundled reader text works offline; bundled episode metadata does **not** bundle audio,
video or artwork. Images/media still require connectivity or explicit downloads.

The content endpoints revalidate (`max-age=0, must-revalidate`) and allow anonymous
cross-origin reads. Native media playback does not require browser CORS, while a
browser-based media downloader would need separately configured R2 CORS. No R2 policy
or storage configuration is changed by this milestone.

## Publication and withdrawal gates

Eligible episodes require explicit `hold: false` plus either verified native podcast
evidence or canonical imported historical publication metadata. Future publication
times are excluded even when audio bytes have already been uploaded. Future or
unverified private video schedules export `video: null`. An elapsed schedule needs
successful public YouTube oEmbed readback; transient errors stop the build. No video
approval, privacy status or production receipt is changed by this read-only check.

Malformed JSON stops a build. If an episode in the prior release disappears, the build
requires an explicit episode/item hold before deleting generated content. Missing
source folders or receipts cannot masquerade as an authorized withdrawal. Removing
an episode from disk is not the withdrawal workflow: retain production originals and
set the hold through the existing authorized production process.

The general publisher saves final media evidence before its website handoff. Immediate
publication attempts a sync; future scheduling records `status: deferred` and the
release time in the website receipt. **Run `daily-butler sync-website --episode DATE`
after that time** from the release runner/operator. The weekly repair timer is only
a backstop. No daily scheduler is installed here. A website failure never reverses
media success or asks the operator to upload the media again.

Website sync still requires clean website `main` matching the approved GitHub remote.
It builds/tests in isolation, commits only allowlisted generated output, pushes without
force and compares actual live bytes for all five content files as well as the original
HTML/asset checks. Receipts include `app_content_version` for troubleshooting.

## Media and cache corrections

The catalogue supplies HTTPS audio URLs, byte size, duration and available native
receipt hashes. Some historical audio has no checksum; `sha256` is explicitly `null`.
Square artwork uses published, hash-bound podcast art at 320px and 960px; the fallback
is the canonical show cover. Landscape thumbnails remain separate.

Available media hashes are included as `?v=HASH` cache revisions. These URLs do not
promise permanently retained, immutable old bytes: source R2 keys and website asset
names can be replaced by an authorized correction. Download clients should key their
cache by episode ID **and** media revision, validate available hashes, refresh metadata
on a mismatch, and avoid mixing an old partial download with corrected bytes. Real
device resumable downloads and lock-screen playback are a later native milestone.

## Compatibility and rollout

Additive optional fields may be introduced within v1; clients must ignore unknown
fields. Existing required fields, meanings, IDs and nullability must not change within
v1. Breaking changes need a new versioned endpoint while v1 remains supported for old
installed apps. The shipped app schema/types come from the same reviewed source schema.

Deploy the website source and generated contract together first, using the ordinary
reviewed website release workflow. Install `build/requirements.txt` in the interpreter
used by production sync. Verify all live content documents before pointing a native
release at them. Do not merge these source changes through the generated-only daily
sync command. Then import the verified public release into the app's offline bundle
and run its TypeScript and content tests. Daily runtime refreshes thereafter do not
require a new App Store/Play Store binary.

This phase intentionally retains the static website and separate app repository.
User accounts, cross-device progress, push notifications, support/privacy pages and
native screens/player are subsequent work, not implicit dependencies of public content.
