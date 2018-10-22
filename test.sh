#!/bin/bash

all_ok=0

mypy --strict --config-file=setup.cfg pydsdl
all_ok=$(($all_ok + $?))

pytest --capture=no -vv pydsdl || exit 1
all_ok=$(($all_ok + $?))

exit $all_ok
