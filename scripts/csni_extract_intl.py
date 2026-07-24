#!/usr/bin/env python3
"""csni-migrate — extract the English and French archives to local Markdown.

The foreign archives sit on the same custom-PHP backend as the Romanian one and
share its page layout exactly: the same `<font size="4">` body wrapper, the same
right-aligned footer date, the same italics/nesting/multi-part quirks, and the
same `href="…/audio/…mp3"` player. Only the query-string dialect differs:

                Romanian          English           French
    archive     arhiva.html       archive.html      archives.html
    year link   pg=get            pg=geten          pg=getfr
    message     pg=look           pg=looken         pg=lookfr
    theme link  pg=subcapitole    pg=subtopics      pg=subsujets
    audio       <cheie>.mp3       <cheie>en.mp3     <cheie>fr.mp3

So this script does NOT re-implement the fragile HTML→Markdown engine — it reuses
csni_extract wholesale (fetch, extract_document, html_to_md, the anchor/multi-part
logic, download_audio) and only supplies the per-language dialect plus language-
scoped output/cache paths. `csni_extract` itself is left untouched.

The message `cheie` and year `k` numbers are a *separate* namespace per language
(EN cheie=2 ≠ RO cheie=2), so cache files and outputs are namespaced by language
to avoid collisions with the Romanian crawl.

Usage:
    python3 scripts/csni_extract_intl.py --all                 # EN + FR, text then audio
    python3 scripts/csni_extract_intl.py --all --no-audio      # text only
    python3 scripts/csni_extract_intl.py --lang en             # one language
    python3 scripts/csni_extract_intl.py --lang fr --k 74      # single year (getfr ?k=)
"""
import argparse
import os
import re
import time

import csni_extract as ro

# Per-language dialect. `subcap` is the theme-link query param whose cap/sub IDs
# we preserve verbatim in the [legatura_la_teme] shortcode: the topic taxonomy is
# the same tree translated, numbered identically across languages, so the numeric
# IDs round-trip and Phase 2 can map EN/FR shortcodes the same way as Romanian.
LANGS = {
    "en": {
        "archive": "archive.html",
        "get": "geten",
        "look": "looken",
        "subcap": r"pg=subtopics&cap=(\d+)&sub=(\d+)",
    },
    "fr": {
        "archive": "archives.html",
        "get": "getfr",
        "look": "lookfr",
        "subcap": r"pg=subsujets&cap=(\d+)&sub=(\d+)",
    },
}

# Data dirs live at the repo root; this script sits in scripts/ (one level down),
# so anchor every path to the root via __file__ — the crawl works from any CWD.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out", "markdown")
OUT_AUDIO = os.path.join(ROOT, "out", "audio")
LOGS = os.path.join(ROOT, "logs")  # crawl completion sentinel + failure log land here


def year_map(lang):
    """Return [(year:int, k:str)] for a language's archive page, sorted.

    Same shape as csni_extract.year_map but for archive.html / archives.html and
    the geten/getfr year param.
    """
    cfg = LANGS[lang]
    arh = ro.fetch(f"{ro.BASE}{cfg['archive']}", cfg["archive"])
    pairs = re.findall(rf"pg={cfg['get']}&k=(\d+)\"[^>]*?>\s*(\d{{4}})", arh)
    seen = {}
    for k, y in pairs:
        seen.setdefault(int(y), k)  # first k wins if a year repeats
    return sorted(seen.items())


def parse_year_index(html_text, look):
    """Return [(iso_date, cheie, title)] from a year page (looken/lookfr)."""
    items = []
    pat = re.compile(
        r"<li>\s*(\d{2}-\d{2}-\d{4})\s*"
        rf'<a href="(index1\.php\?pg={look}&cheie=(\d+))"[^>]*>(.*?)</a>',
        re.S,
    )
    for m in pat.finditer(html_text):
        items.append(
            (ro.iso_date(m.group(1)), m.group(3), ro.clean_text(m.group(4)))
        )
    return items


