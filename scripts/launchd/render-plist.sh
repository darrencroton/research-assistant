#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
template="$script_dir/com.user.re-ass.plist.template"
tmp_dir="$repo_root/tmp/launchd"
log_dir="$repo_root/logs"
output="$tmp_dir/com.user.re-ass.plist"

uv_bin="$(command -v uv || true)"
if [[ -z "$uv_bin" ]]; then
  printf 'uv is required but was not found on PATH.\n' >&2
  exit 1
fi

mkdir -p "$tmp_dir" "$log_dir"

escape_for_sed() {
  printf '%s' "$1" | sed 's/[\/&]/\\&/g'
}

escaped_uv_bin="$(escape_for_sed "$uv_bin")"
escaped_repo_root="$(escape_for_sed "$repo_root")"
escaped_log_dir="$(escape_for_sed "$log_dir")"

sed \
  -e "s/__UV_BIN__/$escaped_uv_bin/g" \
  -e "s/__REPO_ROOT__/$escaped_repo_root/g" \
  -e "s/__LOG_DIR__/$escaped_log_dir/g" \
  "$template" > "$output"

printf '%s\n' "$output"
