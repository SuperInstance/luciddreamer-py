# Recovery note

This repository was **recovered from the published npm tarball**
`@superinstance/luciddreamer@0.1.1` on 2026-10-18.

## Why it exists

The package's `repository` field pointed at `SuperInstance/luciddreamer` —
which is **luciddreamer.ai, a marketing/demo site** holding three files
(`.wrangler/`, `README.md`, `index.html`). The 3,464 lines of Python that
the npm package actually ships existed in **no repository on the account**.

The tarball was therefore the only copy, and npm garbage-collects packages
nothing depends on — taking the tarball with it. This repository is that
copy, safe.

## What the tarball carried

```
luciddreamer/            10 modules, 3,464 lines, py.typed
  __init__.py  bathymetry.py  chart.py  cli.py  cocapn.py
  compiler.py   mesh.py       router.py simulators.py  tiles.py
  training.py
docs/                    8 documents
index.js                 the Node shim
README.md  CHANGELOG.md  LICENSE
```

## Three defects found while recovering it, and fixed here

These were found by writing the test suite, and each is covered by a
regression test plus a mutation in `sabotage.py`.

### 1. A save/load round trip silently disarmed the store

`Tile.to_dict()` wrote only the base fields, and `Tile.from_dict()`
returned a base `Tile` regardless of the tile's type. So a `CommandTile`
came back as a `Tile` and **lost its `regex_pattern`** — the field that
compiled matching is built on.

The export/import path reported the right number of tiles and the right
ids the whole time. The operation was green and the payload was worse.

*Fixed:* `to_dict()` carries the subclass's own fields; `from_dict()`
dispatches to the class that owns the tile type; tuple fields are
restored as tuples.

### 2. One malformed tile regex killed the entire compile pass

`CompiledCommand` compiles its pattern eagerly, so a bad pattern raised
out of `RigidFinder.try_compile()` and out of `compile_all()`. Because
`compile_all()` iterates the store, **every other tile in the store went
uncompiled because of one bad one.**

*Fixed:* `try_compile()` catches `re.error` and skips that tile.

### 3. `_auto_pattern()`'s two substitutions were dead code

It escaped the text first, then searched the escaped string for a literal
`\d` and a literal `e\s`. Neither is ever there: `re.escape` does not
escape digits, and it escapes a space as `\ `, not `\s`.

So every auto-generated pattern was a plain literal match, and the `n`
named group — which the source plainly intended to carry the parsed
number — could never appear in a match result.

*Fixed:* digits become a named group (the first is `n`, later ones are
numbered so two groups cannot collide); a word ending in `e` may
optionally take an `s`.

## A fourth, found by reading rather than by running

`TileStore.add()` appended the tile id to the type index unconditionally,
so adding the same tile twice indexed it twice and `find_by_type()`
returned the same tile twice while `len(store)` said 1. A consumer
counting tiles by type double-counted them.

*Fixed:* the type index holds each id once.

## The suite

```
python -m unittest discover -s tests    # 76 tests
python sabotage.py                      # 13 mutations, all caught
```

`sabotage.py` is the negative control: it breaks one real behaviour at a
time in a throwaway copy of the source and requires the suite to go red
for every one. **A green suite proves nothing unless it can go red.**
