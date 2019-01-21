PyDSDL
======

[![Forum](https://img.shields.io/discourse/https/forum.uavcan.org/users.svg)](https://forum.uavcan.org)
[![Travis CI](https://travis-ci.org/UAVCAN/pydsdl.svg?branch=master)](https://travis-ci.org/UAVCAN/pydsdl)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/pydsdl.svg)](https://test.pypi.org/project/pydsdl/)


**PyDSDL is a [UAVCAN](https://uavcan.org) DSDL parser implemented in Python.**

## Requirements

PyDSDL requires Python 3.5 or newer.
No third-party dependencies are needed to use the library.

## Installation

Install from PIP: `pip install pydsdl`.
Alternatively, fetch this repository or add it as a submodule,
add its root to the Python import lookup paths, and you're ready to roll.

Make sure that it works by importing it: `import pydsdl`.

## Features

Supports all DSDL features defined in the UAVCAN specification,
and performs all mandatory static definition validity checks.
Additionally, checks for bit compatibility for data type definitions under the same major version.

## Usage

### Library API

The library API is very simple and contains only the following entities
(read their documentation for usage information, e.g., `help(pydsdl.data_type.CompoundType)`):

* The main function `pydsdl.parse_namespace()`.
* Data type model defined in the module `pydsdl.data_type`.
* Parsing error exceptions defined in the module `pydsdl.parse_error`.

#### The main function `parse_namespace`

The application invokes the function `pydsdl.parse_namespace()`.
It returns a list of top-level compound type definitions found in the provided namespace.
If errors are found, a corresponding exception will be raised (see below).

The function has an optional callable argument that will be invoked when the parser encounters a
`@print <expression>` directive in a definition.
The callable is provided with the value to print (which can have an arbitrary type, whatever the expression
has yielded upon its evaluation) and the location of the print statement for diagnostic purposes.
If the function is not provided, `@print` statements will not produce any output besides the log,
but their expressions will be evaluated nevertheless (and a failed evaluation will still be treated as a fatal error).

As demanded by the specification, the parser rejects unregulated fixed port ID by default.
To allow unregulated fixed port ID, pass the parameter `allow_unregulated_fixed_port_id` as True.

Assertion checks can be computationally taxing, e.g., if the parser is asked to prove correctness of binary layouts.
To accelerate parsing, assertion checks can be skipped by passing the parameter `skip_assertion_checks` as True.

#### Data type model

Data types are represented as one of the following types defined in `pydsdl.data_type`,
all rooted in the common ancestor `DataType`:

* `DataType`
  * `VoidType` - e.g., `void16`
  * `PrimitiveType`
    * `BooleanType` - e.g., `bool`
    * `ArithmeticType`
      * `FloatType` - e.g., `float16`
      * `IntegerType`
        * `SignedIntegerType` - e.g., `int16`
        * `UnsignedIntegerType` - e.g., `uint32`
  * `ArrayType`
    * `StaticArrayType` - e.g., `uint8[256]`
    * `DynamicArrayType` - e.g., `uint8[<256]`
  * `CompoundType` - see below
    * `UnionType` - message types or nested structures
    * `StructureType` - message types or nested structures
    * `ServiceType` - service types

The `ServiceType` is a special case: unlike other types, it can't be serialized directly;
rather, it contains two pseudo-fields: `request` and `response`, which contain the request and the
response structure of the service type, respectively.

The user application should not instantiate data type classes directly,
as their instantiation protocol uses a different error model internally,
and since that is not a part of the library API, it may change in incompatible ways arbitrarily.

Every data type (i.e., the `DataType` root class) has the following attributes
(although they raise `TypeError` when invoked against an instance of `ServiceType`):

* `bit_length_range: Tuple[int, int]` - returns a named tuple containing `min:int` and `max:int`, in bits,
which represent the minimum and the maximum possible bit length of an encoded representation.
* `compute_bit_length_values() -> Set[int]` - this function performs a bit length combination analysis on
the data type and returns a full set of bit lengths of all possible valid encoded representations of the data type.
Due to the involved computations, the function can be expensive to invoke, so use with care.

Instances of `CompoundType` (and its derivatives) contain *attributes*.
Per the specification, an attribute can be a field or a constant.
The corresponding data model is shown below:

* `Attribute`
  * `Field` - e.g., `uavcan.node.Heartbeat.1 data`
    * `PaddingField` - e.g., `void5` (the name is always empty)
  * `Constant` - e.g., `uint16 VALUE = 0x1234`

#### Error model

The root exception types defined in `pydsdl.parse_error` are used to represent errors occuring during the
parsing process:

* `ParseError` - contains properties `path:str` and `line:int`, both of which are optional,
which (if set) point out to the exact location where the error has occurred: the path of the file and
the line number within the file (starting from one). If line is set, path is also set.
  * `InternalError` - an error that occurred within the parser itself, at no fault of the parsed definition.
  * `InvalidDefinitionError` - represents a problem with the parsed definition.
This type is inherited by a dozen of specialized error exception classes; however, the class hierarchy beneath
this type is unstable and should not be used by the application directly.

Converting a `ParseError` (or derived) object to `str` yields an error message in a conventional error format
suitable for error parsers of most IDEs; for example:

```
uavcan/internet/udp/500.HandleIncomingPacket.0.1.uavcan:33: Error such and such
```

### Example

```python
import sys
import pydsdl

try:
    compound_types = pydsdl.parse_namespace('path/to/root_namespace', ['path/to/dependencies'])
except pydsdl.parse_error.InvalidDefinitionError as ex:
    print(ex, file=sys.stderr)                      # The DSDL definition is invalid
except pydsdl.parse_error.InternalError as ex:
    print('Internal error:', ex, file=sys.stderr)   # Oops! Please report.
else:
    for t in compound_types:
        if isinstance(t, pydsdl.data_type.ServiceType):
            blr, blv = 0, {0}
        else:
            blr, blv = t.bit_length_range, t.compute_bit_length_values()
        # The above is because service types are not directly serializable (see the UAVCAN specification)
        print(t.full_name, t.version, t.fixed_port_id, t.deprecated, blr, len(blv))
        for f in t.fields:
            print('\t', str(f.data_type), f.name)
        for c in t.constants:
            print('\t', str(c.data_type), c.name, '=', str(c.value))
```

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

100% coverage is required.

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
