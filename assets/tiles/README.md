# Tile artwork

`_wordless/` has no text and is used for every language without a set of its
own. It is the default, not the exception — see `../../locales/README.md` for
why most languages should stay wordless.

`en/` is the English set, and the template for any other.

Both are generated: `python3 scripts/make-tiles.py [--lang <code>]`. The
specification, the provenance of every mark, and the licences are in
`docs/tile-art.md`. The source marks are in `../marks/`, vendored so that a
rebuild needs no network.

Nothing here is fetched at run time. Artwork ships with the program.
