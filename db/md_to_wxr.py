#!/usr/bin/env python3
"""
md_to_wxr.py — Phase 2 generator PROTOTYPE.

Turns extracted `out/markdown/**.md` messages into a WordPress WXR import file
using **strategy A**: emit Divi-4 shortcode content + the builder meta bundle,
and let the live Divi 5 site's built-in D4->D5 converter upgrade on load.

Validated against the site's own `_et_pb_divi_4_content` (see db/FINDINGS.md).

Usage:
    python3 md_to_wxr.py out/markdown/2025/2025-11-16--*.md ... -o db/out/sample.wxr
    python3 md_to_wxr.py --emit-d4 out/markdown/2025/2025-11-16--*.md   # print D4 body only
"""
import argparse
import copy
import glob
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta
from xml.sax.saxutils import escape as xml_escape

# --- fixed target facts (from the live DB) ---------------------------------
# SITE_URL is the FQDN of the site the WXR will be imported into. It's asked for
# at generation time (or via --site-url) and baked as an ABSOLUTE audio URL —
# the Divi audio module misbehaves with a root-relative src, so the mp3 must
# carry the full host of wherever the files are uploaded.
SITE_URL = "https://noulierusalim.ro"
UPLOADS = SITE_URL + "/wp-content/uploads/"   # recomputed from SITE_URL at runtime
CAT_NAME = "Cuvântul lui Dumnezeu"
CAT_SLUG = "cuvantul"
CAT_TERM_ID = 0  # let WP resolve by nicename on import
AUTHOR = "admin"
DEFAULT_TIME = "18:00:00"  # source has date only; publish time is editorial
TZ_OFFSET_H = 2            # Romania EET (winter). Summer is +3; see NOTE below.

# Divi builder meta bundle every post needs (mirrors the migrated posts).
# We emit NATIVE Divi-5 blocks, so _et_pb_use_divi_5 is 'on'.
META_BUNDLE = {
    "_et_pb_use_builder": "on",
    "_et_pb_use_divi_5": "on",
    "_et_builder_version": "VB|Divi|4.27.5",
    "_et_pb_built_for_post_type": "page",
    "_et_pb_page_layout": "et_no_sidebar",
    "_et_pb_show_title": "on",
    "_et_pb_side_nav": "off",
    "_et_pb_post_hide_nav": "default",
    "_et_gb_content_width": "1080",
    "_thumbnail_id": "0",
}

# Divi-5 block attribute dicts, copied verbatim from a live post (ID 19) and
# validated by round-tripping through json.loads. Static blocks are used as-is;
# the audio/text blocks get their dynamic value substituted at build time.
_BV_STRUCT = "5.0.0-public-alpha.18.2"   # builderVersion on section/row/column
_BV_MODULE = "5.0.0-public-beta.1"       # builderVersion on audio/text

SECTION_ATTRS = {"builderVersion": _BV_STRUCT, "modulePreset": ["default"], "module": {"decoration": {"spacing": {"desktop": {"value": {"margin": {"top": "5px", "right": "", "bottom": "5px", "left": "", "syncVertical": "off", "syncHorizontal": "off"}, "padding": {"top": "5px", "right": "", "bottom": "5px", "left": "", "syncVertical": "off", "syncHorizontal": "off"}}}}, "layout": {"desktop": {"value": {"display": "block"}}}}}}
ROW_ATTRS = {"builderVersion": _BV_STRUCT, "modulePreset": ["default"], "module": {"decoration": {"layout": {"desktop": {"value": {"display": "block"}}}}}}
COLUMN_ATTRS = {"module": {"advanced": {"type": {"desktop": {"value": "4_4"}}}, "decoration": {"layout": {"desktop": {"value": {"display": "block"}}}}}, "builderVersion": _BV_STRUCT, "modulePreset": ["default"]}
AUDIO_ATTRS = {"audio": {"innerContent": {"desktop": {"value": None}}}, "builderVersion": _BV_MODULE, "modulePreset": ["default"], "module": {"decoration": {"spacing": {"desktop": {"value": {"margin": {"top": "", "right": "", "bottom": "", "left": "", "syncVertical": "off", "syncHorizontal": "off"}, "padding": {"top": "20px", "right": "", "bottom": "20px", "left": "", "syncVertical": "off", "syncHorizontal": "off"}}}}, "border": {"desktop": {"value": {"radius": {"sync": "on", "topLeft": "7px", "topRight": "7px", "bottomRight": "7px", "bottomLeft": "7px"}}}}, "boxShadow": {"desktop": {"value": {"style": "preset1"}}}, "layout": {"desktop": {"value": {"display": "block"}}}}}, "image": {"innerContent": {"desktop": {"value": {"titleText": None}}}}}
TEXT_ATTRS = {"builderVersion": _BV_MODULE, "modulePreset": ["default"], "content": {"innerContent": {"desktop": {"value": None}}}, "module": {"decoration": {"layout": {"desktop": {"value": {"display": "block"}}}}}}


