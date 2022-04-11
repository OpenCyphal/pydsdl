# PyDSDL

[![Build status](https://ci.appveyor.com/api/projects/status/lurx5gihhcl9wq1w/branch/master?svg=true)](https://ci.appveyor.com/project/Zubax/pydsdl/branch/master)
[![Documentation Status](https://readthedocs.org/projects/pydsdl/badge/?version=latest)](https://pydsdl.readthedocs.io/en/latest/?badge=latest)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/pydsdl)](https://pypi.org/project/pydsdl/)
[![Forum](https://img.shields.io/discourse/https/forum.opencyphal.org/users.svg)](https://forum.opencyphal.org)

PyDSDL is a [Cyphal](https://opencyphal.org) DSDL compiler front-end implemented in Python.
It accepts a DSDL namespace at the input and produces a well-annotated abstract syntax tree (AST) at the output,
evaluating all constant expressions in the process.
All DSDL features defined in the Cyphal Specification are supported.
The library should, in theory, work on any platform and with any Python implementation.

**Read the docs at [pydsdl.readthedocs.io](https://pydsdl.readthedocs.io/).**

```python
import pydsdl
try:
    types = pydsdl.read_namespace(target_directory, lookup_directories)
except pydsdl.InvalidDefinitionError as ex:
    print(f'{ex.path}:{ex.line}: Invalid DSDL: {ex.text}', file=sys.stderr)
    exit(1)
else:
    for t in types:
        print(t)  # Process the type -- generate code, analyze, etc.
```
