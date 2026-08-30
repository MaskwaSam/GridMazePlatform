#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 /absolute/new/release-directory" >&2
  exit 2
fi

repository_root=$(git rev-parse --show-toplevel)
cd "$repository_root"

release_directory=$1
case "$release_directory" in
  /*) ;;
  *) echo "Release directory must be an absolute path." >&2; exit 2 ;;
esac
case "$release_directory" in
  "$repository_root"|"$repository_root"/*)
    echo "Release directory must be outside the working repository." >&2
    exit 2
    ;;
esac
if [ -e "$release_directory" ] || [ -L "$release_directory" ]; then
  echo "Release directory already exists: $release_directory" >&2
  exit 2
fi
if [ ! -d "$(dirname "$release_directory")" ]; then
  echo "Release parent directory does not exist: $(dirname "$release_directory")" >&2
  exit 2
fi

release_paths='.dockerignore deploy game scripts/generate_game_levels.mjs tests/test_game_contract.py tests/test_mazelab_deploy.py'
release_status=$(git status --porcelain -- .dockerignore deploy game scripts/generate_game_levels.mjs tests/test_game_contract.py tests/test_mazelab_deploy.py)
if [ -n "$release_status" ]; then
  echo "Release surface is not clean and committed:" >&2
  printf '%s\n' "$release_status" >&2
  exit 1
fi

release_commit=$(git rev-parse HEAD)
release_short_commit=$(git rev-parse --short=12 HEAD)
printf '%s\n' "$release_commit" | grep -Eq '^[0-9a-f]{40}$'

release_staging="${release_directory}.partial.$$"
archive_extract=$(mktemp -d /tmp/mazelab-release-extract.XXXXXX)
cleanup() {
  rm -rf "$archive_extract"
  if [ -d "$release_staging" ]; then
    rm -rf "$release_staging"
  fi
}
trap cleanup EXIT HUP INT TERM
mkdir "$release_staging"

archive_name="GridMazePlatform-${release_short_commit}.tar.gz"
archive_path="$release_staging/$archive_name"
git archive \
  --format=tar.gz \
  --prefix="GridMazePlatform-${release_short_commit}/" \
  --output="$archive_path" \
  "$release_commit" \
  -- .dockerignore deploy game scripts/generate_game_levels.mjs tests/test_game_contract.py tests/test_mazelab_deploy.py

hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

source_archive_sha256=$(hash_file "$archive_path")
tar -xzf "$archive_path" -C "$archive_extract"
archive_root="$archive_extract/GridMazePlatform-${release_short_commit}"

runtime_sha256=$("$archive_root/deploy/compute-runtime-sha256.sh" "$archive_root/game")
(
  cd "$archive_root"
  node scripts/generate_game_levels.mjs --check
  node game/tests/validate.mjs
  node deploy/verify-config.mjs
  python3 -m unittest tests.test_game_contract tests.test_mazelab_deploy
)

runtime_suffix=$(printf '%s' "$runtime_sha256" | cut -c1-12)
image_tag="${release_short_commit}-${runtime_suffix}"

{
  printf 'MAZELAB_GIT_COMMIT=%s\n' "$release_commit"
  printf 'MAZELAB_RUNTIME_SHA256=%s\n' "$runtime_sha256"
  printf 'MAZELAB_SOURCE_ARCHIVE_SHA256=%s\n' "$source_archive_sha256"
  printf 'MAZELAB_IMAGE_TAG=%s\n' "$image_tag"
} > "$release_staging/release.env"

{
  printf 'Maskwa Maze Lab release receipt\n'
  printf 'commit: %s\n' "$release_commit"
  printf 'runtime_sha256: %s\n' "$runtime_sha256"
  printf 'source_archive: %s\n' "$archive_name"
  printf 'source_archive_sha256: %s\n' "$source_archive_sha256"
  printf 'image_tag: mazelab:%s\n' "$image_tag"
  printf 'release_paths: %s\n' "$release_paths"
} > "$release_staging/receipt.txt"

mv "$release_staging" "$release_directory"
trap - EXIT HUP INT TERM
rm -rf "$archive_extract"

echo "Prepared exact committed release: $release_directory"
sed -n '1,20p' "$release_directory/receipt.txt"
