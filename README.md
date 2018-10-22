PyDSDL
======

[![Travis CI](https://img.shields.io/discourse/https/forum.uavcan.org/users.svg)](https://forum.uavcan.org)
[![Travis CI](https://travis-ci.org/UAVCAN/pydsdl.svg?branch=master)](https://travis-ci.org/UAVCAN/pydsdl)

**PyDSDL is a [UAVCAN](https://uavcan.org) DSDL parser implemented in Python.**

## Requirements

PyDSDL requires Python 3.5 or newer.
No third-party dependencies are needed to use the library.

## Installation

Either clone this repository or run `pip install pydsdl`.

Make sure that it works by importing it: `import pydsdl`.

## Usage

CBL

## Development

### Dependencies

Despite the fact that the library itself is dependency-free,
some additional packages are needed for development and testing.
They are listed in `requirements.txt`.

### Coding conventions

Follow [PEP8](https://www.python.org/dev/peps/pep-0008/) with the following exception:
the line length limit is 120 characters (not 79).

All public functions and methods must be type-annotated.
This is enforced statically with MyPy.

Ensure compatibility with Python 3.5 and all newer versions.

### Writing tests

Write unit tests as functions without arguments prefixed with `_unittest_`.
Test functions should be located as close as possible to the tested code,
preferably at the end of the same Python module.

Make assertions using the standard `assert` statement.
For extra functionality, import `pytest` in your test function locally.
**Never import pytest outside of your test functions** because it will break the library
outside of test-enabled environments.

```python
def _unittest_my_test() -> None:    # Type annotations required
    import pytest  # OK to import inside test functions only (rarely useful)
    assert get_the_answer() == 42
```

For more information refer to the PyTest documentation.
