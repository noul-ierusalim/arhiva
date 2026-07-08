#!/usr/bin/env python3
"""csni-migrate — extract messages from noul-ierusalim.ro to local Markdown.

Phase 1: crawl a year archive and write one Markdown file per message.
Stdlib only. Raw HTML is cached under cache/ so re-runs don't re-hit the server.

Usage:
    python3 csni_extract.py --k 86 --year 2026
"""
import argparse
import html
import os
import re
import time
import unicodedata
import urllib.request

BASE = "https://noul-ierusalim.ro/"
UA = "csni-migrate/0.1 (archive migration; contact bogdan@grozoiu.com)"
CACHE = "cache"
OUT = "out/markdown"
OUT_AUDIO = "out/audio"
DELAY = 0.5  # seconds between live requests (politeness)


def fetch(url, cache_name, retries=4):
    """Fetch url, caching raw bytes under cache/. Returns decoded HTML.

    Retries with backoff because the source site is unstable. Raises the last
    error only after exhausting retries, so callers can skip-and-continue.
    """
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, cache_name)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, encoding="utf-8") as f:
            return f.read()
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            raw = urllib.request.urlopen(req, timeout=30).read().decode(
                "utf-8", "replace"
            )
            with open(path, "w", encoding="utf-8") as f:
                f.write(raw)
            time.sleep(DELAY)
            return raw
        except Exception as e:  # noqa: BLE001 - unstable source, keep trying
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def audio_filename(iso):
    """ISO date 2026-01-04 -> local audio name 26.01.04.mp3."""
    y, m, d = iso.split("-")
    return f"{y[2:]}.{m}.{d}.mp3"


def download_audio(url, year, name):
    """Download url to out/audio/<year>/<name>. Skip if already present.

    Returns (local_name, bytes) or (None, 0) on failure.
    """
    d = os.path.join(OUT_AUDIO, str(year))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, name)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return name, os.path.getsize(path)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        data = urllib.request.urlopen(req, timeout=120).read()
    except Exception as e:  # noqa: BLE001 - report and continue the run
        print(f"    ! audio download failed: {url} ({e})")
        return None, 0
    # Atomic write: a killed process can never leave a half file that the
    # resume logic would mistake for a complete download.
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    time.sleep(DELAY)
    return name, len(data)


def strip_tags(s):
    # Consume quoted attribute values wholesale so a `>` *inside* an attribute
    # (e.g. an <embed> whose flashvars carries a literal `<br>…</br>`, cheie=1133)
    # doesn't end the tag early and leak the attribute tail as visible text.
    return re.sub(r"""<(?:[^>"']|"[^"]*"|'[^']*')*>""", "", s)


def clean_text(s):
    """Strip tags, decode entities, collapse whitespace — for titles."""
    return re.sub(r"\s+", " ", html.unescape(strip_tags(s))).strip()


def slugify(title):
    t = unicodedata.normalize("NFKD", title)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:70] or "fara-titlu"


def iso_date(ddmmyyyy):
    d, m, y = ddmmyyyy.split("-")
    return f"{y}-{m}-{d}"


def parse_year_index(html_text):
    """Return list of (iso_date, cheie, title) from a year page."""
    items = []
    pat = re.compile(
        r"<li>\s*(\d{2}-\d{2}-\d{4})\s*"
        r'<a href="(index1\.php\?pg=look&cheie=(\d+))"[^>]*>(.*?)</a>',
        re.S,
    )
    for m in pat.finditer(html_text):
        items.append((iso_date(m.group(1)), m.group(3), clean_text(m.group(4))))
    return items


