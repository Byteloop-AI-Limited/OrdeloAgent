#!/usr/bin/env python3
import os
import subprocess
import sys
import tempfile


def main():
    file_path = os.environ.get("ZED_FILE")
    row_str = os.environ.get("ZED_ROW")
    col_str = os.environ.get("ZED_COLUMN")

    if not file_path or row_str is None or col_str is None:
        print("ZED_* env vars not found. Got:", file=sys.stderr)
        for k, v in sorted(os.environ.items()):
            if k.startswith("ZED_"):
                print(f"{k}={v!r}", file=sys.stderr)
        sys.exit(1)

    row = int(row_str)
    col = int(col_str)

    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()

    # Convert (row, col) → absolute character index
    # ZED_ROW / ZED_COLUMN are 0-based.
    lines = text.splitlines(keepends=True)
    if row >= len(lines):
        cursor_index = len(text)
    else:
        cursor_index = sum(len(lines[i]) for i in range(row)) + col

    # Find next "#%%" after cursor
    next_marker = text.find("#%%", cursor_index)

    if next_marker == -1:
        end = len(text)
    else:
        # Go to start of the line containing "#%%"
        line_start = text.rfind("\n", 0, next_marker)
        end = 0 if line_start == -1 else line_start + 1

    code = text[:end]

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    print(f">>> Running {os.path.basename(file_path)} from start up to index {end}")
    if next_marker == -1:
        print(">>> No next #%% found; executed to end of file.\n")
    else:
        print(f">>> Stopped before next #%% at index {next_marker}.\n")

    try:
        subprocess.run(["python3", tmp_path], check=False)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

            pass

if __name__ == "__main__":
    main()
