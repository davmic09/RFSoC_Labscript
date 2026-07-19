"""Headless labscript compiler.

Compiles a labscript experiment file into a shot .h5 file without opening the
runmanager GUI. Useful for quickly validating that a connection table and
experiment logic compile correctly.

Usage:
    python compile_shot.py simple_example.py
    python compile_shot.py simple_example.py --out shot.h5

The output shot can be inspected with runviewer:
    runviewer <path-to-shot>.h5
"""
import argparse
import os

import runmanager


def compile_shot(labscript_file, run_file=None):
    labscript_file = os.path.abspath(labscript_file)

    # Ask labconfig where this sequence's shots should live and claim an index.
    seq_attrs, out_dir, prefix = runmanager.new_sequence_details(
        labscript_file, increment_sequence_index=True
    )
    if run_file is None:
        os.makedirs(out_dir, exist_ok=True)
        run_file = os.path.join(out_dir, prefix + ".h5")
    run_file = os.path.abspath(run_file)

    # Create the shot file with (empty) globals — this example has no scanned globals.
    runmanager.make_single_run_file(
        run_file,
        sequenceglobals={},
        runglobals={},
        sequence_attrs=seq_attrs,
        run_no=0,
        n_runs=1,
    )

    result = {}
    runmanager.compile_labscript_async(
        labscript_file,
        run_file,
        stream_port=None,  # stream compiler stdout/stderr to this console
        done_callback=lambda ok: result.__setitem__("ok", ok),
    )
    return run_file, result.get("ok", False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labscript_file", help="path to the labscript experiment .py")
    parser.add_argument("--out", default=None, help="output shot .h5 path (optional)")
    args = parser.parse_args()

    run_file, ok = compile_shot(args.labscript_file, args.out)
    print()
    if ok:
        print(f"[OK] Compiled shot: {run_file}")
    else:
        print("[FAILED] Compilation failed — see errors above.")
        raise SystemExit(1)