def extract_document(html_text):
    """Return (title, audio_url, markdown_body) from a document page."""
    m = re.search(r"<h1\b[^>]*>(.*?)</h1>", html_text, re.S)
    title = clean_text(m.group(1)) if m else ""

    am = re.search(r'href="([^"]*/audio/[^"]+\.mp3)"', html_text)
    audio = html.unescape(am.group(1)) if am else ""

    # Body: content of the <font size="4"> wrapper that follows the <h1>,
    # stopping at the footer, which every page marks with the right-aligned
    # date div (`<div align="right">DD-MM-YYYY…</div>`) just before the niro
    # logo. We must NOT cut at the first <center>: some messages are split into
    # parts ("Partea a doua") whose sub-headings are centered mid-document, so
    # a <center> can appear well inside the real body (e.g. cheie=1130).
    start = html_text.find('<font size="4"')
    body_html = ""
    if start != -1:
        start = html_text.index(">", start) + 1
        foot = re.search(r'<div align="right"', html_text[start:])
        end = start + foot.start() if foot else html_text.find("</font>", start)
        body_html = html_text[start:end if end != -1 else None]

    return title, audio, html_to_md(body_html)


# Anchor open- and close-tags. The open-tag matcher consumes quoted attribute
# values wholesale, so `>` chars inside an onMouseOver tooltip don't end it
# early.
A_TOKEN = re.compile(
    r"""<a\b(?:[^>"']|"[^"]*"|'[^']*')*>|</a\s*>""", re.S
)
SUBCAP = re.compile(r"pg=subcapitole&cap=(\d+)&sub=(\d+)")


def _resolve_anchors(body_html):
    """Linearize anchor tags into [legatura_la_teme] shortcodes.

    The source occasionally *nests* <a> tags (invalid HTML): a theme link that
    opens, then a second theme link before the first has closed (e.g. cheie=221,
    where one message points at two different chapters). Browsers auto-close the
    first anchor when a new <a> begins, so we do the same — otherwise the inner
    link's open-tag is swallowed into the outer link's text and the second theme
    reference is lost. Each theme link therefore spans from its own <a> up to the
    next <a> or </a>, whichever comes first, and may cross <p> boundaries.
    """
    out, pos, open_theme = [], 0, False
    for m in A_TOKEN.finditer(body_html):
        out.append(body_html[pos:m.start()])
        pos = m.end()
        tok = m.group(0)
        if open_theme:
            # A new <a> auto-closes the current theme link; so does any </a>.
            out.append("[/legatura_la_teme]")
            open_theme = False
        if not tok.startswith("</a"):  # opening <a …>
            sub = SUBCAP.search(tok)
            if sub:
                # A "theme link": open a shortcode; its (possibly multi-
                # paragraph) content round-trips to the new site's shortcode.
                out.append(
                    f'[legatura_la_teme id_capitol="{sub.group(1)}" '
                    f'id_subcapitol="{sub.group(2)}"]'
                )
                open_theme = True
            # Other links (audio, footer logo, etc.): drop the tag, keep text.
    out.append(body_html[pos:])
    if open_theme:
        out.append("[/legatura_la_teme]")
    return "".join(out)


# A run of whitespace and/or HTML tags anchored at one edge of a string.
_EDGE = re.compile(r"^(?:\s|<[^>]+>)+|(?:\s|<[^>]+>)+$")


def _emphasize(marker):
    """Wrap the visible inner text in `marker`, hoisting edge whitespace out.

    Edge whitespace must sit *outside* the markers or CommonMark won't parse
    them as emphasis. The inner may also carry HTML tags at its edges — e.g. a
    color <span> that closes right before </i> (`…omul? </span></i>`). Those
    tags are stripped later, so leaving them inside the markers would expose a
    space touching the marker and produce broken emphasis (`*…omul? *`). So we
    judge edge whitespace from the tag-stripped text and wrap only the core,
    with any edge whitespace/tags moved outside.
    """
    def repl(m):
        inner = m.group(1)
        visible = strip_tags(inner)
        if not visible.strip():
            return inner  # nothing visible to emphasize
        core = _EDGE.sub("", inner)
        lead = " " if visible[:1].isspace() else ""
        trail = " " if visible[-1:].isspace() else ""
        return f"{lead}{marker}{core}{marker}{trail}"
    return repl


