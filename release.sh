#!/bin/bash
#
# PyPI release automation.
# https://gist.github.com/boppreh/ac7522b3a4ac46b4f6010eecddc57f21
#

set -o nounset

function die()
{
    echo >&2 "FAILURE: $*"
    exit 1
}

function clean()
{
    rm -rf dist build ./*.egg-info &> /dev/null
}

[[ "$(git rev-parse --abbrev-ref HEAD)" = 'master' ]]  || die "Can only release from the master branch."
[[ -z "$(git diff)" ]]                                 || die "Please commit all changes, then try again."
[[ -z "$(git log '@{u}..')" ]]                         || die "Please push all commits, then try again."

./test.sh  || die "Test failed."

python3 -m pip uninstall pydsdl -y &> /dev/null  # Extra precautions.

clean || die "Clean failed. It is required to prevent unnecessary files from being included in the release package."

./setup.py sdist bdist_wheel   || die "Execution of setup.py has failed."
python3 -m twine upload dist/* || die "Twine upload has failed."
clean  # May fail, we don't care.

export PYTHONPATH=.
version=$(python3 -c 'import pydsdl; print(pydsdl.__version__)')
(git tag -a "${version}" -m "${version}" && git push --tags) || die "Could not tag the release. Please do it manually."
