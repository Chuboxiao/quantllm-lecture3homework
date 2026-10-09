#!/bin/zsh
task_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$task_dir"
"$task_dir/.venv/bin/python" "$task_dir/webapp.py" --open
