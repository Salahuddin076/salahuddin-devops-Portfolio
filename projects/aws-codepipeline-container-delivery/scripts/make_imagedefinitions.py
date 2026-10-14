#!/usr/bin/env python3
"""Write imagedefinitions.json for the CodePipeline ECS (standard) deploy action.

The deploy action reads a JSON list of {"name": <container>, "imageUri": <uri>}
and registers a new task definition revision with that image. A typo in the
container name fails the deploy late, after the approval; a mutable tag such
as `latest` makes rollback ambiguous. Both are rejected here, at build time.

Usage:
  make_imagedefinitions.py --container app \
      --image 123456789012.dkr.ecr.us-east-1.amazonaws.com/demo:<40-hex-sha> \
      --output imagedefinitions.json [--require-commit-sha]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile

# ECS container names: up to 255 letters, numbers, hyphens and underscores.
CONTAINER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,255}$")

# Private ECR image URI: <account>.dkr.ecr.<region>.amazonaws.com[.cn]/<repo>(:<tag>|@sha256:<digest>)
ECR_URI_RE = re.compile(
    r"^(?P<registry>\d{12}\.dkr\.ecr\.[a-z]{2}(-gov)?-[a-z]+-\d\.amazonaws\.com(\.cn)?)"
    r"/(?P<repo>[a-z0-9]+(?:[._/-][a-z0-9]+)*)"
    r"(?:(?::(?P<tag>[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}))|(?:@(?P<digest>sha256:[0-9a-f]{64})))$"
)
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MUTABLE_TAGS = {"latest", "stable", "main", "master", "prod", "staging"}


class ValidationError(ValueError):
    pass


def validate_container_name(name: str) -> str:
    if not CONTAINER_NAME_RE.match(name or ""):
        raise ValidationError(
            f"invalid container name {name!r}: use 1-255 letters, digits, '-' or '_' "
            "and match the name in the task definition"
        )
    return name


def validate_image_uri(uri: str, require_commit_sha: bool = False) -> str:
    match = ECR_URI_RE.match(uri or "")
    if not match:
        raise ValidationError(
            f"invalid image URI {uri!r}: expected "
            "<account>.dkr.ecr.<region>.amazonaws.com/<repo>:<tag> or ...@sha256:<digest>"
        )
    tag = match.group("tag")
    if tag is not None:
        if tag.lower() in MUTABLE_TAGS:
            raise ValidationError(f"refusing mutable tag {tag!r}: deploy an immutable commit-SHA tag")
        if require_commit_sha and not COMMIT_SHA_RE.match(tag):
            raise ValidationError(f"tag {tag!r} is not a 40-character lowercase commit SHA")
    return uri


def build_definitions(container: str, image: str, require_commit_sha: bool = False) -> list[dict]:
    return [
        {
            "name": validate_container_name(container),
            "imageUri": validate_image_uri(image, require_commit_sha),
        }
    ]


def write_json_atomic(path: str, data: object) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".imagedefinitions-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write imagedefinitions.json for the ECS deploy action.")
    parser.add_argument("--container", required=True, help="container name in the task definition")
    parser.add_argument("--image", required=True, help="full ECR image URI")
    parser.add_argument("--output", default="imagedefinitions.json")
    parser.add_argument(
        "--require-commit-sha",
        action="store_true",
        help="require the tag to be a 40-character commit SHA (the pipeline sets this)",
    )
    args = parser.parse_args(argv)

    try:
        definitions = build_definitions(args.container, args.image, args.require_commit_sha)
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    write_json_atomic(args.output, definitions)
    print(f"wrote {args.output}: {json.dumps(definitions)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
