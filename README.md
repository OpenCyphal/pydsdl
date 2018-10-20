PyDSDL
======

**PyDSDL is a [UAVCAN](https://uavcan.org) DSDL parser implemented in Python.**

## Requirements

PyDSDL requires Python 3.5 or newer.

## Installation

Either clone this repository or run `pip install pydsdl`.

Make sure that it works by importing it: `import pydsdl`.

## Usage

CBL

## Development

### Coding conventions

Follow [PEP8](https://www.python.org/dev/peps/pep-0008/) with the following exception:
the line length limit is 120 characters (not 79).

Arguments and return types of all public functions and methods must be well-annotated.

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
def _unittest_my_test():
    import pytest  # OK to import inside test functions only (rarely useful)
    assert get_the_answer() == 42
```

For more information refer to the PyTest documentation.
