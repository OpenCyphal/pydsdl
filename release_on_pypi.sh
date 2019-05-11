#!/bin/bash
#
# PyPI release automation.
# https://gist.github.com/boppreh/ac7522b3a4ac46b4f6010eecddc57f21
#

rm -rf dist &> /dev/null

python3 -m pip install twine wheel

./setup.py sdist bdist_wheel

python3 -m twine upload dist/*