def write_markdown(lang, year, iso, cheie, title, audio, audio_file, body):
    """Write one message to out/markdown/<lang>/<year>/. Mirrors the Romanian
    frontmatter, adding `lang` and pointing source_url at the correct look param."""
    look = LANGS[lang]["look"]
    d = os.path.join(OUT, lang, str(year))
    os.makedirs(d, exist_ok=True)
    slug = ro.slugify(title)
    path = os.path.join(d, f"{iso}--{slug}.md")
    fm = (
        "---\n"
        f'title: "{title.replace(chr(34), chr(39))}"\n'
        f"date: {iso}\n"
        f"year: {year}\n"
        f"lang: {lang}\n"
        f"source_url: {ro.BASE}index1.php?pg={look}&cheie={cheie}\n"
        f"cheie: {cheie}\n"
        f"audio: {audio}\n"
        f"audio_file: {audio_file}\n"
        "---\n\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(fm + body + "\n")
    return path


def audio_name(iso, lang):
    """Local audio filename: yy.mm.dd-<lang>.mp3 (lang suffix mirrors the
    source's <cheie>en/fr.mp3 and keeps EN/FR/RO audio from colliding)."""
    return ro.audio_filename(iso).replace(".mp3", f"-{lang}.mp3")


def process_year(lang, year, k, do_audio, failures):
    """Extract one year of a language to Markdown (+audio). Resilient: a failed
    document is logged and skipped. Returns (n_ok, n_fail)."""
    cfg = LANGS[lang]
    try:
        year_html = ro.fetch(
            f"{ro.BASE}index1.php?pg={cfg['get']}&k={k}",
            f"{lang}_year_k{k}.html",
        )
    except Exception as e:  # noqa: BLE001
        failures.append(("year", k, f"{lang}/{year}", str(e)))
        print(f"  ! {lang.upper()} {year} (k={k}) index failed: {e}")
        return 0, 1
    items = parse_year_index(year_html, cfg["look"])
    ok = fail = 0
    for iso, cheie, list_title in items:
        try:
            doc_html = ro.fetch(
                f"{ro.BASE}index1.php?pg={cfg['look']}&cheie={cheie}",
                f"{lang}_doc_{cheie}.html",
            )
            title, audio, body = ro.extract_document(doc_html)
            title = title or list_title
            audio_file = ""
            if audio and do_audio:
                name, _ = ro.download_audio(audio, year, audio_name(iso, lang))
                audio_file = name or ""
            elif audio:
                audio_file = audio_name(iso, lang)  # predict name (text pass)
            write_markdown(lang, year, iso, cheie, title, audio, audio_file, body)
            ok += 1
        except Exception as e:  # noqa: BLE001
            failures.append(("doc", cheie, f"{lang}/{year}", str(e)))
            print(f"  ! {lang.upper()} {year} cheie={cheie} failed: {e}")
            fail += 1
    tag = "audio+text" if do_audio else "text"
    print(f"  {lang.upper()} {year} (k={k}): {ok} ok, {fail} failed  [{tag}]")
    return ok, fail


def crawl(langs, do_audio):
    """Text pass (all langs), then optional audio pass. `extract_document`'s
    theme-link param is language-specific, so we point csni_extract.SUBCAP at the
    right dialect before each language's block; csni_extract.OUT_AUDIO is aimed at
    the per-language audio dir so the reused atomic downloader lands files there."""
    failures = []

    def run(do_audio_pass):
        tot_ok = tot_fail = 0
        for lang in langs:
            ro.SUBCAP = re.compile(LANGS[lang]["subcap"])
            ro.OUT_AUDIO = os.path.join(OUT_AUDIO, lang)
            years = year_map(lang)
            print(f"[{lang.upper()}] {len(years)} years "
                  f"({years[0][0]}–{years[-1][0]})")
            for year, k in years:
                ok, fail = process_year(lang, year, k, do_audio_pass, failures)
                tot_ok += ok
                tot_fail += fail
        return tot_ok, tot_fail

    print("=== PASS 1: text + Markdown (no audio) ===")
    t0 = time.time()
    tot_ok, tot_fail = run(do_audio_pass=False)
    print(f"\nTEXT PASS complete: {tot_ok} docs, {tot_fail} failed, "
          f"{time.time() - t0:.0f}s\n")

    if do_audio:
        print("=== PASS 2: downloading audio ===")
        run(do_audio_pass=True)
        print("\nAUDIO PASS complete.\n")
        n_mp3 = sum(
            len(files)
            for lang in langs
            for _, _, files in os.walk(os.path.join(OUT_AUDIO, lang))
        )
        os.makedirs(LOGS, exist_ok=True)
        with open(os.path.join(LOGS, "CRAWL_DONE_INTL.txt"), "w", encoding="utf-8") as f:
            f.write(
                f"done: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"langs: {','.join(langs)}\n"
                f"markdown_docs: {tot_ok}\n"
                f"audio_files: {n_mp3}\n"
                f"failures: {len(failures)}\n"
            )

    if failures:
        os.makedirs(LOGS, exist_ok=True)
        log_path = os.path.join(LOGS, "failures_intl.log")
        with open(log_path, "w", encoding="utf-8") as f:
            for kind, ident, where, err in failures:
                f.write(f"{kind}\t{ident}\t{where}\t{err}\n")
        print(f"{len(failures)} failures written to {log_path} "
              f"(re-run to retry — cache resumes automatically)")
    else:
        print("No failures.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="crawl every year of the selected language(s)")
    ap.add_argument("--lang", choices=["en", "fr", "both"], default="both",
                    help="which archive (default: both)")
    ap.add_argument("--no-audio", action="store_true", help="skip audio download")
    ap.add_argument("--k", help="single-year archive id (geten/getfr ?k=)")
    ap.add_argument("--year", type=int, help="single-year label (with --k)")
    args = ap.parse_args()

    langs = ["en", "fr"] if args.lang == "both" else [args.lang]

    if args.k:
        if args.lang == "both":
            ap.error("--k needs a single --lang en|fr")
        failures = []
        lang = langs[0]
        ro.SUBCAP = re.compile(LANGS[lang]["subcap"])
        ro.OUT_AUDIO = os.path.join(OUT_AUDIO, lang)
        process_year(lang, args.year or 0, args.k,
                     do_audio=not args.no_audio, failures=failures)
        return

    crawl(langs, do_audio=not args.no_audio)


if __name__ == "__main__":
    main()
