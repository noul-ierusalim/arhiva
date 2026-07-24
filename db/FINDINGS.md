# Phase 2 target analysis — from `dump_dcsannmy_WPLTV.sql`

Loaded the live WordPress DB (prefix `Bwr_`) into `db/wp.sqlite` via
`dump_to_sqlite.py` and queried it. This is what the target actually looks like.

## 1. What's already migrated: a recent-only pilot

- **54 published posts**, dates **2025-11-09 → 2026-07-19**. These are the newest
  messages only — *not* the full 1,745. Phase 2 must generate the other ~1,691.
- Every one of the 54 has an audio module (recent years always have audio).
- 1,497 `revision` rows exist (Divi autosaves) — Phase 2 does **not** need to create these.

## 2. Content format: Divi **5** Gutenberg blocks (not shortcodes)

`post_content` is WordPress block markup, e.g.:

```
<!-- wp:divi/placeholder -->
<!-- wp:divi/section {"builderVersion":"5.0.0-...","module":{...}} -->
  <!-- wp:divi/row {...} -->
    <!-- wp:divi/column {"module":{"advanced":{"type":{"desktop":{"value":"4_4"}}}...}} -->
      <!-- wp:divi/heading {"title":{"innerContent":{"desktop":{"value":"<subtitle>"}}}} /-->
      <!-- wp:divi/text  {"content":{"innerContent":{"desktop":{"value":"<BODY>"}}}} /-->
      <!-- wp:divi/audio {"audio":{"innerContent":{"desktop":{"value":"<mp3 url>"}}}} /-->
<!-- /wp:divi/placeholder -->
```

Block types used across the corpus: `section` (2/post), `row`, `column`,
`placeholder`, `text` (1–2/post), `audio` (1/post), `heading` (rare — only 3 total).

- **Body text** lives inside the `wp:divi/text` block at
  `content.innerContent.desktop.value` — a single JSON string. Paragraphs are
  separated by literal `\n` (no `<p>` tags).
- **Theme links** are the `[legatura_la_teme id_capitol=4 id_subcapitol=4]…[/legatura_la_teme]`
  shortcode embedded **inline inside that text value**. Note attributes are
  **unquoted** (`id_capitol=4`, not `id_capitol="4"`). 145 occurrences across the 54 posts.
- **Audio** is its own `wp:divi/audio` block, mp3 URL in `audio.innerContent.desktop.value`.

## 3. Required postmeta bundle (~30 keys per post)

Divi will not render the blocks without its builder flags. Key ones observed:

| meta_key | value | note |
|---|---|---|
| `_et_pb_use_builder` | `on` | **mandatory** — else content shows raw |
| `_et_pb_use_divi_5` | `on` | marks Divi-5 block content |
| `_et_builder_version` | `VB\|Divi\|4.27.5` | |
| `_et_pb_built_for_post_type` | `page` | (not `post`) |
| `_et_pb_page_layout` | `et_no_sidebar` | |
| `_et_pb_divi_4_content` | `[et_pb_section]…` | Divi-4 shortcode fallback, kept |
| `_et_pb_divi_5_conversion_status` | `{"status":"success",...}` | D4→D5 converter ran |
| `_et_pb_old_content`, `_et_pb_truncate_post` | (rendered HTML cache) | |
| `_thumbnail_id` | `0` | |
| `legatura_la_teme` / `_legatura_la_teme` | (ACF field `field_69234…`) | ACF field exists on these posts |

## 4. Taxonomy & permalinks — differs from the CLAUDE.md plan

- **Single category** `Cuvântul lui Dumnezeu` (slug **`cuvantul`**, term count 54).
  There is **no per-year category**. CLAUDE.md's "category = year" is **wrong** vs reality.
- `permalink_structure` = `/%category%/%year%/%monthnum%/%postname%/`
  → a post URL is **`/cuvantul/YYYY/MM/<slug>/`**. The **year comes from `post_date`**,
  not a category. (CLAUDE.md said `/cuvantul/YYYY/MM/slug/` — confirmed.)
- `post_name` (slug) is the sanitized title, e.g.
  `cuvantul-lui-dumnezeu-din-duminica-a-douazeci-si-patra-dupa-rusalii`.

## 5. Audio naming — confirmed

Uploads are `wp-content/uploads/yy.mm.dd.mp3` (e.g. `25.11.09.mp3`) — **exactly** our
`out/audio/<year>/yy.mm.dd.mp3` convention. URLs use `noulierusalim.ro` (one stray
`.com` guid on post 47, built on staging).

