#!/usr/bin/env bash
#
# Build the course-studio image.
#
# This script exists because the image's behaviour is decided by build
# arguments, and a build argument that is forgotten does not fail — it produces
# an image that starts, serves pages, and is wrong:
#
#   NEXT_PUBLIC_STUDIO_BASE_PATH  forgotten, the studio serves at the origin
#                                 root while the pin and the healthcheck say
#                                 otherwise, and the container never reports
#                                 healthy.
#   NEXT_PUBLIC_PERSISTENCE       forgotten, the browser silently keeps
#                                 everything locally instead of talking to the
#                                 server, and every per-account isolation
#                                 property this deployment has is simply not
#                                 exercised. Nothing anywhere reports it.
#
# So the values live here, next to the pin that records them, and
# check_openmaic_contract.py asserts this file and the pin still agree.
#
# Usage, from the repository root:
#     deploy/build-studio.sh /path/to/OpenMAIC [image-tag]
#
# On Windows run it from Git Bash with MSYS_NO_PATHCONV=1, or from PowerShell
# using the docker command it prints: Git Bash rewrites any argument beginning
# with "/" into a Windows path, so --build-arg NEXT_PUBLIC_STUDIO_BASE_PATH=/x
# arrives as C:/Program Files/Git/x and Next refuses it.
set -euo pipefail

SOURCE="${1:?usage: deploy/build-studio.sh /path/to/OpenMAIC [image-tag]}"
TAG="${2:-deepwitya-studio:local}"

# Kept in step with openmaic-pin.json's contract block by the contract check.
BASE_PATH=/deepwitya/studio
PERSISTENCE=1

if [ ! -d "$SOURCE" ]; then
  echo "no OpenMAIC checkout at $SOURCE" >&2
  exit 1
fi

echo "building $TAG from $SOURCE"
echo "  base path  $BASE_PATH"
echo "  persistence $PERSISTENCE"

MSYS_NO_PATHCONV=1 docker build \
  --build-arg "NEXT_PUBLIC_STUDIO_BASE_PATH=$BASE_PATH" \
  --build-arg "NEXT_PUBLIC_PERSISTENCE=$PERSISTENCE" \
  --tag "$TAG" \
  "$SOURCE"

echo
echo "built $TAG"
echo "record its digest in deploy/openmaic-patches/openmaic-pin.json before deploying:"
echo "  docker image inspect --format '{{index .RepoDigests 0}}' $TAG"
