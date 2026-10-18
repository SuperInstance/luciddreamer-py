"""Negative control: prove this test suite can fail.

A green suite proves nothing unless it CAN go red.  Each mutation below
breaks one real behaviour in the source, and the suite MUST fail for
each one.  If a mutation passes, the suite is not guarding that
behaviour and the mutation is reported as a SURVIVOR.

Run:  python3 sabotage.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

MUTATIONS = [
    ("confidence is no longer capped at 1.0",
     "luciddreamer/tiles.py",
     "self.confidence = min(1.0, self.confidence + 0.02)",
     "self.confidence = self.confidence + 0.02"),

    ("confidence is no longer floored at 0.0",
     "luciddreamer/tiles.py",
     "self.confidence = max(0.0, self.confidence - 0.1)",
     "self.confidence = self.confidence - 0.1"),

    ("the tile id is no longer content-derived",
     "luciddreamer/tiles.py",
     'content = f"{self.tile_type.value}:{self.input_pattern}:{self.output_action}"',
     'content = f"{self.input_pattern}"'),

    ("the confidence classes collapse into one",
     "luciddreamer/tiles.py",
     "if self.confidence >= 0.90:",
     "if self.confidence >= 0.0:"),

    ("the type index double-counts again",
     "luciddreamer/tiles.py",
     "            if tid not in ids:\n                ids.append(tid)",
     "            ids.append(tid)"),

    ("to_dict stops carrying the subclass fields",
     "luciddreamer/tiles.py",
     "        for f in dataclasses.fields(self):",
     "        for f in []:"),

    ("from_dict stops dispatching to the subclass",
     "luciddreamer/tiles.py",
     "        target = _TILE_CLASSES.get(tile_type)",
     "        target = None"),

    ("the compiler's confidence threshold is removed",
     "luciddreamer/compiler.py",
     "if tile.confidence < self.COMPILE_THRESHOLD:",
     "if tile.confidence < 0.0:"),

    ("the compiler's minimum-sample gate is removed",
     "luciddreamer/compiler.py",
     "if tile.times_used < self.MIN_SAMPLES:",
     "if tile.times_used < 0:"),

    ("a malformed tile regex is fatal again",
     "luciddreamer/compiler.py",
     "        except re.error:",
     "        except ZeroDivisionError:"),

    ("the auto pattern stops making digits a named group",
     "luciddreamer/compiler.py",
     "pattern = re.sub(r'(?<!\\\\)\\d+', _named, pattern)",
     "pattern = pattern"),

    ("the router's negative-constraint pass is removed",
     "luciddreamer/router.py",
     "if tile.tile_type == TileType.NEGATIVE:",
     "if False:"),

    ("the router's ambiguous band collapses",
     "luciddreamer/router.py",
     "elif best.confidence >= 0.5:",
     "elif best.confidence >= 0.0:"),
]


def run_suite(root):
    env = dict(os.environ)
    env["PYTHONPATH"] = root
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=root, env=env, capture_output=True, text=True, timeout=180,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main():
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "pkg")
        shutil.copytree(HERE, work, ignore=shutil.ignore_patterns(
            "__pycache__", ".git", "*.pyc", "sabotage.py"))
        baseline_code, baseline_out = run_suite(work)
        if baseline_code != 0:
            print("  BASELINE IS RED -- the suite does not pass on the "
                  "unmutated source, so it proves nothing.")
            print(baseline_out[-2500:])
            return 1
        print("  baseline: suite passes on the unmutated source")

        survivors = []
        for name, path, old, new in MUTATIONS:
            target = os.path.join(work, path)
            with open(target, encoding="utf-8") as fh:
                original = fh.read()
            if old not in original:
                print(f"  SKIP  {name}: the anchor text is not in {path}")
                survivors.append((name, "ANCHOR MISSING"))
                continue
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(original.replace(old, new, 1))
            try:
                code, out = run_suite(work)
            finally:
                with open(target, "w", encoding="utf-8") as fh:
                    fh.write(original)
            if code != 0:
                print(f"  CAUGHT  {name}")
            else:
                print(f"  SURVIVED  {name}  <-- the suite does not guard this")
                survivors.append((name, "MUTATION SURVIVED"))

        print()
        print(f"  {len(MUTATIONS) - len(survivors)}/{len(MUTATIONS)} "
              f"mutations caught")
        if survivors:
            print("  SURVIVORS:")
            for name, why in survivors:
                print(f"    - {name}: {why}")
            return 1
        print("  every mutation was caught -- the suite can fail.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
