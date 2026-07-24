#!/usr/bin/env python3
"""
dump_to_sqlite.py — load the WordPress tables we care about out of a mysqldump
into a local SQLite file, so Phase 2 can be built/queried without a MySQL server.

Robust against mysqldump quirks: extended INSERTs (many tuples per statement),
backslash escapes (\\', \\n, \\\\, ...), and literal newlines inside string
values. Parses char-by-char, not line-by-line.

Usage:  python3 db/dump_to_sqlite.py dump_dcsannmy_WPLTV.sql   # writes db/wp.sqlite
"""
import os
import re
import sqlite3
import sys

# The SQLite DB lives beside this script, in db/. Anchor to __file__ so the
# default output is db/wp.sqlite regardless of the working directory.
DB_DIR = os.path.dirname(os.path.abspath(__file__))

# Tables to import (without prefix). Prefix is auto-detected.
WANT = {
    "posts", "postmeta",
    "terms", "term_taxonomy", "term_relationships", "termmeta",
    "yoast_indexable", "options",
}


def detect_prefix(sql: str) -> str:
    m = re.search(r"CREATE TABLE `([A-Za-z0-9_]*?)posts`", sql)
    if not m:
        sys.exit("Could not detect table prefix (no *posts table).")
    return m.group(1)


def parse_columns(sql: str, table: str):
    """Column names, in order, from a CREATE TABLE block."""
    start = sql.index(f"CREATE TABLE `{table}`")
    open_paren = sql.index("(", start)
    # walk to matching close paren
    depth, i = 0, open_paren
    while i < len(sql):
        if sql[i] == "(":
            depth += 1
        elif sql[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    body = sql[open_paren + 1:i]
    cols = []
    for line in body.splitlines():
        line = line.strip()
        m = re.match(r"`([^`]+)`\s", line)
        if m:  # a column def starts with `name` <type>; keys start with KEY/PRIMARY/etc.
            cols.append(m.group(1))
    return cols


def iter_values(sql: str, table: str):
    """Yield each row (list of Python values) from all INSERT INTO `table`.

    Handles the phpMyAdmin form:
        INSERT INTO `t` (`c1`, `c2`, ...) VALUES\n(...),\n(...);
    i.e. an optional column list, then VALUES, then the tuples.
    """
    start_re = re.compile(r"INSERT INTO `" + re.escape(table) + r"`\s*(\([^)]*\))?\s*VALUES")
    pos = 0
    n = len(sql)
    while True:
        m = start_re.search(sql, pos)
        if m is None:
            return
        i = m.end()
        # parse tuples until the terminating ';'
        while i < n:
            # skip whitespace/commas between tuples
            while i < n and sql[i] in " \t\r\n,":
                i += 1
            if i < n and sql[i] == ";":
                i += 1
                break
            if sql[i] != "(":
                break
            row, i = _parse_tuple(sql, i)
            yield row
        pos = i


def _parse_tuple(sql: str, i: int):
    """Parse one (v,v,...) starting at '(' -> (list, index after ')')."""
    assert sql[i] == "("
    i += 1
    values = []
    n = len(sql)
    while i < n:
        c = sql[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == ")":
            i += 1
            return values, i
        if c == ",":
            i += 1
            continue
        if c == "'":
            val, i = _parse_string(sql, i)
            values.append(val)
        else:
            # unquoted token: number, NULL, or keyword up to , or )
            j = i
            while j < n and sql[j] not in ",)":
                j += 1
            tok = sql[i:j].strip()
            values.append(None if tok == "NULL" else tok)
            i = j
    raise ValueError("Unterminated tuple")


_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "b": "\b", "Z": "\x1a"}


def _parse_string(sql: str, i: int):
    """Parse a single-quoted string starting at the opening quote."""
    assert sql[i] == "'"
    i += 1
    out = []
    n = len(sql)
    while i < n:
        c = sql[i]
        if c == "\\":
            nxt = sql[i + 1]
            out.append(_ESCAPES.get(nxt, nxt))
            i += 2
        elif c == "'":
            # doubled '' -> literal ' ; otherwise end of string
            if i + 1 < n and sql[i + 1] == "'":
                out.append("'")
                i += 2
            else:
                return "".join(out), i + 1
        else:
            out.append(c)
            i += 1
    raise ValueError("Unterminated string")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "dump_dcsannmy_WPLTV.sql"
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(DB_DIR, "wp.sqlite")

    with open(src, "r", encoding="utf-8", errors="replace") as f:
        sql = f.read()

    prefix = detect_prefix(sql)
    print(f"prefix: {prefix}")

    con = sqlite3.connect(dst)
    con.execute("PRAGMA journal_mode=OFF")
    cur = con.cursor()

    for short in sorted(WANT):
        table = f"{prefix}{short}"
        if f"CREATE TABLE `{table}`" not in sql:
            print(f"  skip {short}: not in dump")
            continue
        cols = parse_columns(sql, table)
        cur.execute(f'DROP TABLE IF EXISTS "{short}"')
        col_defs = ", ".join(f'"{c}"' for c in cols)
        cur.execute(f'CREATE TABLE "{short}" ({col_defs})')
        placeholders = ",".join("?" * len(cols))
        rows = list(iter_values(sql, table))
        # guard: row width must match column count
        good = [r for r in rows if len(r) == len(cols)]
        if len(good) != len(rows):
            print(f"  WARN {short}: {len(rows)-len(good)} rows with wrong arity dropped")
        cur.executemany(f'INSERT INTO "{short}" VALUES ({placeholders})', good)
        print(f"  {short}: {len(good)} rows, {len(cols)} cols")

    con.commit()
    con.close()
    print(f"wrote {dst}")


if __name__ == "__main__":
    main()