def _block(name, attrs, self_closing):
    """Serialize one Divi-5 block comment. `<`/`>` in the JSON (only ever inside
    body content) become \\u003c/\\u003e — matches Divi's json_encode(JSON_HEX_TAG)
    and guarantees the body can never produce a stray '-->'."""
    j = json.dumps(attrs, ensure_ascii=False, separators=(",", ":"))
    j = j.replace("<", "\\u003c").replace(">", "\\u003e")
    tail = " /-->" if self_closing else " -->"
    return f"<!-- {name} {j}{tail}"


# Romanian diacritic normalization: the source archive was authored over decades
# and mixes legacy cedilla forms (ş/ţ, Turkish-style) with the correct comma-below
# forms (ș/ț). Cedilla s/t is always a mis-encoding in Romanian — fold to comma-below
# so the imported site is uniform. 1:1 map, applied to the whole file at read time.
_RO_CEDILLA = str.maketrans({"ş": "ș", "ţ": "ț", "Ş": "Ș", "Ţ": "Ț"})


def parse_md(path):
    """Return (frontmatter dict, body str)."""
    with open(path, encoding="utf-8") as f:
        raw = f.read().translate(_RO_CEDILLA)
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        sys.exit(f"{path}: no frontmatter")
    fm = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] == '"':
            v = v[1:-1]
        fm[k.strip()] = v
    return fm, m.group(2).strip()


# italics: *text* -> <em>text</em>  (source has no bold; ** would need care)
_ITALIC = re.compile(r"\*(.+?)\*", re.S)


def body_to_html(body: str) -> str:
    """Source markdown body -> text-module HTML value (paragraphs stay \\n\\n-
    separated, as in the live D5 posts; italics become <em>). json.dumps handles
    the JSON-string escaping when the block is serialized."""
    return _ITALIC.sub(r"<em>\1</em>", body)


def build_content(fm, body) -> str:
    """Full Divi-5 post_content: placeholder > section > row > column >
    [audio] + text. Native block markup — no D4 shortcodes, no compat layer."""
    inner = []

    audio_file = fm.get("audio_file", "").strip()
    if audio_file:
        a = copy.deepcopy(AUDIO_ATTRS)
        a["audio"]["innerContent"]["desktop"]["value"] = UPLOADS + audio_file
        a["image"]["innerContent"]["desktop"]["value"]["titleText"] = audio_file
        inner.append(_block("wp:divi/audio", a, True))

    t = copy.deepcopy(TEXT_ATTRS)
    t["content"]["innerContent"]["desktop"]["value"] = body_to_html(body)
    inner.append(_block("wp:divi/text", t, True))

    return (
        "<!-- wp:divi/placeholder -->"
        + _block("wp:divi/section", SECTION_ATTRS, False)
        + _block("wp:divi/row", ROW_ATTRS, False)
        + _block("wp:divi/column", COLUMN_ATTRS, False)
        + "".join(inner)
        + "<!-- /wp:divi/column -->"
        + "<!-- /wp:divi/row -->"
        + "<!-- /wp:divi/section -->"
        + "<!-- /wp:divi/placeholder -->"
    )


