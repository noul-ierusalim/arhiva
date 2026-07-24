#!/usr/bin/env python3
"""
dedup.py — decide which Romanian source messages are NOT yet on the live site,
so the full WXR import doesn't duplicate the 54 already migrated.

Matching is content-based (dates/titles are editorial on the pilot and don't
align). We reduce both sides to letters-only (lowercased, tags/shortcodes/escapes
stripped) and test whether a long contiguous slice of the source appears verbatim
in a live post — a 250-char letter run is effectively unique per message.

Outputs:
  db/out/import_set.txt   — RO source files to import (one path per line)
  db/out/excluded.txt     — RO source files skipped (already live)
Prints a coverage report (how many of the 54 live posts were matched).
"""
import glob
import json
import os
import re
import sqlite3
import unicodedata

SQLITE = "db/wp.sqlite"
PROBE_LEN = 250


def decode_u(s):
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)


def prose_letters(s):
    """Pure message prose as ascii letters: drop shortcodes and tags first (so
    `[legatura_la_teme …]` words don't count), strip diacritics (cedilla `ş`
    matches comma `ș`), lowercase, keep a-z only."""
    s = re.sub(r"\[[^\]]*\]", " ", s)   # shortcodes
    s = re.sub(r"<[^>]*>", " ", s)      # html tags
    s = unicodedata.normalize("NFKD", s)
    return "".join(c.lower() for c in s if "a" <= c.lower() <= "z")


def live_prose(post_content):
    """Extract just the wp:divi/text body from a live D5 post, ignoring block JSON."""
    vals = []
    for attrs in re.findall(r"wp:divi/text\s*(\{.*?\})\s*/-->", post_content, re.S):
        try:
            vals.append(json.loads(attrs)["content"]["innerContent"]["desktop"]["value"])
        except Exception:
            pass
    return prose_letters(" ".join(vals)) if vals else prose_letters(decode_u(post_content))


def md_body(path):
    raw = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n.*?\n---\n(.*)$", raw, re.S)
    return m.group(1) if m else ""


def main():
    con = sqlite3.connect(SQLITE)
    live = con.execute(
        "SELECT ID, post_date, post_content FROM posts "
        "WHERE post_type='post' AND post_status='publish'"
    ).fetchall()
    live_letters = [(pid, pdate, live_prose(pc)) for pid, pdate, pc in live]
    print(f"live published posts: {len(live)}")

    ro = sorted(
        f for f in glob.glob("out/markdown/**/*.md", recursive=True)
        if "/en/" not in f and "/fr/" not in f
    )
    print(f"RO source messages:   {len(ro)}")

    excluded, import_set = [], []
    matched_pid = {}
    for f in ro:
        L = prose_letters(md_body(f))
        # two probes from the interior, away from the leading shortcode/heading
        probes = [L[i:i + PROBE_LEN] for i in (len(L) // 3, 2 * len(L) // 3)]
        hit = None
        for pid, _, tl in live_letters:
            if any(p and p in tl for p in probes):
                hit = pid
                break
        if hit:
            excluded.append(f)
            matched_pid.setdefault(hit, f)
        else:
            import_set.append(f)

    os.makedirs("db/out", exist_ok=True)
    open("db/out/import_set.txt", "w").write("\n".join(import_set) + "\n")
    open("db/out/excluded.txt", "w").write("\n".join(excluded) + "\n")

    covered = set(matched_pid)
    print(f"\nexcluded (already live): {len(excluded)}")
    print(f"to import:               {len(import_set)}")
    print(f"live posts matched:      {len(covered)}/{len(live)}")
    uncovered = [(pid, pd[:10]) for pid, pd, _ in live_letters if pid not in covered]
    if uncovered:
        print(f"live posts NOT matched to any source (won't be touched): {uncovered}")
    print("\nwrote db/out/import_set.txt and db/out/excluded.txt")


if __name__ == "__main__":
    main()
