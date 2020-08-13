#!/bin/bash
# This script is for maintainers only. There is no documentation because if you're a maintainer you will
# know what it is and how to use it. Good luck, and try not to shoot yourself in the foot, please.
# Invoke like this:
#   ./update_third_party_subtrees.sh 0.8.1

THIRD_PARTY_DIR="pydsdl/third_party"

git rm -rf $THIRD_PARTY_DIR/* &> /dev/null
rm -rf $THIRD_PARTY_DIR/* &> /dev/null

# Updating Parsimonious.
parsimonious_tag="$1"
[ -n "$parsimonious_tag" ] || exit 1
git fetch https://github.com/erikrose/parsimonious $parsimonious_tag || exit 2
git read-tree --prefix=$THIRD_PARTY_DIR/parsimonious/ -vu FETCH_HEAD:parsimonious || exit 3
rm -rf $THIRD_PARTY_DIR/parsimonious/tests/  # We don't want to keep its tests around, they're no use for us anyway.

# Updating six.py, needed for Parsimonious only.
wget https://raw.githubusercontent.com/benjaminp/six/1.15.0/six.py -P $THIRD_PARTY_DIR || exit 4