## 6. Italics — RESOLVED (post 2331, `…/2026/07/…-saptea-dupa-rusalii/`)

Italics are **`<em>…</em>`**, stored inside the block's JSON `value` string with
`<`/`>` **Unicode-escaped**: `<em>…</em>`. This is standard
PHP `json_encode(… JSON_HEX_TAG | JSON_HEX_QUOT)` — the same reason the theme-link
quotes appear escaped: `[legatura_la_teme id_capitol="4" …]` (= `id_capitol="4"`).

So the encoding rule for the text block value is: build the HTML/shortcode string
(`<em>`, `[legatura_la_teme id_capitol="X" …]`, paragraphs as `\n`), then JSON-encode
with `<`→`<`, `>`→`>`, `"`→`"`.

Note: shortcode attribute quoting is **inconsistent** across the pilot — post 47 has
unquoted `id_capitol=4`, post 2331 has quoted `id_capitol="4"`. WordPress accepts both;
our `*…*`→`<em>` and quoted-attribute convention is fine.

**This makes strategy (A) clearly preferable:** if we emit Divi-4 shortcodes / plain
HTML and let Divi's D4→D5 converter run, we write `<em>` and `[legatura_la_teme
id_capitol="X"]` in the clear and never hand-roll the `<` JSON escaping. Only
strategy (B) requires replicating that escaping.

## Implications for Phase 2

1. Target is **Divi 5 block markup**, not the WXR-of-plain-HTML implied earlier. Two paths:
   - **(A) Emit Divi-4 shortcodes** (`[et_pb_section]…[et_pb_text]…`) + `_et_pb_use_builder=on`
     and let Divi's built-in D4→D5 converter upgrade on load. Much simpler to generate;
     the dump proves the site round-trips (`_et_pb_divi_4_content` + conversion status present).
   - **(B) Emit Divi-5 blocks directly** by templating one real post and substituting
     title / body / audio / teme. Faithful but must reproduce block JSON + `builderVersion` exactly.
   - Recommendation: **(A)** — generate D4 shortcodes, carry the full meta bundle, import via WXR.
2. Category is a constant (`cuvantul`); **year is derived from the post date**, not a term.
3. Body text → one text block, paragraphs joined by `\n`, `[legatura_la_teme]` inline with
   **unquoted** attributes; audio → separate audio block with `…/uploads/yy.mm.dd.mp3`.
4. Resolve the italics encoding before generating the ~1,691 older messages.

_Reproduce:_ `python3 db/dump_to_sqlite.py dump_dcsannmy_WPLTV.sql`, then query `db/wp.sqlite`.

## 7. Generator prototype (`md_to_wxr.py`) — validated, with one blocker found

Built a strategy-A prototype: Markdown → WXR with Divi-4 shortcode content + the
meta bundle. `python3 md_to_wxr.py <md files> -o db/out/sample.wxr` (well-formed XML,
9-key meta, `[et_pb_audio]` + `[legatura_la_teme]` + `<em>` all present).

**Transform validated against ground truth.** Generated D4 body for the "La început a
făcut Dumnezeu…" message matches the site's own `_et_pb_divi_4_content` (post 19)
**exactly** — identical theme-link ids (`id_capitol="1"/"5"`, `"3"/"4"`) and italics.
Only paragraph-join style differs: we emit `\n\n` (matches post **47**); post 19 used
`<p>…<br />…</p>`. The pilot is internally inconsistent here; both render the same via
Divi's wpautop. Keeping `\n\n`.

**BLOCKER — source↔target don't align by date or title.** DB post 19 is dated
`2025-11-16`, titled *"a Douăzeci și doua după Rusalii"* (22nd), but its body is the
message our archive dates `2025-11-23`, titled *"a Douăzeci și cincea"* (25th). The
pilot's publish dates/titles are **editorial**, not the archive's. Consequences for
Phase 2:
- **Dedup** (don't re-import the 54 already-migrated messages) must key on **body /
  theme-link ids / content**, not date or title.
- If the live site's dates are authoritative, our permalink `/cuvantul/YYYY/MM/slug/`
  (built from the archive date) will **not** match the site's. Need a decision:
  keep archive dates, or adopt the site's editorial dates/titles.
- The title mismatch (22nd vs 25th Sunday) means one source is wrong about the
  liturgical Sunday — worth a spot-check of our title extraction.

## 8. Round-trip CONFIRMED on the sandbox (strategy A works)

Imported the Boboteaza-2015 message (an un-migrated 2015 message, verified not in the
54) via **WXR → Tools → Import** on `sandbox.noulierusalim.ro`. Checked the raw rendered
HTML (not markdown — audio players don't survive HTML→markdown, which gave a false
negative on the first pass). All correct:
- **Audio** renders as a real Divi audio module (`et_pb_audio_module`, mediaelement).
- **All 3 theme links** map to the right pages: ids `3/4`,`3/1`,`2/5` →
  `/teme/capitolul-3/subcapitolul-4/` etc.
- **Italics**, full body, correct title + permalink `/cuvantul/2015/01/…-bobotezei/`.
- **Zero** raw `[et_pb_*` / `[legatura_la_teme]` leaked.

The audio module's `et_d4_element` class shows **Divi 5 renders the Divi-4 shortcodes in
frontend compatibility mode**. WXR is the preferred path (prefix-agnostic, runs WP's hooks);
the `Kup_`-prefixed SQL remains the DB-level fallback.

## 9. CORRECTION + pivot to native Divi-5 blocks

The strategy-A "success" in §8 was **wrong for the audio module**. The `[et_pb_audio]`
D4 shortcode does **not** render a player on this Divi 5 site — the compat layer builds
the styled wrapper but prints the quoted `audio` URL as text (visible teal box showing
`"…/15.01.19.mp3"`, no controls). Body/italics/theme-links were genuinely fine; only
audio broke. My earlier read was misled by site-wide mediaelement scripts.

**Fix (implemented):** the generator now emits **native Divi-5 block markup**
(`<!-- wp:divi/section … wp:divi/audio … wp:divi/text -->`), copied structurally from a
live post (ID 19) and validated: all block-JSONs `json_decode`-parse, and each block
matches the live structure byte-for-byte except the audio URL / body. Body value is
JSON-encoded with `<`/`>`→`<`/`>` (matches Divi's `json_encode(JSON_HEX_TAG)`
and prevents any stray `-->`). Meta bundle now includes `_et_pb_use_divi_5=on`.

This is **strategy B**, and it's now the approach. The `_module_preset="default"`
references mean posts still inherit the site's audio preset (fix its malformed
`"`-in-spacing values, §7-adjacent) once, for all posts.

## 10. Pipeline VALIDATED end-to-end (single message)

Re-imported the D5-block Boboteaza WXR into the sandbox — renders correctly: real
audio player, working theme links, italics, full body, correct permalink. Confirmed
by the user.

Two audio-URL details settled:
- **Absolute URL required.** A root-relative `/wp-content/uploads/…mp3` plays but the
  Divi audio module misbehaves. Must be the full FQDN of the target host.
- **Generator prompts for the target FQDN** (or `--site-url`). It's baked into the
  absolute audio URL + guid + permalink + WXR base_url. So production builds use the
  production FQDN; sandbox test builds use the sandbox FQDN — same script/content.

**State:** `db/md_to_wxr.py` produces a correct, importable single-message WXR.

## 11. FULL RO ARCHIVE IMPORTED (sandbox) — verified

Scope: year folders = **1,747 RO messages** (`en/` 1,088 + `fr/` 429 are separate,
out of scope). Dedup (`db/dedup.py`, content-based letters-only match, diacritic- and
shortcode-insensitive, extracts the live D5 text-body) → **51 excluded, 1,696 imported**,
0 overlap, bidirectionally confirmed no duplicates of the 54 live posts.

Slugs: WP enforces globally-unique `post_name` (verified on sandbox — a duplicate slug
got `-2`, even with a date permalink). So slugs are **date-prefixed** `YYYY-MM-DD-<title>`
(`--slug-suffix date-prefix`, the default) — unique + sortable — paired with a flat
`/%category%/%postname%/` permalink → `/cuvantul/1955-04-30-…/`.

One 29 MB WXR (`db/out/ro_all.wxr`), 1,696 items, imported into the sandbox. Verified
live: flat permalinks 200, body prose, theme links, audio player (with sandbox mp3 URL)
for recorded messages, no audio module for the 904 never-recorded ones, zero leaked
blocks/shortcodes.

Re-import cycle: `db/wipe_imported.sql` (phpMyAdmin, `Kup_`) deletes only date-prefixed
posts (leaves the 54), then re-import — needed because the WP importer skips existing
posts, never updates. Remaining: upload the 843 mp3s to the target `wp-content/uploads/`;
regenerate with the production FQDN for go-live; optional heading support (2 pilot posts).
