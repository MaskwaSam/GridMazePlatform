from __future__ import print_function

import argparse
import os
import re


MACOS_RHINO_USER_PATH = re.compile(
    rb"/Users/([^/\x00]+)/(?=Library/Application Support/McNeel/)"
)


def sanitize_user_paths(data):
    """Redact macOS usernames without changing the byte length of a 3dm file."""
    replacements = []

    def replace(match):
        username = match.group(1)
        replacements.append(username)
        return b"/Users/" + (b"_" * len(username)) + b"/"

    return MACOS_RHINO_USER_PATH.sub(replace, data), replacements


def sanitize_file(source, target):
    with open(source, "rb") as handle:
        original = handle.read()
    sanitized, replacements = sanitize_user_paths(original)
    if len(sanitized) != len(original):
        raise RuntimeError("3dm sanitization changed the file length")
    folder = os.path.dirname(os.path.abspath(target))
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(target, "wb") as handle:
        handle.write(sanitized)
    return replacements


def main(argv=None):
    parser = argparse.ArgumentParser(description="Redact macOS usernames from Rhino 3dm render metadata.")
    parser.add_argument("source")
    parser.add_argument("target")
    args = parser.parse_args(argv)
    replacements = sanitize_file(args.source, args.target)
    print("Sanitized %d Rhino user-path occurrence(s)." % len(replacements))


if __name__ == "__main__":
    main()
