#!/bin/bash
# This script is for maintainers only. There is no documentation because if you're a maintainer you will
# know what it is and how to use it. Good luck, and try not to shoot yourself in the foot, please.
# Invoke like this:
#   ./update_subtree_parsimonious.sh 0.8.1

# Where to put the fetched stuff to.
# Per the read-tree docs, this path must end with a slash.
LOCAL_DIRECTORY="pydsdl/parsimonious/"

# Which subdirectory of the remote repository to fetch.
REMOTE_DIRECTORY="parsimonious"

# Which tag or commit to fetch from the remote repo; e.g. "0.8.1".
target_tag="$1"
[ -n "$target_tag" ] || exit 1

# Drop the old stuff.
git rm -rf $LOCAL_DIRECTORY &> /dev/null
    rm -rf $LOCAL_DIRECTORY &> /dev/null

# Fetch the remote; it will be stored into a short-lived ref FETCH_HEAD.
git fetch https://github.com/erikrose/parsimonious $target_tag || exit 2

# Now extract the stuff we need from what we just fetched, ignoring the rest.
git read-tree --prefix=$LOCAL_DIRECTORY -vu FETCH_HEAD:$REMOTE_DIRECTORY || exit 3