# A <p> boundary: used both to redistribute emphasis across paragraphs and to
# split the body into paragraphs.
P_BOUNDARY = re.compile(r"</?p\b[^>]*>")


def _redistribute_emphasis(body_html):
    """Re-emit emphasis inside every paragraph it spans, before splitting.

    The source routinely opens an <i>/<em> (or <b>) at the tail of one <p> and
    closes it inside a later one, e.g. `...credeţi? <i></p><p>— Da, Doamne! </i>`
    (cheie=501). A browser keeps the run open across the boundary, so the whole
    span renders italic — but html_to_md() converts emphasis per paragraph, so a
    run cut by a </p><p> boundary matches in neither slice and loses its markers.
    Here, like _resolve_anchors, we work on the whole body first: each emphasis
    run that crosses a boundary is rewritten into one self-contained <tag>…</tag>
    per paragraph slice (whitespace-only slices get none), so the per-paragraph
    pass then converts them faithfully. Runs already within one paragraph are
    left untouched.
    """
    def redistribute(open_tag, close_tag):
        def repl(m):
            inner = m.group(1)
            if not P_BOUNDARY.search(inner):
                return m.group(0)  # contained in one paragraph — leave as-is
            pieces = P_BOUNDARY.split(inner)
            delims = P_BOUNDARY.findall(inner)
            out = []
            for i, seg in enumerate(pieces):
                out.append(f"{open_tag}{seg}{close_tag}" if seg.strip() else seg)
                if i < len(delims):
                    out.append(delims[i])
            return "".join(out)
        return repl

    for tag in ("i", "em", "b", "strong"):
        # re.I because the source mixes tag case, e.g. <i>…</I> (cheie=1217):
        # a case-sensitive match runs past the real close to the next same-case
        # one, swallowing text and mangling the markers.
        body_html = re.sub(
            rf"<{tag}\b[^>]*>(.*?)</{tag}>",
            redistribute(f"<{tag}>", f"</{tag}>"),
            body_html,
            flags=re.S | re.I,
        )
    return body_html


_THEME_CLOSE = "[/legatura_la_teme]"


def _tighten_theme_shortcodes(paras):
    """Make each theme-link shortcode hug the text it wraps at paragraph edges.

    A shortcode must open flush against its first word and close flush against
    its last word, but the source scatters whitespace and block tags (</p>,
    <br>, </span>) between the <a>/</a> and the text. Intra-paragraph slack is
    squeezed by regex in the paragraph loop; here we handle the shortcode left
    marooned at a paragraph boundary by a </p>: a close that *begins* a
    paragraph belongs to the end of the previous one, and an open that *ends* a
    paragraph belongs to the start of the next one. We move only the shortcode
    token across the break, never merging the paragraphs on its far side.
    """
    # A close at the head of a paragraph -> tail of the previous paragraph.
    joined = []
    for p in paras:
        if p.startswith(_THEME_CLOSE) and joined:
            joined[-1] += _THEME_CLOSE
            rest = p[len(_THEME_CLOSE):].lstrip()
            if rest:
                joined.append(rest)
        else:
            joined.append(p)
    # An open at the tail of a paragraph -> head of the next paragraph. Anchor
    # at the end: a paragraph may hold earlier shortcodes (e.g. a preceding
    # close, `…word.[/legatura_la_teme][legatura_la_teme …]`), so only the
    # trailing open — the one orphaned from its text by a </p> — is moved.
    out = []
    for i, p in enumerate(joined):
        m = re.search(r"\[legatura_la_teme[^\]]*\]$", p)
        if m and i + 1 < len(joined):
            head = p[: m.start()].rstrip()
            if head:
                out.append(head)
            joined[i + 1] = m.group(0) + joined[i + 1]
        else:
            out.append(p)
    return out


