#!/bin/bash

status=0

# Static type checking
export MYPYPATH="pydsdl/third_party/"
if ! mypy --strict --strict-equality --no-implicit-reexport --config-file=setup.cfg pydsdl
then
    status=1
fi

# Code style checking
if ! pycodestyle --show-source pydsdl
then
    status=1
fi

# Unit tests
if coverage run --source pydsdl -m pytest
then
    coverage report
else
    status=1
fi

exit $status
