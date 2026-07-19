"""Patch the installed labscript suite for NumPy 2.0 compatibility.

labscript 3.4.2 (the latest release as of this writing) uses the legacy NumPy
byte-string dtype spelling ``'a256'`` and the removed alias ``numpy.string_``.
Both were removed in NumPy 2.0. On Python 3.13 there are no NumPy < 2 wheels, so
downgrading NumPy is not an option — instead we rewrite the dtype spellings in
the installed packages to their still-valid equivalents:

    'a256'         -> 'S256'          (identical fixed-width bytes dtype)
    'a' + str(n)   -> 'S' + str(n)
    numpy.string_  -> numpy.bytes_

This is idempotent — re-running it (e.g. after `pip install --upgrade`) is safe.

Usage:
    python patch_labscript_numpy2.py            # apply
    python patch_labscript_numpy2.py --check    # report only, exit 1 if patches needed
"""
import argparse
import os
import re
import sys

# Packages in the labscript suite that may carry legacy dtype spellings.
PACKAGES = [
    "labscript",
    "labscript_utils",
    "labscript_devices",
    "runmanager",
    "blacs",
    "runviewer",
    "lyse",
]

# (compiled pattern, replacement) pairs. Ordered; applied to every source line.
SUBS = [
    # 'a256' / "a256"  ->  'S256' / "S256"   (byte-string dtype, numeric width)
    (re.compile(r"(['\"])a(\d+)\1"), r"\1S\2\1"),
    # 'a' + str(...)   ->  'S' + str(...)    (dynamic-width byte-string dtype)
    (re.compile(r"(['\"])a\1(\s*\+\s*str\()"), r"\1S\1\2"),
    # numpy.string_ / np.string_  ->  numpy.bytes_ / np.bytes_
    (re.compile(r"\bnumpy\.string_\b"), "numpy.bytes_"),
    (re.compile(r"\bnp\.string_\b"), "np.bytes_"),
]


def package_dir(pkg):
    try:
        mod = __import__(pkg)
    except Exception:
        return None
    f = getattr(mod, "__file__", None)
    return os.path.dirname(f) if f else None


def patch_file(path, check_only):
    with open(path, "r", encoding="utf-8") as fh:
        original = fh.read()
    patched = original
    for pattern, repl in SUBS:
        patched = pattern.sub(repl, patched)
    if patched == original:
        return 0
    n = sum(1 for a, b in zip(original.splitlines(), patched.splitlines()) if a != b)
    if not check_only:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(patched)
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="report only, don't write")
    args = ap.parse_args()

    total_files = 0
    total_lines = 0
    for pkg in PACKAGES:
        root = package_dir(pkg)
        if not root:
            print(f"  (skip) {pkg}: not installed")
            continue
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                changed = patch_file(path, args.check)
                if changed:
                    total_files += 1
                    total_lines += changed
                    rel = os.path.relpath(path, os.path.dirname(root))
                    verb = "would patch" if args.check else "patched"
                    print(f"  {verb}: {rel} ({changed} line(s))")

    print()
    if total_files == 0:
        print("Nothing to patch — suite is already NumPy 2 compatible.")
        return 0
    if args.check:
        print(f"{total_lines} line(s) across {total_files} file(s) need patching.")
        return 1
    print(f"Patched {total_lines} line(s) across {total_files} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
