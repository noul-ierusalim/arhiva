# csni-migrate

Migrate the archive of **noul-ierusalim.ro** (old, custom-PHP, at risk of crashing)
to the new **noulierusalim.ro** site (WordPress + Divi).

## Layout

- `scripts/csni_extract.py` — the extractor (stdlib only, no third-party deps).
  `scripts/csni_extract_intl.py` — the EN/FR extractor (reuses the RO engine).
- `cache/` — raw source HTML, one file per fetched page. The offline safety net; message
  pages (immutable) are never re-fetched once cached. The listing pages (`arhiva.html`,
  per-year index) are always re-fetched (`fetch(..., refresh=True)`) — they grow as new
  messages are posted, so a cached copy would hide the latest post.
- `out/markdown/<lang>/<year>/YYYY-MM-DD--slug.md` — one message per file, grouped by
  language (`ro`/`en`/`fr`; see frontmatter below).
- `out/audio/<lang>/<year>/yy.mm.dd-<lang>.mp3` — recordings, per language (`ro`/`en`/`fr`;
  recent years only). Git-ignored (large).
- `logs/` — crawl sentinels (`CRAWL_DONE*.txt`) and failure logs. The scripts anchor all
  data paths (`cache/`, `out/`, `logs/`) to the repo root via `__file__`, so they run
  correctly from any working directory.

## Commands

```bash
python3 scripts/csni_extract.py --all                 # full crawl: text pass, then audio
python3 scripts/csni_extract.py --all --no-audio      # text only
python3 scripts/csni_extract.py --k 86 --year 2026    # single year (k = arhiva.html ?k= id)
```

Re-running is **idempotent and resumable**: cached HTML is skipped, existing MP3s are
skipped, downloads are atomic (`.part` → rename). Interrupted? Just run `--all` again.
Failures are logged to `logs/failures.log`; completion writes `logs/CRAWL_DONE.txt`.

## Source structure

`arhiva.html` → 67 year links (`?pg=get&k=N`) → per-year list of
`(date, title, ?pg=look&cheie=M)` → each `cheie` is one message. Body is the
`<p>` run inside `<font size="4">`, ending at the footer date div.

## Extraction conventions (validated against a real migrated page)

- **Italics** `<i>`/`<em>` → `*…*`. **Bold**: handled (`**`) but the source has none.
- **Colored text** (`<span style="color:#800000">`): color ignored, text kept.
- **Theme links**: `?pg=subcapitole&cap=X&sub=Y` → `[legatura_la_teme id_capitol="X"
  id_subcapitol="Y"]…[/legatura_la_teme]`, spanning across paragraphs. Maps 1:1 to the
  new site's `/teme/capitolul-X/subcapitolul-Y/`.
- **Audio**: source `<cheie>.mp3` saved locally as `out/audio/ro/<year>/yy.mm.dd-ro.mp3`.
  The `-ro` language suffix (en/fr carry `-en`/`-fr`) lets all archives share the new
  site's one `wp-content/uploads/` folder without colliding.

Frontmatter:
```yaml
title, date, year, source_url, cheie, audio (source URL), audio_file (local mp3)
```

## Status

Full RO archive extracted: **1,748 messages** (1955–2026), 844 audio files. **Phase 2
built and validated on the sandbox** — Markdown → WordPress WXR (native Divi-5 blocks),
imported into the Divi site. `en/` (1,088) and `fr/` (429) are separate archives,
pending an i18n decision.

### Phase 2 pipeline (`db/`) — see `db/FINDINGS.md` for the full derivation

Grounded in the live DB: `db/dump_to_sqlite.py` loads a phpMyAdmin dump into SQLite
(prefix `Bwr_` prod, `Kup_` sandbox). DB access is cPanel/phpMyAdmin only — deliver
pasteable SQL, never shell/mysqldump.

- **`db/md_to_wxr.py`** — the generator. Markdown → WXR of **native Divi-5 block
  markup** (`<!-- wp:divi/section → row → column → audio? → text -->`), copied
  structurally from a real live post and validated (all block JSON `json_decode`-parses).
  - Body → `wp:divi/text` value: `*…*`→`<em>`, paragraphs kept as `\n\n`,
    `[legatura_la_teme id_capitol="X" id_subcapitol="Y"]…[/legatura_la_teme]` inline;
    JSON-encoded with `<`/`>`→`<`/`>`.
  - Audio → `wp:divi/audio` **only when `audio_file` is non-empty** (904 old messages
    have none → text-only post). URL is **absolute** with the target FQDN (root-relative
    breaks the Divi audio module).
  - Meta bundle incl. `_et_pb_use_builder=on`, `_et_pb_use_divi_5=on`.
  - `--site-url` (prompted) sets the FQDN; `--slug-suffix date-prefix` (default) makes
    slugs `YYYY-MM-DD-<title>`; `--file-list` reads many paths.
- **Strategy note:** D4 shortcodes + Divi's compat renderer (the old plan) was dropped —
  it renders the audio module as a quoted URL, not a player. Native D5 blocks are required.
- **Slugs / permalinks:** WP enforces globally-unique `post_name` (date permalinks do NOT
  relax it — verified). Recurring liturgical titles collide, so slugs are date-prefixed
  and paired with a flat **`/%category%/%postname%/`** permalink → `/cuvantul/YYYY-MM-DD-slug/`.
  Single category `Cuvântul lui Dumnezeu` (slug `cuvantul`).
- **Dedup** (`db/dedup.py`) — content-based (letters-only, diacritic/shortcode-insensitive)
  to skip already-live posts. Only needed when importing into a site that already has some;
  a full-wipe reload needs no dedup.

### Deliverables & runbook — `db/out/`

`sdbx_ro_full.xml` / `prod_ro_full.xml` (full 1,748-post WXR per FQDN),
`sdbx_wipe.sql` (`Kup_`) / `prod_wipe.sql` (`Bwr_`) (category-scoped reset), and
**`db/out/README.md`** (wipe→import→mp3 sequence). The WP importer **skips existing
posts, never updates** — so re-import = wipe first, then import. Sandbox full import
verified rendering correctly (permalinks, body, italics, theme links, conditional audio).
mp3s must be uploaded to `wp-content/uploads/` separately (git-ignored, `yy.mm.dd-ro.mp3`).
