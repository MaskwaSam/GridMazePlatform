#!/bin/sh
set -eu

runtime_root=${1:-game}

if [ ! -d "$runtime_root" ]; then
  echo "Runtime root does not exist: $runtime_root" >&2
  exit 1
fi

hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

inventory_file=$(mktemp)
hashes_file=$(mktemp)
payload_file=$(mktemp)
trap 'rm -f "$inventory_file" "$hashes_file" "$payload_file"' EXIT HUP INT TERM

(
  cd "$runtime_root"
  for file in \
    index.html \
    styles.css \
    icon.svg \
    manifest.webmanifest \
    service-worker.js \
    THIRD_PARTY_NOTICES.md
  do
    test -f "$file"
    printf '%s\n' "$file"
  done

  for directory in js levels assets/stl vendor
  do
    test -d "$directory"
    find "$directory" -type f -print
  done
) | LC_ALL=C sort -u > "$inventory_file"

(
  cd "$runtime_root"
  find . -type f \
    ! -path './README.md' \
    ! -path './tests/*' \
    -print | sed 's#^\./##' | LC_ALL=C sort
) > "$payload_file"

if ! cmp -s "$inventory_file" "$payload_file"; then
  echo "Runtime payload contains files outside the deployment allowlist." >&2
  diff -u "$inventory_file" "$payload_file" >&2 || true
  exit 1
fi

if find "$runtime_root" -type l -print -quit | grep -q .; then
  echo "Runtime payload must not contain symbolic links." >&2
  exit 1
fi

while IFS= read -r relative_path
do
  file_hash=$(hash_file "$runtime_root/$relative_path")
  printf '%s  %s\n' "$file_hash" "$relative_path"
done < "$inventory_file" > "$hashes_file"

hash_file "$hashes_file"
