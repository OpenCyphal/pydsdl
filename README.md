# PyDSDL

[![Travis CI](https://travis-ci.org/UAVCAN/pydsdl.svg?branch=master)](https://travis-ci.org/UAVCAN/pydsdl)
[![Build status](https://ci.appveyor.com/api/projects/status/lurx5gihhcl9wq1w/branch/master?svg=true)](https://ci.appveyor.com/project/Zubax/pydsdl/branch/master)
[![Documentation Status](https://readthedocs.org/projects/pydsdl/badge/?version=latest)](https://pydsdl.readthedocs.io/en/latest/?badge=latest)
[![Coverage Status](https://coveralls.io/repos/github/UAVCAN/pydsdl/badge.svg)](https://coveralls.io/github/UAVCAN/pydsdl)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/pydsdl.svg)](https://pypi.org/project/pydsdl/)
[![Codacy Badge](https://api.codacy.com/project/badge/Grade/a0fdcbe8332a46399a2da90f97900e78)](https://www.codacy.com/app/UAVCAN/pydsdl)
[![Forum](https://img.shields.io/discourse/https/forum.uavcan.org/users.svg)](https://forum.uavcan.org)

PyDSDL is a [UAVCAN](https://uavcan.org) DSDL compiler front-end implemented in Python.
It accepts a DSDL namespace at the input and produces a well-annotated abstract syntax tree (AST) at the output,
evaluating all constant expressions in the process.
All DSDL features defined in the UAVCAN Specification are supported.
The library should, in theory, work on any platform and with any Python implementation.

**Read the docs at [pydsdl.readthedocs.io](https://pydsdl.readthedocs.io/).**


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