def _resolve_i_typos(body_html):
    """Repair the source's `<?i>` typo (an invalid tag standing in for an
    italic delimiter). Its direction isn't fixed: after italic text it means
    `</i>` (cheie=1082, 1563), before it `<i>` (en/707, fr/174). Resolve each by
    the running <i> nesting depth — inside an open italic it closes, else opens.
    """
    depth = 0

    def repl(m):
        nonlocal depth
        tok = m.group(0)
        if tok.replace(" ", "").lower() == "<?i>":
            if depth > 0:
                depth -= 1
                return "</i>"
            depth += 1
            return "<i>"
        if tok.lstrip("<").lstrip().startswith("/"):
            depth = max(0, depth - 1)
        else:
            depth += 1
        return tok

    return re.sub(r"<\?i>|</?\s*i\b[^>]*>", repl, body_html, flags=re.I)


_EMPH_TAG = re.compile(r"<(/?)\s*(i|em)\b[^>]*>", re.I)


def _balance_italics(body_html):
    """Close an italic run the source leaves open, as a browser would.

    An unclosed <i>/<em> keeps rendering to the end of its block: at cheie=268
    an <i> opens near the tail ("şi cine a luat…") and never closes before the
    footer, so the whole remainder is italic on the live site. Our emphasis
    passes require a matching close, so an orphaned open is otherwise stripped
    and its text silently loses the styling. Mirror the browser by appending the
    missing close(s) at the body end. A stray close with no open is left as-is —
    it matches nothing and is stripped later, exactly as a browser ignores it.

    Scoped to italics on purpose. Bold is different: the only <b> runs here are
    editorial scripture citations (`<b>(Apoc: 5/8)</b>`), and the unclosed ones
    are close-tag typos (`<b>(Thessalonians: 3/13)<b>`, cheie=786) whose intended
    close is mid-text — appending </b> at the body end would wrongly embolden the
    whole tail. Run *after* _resolve_anchors so <b>/<i> tucked inside an anchor's
    onMouseOver ddrivetip tooltip are already gone and never counted.
    """
    depth = 0
    for m in _EMPH_TAG.finditer(body_html):
        depth += -1 if m.group(1) else 1
    return body_html + "</i>" * depth if depth > 0 else body_html


