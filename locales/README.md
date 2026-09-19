# Adding a language

Strings ship with the program — the whole English catalogue is under 4 KB — so
a translation is a file and a pull request. Nothing is downloaded and nothing
can go missing.

## The strings

1. Copy `en.json` to `<code>.json`, where `<code>` is a BCP 47 tag: `fr`,
   `de`, `pt-BR`, `zh-Hans`. Lower-case language, upper-case region.
2. Translate the **values**. Never the keys.
3. Fill in `_meta`: the code, the name in that language, the name in English,
   and `direction` (`ltr` or `rtl`).
4. Leave anything you are unsure of out. A missing string falls back to
   English rather than appearing blank, so a partial translation is useful
   from the first line.

`{count}` and `{seconds}` are substituted in. Keep them, and put them where
the sentence needs them — word order is yours to choose.

`pt-BR` falls back to `pt` and then to `en`, so a Brazilian catalogue only
needs to carry what differs from Portuguese, if a `pt` exists.

## The tile artwork

Tiles are pictures with the words baked in, so they are built, not translated
in place. **Most languages should not have a set**, and that is not a
shortcoming:

With the Pillow shipped on Windows there is no text shaping — no raqm, no
harfbuzz, no fribidi. Latin, Cyrillic, Greek and CJK render correctly. Arabic
comes out unjoined and left-to-right, Hebrew reversed, Devanagari and Thai
with their marks in the wrong places. A wordless tile is correct in every
language; a wrongly-shaped one is worse than no words at all.

So: if your language is written in **Latin, Cyrillic, Greek, or CJK**, you can
build a set once your catalogue has a `tiles` section:

```bash
python3 scripts/make-tiles.py --lang fr
```

That writes `assets/tiles/fr/`. Look at every tile before committing it —
particularly that long names have not shrunk to the point of being unreadable.
`docs/tile-art.md` is the specification the pictures follow.

If your language is written in anything else, **stop at the strings**. The
interface will be in your language and the tiles will be the wordless set,
which is the right outcome.

## What the program does with this

`i18n.py` reads the machine's language, walks the fallback chain, and lays the
catalogue over English so nothing is ever blank. For artwork it looks for
`assets/tiles/<code>/`, then the shorter tag, then `assets/tiles/_wordless/`.
A set does not have to be complete: any tile you have not drawn comes from the
wordless set.