def slug_from_path(path):
    base = os.path.basename(path)
    m = re.match(r"\d{4}-\d{2}-\d{2}--(.+)\.md$", base)
    return m.group(1) if m else os.path.splitext(base)[0]


# WordPress enforces globally-unique post_name (date-based permalinks do NOT relax
# this — it appends -2/-3). Recurring liturgical titles collide across years, so we
# fold a deterministic token into the slug. Default 'date-prefix' puts the date at
# the FRONT (YYYY-MM-DD-base) — unique, chronologically sortable, and pairs with a
# flat /cuvantul/%postname%/ permalink. Others append instead.
def unique_slug(base, fm, mode):
    if mode == "none":
        return base
    if mode == "date-prefix":
        return f"{fm['date']}-{base}"      # YYYY-MM-DD-base
    if mode == "year":
        return f"{base}-{fm['date'][:4]}"
    if mode == "cheie":
        return f"{base}-{fm['cheie']}"
    return f"{base}-{fm['date']}"          # date: base-YYYY-MM-DD


def dates(fm):
    d = fm["date"]  # YYYY-MM-DD
    local = f"{d} {DEFAULT_TIME}"
    dt = datetime.strptime(local, "%Y-%m-%d %H:%M:%S")
    gmt = (dt - timedelta(hours=TZ_OFFSET_H)).strftime("%Y-%m-%d %H:%M:%S")
    return local, gmt


def cdata(s: str) -> str:
    # CDATA can't contain "]]>"; split it if present.
    return "<![CDATA[" + s.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def item_xml(fm, body, post_id):
    slug = None  # set by caller via fm['_slug']
    slug = fm["_slug"]
    local, gmt = dates(fm)
    content = build_content(fm, body)
    # Flat permalink: /cuvantul/<slug>/ (slug carries the date). WP regenerates
    # the real URL from its own permalink setting on import; this is a hint.
    link = f"{SITE_URL}/{CAT_SLUG}/{slug}/"
    meta = "".join(
        f"\n\t\t<wp:postmeta><wp:meta_key>{cdata(k)}</wp:meta_key>"
        f"<wp:meta_value>{cdata(v)}</wp:meta_value></wp:postmeta>"
        for k, v in META_BUNDLE.items()
    )
    return f"""\t<item>
\t\t<title>{xml_escape(fm['title'])}</title>
\t\t<link>{link}</link>
\t\t<pubDate>{local}</pubDate>
\t\t<dc:creator>{cdata(AUTHOR)}</dc:creator>
\t\t<guid isPermaLink="false">{SITE_URL}/?p={post_id}</guid>
\t\t<description></description>
\t\t<content:encoded>{cdata(content)}</content:encoded>
\t\t<excerpt:encoded>{cdata('')}</excerpt:encoded>
\t\t<wp:post_id>{post_id}</wp:post_id>
\t\t<wp:post_date>{cdata(local)}</wp:post_date>
\t\t<wp:post_date_gmt>{cdata(gmt)}</wp:post_date_gmt>
\t\t<wp:comment_status>{cdata('closed')}</wp:comment_status>
\t\t<wp:ping_status>{cdata('closed')}</wp:ping_status>
\t\t<wp:post_name>{cdata(slug)}</wp:post_name>
\t\t<wp:status>{cdata('publish')}</wp:status>
\t\t<wp:post_parent>0</wp:post_parent>
\t\t<wp:menu_order>0</wp:menu_order>
\t\t<wp:post_type>{cdata('post')}</wp:post_type>
\t\t<wp:post_password>{cdata('')}</wp:post_password>
\t\t<wp:is_sticky>0</wp:is_sticky>
\t\t<category domain="category" nicename="{CAT_SLUG}">{cdata(CAT_NAME)}</category>{meta}
\t</item>"""


