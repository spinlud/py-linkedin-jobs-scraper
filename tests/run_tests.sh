#!/usr/bin/env bash

set -euo pipefail

# Chrome for Testing publishes no linux-arm64 build, so the base image is amd64 only
# and must be run under emulation on Apple Silicon.
PLATFORM="${PLATFORM:-linux/amd64}"

docker build --platform "$PLATFORM" -f tests/Dockerfile -t test_image .

docker run --rm --platform "$PLATFORM" -e LI_AT_COOKIE="$LI_AT_COOKIE" test_image
