# PyDSDL

[![Travis CI](https://travis-ci.org/UAVCAN/pydsdl.svg?branch=master)](https://travis-ci.org/UAVCAN/pydsdl)
[![Build status](https://ci.appveyor.com/api/projects/status/lurx5gihhcl9wq1w/branch/master?svg=true)](https://ci.appveyor.com/project/Zubax/pydsdl/branch/master)
[![Coverage Status](https://coveralls.io/repos/github/UAVCAN/pydsdl/badge.svg)](https://coveralls.io/github/UAVCAN/pydsdl)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/pydsdl.svg)](https://pypi.org/project/pydsdl/)
[![Codacy Badge](https://api.codacy.com/project/badge/Grade/a0fdcbe8332a46399a2da90f97900e78)](https://www.codacy.com/app/UAVCAN/pydsdl)
[![Forum](https://img.shields.io/discourse/https/forum.uavcan.org/users.svg)](https://forum.uavcan.org)

PyDSDL is a [UAVCAN](https://uavcan.org) DSDL compiler frontend implemented in Python.
It supports all DSDL features defined in the UAVCAN specification.
A brief usage example is provided in the file `demo.py`.

## Installation

PyDSDL is compatible with any current version of Python.
No third-party dependencies need to be installed to use the library.

Install from PIP: `pip install pydsdl`.
Alternatively, import this repository into your codebase,
add its root to the Python import lookup paths, and you're ready to roll.

Make sure that it works by importing it: `import pydsdl`.

### Bundled third-party software

The library is bundled with the following third-party software libraries (by virtue of being bundled,
they need not be installed by the user):

- [Parsimonious](https://github.com/erikrose/parsimonious) by Erik Rose, MIT license.
- [Six](https://github.com/benjaminp/six) by Benjamin Peterson, MIT license; needed for Parsimonious.

## Library API

The library API is very simple, all of its entities are visible in `__init__.py`.
Use `help(entity)` to read the specific documentation per entity.
Below you will find a brief overview of the main API elements.

### The main function `read_namespace`

The application invokes the function `pydsdl.read_namespace()` with the path of the target root namespace
which is to be read and an optional list of look-up root namespace directories.
It returns a list of top-level composite type definitions found in the target root namespace.
If errors are found, a corresponding exception will be raised (described below).

The function has an optional callable argument that will be invoked when the frontend encounters a
`@print` directive in a definition, or when the frontend needs to emit a diagnostic message.
The callable is provided with the string to print and the location of the relevant statement for diagnostic purposes.
If the function is not provided, `@print` statements will not produce any output (although their expressions will
be evaluated nevertheless, and a failed evaluation will still be treated as a fatal error), and all diagnostics
will be suppressed.
Regardless of this argument, all diagnostics and prints will be also printed in the log.

As demanded by the specification, the frontend rejects unregulated fixed port ID by default.
To allow unregulated fixed port ID, pass the parameter `allow_unregulated_fixed_port_id` as True.
This option is dangerous and you must not use it unless you really understand the implications.

### Data type model

DSDL data types are modeled through the following Python types.
The user application should not instantiate them directly.
All of them share the same common ancestor `SerializableType` and the naming pattern `pydsdl.*Type`:

- `SerializableType` - the root class; it also inherits from `pydsdl.Any`, since DSDL types are also values.
  - `VoidType` - e.g., `void16`
  - `PrimitiveType`
    - `BooleanType` - e.g., `bool`
    - `ArithmeticType`
      - `FloatType` - e.g., `truncated float16`
      - `IntegerType`
        - `SignedIntegerType` - e.g., `int16`
        - `UnsignedIntegerType` - e.g., `saturated uint32`
  - `ArrayType`
    - `FixedLengthArrayType` - e.g., `uint8[256]`
    - `VariableLengthArrayType` - e.g., `uint8[<256]`
  - `CompositeType` - see below.
    - `UnionType` - message types or nested structures.
    - `StructureType` - message types or nested structures.
    - `ServiceType` - service types, not serializable.

The type `CompositeType` is the most interesting one, as it represents actual DSDL definitions upon their interpretation.
The following are its most important properties, their semantics should be obvious enough from their names:
`full_name: str`, `version: pydsdl.Version`, `deprecated: bool`, `fields: List[pydsdl.Field]`,
`constants: List[pydsdl.Constant]`, `fixed_port_id: Optional[int]`.

The `ServiceType` is a special case: unlike other types, it can't be serialized directly;
rather, it contains two pseudo-fields: `request` and `response`, which contain the request and the
response structure of the service type, respectively.

Every data type (i.e., the `SerializableType` root class) has the following public attributes
(although they raise `TypeError` when used against an instance of `ServiceType`):

- `bit_length_set: BitLengthSet` - the set of bit length values of all serialized representations of the type.
The type `BitLengthSet` is similar to the native set of integers `typing.Set[int]`: it is iterable and comparable,
plus there are several important convenience methods for bit length set manipulation.
- `__str__()` - a string representation of a data type is a valid DSDL expression that would
have yielded the same data type if evaluated by a DSDL processor.
For example: `saturated uint8[<=2]`, `uavcan.node.Heartbeat.1.0`.
- `__hash__()` - data types are hashable.

Instances of `CompositeType` (and its derivatives) contain *attributes*.
Per the specification, an attribute can be a field or a constant.
The corresponding data model is shown below:

- `Attribute` - the root class.
  - `Field` - e.g., `uavcan.node.Heartbeat.1.0 status`
    - `PaddingField` - e.g., `void5` (the name is always empty)
  - `Constant` - e.g., `uint16 VALUE = 0x1234`.

The root class `Attribute` exposes the following public properties:

- `data_type: pydsdl.SerializableType` - the data type of the attribute.
- `name: str` - the name of the attribute; always empty for padding fields.

The type `Constant` also has a property `value: pydsdl.Any`, which returns the value of the constant
as a DSDL expression value. Read below for details.

### Error model

The root exception types follow the naming pattern `pydsdl.*Error`, they are used to represent errors:

- `FrontendError` - contains properties `path:str` and `line:int`, both of which are optional,
which (if set) point out to the exact location where the error has occurred: the path of the DSDL file and
the line number within the file (starting from one). If line is set, path is also set.
  - `InternalError` - an error that occurred within the front end itself, at no fault of the processed definition.
  - `InvalidDefinitionError` - represents a problem with the processed definition.
This type is inherited by a dozen of specialized error exception classes; however, the class hierarchy beneath
this type is unstable and should not be used by the application directly.

Converting a `FrontendError` (or derived) object to `str` yields an error message in a conventional error format
suitable for error parsers of most IDEs; for example:

```text
uavcan/internet/udp/500.HandleIncomingPacket.1.0.uavcan:33: Error such and such
```

### Expression model

Constant expression values are represented through Python types rooted under `pydsdl.Any`.
DSDL types are also constant values, so `pydsdl.SerializableType` (the root of the type model) inherits from
`pydsdl.Any`. The class hierarchy is as follows:

- `Any` - has a class property (i.e., "static" property) `TYPE_NAME: str`, which contains the DSDL name of the type.
  - `Primitive` - primitive values; has virtual property `native_value` which yields an appropriate Python-native
representation of the contained value.
    - `Boolean` - a Boolean constant; has `native_value: bool`.
    - `Rational` - real value approximation; has `native_value: fractions.Fraction`, `is_integer() -> bool`, and
`as_native_integer() -> int` (which throws if the contained number is not an integer).
    - `String` - a Unicode string; has `native_value: str`.
  - `Container` - generic container; has `element_type: Type[Any]` and is iterable.
    - `Set` - a DSDL constant homogeneous set.

## Development

### Dependencies

Despite the fact that the library itself is dependency-free,
some additional packages are needed for development and testing.
They are listed in `requirements-dev.txt`.

External runtime dependencies are not allowed in this project --
if you can't bundle it with the library, you can't use it.

### Coding conventions

Follow [PEP8](https://www.python.org/dev/peps/pep-0008/) with the following exception:
the line length limit is 120 characters (not 79).

All functions and methods must be type-annotated. This is enforced statically with MyPy.

Ensure compatibility with all versions of Python that have not yet reached the end-of-life.

Do not import specific entities; instead, import only the package itself and then use verbose references,
as shown below.
If you really need to import a specific entity, consider prefixing it with an underscore to prevent
scope leakage, unless you really want it to be externally visible.
Exception applies to well-encapsulated submodules which are not part of the library API
(i.e., prefixed with an underscore).

```python
from . import _serializable               # Good
from ._serializable import CompositeType  # Pls no
```

### Writing tests

Aim to cover 100% of the code in the branch coverage mode.

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

### Releasing

Use the script `release.sh` to publish new releases on PyPI. Read the source for usage information.
The script will tag the release automatically.
