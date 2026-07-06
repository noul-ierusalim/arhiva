# csni-migrate

Migrate the archive of **noul-ierusalim.ro** (old, custom-PHP, at risk of crashing)
to the new **noulierusalim.ro** site (WordPress + Divi).

## Layout

- `csni_extract.py` — the extractor (stdlib only, no third-party deps).
- `cache/` — raw source HTML, one file per fetched page. The offline safety net; the
  extractor never re-hits the server for a page already here.
- `out/markdown/<year>/YYYY-MM-DD--slug.md` — one message per file (see frontmatter below).
- `out/audio/<year>/yy.mm.dd.mp3` — recordings (recent years only). Git-ignored (large).

## Commands

```bash
python3 csni_extract.py --all                 # full crawl: text pass, then audio
python3 csni_extract.py --all --no-audio      # text only
python3 csni_extract.py --k 86 --year 2026    # single year (k = arhiva.html ?k= id)
```

Re-running is **idempotent and resumable**: cached HTML is skipped, existing MP3s are
skipped, downloads are atomic (`.part` → rename). Interrupted? Just run `--all` again.
Failures are logged to `failures.log`; completion writes `CRAWL_DONE.txt`.

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
- **Audio**: source `<cheie>.mp3` saved locally as `yy.mm.dd.mp3` (matches the new
  site's `wp-content/uploads/` naming).

Frontmatter:
```yaml
title, date, year, source_url, cheie, audio (source URL), audio_file (local mp3)
```

## Status

Full archive extracted: 1,745 messages (1955–2026), 841 audio files. **Phase 2 not
built**: transform Markdown → WordPress WXR (Divi posts, `/cuvantul/YYYY/MM/slug/`
permalinks, `[audio]` + `[legatura_la_teme]` shortcodes; each message a Post, category
= year).