def html_to_md(body_html):
    # Repair a tag whose closing `>` was mistyped as `.`: `<i.` opening an italic
    # quote (cheie=379) and `</span.` (cheie=1099). Do this first, before any
    # tag-based pass reads them — a malformed `<i.«text»` would otherwise be
    # swallowed (deleting the quote) or mis-nested. Only a tag name flush against
    # a `.` matches, so real text and attributed tags are untouched.
    body_html = re.sub(r"(</?[a-zA-Z][a-zA-Z0-9]*)\.", r"\1>", body_html)
    body_html = _resolve_i_typos(body_html)
    # Resolve anchors first, on the whole body: a subcapitole link can span
    # several <p> blocks, so it must be handled before paragraph splitting.
    body_html = _resolve_anchors(body_html)
    # A browser keeps an unclosed <i> italic to the end of its block; the source
    # sometimes omits the close (cheie=268). Restore it now that anchor tooltip
    # markup (which carries its own <b>/<i>) has been stripped.
    body_html = _balance_italics(body_html)
    # Drop empty theme links: the source occasionally closes and immediately
    # reopens an <a> around nothing (e.g. cheie=1346, `…amin. </a><a …></a>`),
    # yielding a shortcode pair wrapping no text. It references nothing, renders
    # nothing, and — left in — would shield an adjacent space from stripping.
    body_html = re.sub(
        r"\[legatura_la_teme[^\]]*\][ \t]*\[/legatura_la_teme\]", "", body_html
    )
    # Make each shortcode hug the word it borders: swap it leftward/rightward
    # past adjacent spaces so a separator the source tucked *inside* the <a>…</a>
    # (e.g. `voi da. </a>Iată`) lands *outside* the shortcode. Doing this now,
    # before emphasis and splitting, lets the existing machinery treat it as an
    # ordinary inter-word space — hoisting it out of an italic or stripping it
    # at a paragraph edge — instead of leaving it stranded against the token.
    # Only swap when the space follows real text, not a tag boundary (`>`): a
    # space after an opening `<i>` is that italic's lead space, which _emphasize
    # must see to hug its marker to the word (cheie=143); such tag-adjacent
    # spaces are handled after tag-stripping by the per-paragraph swap below.
    body_html = re.sub(r"([^>\s])([ \t]+)(\[/legatura_la_teme\])", r"\1\3\2", body_html)
    body_html = re.sub(r"(\[legatura_la_teme[^\]]*\])([ \t]+)([^<\s])", r"\2\1\3", body_html)
    # Emphasis can span <p> boundaries too, so redistribute it before splitting.
    body_html = _redistribute_emphasis(body_html)

    # Split into paragraphs on <p> boundaries.
    parts = P_BOUNDARY.split(body_html)
    paras = []
    for part in parts:
        s = part
        s = re.sub(
            r"<(?:i|em)\b[^>]*>(.*?)</(?:i|em)>", _emphasize("*"), s, flags=re.S | re.I
        )
        s = re.sub(
            r"<(?:b|strong)\b[^>]*>(.*?)</(?:b|strong)>",
            _emphasize("**"),
            s,
            flags=re.S | re.I,
        )
        s = re.sub(r"<br\s*/?>", "\n", s)
        s = strip_tags(s)
        s = html.unescape(s)
        # Re-hug shortcodes: the emphasis pass hoists an italic's trailing space
        # to the outside, which can land it against a shortcode token (e.g.
        # `cer.* [/close]`), and stripping a color <span> can expose a space too.
        # Swap the space back outside the token so it collapses/strips like any
        # other, leaving the shortcode flush with its word.
        s = re.sub(r"([ \t]+)(\[/legatura_la_teme\])", r"\2\1", s)
        s = re.sub(r"(\[legatura_la_teme[^\]]*\])([ \t]+)", r"\2\1", s)
        s = re.sub(r"[ \t]+", " ", s).strip()
        # A paragraph that is only emphasis markers wrapped around a lone
        # shortcode (e.g. `*[/legatura_la_teme]*`, from an <a> the source
        # stranded inside an <i>) is degenerate — the emphasis wraps no text.
        # Drop the markers, leaving the bare shortcode for the edge pass to
        # reattach to its neighbouring paragraph.
        if re.fullmatch(r"\*{0,2}\s*\[/?legatura_la_teme[^\]]*\]\s*\*{0,2}", s):
            s = re.sub(r"\*+", "", s).strip()
        if s:
            paras.append(s)
    return "\n\n".join(_tighten_theme_shortcodes(paras))


