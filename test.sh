#!/bin/bash

status=0

if ! mypy --strict --config-file=setup.cfg pydsdl
then
    status=1
fi

if coverage run -m pytest --capture=no -vv pydsdl
then
    coverage report
else
    status=1
fi

exit $status