def wxr_head():
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
\txmlns:excerpt="http://wordpress.org/export/1.2/excerpt/"
\txmlns:content="http://purl.org/rss/1.0/modules/content/"
\txmlns:wfw="http://wellformedweb.org/CommentAPI/"
\txmlns:dc="http://purl.org/dc/elements/1.1/"
\txmlns:wp="http://wordpress.org/export/1.2/">
<channel>
\t<title>Noul Ierusalim</title>
\t<link>{SITE_URL}</link>
\t<description>Cuvântul lui Dumnezeu</description>
\t<language>ro-RO</language>
\t<wp:wxr_version>1.2</wp:wxr_version>
\t<wp:base_site_url>{SITE_URL}</wp:base_site_url>
\t<wp:base_blog_url>{SITE_URL}</wp:base_blog_url>
\t<wp:author><wp:author_id>1</wp:author_id><wp:author_login>{cdata(AUTHOR)}</wp:author_login></wp:author>
\t<wp:category>
\t\t<wp:term_id>{CAT_TERM_ID}</wp:term_id>
\t\t<wp:category_nicename>{CAT_SLUG}</wp:category_nicename>
\t\t<wp:category_parent></wp:category_parent>
\t\t<wp:cat_name>{cdata(CAT_NAME)}</wp:cat_name>
\t</wp:category>
"""
WXR_TAIL = "</channel>\n</rss>\n"


def mysql_str(s: str) -> str:
    """Escape a Python string as a MySQL single-quoted literal."""
    s = s.replace("\\", "\\\\").replace("'", "\\'")
    return "'" + s + "'"


def build_sql(fm, body, slug, prefix):
    """Self-contained INSERT SQL for one message into a `<prefix>` WordPress DB.

    Strategy A: post_content holds Divi-4 shortcodes + the builder meta bundle;
    Divi 5 renders them via its legacy handler and converts on first edit.
    Creates the `cuvantul` category if absent; uses @vars so no id is hardcoded.
    """
    p = prefix
    local, gmt = dates(fm)
    content = build_content(fm, body)
    meta_rows = ",\n".join(
        f"  (@post_id, {mysql_str(k)}, {mysql_str(v)})" for k, v in META_BUNDLE.items()
    )
    return f"""-- Inject one message into the SANDBOX WordPress DB (prefix `{p}`).
-- Idempotent-ish: re-running creates a duplicate post; delete by slug first if re-testing.
-- Message: {fm['title']}  (source cheie {fm.get('cheie','?')}, archive date {fm['date']})

START TRANSACTION;

-- 1) Ensure the single 'Cuvântul lui Dumnezeu' category exists; capture its ids.
INSERT INTO `{p}terms` (name, slug, term_group)
  SELECT {mysql_str(CAT_NAME)}, {mysql_str(CAT_SLUG)}, 0
  WHERE NOT EXISTS (SELECT 1 FROM `{p}terms` WHERE slug = {mysql_str(CAT_SLUG)});
SET @term_id := (SELECT term_id FROM `{p}terms` WHERE slug = {mysql_str(CAT_SLUG)} LIMIT 1);

INSERT INTO `{p}term_taxonomy` (term_id, taxonomy, description, parent, count)
  SELECT @term_id, 'category', '', 0, 0
  WHERE NOT EXISTS (SELECT 1 FROM `{p}term_taxonomy` WHERE term_id = @term_id AND taxonomy = 'category');
SET @tt_id := (SELECT term_taxonomy_id FROM `{p}term_taxonomy` WHERE term_id = @term_id AND taxonomy = 'category' LIMIT 1);

-- 2) The post itself. Permalink resolves to /cuvantul/{fm['date'][:4]}/{fm['date'][5:7]}/{slug}/
INSERT INTO `{p}posts`
  (post_author, post_date, post_date_gmt, post_content, post_title, post_excerpt,
   post_status, comment_status, ping_status, post_password, post_name, to_ping, pinged,
   post_modified, post_modified_gmt, post_content_filtered, post_parent, guid,
   menu_order, post_type, post_mime_type, comment_count)
VALUES
  (1, {mysql_str(local)}, {mysql_str(gmt)}, {mysql_str(content)}, {mysql_str(fm['title'])}, '',
   'publish', 'closed', 'closed', '', {mysql_str(slug)}, '', '',
   {mysql_str(local)}, {mysql_str(gmt)}, '', 0, '',
   0, 'post', '', 0);
