#!/usr/bin/env bash

set -euo pipefail

# Chrome for Testing publishes no linux-arm64 build, so the base image is amd64 only
# and must be run under emulation on Apple Silicon.
PLATFORM="${PLATFORM:-linux/amd64}"

docker build --platform "$PLATFORM" -f tests/Dockerfile -t test_image .

# Whichever credential is set locally is forwarded: the remember me pair is preferred, since
# it has a session issued per run instead of consuming one.
docker run --rm --platform "$PLATFORM" \
  -e LI_RM_COOKIE="${LI_RM_COOKIE:-}" \
  -e LI_BCOOKIE="${LI_BCOOKIE:-}" \
  -e LI_AT_COOKIE="${LI_AT_COOKIE:-}" \
  test_image
