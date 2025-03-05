#!/usr/bin/env zsh

# Get the next patch version number from poetry
VERSION=$(poetry version minor | awk '{print $NF}') 

echo "Releasing Version: $VERSION"

# Tag the release in git
git tag "$VERSION"

# Push the tags to the origin remote
git push origin --tags
