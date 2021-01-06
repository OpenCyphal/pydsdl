#!/bin/bash

status=0

# Static type checking
export MYPYPATH="pydsdl/third_party/"
if ! mypy --strict --config-file=setup.cfg pydsdl
then
    status=1
fi

# Code style checking
if ! pycodestyle pydsdl
then
    status=1
fi

# Unit tests
if coverage run -m pytest
then
    coverage report
else
    status=1
fi

exit $status
