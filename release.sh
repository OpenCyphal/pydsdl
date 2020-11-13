#!/bin/bash
# PyPI release automation. This script can be invoked manually or from a CI pipeline.
# https://gist.github.com/boppreh/ac7522b3a4ac46b4f6010eecddc57f21

set -o nounset

function die()
{
    echo >&2 "FAILURE: $*"
    exit 1
}

function clean()
{
    rm -rf dist build   &> /dev/null
    rm -rf ./*.egg-info &> /dev/null
    rm -rf docs/_build  &> /dev/null
    rm -rf .coverage*   &> /dev/null
    rm -rf .*cache      &> /dev/null
}

python3 -m pip uninstall pydsdl -y &> /dev/null  # Avoid conflicts

export PYTHONPATH=.
version=$(python3 -c 'import pydsdl; print(pydsdl.__version__)')
tag=$(git describe --tags --abbrev=0)

[[ "$(git rev-parse --abbrev-ref HEAD)" = 'master' ]] || die "Can only release from the master branch."
[[ -z "$(git diff)" ]]                                || die "Commit all changes, then try again."
[[ -z "$(git log '@{u}..')" ]]                        || die "Push all commits, then try again."
[[ "$version" != "$tag" ]]                            || die "Bump the version number first (currently $version)."

clean || die "Clean failed. It is required to prevent unnecessary files from being included in the release package."

./setup.py sdist bdist_wheel   || die "Execution of setup.py has failed."
python3 -m twine upload dist/* || die "Twine upload has failed."
clean  # May fail, we don't care.

(git tag -a "${version}" -m "${version}" && git push --tags) || die "Could not tag the release. Please do it manually."