def write_markdown(year, iso, cheie, title, audio, audio_file, body):
    d = os.path.join(OUT, str(year))
    os.makedirs(d, exist_ok=True)
    slug = slugify(title)
    path = os.path.join(d, f"{iso}--{slug}.md")
    fm = (
        "---\n"
        f'title: "{title.replace(chr(34), chr(39))}"\n'
        f"date: {iso}\n"
        f"year: {year}\n"
        f"source_url: {BASE}index1.php?pg=look&cheie={cheie}\n"
        f"cheie: {cheie}\n"
        f"audio: {audio}\n"
        f"audio_file: {audio_file}\n"
        "---\n\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(fm + body + "\n")
    return path


def year_map():
    """Return [(year:int, k:str)] for every year link on arhiva.html, sorted."""
    arh = fetch(f"{BASE}arhiva.html", "arhiva.html")
    pairs = re.findall(r"pg=get&k=(\d+)\"[^>]*?>\s*(\d{4})", arh)
    seen = {}
    for k, y in pairs:
        seen.setdefault(int(y), k)  # first k wins if a year repeats
    return sorted(seen.items())


def process_year(year, k, do_audio, failures):
    """Extract one year to Markdown (always) and audio (if do_audio).

    Resilient: a failed document is logged to `failures` and skipped so the
    run continues. Returns (n_ok, n_fail).
    """
    try:
        year_html = fetch(f"{BASE}index1.php?pg=get&k={k}", f"year_k{k}.html")
    except Exception as e:  # noqa: BLE001
        failures.append(("year", k, year, str(e)))
        print(f"  ! YEAR {year} (k={k}) index failed: {e}")
        return 0, 1
    items = parse_year_index(year_html)
    ok = fail = 0
    for iso, cheie, list_title in items:
        try:
            doc_html = fetch(
                f"{BASE}index1.php?pg=look&cheie={cheie}", f"doc_{cheie}.html"
            )
            title, audio, body = extract_document(doc_html)
            title = title or list_title
            audio_file = ""
            if audio and do_audio:
                name, _ = download_audio(audio, year, audio_filename(iso))
                audio_file = name or ""
            elif audio:
                # text pass: predict the local name without downloading yet
                audio_file = audio_filename(iso)
            write_markdown(year, iso, cheie, title, audio, audio_file, body)
            ok += 1
        except Exception as e:  # noqa: BLE001
            failures.append(("doc", cheie, year, str(e)))
            print(f"  ! {year} cheie={cheie} failed: {e}")
            fail += 1
    tag = "audio+text" if do_audio else "text"
    print(f"  {year} (k={k}): {ok} ok, {fail} failed  [{tag}]")
    return ok, fail


def crawl_all(do_audio):
    years = year_map()
    print(f"Archive: {len(years)} years ({years[0][0]}–{years[-1][0]})\n")
    failures = []

    print("=== PASS 1: securing all text + Markdown (no audio) ===")
    t0 = time.time()
    tot_ok = tot_fail = 0
    for year, k in years:
        ok, fail = process_year(year, k, do_audio=False, failures=failures)
        tot_ok += ok
        tot_fail += fail
    print(f"\nTEXT PASS complete: {tot_ok} docs, {tot_fail} failed, "
          f"{time.time() - t0:.0f}s\n")

    if do_audio:
        print("=== PASS 2: downloading audio ===")
        a_ok = a_fail = 0
        for year, k in years:
            ok, fail = process_year(year, k, do_audio=True, failures=failures)
            a_ok += ok
            a_fail += fail
        print(f"\nAUDIO PASS complete.\n")

        # Discoverable completion sentinel (survives a dropped session).
        n_mp3 = sum(len(files) for _, _, files in os.walk(OUT_AUDIO))
        with open("CRAWL_DONE.txt", "w", encoding="utf-8") as f:
            f.write(
                f"done: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"years: {len(years)}\n"
                f"markdown_docs: {tot_ok}\n"
                f"audio_files: {n_mp3}\n"
                f"failures: {len(failures)}\n"
            )

    if failures:
        with open("failures.log", "w", encoding="utf-8") as f:
            for kind, ident, year, err in failures:
                f.write(f"{kind}\t{ident}\t{year}\t{err}\n")
        print(f"{len(failures)} failures written to failures.log "
              f"(re-run to retry — cache resumes automatically)")
    else:
        print("No failures.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="crawl every year 1955–now")
    ap.add_argument("--no-audio", action="store_true", help="skip audio download")
    ap.add_argument("--k", help="single-year archive id (arhiva.html ?k=)")
    ap.add_argument("--year", type=int, help="single-year label")
    args = ap.parse_args()

    if args.all:
        crawl_all(do_audio=not args.no_audio)
        return

    if not (args.k and args.year):
        ap.error("provide --all, or both --k and --year")
    failures = []
    process_year(args.year, args.k, do_audio=not args.no_audio, failures=failures)


if __name__ == "__main__":
    main()
