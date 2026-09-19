# Releasing

## The version

`version.py` holds two things and works out the rest:

    RELEASE = "0.1.0"    # what the next release will be called
    CHANNEL = "dev"      # "" once it is one

The build number is `git rev-list --count HEAD`. Nothing to maintain, it never
goes backwards, and it answers the only question a build number is asked: which
one is newer. So a tag and what the program prints are the same thing by
construction, rather than by remembering to keep them in step.

| | reads |
|---|---|
| A development build | `dev 0.1.0.57`, or `0.1.0.dev57` in PEP 440 |
| With uncommitted changes | `dev 0.1.0.57+` -- it is not the commit it claims to be |
| A release | `0.1.0`, both ways |

`.devN` sorts *below* the release it precedes, which is the point of using it.

An installed copy has no git, so `--stamp-build` writes the number into the
source tree and the installer carries it across. Stamping will not replace a
known number with an unknown one: installing from a tarball on a machine
without git would otherwise report build 0.

## How big a bump

**Rolling a release bumps the major or minor version, depending on the scope of
what is in it.** Claude recommends which and says why; the human decides before
anything is tagged.

Patch level is not covered by that rule. If a release looks like it warrants
only a patch, ask rather than assume.

## Cutting a development build

Every build is one of these until there is a release. Nothing to bump -- the
number is already whatever the commit count reached.

    git tag -a v0.1.0.dev57 -m "dev 0.1.0.57"
    git push origin v0.1.0.dev57
    gh release create v0.1.0.dev57 --title "dev 0.1.0.57" \
        --notes-file notes.md --prerelease

Releases work on a private repository; they are visible to you and to
collaborators, and stay as they are when the repository goes public.

## Cutting a release

0. **Check the tile artwork.** Logos change -- Fedora's in 2021, Ubuntu's in
   2022, Windows' in 2021 -- and a tile carrying last decade's mark looks like
   abandonware. `docs/tile-art.md` lists every mark we ship and where it came
   from; confirm each is still current, and rebuild with
   `scripts/make-tiles.py` if any has moved on.
1. Agree the bump, by the rule above.
2. Set `RELEASE` to the new number and `CHANNEL = ""` in `version.py`. The word
   "dev" and the build number both disappear from everything that shows a
   version, because they all come from there.
3. Commit, tag `v<RELEASE>`, and write notes that say what changed and what is
   still not done.
4. Set `CHANNEL = "dev"` again and bump `RELEASE` to whatever comes next, so
   builds after the release describe themselves as heading somewhere rather
   than claiming to be the release that just went out.

## One thing that will need settling

The build number is unambiguous because there is a single line of history. Two
branches at the same depth produce the same count for different commits, so the
day development moves to its own branch, the build number has to carry the
branch or stop being the commit count. See `backlog.md`.