SET @post_id := LAST_INSERT_ID();
UPDATE `{p}posts` SET guid = CONCAT({mysql_str(SITE_URL + '/?p=')}, @post_id) WHERE ID = @post_id;

-- 3) Divi builder meta bundle (without it Divi renders raw markup).
INSERT INTO `{p}postmeta` (post_id, meta_key, meta_value) VALUES
{meta_rows};

-- 4) Attach to the category and bump its count.
INSERT INTO `{p}term_relationships` (object_id, term_taxonomy_id, term_order)
  VALUES (@post_id, @tt_id, 0);
UPDATE `{p}term_taxonomy` SET count = count + 1 WHERE term_taxonomy_id = @tt_id;

COMMIT;

-- Verify:
SELECT @post_id AS new_post_id, @term_id AS cat_term_id, @tt_id AS cat_tt_id;
"""


def normalize_site(u: str) -> str:
    """Accept 'sandbox.noulierusalim.ro' or 'https://…' -> 'https://host' (no slash)."""
    u = u.strip().rstrip("/")
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


def main():
    global SITE_URL, UPLOADS
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--file-list", help="read newline-separated source paths from a file "
                                        "(e.g. db/out/import_set.txt)")
    ap.add_argument("-o", "--out", default="db/out/sample.wxr")
    ap.add_argument("--emit-d4", action="store_true",
                    help="print each post's D4 post_content to stdout, no WXR")
    ap.add_argument("--sql", action="store_true",
                    help="emit direct-injection SQL (to --out) instead of WXR")
    ap.add_argument("--prefix", default="Kup_", help="target table prefix (sandbox)")
    ap.add_argument("--site-url", default=None,
                    help="FQDN of the target site the content is imported into "
                         "(e.g. https://sandbox.noulierusalim.ro). Baked into the "
                         "absolute audio URL, guid, permalink and WXR base_url. "
                         "If omitted you'll be prompted.")
    ap.add_argument("--slug-suffix",
                    choices=["date-prefix", "date", "year", "cheie", "none"],
                    default="date-prefix",
                    help="make recurring-title slugs unique (WP enforces unique slugs). "
                         "date-prefix=YYYY-MM-DD-base (default, pairs with a flat "
                         "/cuvantul/%%postname%%/ permalink); date=base-YYYY-MM-DD; year; "
                         "cheie; none.")
    ap.add_argument("--start-id", type=int, default=9001)
    args = ap.parse_args()

    site = args.site_url
    if not site:
        site = input(f"Target site FQDN [{SITE_URL}]: ").strip() or SITE_URL
    SITE_URL = normalize_site(site)
    UPLOADS = SITE_URL + "/wp-content/uploads/"
    print(f"Target site: {SITE_URL}")

    paths = []
    for pat in args.files:
        paths.extend(sorted(glob.glob(pat)))
    if args.file_list:
        with open(args.file_list, encoding="utf-8") as fh:
            paths.extend(line.strip() for line in fh if line.strip())
    if not paths:
        sys.exit("no files matched")

    if args.emit_d4:
        for p in paths:
            fm, body = parse_md(p)
            print(f"===== {os.path.basename(p)} =====")
            print(build_content(fm, body))
            print()
        return

    if args.sql:
        if len(paths) != 1:
            sys.exit("--sql expects exactly one message (focus on one at a time)")
        fm, body = parse_md(paths[0])
        slug = unique_slug(slug_from_path(paths[0]), fm, args.slug_suffix)
        sql = build_sql(fm, body, slug, args.prefix)
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(sql)
        print(f"wrote {args.out} (prefix {args.prefix})")
        return

    items = []
    for i, p in enumerate(paths):
        fm, body = parse_md(p)
        fm["_slug"] = unique_slug(slug_from_path(p), fm, args.slug_suffix)
        items.append(item_xml(fm, body, args.start_id + i))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(wxr_head())
        f.write("\n".join(items))
        f.write("\n" + WXR_TAIL)
    print(f"wrote {args.out} ({len(items)} items)")


if __name__ == "__main__":
    main()
