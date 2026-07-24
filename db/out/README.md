# Phase 2 deliverables — WXR import runbook

Generated files for migrating the Romanian archive (1,748 messages, 1955–2026) into
the WordPress/Divi site as native Divi-5 blocks. Regenerate any of these from source
with the commands below — nothing here is hand-edited.

| File | What | Target |
|------|------|--------|
| `sdbx_ro_full.wxr` / `.xml` | Full archive import (1,748 posts) | sandbox (`https://sandbox.noulierusalim.ro`) |
| `prod_ro_full.wxr` / `.xml` | Full archive import (1,748 posts) | production (`https://noulierusalim.ro`) |
| `sdbx_wipe.sql` | Delete every post in the `cuvantul` category | sandbox DB, prefix `Kup_` |
| `prod_wipe.sql` | Delete every post in the `cuvantul` category | production DB, prefix `Bwr_` |

`.wxr` and `.xml` are byte-identical — some hosts reject the `.wxr` upload extension,
so use `.xml` if the importer complains ("missing/invalid WXR version").

## One-time WordPress setup (per site)

1. **Permalinks** → Settings → Permalinks → Custom Structure: `/%category%/%postname%/`
   → URLs become `/cuvantul/YYYY-MM-DD-<title>/` (the date is in the slug).
2. **WordPress Importer** plugin installed & active (Tools → Import → WordPress).
3. **Audio files**: upload all 844 mp3s to `wp-content/uploads/` (SFTP / host file
   manager). They are git-ignored and NOT in the WXR — the audio blocks only
   reference them by absolute URL. Naming: `yy.mm.dd.mp3` (e.g. `26.07.19.mp3`).

## Reset → reload cycle (idempotent)

The WP importer **skips** posts that already exist (matched on title+date) and never
updates them — so to apply changes you must wipe first, then re-import.

1. **Back up the DB** (phpMyAdmin → Export). Non-negotiable for prod.
2. **Wipe**: run the env's `*_wipe.sql` in phpMyAdmin. Run the top `SELECT COUNT(*)`
   on its own first as a dry run, confirm the number, then run the whole script.
3. **Import**: Tools → Import → WordPress → upload the env's `*_ro_full.xml` → Run.
   - If it times out on the managed host, switch to per-year batches (regenerate — see
     below). ~1,748 posts in one pass can exceed PHP `max_execution_time`.
4. **Verify**: spot-check a random handful across decades — body, italics, theme
   links, audio player (needs the mp3 uploaded), and the `/cuvantul/<date-slug>/` URL.

Notes:
- `prod_wipe.sql` clears the 54 hand-migrated posts too (full reset). Their editorial
  tweaks — e.g. run-on titles split into subtitle headings — are NOT reproduced by the
  generator; the full text is preserved but as a single title.
- The wipe does not touch `wp-content/uploads/`, so mp3s persist across re-imports.

## Regenerating from source

```bash
# full RO file list (year folders only; en/ and fr/ are separate archives)
find out/markdown -name '*.md' -not -path '*/en/*' -not -path '*/fr/*' | sort > db/out/all_ro_files.txt

# WXR (swap --site-url for the target; --slug-suffix date-prefix is the default)
python3 db/md_to_wxr.py --file-list db/out/all_ro_files.txt \
  --site-url https://sandbox.noulierusalim.ro -o db/out/sdbx_ro_full.wxr
python3 db/md_to_wxr.py --file-list db/out/all_ro_files.txt \
  --site-url https://noulierusalim.ro       -o db/out/prod_ro_full.wxr

# refresh the current year from the old site before regenerating, e.g. 2026:
python3 csni_extract.py --k 86 --year 2026 --no-audio
```

The wipe SQLs are produced by the inline template in the session history (category-scoped,
prefix-parameterized: `Kup_` sandbox / `Bwr_` prod).

## Not yet handled

- **en/ (1,088) and fr/ (429)** archives — separate, pending an i18n decision.
- **Heading split** — 2 pilot posts split a run-on title into subtitle `wp:divi/heading`
  modules; the generator emits a single text module. Cosmetic; text is intact.
- **Redirects** — if the 54 prod posts were indexed, their URLs change on a full reset.
