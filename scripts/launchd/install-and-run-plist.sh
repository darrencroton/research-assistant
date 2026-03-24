#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
printf 'install-and-run-plist.sh now installs and reloads the LaunchAgent without running it.\n'
printf 'Use ./scripts/launchd/install-plist.sh instead.\n\n'

exec "$script_dir/install-plist.sh" "$@"
