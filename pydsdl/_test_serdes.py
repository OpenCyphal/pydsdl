# Copyright (c) 2018 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

# pylint: disable=protected-access,too-many-statements

from __future__ import annotations

from pathlib import Path
import math
import typing
import pytest  # This is only safe to import in test files!

from ._serdes import (
    SerDesError,
    ArrayLengthError,
    UnionFieldError,
    UnionTagError,
    DelimiterHeaderError,
    _BitWriter,
    _BitReader,
    _serialize_primitive,
    _deserialize_primitive,
    _serialize_array,
    _deserialize_array,
    _serialize_composite,
    _deserialize_composite,
    _serialize_element,
    _deserialize_element,
    _serialize_field_value,
    _deserialize_field_value,
    _default_value,
    _Value,
    _Obj,
    serialize,
    deserialize,
)
from ._serializable import (
    PrimitiveType,
    BooleanType,
    SignedIntegerType,
    UnsignedIntegerType,
    FloatType,
    VoidType,
    ArrayType,
    FixedLengthArrayType,
    VariableLengthArrayType,
    UTF8Type,
    ByteType,
    StructureType,
    UnionType,
    ServiceType,
    DelimitedType,
    Field,
    PaddingField,
)
from ._serializable._composite import Version

__all__: list[str] = []


def _unittest_serdes_module() -> None:
    """
    Minimal unit test to verify the module structure and imports.
    """
    # Verify that error classes are defined and inherit from Exception
    assert issubclass(SerDesError, Exception)
    assert issubclass(ArrayLengthError, SerDesError)
    assert issubclass(UnionFieldError, SerDesError)
    assert issubclass(UnionTagError, SerDesError)
    assert issubclass(DelimiterHeaderError, SerDesError)

    # Verify that SerDesError inherits from FrontendError (via Error)
    from ._error import FrontendError

    assert issubclass(SerDesError, FrontendError)

    # Verify that type aliases are defined
    assert _Value is not None
    assert _Obj is not None

    # Verify that functions are defined with correct signatures
    assert callable(serialize)
    assert callable(deserialize)


def _unittest_serdes_api() -> None:
    """
    Test the public serialize/deserialize API with various scenarios.
    """
    # Test 1: Verify functions are callable and have correct signatures
    assert callable(serialize)
    assert callable(deserialize)

    # Test 2: ServiceType rejection - create a mock ServiceType
    class MockServiceType(ServiceType):
        pass

    mock_service = MockServiceType.__new__(MockServiceType)
    with pytest.raises(TypeError, match="Service types are not directly serializable"):
        serialize(mock_service, {})

    with pytest.raises(TypeError, match="Service types are not directly deserializable"):
        deserialize(mock_service, bytes([0]))

    # Test 3: with_delimiter_header=True on non-delimited type raises ValueError
    class MockStructureType(StructureType):
        pass

    mock_struct = MockStructureType.__new__(MockStructureType)
    with pytest.raises(ValueError, match="with_delimiter_header=True is only valid for delimited types"):
        serialize(mock_struct, {}, with_delimiter_header=True)

    with pytest.raises(ValueError, match="with_delimiter_header=True is only valid for delimited types"):
        deserialize(mock_struct, bytes([0]), with_delimiter_header=True)

    # Test 4: Verify imports work at package level
    import pydsdl

    assert hasattr(pydsdl, "serialize")
    assert hasattr(pydsdl, "deserialize")
    assert hasattr(pydsdl, "SerDesError")
    assert hasattr(pydsdl, "ArrayLengthError")
    assert hasattr(pydsdl, "UnionFieldError")
    assert hasattr(pydsdl, "UnionTagError")
    assert hasattr(pydsdl, "DelimiterHeaderError")


def _unittest_serdes_bit_writer() -> None:
    """
    Test _BitWriter with various bit lengths, cross-byte writes, and alignment.
    """
    w = _BitWriter()
    assert w.bit_offset == 0

    w.write_bits(0xFF, 8)
    assert w.bit_offset == 8
    assert w.finish() == bytes([0xFF])

    w = _BitWriter()
    w.write_bits(0b110, 3)
    assert w.bit_offset == 3
    assert w.finish() == bytes([0b00000110])

    w = _BitWriter()
    w.write_bits(0b1, 1)
    w.write_bits(0b1, 1)
    w.write_bits(0b0, 1)
    assert w.finish() == bytes([0b00000011])

    w = _BitWriter()
    w.write_bits(0xFF, 8)
    w.write_bits(0xAA, 8)
    assert w.finish() == bytes([0xFF, 0xAA])

    w = _BitWriter()
    w.write_bits(0x0F, 4)
    w.write_bits(0x0A, 4)
    assert w.finish() == bytes([0xAF])

    w = _BitWriter()
    w.write_bits(0x1, 4)
    w.write_bits(0x2, 4)
    w.write_bits(0x3, 4)
    assert w.finish() == bytes([0x21, 0x03])

    w = _BitWriter()
    w.write_bits(0, 5)
    w.align_to(8)
    assert w.bit_offset == 8
    assert w.finish() == bytes([0x00])

    w = _BitWriter()
    w.write_bits(0xFF, 3)
    w.align_to(8)
    assert w.bit_offset == 8
    assert w.finish() == bytes([0x07])

    w = _BitWriter()
    w.write_bits(0xFFFFFFFF, 32)
    assert w.finish() == bytes([0xFF, 0xFF, 0xFF, 0xFF])


def _unittest_serdes_bit_reader() -> None:
    """
    Test _BitReader with various bit lengths, cross-byte reads, zero extension, and bounded sub-readers.
    """
    r = _BitReader(bytes([0xFF]))
    assert r.bit_offset == 0
    assert r.read_bits(8) == 0xFF
    assert r.bit_offset == 8

    r = _BitReader(bytes([0b00000110]))
    assert r.read_bits(3) == 0b110

    r = _BitReader(bytes([0b00000011]))
    assert r.read_bits(1) == 0b1
    assert r.read_bits(1) == 0b1
    assert r.read_bits(1) == 0b0

    r = _BitReader(bytes([0xFF, 0xAA]))
    assert r.read_bits(8) == 0xFF
    assert r.read_bits(8) == 0xAA

    r = _BitReader(bytes([0xAF]))
    assert r.read_bits(4) == 0x0F
    assert r.read_bits(4) == 0x0A

    r = _BitReader(bytes([0x21, 0x03]))
    assert r.read_bits(4) == 0x1
    assert r.read_bits(4) == 0x2
    assert r.read_bits(4) == 0x3

    r = _BitReader(bytes([0xAB]))
    assert r.read_bits(16) == 0x00AB

    r = _BitReader(bytes([0xFF]))
    _ = r.read_bits(8)
    r.align_to(8)
    assert r.bit_offset == 8

    r = _BitReader(bytes([0xFF]))
    _ = r.read_bits(3)
    r.align_to(8)
    assert r.bit_offset == 8

    r = _BitReader(bytes([0x12, 0x34, 0x56]))
    sub = r.bounded_subreader(8)
    assert sub.read_bits(8) == 0x12
    assert r.bit_offset == 8

    r = _BitReader(bytes([0x12, 0x34, 0x56]))
    sub = r.bounded_subreader(16)
    assert sub.read_bits(8) == 0x12
    assert sub.read_bits(8) == 0x34
    assert r.bit_offset == 16

    r = _BitReader(bytes([]))
    assert r.read_bits(8) == 0

    r = _BitReader(bytes([0xFF]))
    assert r.remaining_bits == 8
    _ = r.read_bits(3)
    assert r.remaining_bits == 5


def _unittest_serdes_primitive_codec() -> None:
    """
    Test primitive codec with various types, cast modes, and edge cases.
    """
    CM = PrimitiveType.CastMode

    w = _BitWriter()
    _serialize_primitive(w, BooleanType(), True)
    assert w.finish() == bytes([0x01])

    w = _BitWriter()
    _serialize_primitive(w, BooleanType(), False)
    assert w.finish() == bytes([0x00])

    w = _BitWriter()
    _serialize_primitive(w, UnsignedIntegerType(8, CM.TRUNCATED), 42)
    assert w.finish() == bytes([0x2A])

    w = _BitWriter()
    _serialize_primitive(w, SignedIntegerType(8, CM.SATURATED), -1)
    assert w.finish() == bytes([0xFF])

    w = _BitWriter()
    _serialize_primitive(w, SignedIntegerType(8, CM.SATURATED), -128)
    assert w.finish() == bytes([0x80])

    w = _BitWriter()
    _serialize_primitive(w, SignedIntegerType(8, CM.SATURATED), 127)
    assert w.finish() == bytes([0x7F])

    w = _BitWriter()
    _serialize_primitive(w, UnsignedIntegerType(16, CM.TRUNCATED), 0xABCD)
    result = w.finish()
    assert result == bytes([0xCD, 0xAB])

    w = _BitWriter()
    _serialize_primitive(w, FloatType(32, CM.SATURATED), 1.5)
    result = w.finish()
    r = _BitReader(result)
    val = _deserialize_primitive(r, FloatType(32, CM.SATURATED))
    assert isinstance(val, float) and abs(val - 1.5) < 0.0001

    w = _BitWriter()
    _serialize_primitive(w, FloatType(64, CM.SATURATED), 3.14159)
    result = w.finish()
    r = _BitReader(result)
    val = _deserialize_primitive(r, FloatType(64, CM.SATURATED))
    assert isinstance(val, float) and abs(val - 3.14159) < 0.00001

    r = _BitReader(bytes([0x01]))
    assert _deserialize_primitive(r, BooleanType()) is True

    r = _BitReader(bytes([0x00]))
    assert _deserialize_primitive(r, BooleanType()) is False

    r = _BitReader(bytes([0x2A]))
    assert _deserialize_primitive(r, UnsignedIntegerType(8, CM.TRUNCATED)) == 42

    r = _BitReader(bytes([0xFF]))
    assert _deserialize_primitive(r, SignedIntegerType(8, CM.SATURATED)) == -1

    r = _BitReader(bytes([0x80]))
    assert _deserialize_primitive(r, SignedIntegerType(8, CM.SATURATED)) == -128

    r = _BitReader(bytes([0x7F]))
    assert _deserialize_primitive(r, SignedIntegerType(8, CM.SATURATED)) == 127

    w = _BitWriter()
    _serialize_primitive(w, UnsignedIntegerType(2, CM.TRUNCATED), 3)
    assert w.finish() == bytes([0x03])

    w = _BitWriter()
    _serialize_primitive(w, UnsignedIntegerType(3, CM.TRUNCATED), 7)
    assert w.finish() == bytes([0x07])

    w = _BitWriter()
    _serialize_primitive(w, UnsignedIntegerType(5, CM.TRUNCATED), 31)
    assert w.finish() == bytes([0x1F])

    w = _BitWriter()
    _serialize_primitive(w, SignedIntegerType(2, CM.SATURATED), -2)
    assert w.finish() == bytes([0x02])

    w = _BitWriter()
    _serialize_primitive(w, SignedIntegerType(2, CM.SATURATED), 1)
    assert w.finish() == bytes([0x01])

    w = _BitWriter()
    _serialize_primitive(w, SignedIntegerType(3, CM.SATURATED), -4)
    assert w.finish() == bytes([0x04])

    w = _BitWriter()
    _serialize_primitive(w, SignedIntegerType(3, CM.SATURATED), 3)
    assert w.finish() == bytes([0x03])

    w = _BitWriter()
    _serialize_primitive(w, UnsignedIntegerType(64, CM.TRUNCATED), 0xFFFFFFFFFFFFFFFF)
    result = w.finish()
    assert len(result) == 8

    w = _BitWriter()
    _serialize_primitive(w, SignedIntegerType(64, CM.SATURATED), -1)
    result = w.finish()
    assert len(result) == 8

    w = _BitWriter()
    _serialize_primitive(w, UnsignedIntegerType(8, CM.SATURATED), 300)
    assert w.finish() == bytes([0xFF])

    w = _BitWriter()
    _serialize_primitive(w, UnsignedIntegerType(8, CM.TRUNCATED), 300)
    assert w.finish() == bytes([0x2C])

    w = _BitWriter()
    _serialize_primitive(w, SignedIntegerType(8, CM.SATURATED), 200)
    assert w.finish() == bytes([0x7F])

    w = _BitWriter()
    _serialize_primitive(w, SignedIntegerType(8, CM.SATURATED), -200)
    assert w.finish() == bytes([0x80])

    w = _BitWriter()
    _serialize_primitive(w, UnsignedIntegerType(8, CM.TRUNCATED), 42.4)
    assert w.finish() == bytes([0x2A])

    w = _BitWriter()
    _serialize_primitive(w, SignedIntegerType(8, CM.SATURATED), -1.4)
    assert w.finish() == bytes([0xFF])

    with pytest.raises(ValueError):
        w = _BitWriter()
        _serialize_primitive(w, UnsignedIntegerType(8, CM.TRUNCATED), "invalid")

    with pytest.raises(ValueError):
        w = _BitWriter()
        _serialize_primitive(w, BooleanType(), float("inf"))

    with pytest.raises(ValueError):
        w = _BitWriter()
        _serialize_primitive(w, UnsignedIntegerType(8, CM.TRUNCATED), float("nan"))

    w = _BitWriter()
    _serialize_primitive(w, VoidType(8), None)
    assert w.finish() == bytes([0x00])

    r = _BitReader(bytes([0x00]))
    assert _deserialize_primitive(r, VoidType(8)) is None


def _unittest_serdes_array_codec() -> None:
    """
    Test array codec with fixed-length, variable-length, UTF-8, and byte arrays.
    """
    CM = PrimitiveType.CastMode

    w = _BitWriter()
    schema = FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 3)
    _serialize_array(w, schema, [1, 2, 3])
    assert w.finish() == bytes([0x01, 0x02, 0x03])

    w = _BitWriter()
    schema = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 255)  # type: ignore
    _serialize_array(w, schema, [1, 2, 3])
    data = w.finish()
    assert data[0] == 3
    assert data[1:] == bytes([0x01, 0x02, 0x03])

    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == [1, 2, 3]

    w = _BitWriter()
    schema = FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 3)
    _serialize_array(w, schema, (1, 2, 3))
    assert w.finish() == bytes([0x01, 0x02, 0x03])

    with pytest.raises(ArrayLengthError):
        w = _BitWriter()
        schema = FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 3)
        _serialize_array(w, schema, [1, 2])

    with pytest.raises(ArrayLengthError):
        w = _BitWriter()
        schema = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 3)  # type: ignore
        _serialize_array(w, schema, [1, 2, 3, 4])

    w = _BitWriter()
    schema = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 255)  # type: ignore
    _serialize_array(w, schema, [])
    data = w.finish()
    assert data[0] == 0

    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == []

    w = _BitWriter()
    schema = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 255)  # type: ignore
    _serialize_array(w, schema, list(range(255)))
    data = w.finish()
    assert data[0] == 255

    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert isinstance(result, list) and len(result) == 255

    w = _BitWriter()
    schema = VariableLengthArrayType(UTF8Type(), 255)  # type: ignore
    _serialize_array(w, schema, "hello")
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == "hello"
    assert isinstance(result, str)

    w = _BitWriter()
    schema = VariableLengthArrayType(UTF8Type(), 255)  # type: ignore
    _serialize_array(w, schema, b"hello")
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == "hello"

    w = _BitWriter()
    schema = VariableLengthArrayType(ByteType(), 255)  # type: ignore
    _serialize_array(w, schema, b"hello")
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == b"hello"
    assert isinstance(result, bytes)

    w = _BitWriter()
    schema = VariableLengthArrayType(ByteType(), 255)  # type: ignore
    _serialize_array(w, schema, "hello")
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == b"hello"

    w = _BitWriter()
    inner_schema = FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 2)
    outer_schema = FixedLengthArrayType(inner_schema, 2)
    _serialize_array(w, outer_schema, [[1, 2], [3, 4]])
    data = w.finish()
    assert data == bytes([0x01, 0x02, 0x03, 0x04])

    r = _BitReader(data)
    result = _deserialize_array(r, outer_schema)
    assert result == [[1, 2], [3, 4]]

    with pytest.raises(TypeError):
        w = _BitWriter()
        schema = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 255)  # type: ignore
        _serialize_array(w, schema, "invalid")

    with pytest.raises(TypeError):
        w = _BitWriter()
        schema = FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 3)
        _serialize_array(w, schema, 123)


def _unittest_serdes_composite_codec() -> None:
    """
    Test composite codec with structures, unions, alignment, and default initialization.
    """
    CM = PrimitiveType.CastMode

    w = _BitWriter()
    schema = StructureType(
        name="test.S",
        version=Version(1, 0),
        attributes=[Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")],
        deprecated=False,
        fixed_port_id=None,
        source_file_path=Path("test", "S"),
        has_parent_service=False,
    )
    _serialize_composite(w, schema, {"x": 42})
    assert w.finish() == bytes([0x2A])

    r = _BitReader(bytes([0x2A]))
    result = _deserialize_composite(r, schema)
    assert result == {"x": 42}

    w = _BitWriter()
    schema = StructureType(
        name="test.S2",
        version=Version(1, 0),
        attributes=[
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "x"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "y"),
        ],
        deprecated=False,
        fixed_port_id=None,
        source_file_path=Path("test", "S2"),
        has_parent_service=False,
    )
    _serialize_composite(w, schema, {"x": 1, "y": 2})
    data = w.finish()
    assert data == bytes([0x01, 0x02])

    r = _BitReader(data)
    result = _deserialize_composite(r, schema)
    assert result == {"x": 1, "y": 2}

    with pytest.raises(ValueError, match="Unknown field"):
        w = _BitWriter()
        schema = StructureType(
            name="test.S3",
            version=Version(1, 0),
            attributes=[Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")],
            deprecated=False,
            fixed_port_id=None,
            source_file_path=Path("test", "S3"),
            has_parent_service=False,
        )
        _serialize_composite(w, schema, {"x": 1, "unknown": 2})

    w = _BitWriter()
    schema = StructureType(
        name="test.S4",
        version=Version(1, 0),
        attributes=[Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")],
        deprecated=False,
        fixed_port_id=None,
        source_file_path=Path("test", "S4"),
        has_parent_service=False,
    )
    _serialize_composite(w, schema, {})
    data = w.finish()
    assert data == bytes([0x00])

    with pytest.raises(ValueError, match="exactly one field"):
        w = _BitWriter()
        schema = UnionType(  # type: ignore
            name="test.U",
            version=Version(1, 0),
            attributes=[
                Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"),
                Field(UnsignedIntegerType(8, CM.TRUNCATED), "b"),
            ],
            deprecated=False,
            fixed_port_id=None,
            source_file_path=Path("test", "U"),
            has_parent_service=False,
        )
        _serialize_composite(w, schema, {})

    with pytest.raises(ValueError, match="exactly one field"):
        w = _BitWriter()
        schema = UnionType(  # type: ignore
            name="test.U2",
            version=Version(1, 0),
            attributes=[
                Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"),
                Field(UnsignedIntegerType(8, CM.TRUNCATED), "b"),
            ],
            deprecated=False,
            fixed_port_id=None,
            source_file_path=Path("test", "U2"),
            has_parent_service=False,
        )
        _serialize_composite(w, schema, {"a": 1, "b": 2})

    with pytest.raises(UnionFieldError, match="Unknown union variant"):
        w = _BitWriter()
        schema = UnionType(  # type: ignore
            name="test.U3",
            version=Version(1, 0),
            attributes=[
                Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"),
                Field(UnsignedIntegerType(8, CM.TRUNCATED), "b"),
            ],
            deprecated=False,
            fixed_port_id=None,
            source_file_path=Path("test", "U3"),
            has_parent_service=False,
        )
        _serialize_composite(w, schema, {"unknown": 1})

    w = _BitWriter()
    schema = UnionType(  # type: ignore
        name="test.U4",
        version=Version(1, 0),
        attributes=[
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "b"),
        ],
        deprecated=False,
        fixed_port_id=None,
        source_file_path=Path("test", "U4"),
        has_parent_service=False,
    )
    _serialize_composite(w, schema, {"a": 42})
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_composite(r, schema)
    assert result == {"a": 42}

    w = _BitWriter()
    schema = UnionType(  # type: ignore
        name="test.U5",
        version=Version(1, 0),
        attributes=[
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "b"),
        ],
        deprecated=False,
        fixed_port_id=None,
        source_file_path=Path("test", "U5"),
        has_parent_service=False,
    )
    _serialize_composite(w, schema, {"b": 99})
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_composite(r, schema)
    assert result == {"b": 99}

    default = _default_value(UnsignedIntegerType(8, CM.TRUNCATED))
    assert default == 0

    default = _default_value(BooleanType())
    assert default is False

    default = _default_value(FloatType(32, CM.SATURATED))
    assert default == 0.0

    default = _default_value(FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 3))
    assert default == [0, 0, 0]

    default = _default_value(VariableLengthArrayType(UTF8Type(), 255))
    assert default == ""

    default = _default_value(VariableLengthArrayType(ByteType(), 255))
    assert default == b""

    default = _default_value(VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 255))
    assert default == []


def _unittest_serdes_delimited() -> None:
    """
    Test delimited composite handling with nested structures and unions.
    """
    CM = PrimitiveType.CastMode

    inner = StructureType(
        name="test.Inner",
        version=Version(1, 0),
        attributes=[Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")],
        deprecated=False,
        fixed_port_id=None,
        source_file_path=Path("test", "Inner"),
        has_parent_service=False,
    )
    delimited_inner = DelimitedType(inner, inner.extent)

    outer = StructureType(
        name="test.Outer",
        version=Version(1, 0),
        attributes=[
            Field(delimited_inner, "nested"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "y"),
        ],
        deprecated=False,
        fixed_port_id=None,
        source_file_path=Path("test", "Outer"),
        has_parent_service=False,
    )

    w = _BitWriter()
    _serialize_composite(w, outer, {"nested": {"x": 42}, "y": 99})
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_composite(r, outer)
    assert result == {"nested": {"x": 42}, "y": 99}

    w = _BitWriter()
    inner_union = UnionType(
        name="test.InnerU",
        version=Version(1, 0),
        attributes=[
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "b"),
        ],
        deprecated=False,
        fixed_port_id=None,
        source_file_path=Path("test", "InnerU"),
        has_parent_service=False,
    )
    delimited_union = DelimitedType(inner_union, inner_union.extent)

    outer_with_union = StructureType(
        name="test.OuterU",
        version=Version(1, 0),
        attributes=[
            Field(delimited_union, "nested"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "y"),
        ],
        deprecated=False,
        fixed_port_id=None,
        source_file_path=Path("test", "OuterU"),
        has_parent_service=False,
    )

    w = _BitWriter()
    _serialize_composite(w, outer_with_union, {"nested": {"a": 42}, "y": 99})
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_composite(r, outer_with_union)
    assert result == {"nested": {"a": 42}, "y": 99}

    with pytest.raises(DelimiterHeaderError):
        w = _BitWriter()
        _serialize_composite(w, outer, {"nested": {"x": 42}, "y": 99})
        data = w.finish()

        r = _BitReader(data[:3])
        _ = _deserialize_composite(r, outer)


CM = PrimitiveType.CastMode


def _mk_structure(name: str, attributes: list[Field]) -> StructureType:
    return StructureType(
        name=name,
        version=Version(1, 0),
        attributes=attributes,
        deprecated=False,
        fixed_port_id=None,
        source_file_path=Path("test", name.split(".")[-1]),
        has_parent_service=False,
    )


def _mk_union(name: str, attributes: list[Field]) -> UnionType:
    return UnionType(
        name=name,
        version=Version(1, 0),
        attributes=attributes,
        deprecated=False,
        fixed_port_id=None,
        source_file_path=Path("test", name.split(".")[-1]),
        has_parent_service=False,
    )


def test_serialize_delimited_with_header() -> None:
    inner = _mk_structure("test.InnerA1", [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")])
    schema = DelimitedType(inner, inner.extent)
    obj = {"x": 123}

    bare = serialize(schema, obj)
    explicit_bare = serialize(schema, obj, with_delimiter_header=False)
    with_header = serialize(schema, obj, with_delimiter_header=True)

    assert bare == explicit_bare == bytes([123])
    assert len(with_header) == 5
    assert with_header[:4] == bytes([1, 0, 0, 0])
    assert with_header[4:] == bytes([123])


def test_deserialize_delimited_with_header() -> None:
    inner = _mk_structure("test.InnerA2", [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")])
    schema = DelimitedType(inner, inner.extent)
    obj = {"x": 42}

    payload = serialize(schema, obj)
    with_header = serialize(schema, obj, with_delimiter_header=True)

    assert deserialize(schema, payload) == obj
    assert deserialize(schema, payload, with_delimiter_header=False) == obj
    assert deserialize(schema, with_header, with_delimiter_header=True) == obj

    with pytest.raises(DelimiterHeaderError, match="Delimiter header specifies"):
        deserialize(schema, bytes([2, 0, 0, 0, 1]), with_delimiter_header=True)


def test_serialize_plain_composite_via_api() -> None:
    schema = _mk_structure(
        "test.PlainA3",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"), Field(BooleanType(), "b")],
    )
    assert serialize(schema, {"a": 7, "b": True}) == bytes([7, 1])


def test_deserialize_plain_composite_via_api() -> None:
    schema = _mk_structure(
        "test.PlainA4",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"), Field(BooleanType(), "b")],
    )
    assert deserialize(schema, bytes([8, 0])) == {"a": 8, "b": False}


def test_primitive_float16() -> None:
    w = _BitWriter()
    schema = FloatType(16, CM.SATURATED)
    _serialize_primitive(w, schema, 1.5)
    out = w.finish()
    assert len(out) == 2
    r = _BitReader(out)
    value = _deserialize_primitive(r, schema)
    assert isinstance(value, float)
    assert abs(value - 1.5) < 0.01


def test_primitive_float_saturated_special_values(special: float) -> None:
    schema = FloatType(32, CM.SATURATED)
    w = _BitWriter()
    _serialize_primitive(w, schema, special)
    value = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert isinstance(value, float)
    if math.isnan(special):
        assert math.isnan(value)
    elif special > 0:
        assert value == float("inf")
    else:
        assert value == float("-inf")


def test_primitive_float_truncated_mode() -> None:
    schema = FloatType(32, CM.TRUNCATED)
    w = _BitWriter()
    _serialize_primitive(w, schema, 1.234)
    value = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert isinstance(value, float)
    assert abs(float(value) - 1.234) < 1e-6


def test_primitive_bool_from_float(value: float, expected: bool | None, should_fail: bool) -> None:
    w = _BitWriter()
    if should_fail:
        with pytest.raises(ValueError, match="Non-finite float"):
            _serialize_primitive(w, BooleanType(), value)
    else:
        _serialize_primitive(w, BooleanType(), value)
        decoded = _deserialize_primitive(_BitReader(w.finish()), BooleanType())
        assert decoded is expected


def test_primitive_signed_truncated_mode() -> None:
    schema = SignedIntegerType(8, CM.SATURATED)
    schema._cast_mode = CM.TRUNCATED
    w = _BitWriter()
    _serialize_primitive(w, schema, -1)
    assert w.finish() == bytes([0xFF])


def test_primitive_float_to_int_coercion() -> None:
    w = _BitWriter()
    _serialize_primitive(w, UnsignedIntegerType(8, CM.TRUNCATED), 2.6)
    assert _deserialize_primitive(_BitReader(w.finish()), UnsignedIntegerType(8, CM.TRUNCATED)) == 3


def test_primitive_unknown_type_error() -> None:
    with pytest.raises(ValueError, match="Unknown primitive type"):
        _serialize_primitive(_BitWriter(), typing.cast(typing.Any, object()), 0)

    with pytest.raises(ValueError, match="Unknown primitive type"):
        _deserialize_primitive(_BitReader(bytes([0])), typing.cast(typing.Any, object()))


def test_primitive_invalid_float_bit_length_paths() -> None:
    bad = FloatType(32, CM.SATURATED)
    bad._bit_length = 24

    with pytest.raises(ValueError, match="Invalid float bit length"):
        _serialize_primitive(_BitWriter(), bad, 1.0)

    with pytest.raises(ValueError, match="Invalid float bit length"):
        _deserialize_primitive(_BitReader(bytes([0, 0, 0])), bad)


def test_primitive_input_validation_errors() -> None:
    with pytest.raises(ValueError, match="Boolean requires numeric input"):
        _serialize_primitive(_BitWriter(), BooleanType(), "x")

    with pytest.raises(ValueError, match="Float requires numeric input"):
        _serialize_primitive(_BitWriter(), FloatType(32, CM.SATURATED), "x")

    with pytest.raises(ValueError, match="Integer requires numeric input"):
        _serialize_primitive(_BitWriter(), SignedIntegerType(8, CM.SATURATED), "x")

    with pytest.raises(ValueError, match="Non-finite float cannot be converted to int"):
        _serialize_primitive(_BitWriter(), SignedIntegerType(8, CM.SATURATED), float("inf"))


def test_float_widths_parametrized(width: int) -> None:
    schema = FloatType(width, CM.SATURATED)
    w = _BitWriter()
    _serialize_primitive(w, schema, 0.5)
    value = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert isinstance(value, float)
    assert abs(float(value) - 0.5) < 0.01


def test_unsigned_integer_widths_and_cast_modes_parametrized(width: int, cast_mode: PrimitiveType.CastMode) -> None:
    schema = UnsignedIntegerType(width, cast_mode)
    value = (1 << width) + 1
    w = _BitWriter()
    _serialize_primitive(w, schema, value)
    decoded = _deserialize_primitive(_BitReader(w.finish()), schema)
    expected = ((1 << width) - 1) if cast_mode == CM.SATURATED else 1
    assert decoded == expected


def test_array_byte_from_list_input(container: list[int] | tuple[int, ...]) -> None:
    schema = VariableLengthArrayType(ByteType(), 8)
    w = _BitWriter()
    _serialize_array(w, schema, container)
    assert _deserialize_array(_BitReader(w.finish()), schema) == b"hi"


def test_array_byte_type_error() -> None:
    schema = VariableLengthArrayType(ByteType(), 8)
    with pytest.raises(TypeError, match="Byte array requires"):
        _serialize_array(_BitWriter(), schema, 123)


def test_array_utf8_type_error() -> None:
    schema = VariableLengthArrayType(UTF8Type(), 8)
    with pytest.raises(TypeError, match="UTF-8 array requires"):
        _serialize_array(_BitWriter(), schema, 123)


def test_array_unknown_type_error() -> None:
    class MockArray:
        element_type = UnsignedIntegerType(8, CM.TRUNCATED)

    with pytest.raises(ValueError, match="Unknown array type"):
        _serialize_array(_BitWriter(), typing.cast(ArrayType, typing.cast(object, MockArray())), [1])

    with pytest.raises(ValueError, match="Unknown array type"):
        _deserialize_array(_BitReader(bytes([1])), typing.cast(ArrayType, typing.cast(object, MockArray())))


def test_array_deserialized_length_overflow() -> None:
    schema = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 2)
    with pytest.raises(ArrayLengthError, match="exceeds capacity"):
        _deserialize_array(_BitReader(bytes([3, 1, 2, 3])), schema)


def test_array_composite_elements() -> None:
    elem = _mk_structure("test.ArrayElem", [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")])
    schema = FixedLengthArrayType(elem, 2)
    w = _BitWriter()
    _serialize_array(w, schema, [{"x": 1}, {"x": 2}])
    assert _deserialize_array(_BitReader(w.finish()), schema) == [{"x": 1}, {"x": 2}]


def test_array_nested_array_elements() -> None:
    inner = FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 2)
    outer = FixedLengthArrayType(inner, 2)
    w = _BitWriter()
    _serialize_array(w, outer, [[5, 6], [7, 8]])
    assert _deserialize_array(_BitReader(w.finish()), outer) == [[5, 6], [7, 8]]


def test_element_unknown_type_error() -> None:
    with pytest.raises(ValueError, match="Unknown element type"):
        _serialize_element(_BitWriter(), object(), 1)

    with pytest.raises(ValueError, match="Unknown element type"):
        _deserialize_element(_BitReader(bytes([0])), object())


def test_composite_union_non_dict_error() -> None:
    schema = _mk_union(
        "test.Undict",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"), Field(UnsignedIntegerType(8, CM.TRUNCATED), "b")],
    )
    with pytest.raises(ValueError, match="Union value must be a dict"):
        _serialize_composite(_BitWriter(), schema, typing.cast(_Obj, typing.cast(object, "bad")))


def test_composite_service_type_error() -> None:
    class MockServiceType(ServiceType):
        pass

    schema = MockServiceType.__new__(MockServiceType)
    with pytest.raises(TypeError, match="not directly serializable"):
        _serialize_composite(_BitWriter(), schema, {})
    with pytest.raises(TypeError, match="not directly deserializable"):
        _deserialize_composite(_BitReader(bytes([0])), schema)


def test_composite_unknown_type_error() -> None:
    class MockComposite:
        pass

    with pytest.raises(ValueError, match="Unknown composite type"):
        _serialize_composite(_BitWriter(), typing.cast(typing.Any, MockComposite()), {})

    with pytest.raises(ValueError, match="Unknown composite type"):
        _deserialize_composite(_BitReader(bytes([0])), typing.cast(typing.Any, MockComposite()))


def test_composite_delimited_in_composite() -> None:
    inner = _mk_structure("test.InnerD1", [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")])
    delimited = DelimitedType(inner, inner.extent)
    outer = _mk_structure(
        "test.OuterD1",
        [Field(delimited, "nested"), Field(UnsignedIntegerType(8, CM.TRUNCATED), "y")],
    )
    obj = {"nested": {"x": 9}, "y": 10}
    data = serialize(outer, obj)
    assert deserialize(outer, data) == obj


def test_composite_deserialized_delimited_truncated() -> None:
    inner = _mk_structure("test.InnerD2", [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")])
    delimited = DelimitedType(inner, inner.extent)
    with pytest.raises(DelimiterHeaderError, match="Delimiter header specifies"):
        _deserialize_composite(_BitReader(bytes([2, 0, 0, 0, 1])), delimited)


def test_composite_deserialize_union_invalid_tag() -> None:
    schema = _mk_union(
        "test.BadTag",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"), Field(UnsignedIntegerType(8, CM.TRUNCATED), "b")],
    )
    with pytest.raises(UnionTagError, match="Invalid union tag"):
        _deserialize_composite(_BitReader(bytes([255])), schema)


def test_composite_struct_padding_field() -> None:
    schema = _mk_structure(
        "test.WithPadding",
        [Field(UnsignedIntegerType(3, CM.TRUNCATED), "a"), PaddingField(VoidType(5)), Field(BooleanType(), "b")],
    )
    data = serialize(schema, {"a": 5, "b": True})
    assert data == bytes([0b00000101, 0b00000001])
    assert deserialize(schema, data) == {"a": 5, "b": True}


def test_field_value_unknown_type_error() -> None:
    with pytest.raises(ValueError, match="Unknown field type"):
        _serialize_field_value(_BitWriter(), object(), 1)
    with pytest.raises(ValueError, match="Unknown field type"):
        _deserialize_field_value(_BitReader(bytes([0])), object())


def test_field_value_composite_in_struct() -> None:
    inner = _mk_structure("test.InnerField", [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")])
    outer = _mk_structure("test.OuterField", [Field(inner, "inner")])
    obj = {"inner": {"x": 77}}
    assert deserialize(outer, serialize(outer, obj)) == obj


def test_field_value_array_in_struct() -> None:
    arr = FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 3)
    schema = _mk_structure("test.ArrayField", [Field(arr, "items")])
    obj = {"items": [1, 2, 3]}
    assert deserialize(schema, serialize(schema, obj)) == obj


def test_default_value_all_types() -> None:
    struct_inner = _mk_structure("test.DefaultStruct", [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")])
    union_inner = _mk_union(
        "test.DefaultUnion",
        [Field(BooleanType(), "flag"), Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")],
    )
    delimited = DelimitedType(struct_inner, struct_inner.extent)

    assert _default_value(BooleanType()) is False
    assert _default_value(SignedIntegerType(8, CM.SATURATED)) == 0
    assert _default_value(UnsignedIntegerType(8, CM.TRUNCATED)) == 0
    assert _default_value(FloatType(32, CM.SATURATED)) == 0.0
    assert _default_value(VoidType(8)) is None
    assert _default_value(FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 2)) == [0, 0]
    assert _default_value(VariableLengthArrayType(UTF8Type(), 4)) == ""
    assert _default_value(VariableLengthArrayType(ByteType(), 4)) == b""
    assert _default_value(VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 4)) == []
    assert _default_value(struct_inner) == {"x": 0}
    assert _default_value(union_inner) == {"flag": False}
    assert _default_value(delimited) == {"x": 0}

    with pytest.raises(ValueError, match="Unknown type for default value"):
        _default_value(object())


def test_default_value_struct_with_missing_fields() -> None:
    nested = _mk_structure("test.NestedDefault", [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")])
    schema = _mk_structure(
        "test.MissingDefaults",
        [
            Field(BooleanType(), "flag"),
            Field(FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 2), "arr"),
            Field(nested, "nested"),
        ],
    )
    assert deserialize(schema, serialize(schema, {})) == {"flag": False, "arr": [0, 0], "nested": {"x": 0}}


def test_bit_writer_align_to_zero() -> None:
    w = _BitWriter()
    w.write_bits(0b101, 3)
    before = w.bit_offset
    w.align_to(0)
    assert w.bit_offset == before
    w.align_to(-1)
    assert w.bit_offset == before


def test_bit_reader_align_to_zero() -> None:
    r = _BitReader(bytes([0xFF]))
    _ = r.read_bits(3)
    before = r.bit_offset
    r.align_to(0)
    assert r.bit_offset == before


def test_bit_reader_remaining_bits_with_limit() -> None:
    parent = _BitReader(bytes([0x12, 0x34]))
    child = parent.bounded_subreader(8)
    assert child.remaining_bits == 8
    _ = child.read_bits(4)
    assert child.remaining_bits == 4
    _ = child.read_bits(4)
    assert child.remaining_bits == 0


def _pack_chunks_lsb_first(chunks: list[tuple[int, int]]) -> bytes:
    total_value = 0
    total_bit_length = 0
    for value, bit_length in chunks:
        total_value |= (value & ((1 << bit_length) - 1)) << total_bit_length
        total_bit_length += bit_length
    return total_value.to_bytes((total_bit_length + 7) // 8, "little")


def test_bit_io_aligned_roundtrip() -> None:
    cases = [
        (0xAB, 8),
        (0xABCD, 16),
        (0xDEADBEEF, 32),
        (0x0123456789ABCDEF, 64),
    ]

    for value, bit_length in cases:
        expected = value.to_bytes(bit_length // 8, "little")
        writer = _BitWriter()
        writer.write_bits(value, bit_length)
        encoded = writer.finish()
        assert encoded == expected
        assert writer.bit_offset == bit_length

        reader = _BitReader(encoded)
        assert reader.read_bits(bit_length) == value
        assert reader.bit_offset == bit_length


def test_bit_io_aligned_non_multiple_of_byte() -> None:
    value = 0xABC
    bit_length = 12
    expected = _pack_chunks_lsb_first([(value, bit_length)])

    writer = _BitWriter()
    writer.write_bits(value, bit_length)
    encoded = writer.finish()
    assert encoded == expected

    reader = _BitReader(encoded)
    assert reader.read_bits(bit_length) == value


def test_bit_io_unaligned_sequence() -> None:
    chunks = [(0b101, 3), (0xABCD, 16), (0b11, 2)]
    expected = _pack_chunks_lsb_first(chunks)

    writer = _BitWriter()
    for value, bit_length in chunks:
        writer.write_bits(value, bit_length)
    encoded = writer.finish()
    assert encoded == expected

    reader = _BitReader(encoded)
    for value, bit_length in chunks:
        assert reader.read_bits(bit_length) == value


def test_bit_io_mixed_aligned_unaligned_sequence() -> None:
    chunks_before_alignment = [(0xEF, 8), (0b101, 3), (0x5A, 8)]
    alignment_padding = 5
    chunks_after_alignment = [(0xBEEF, 16)]
    expected = _pack_chunks_lsb_first(chunks_before_alignment + [(0, alignment_padding)] + chunks_after_alignment)

    writer = _BitWriter()
    for value, bit_length in chunks_before_alignment:
        writer.write_bits(value, bit_length)
    writer.align_to(8)
    for value, bit_length in chunks_after_alignment:
        writer.write_bits(value, bit_length)
    encoded = writer.finish()
    assert encoded == expected

    reader = _BitReader(encoded)
    for value, bit_length in chunks_before_alignment:
        assert reader.read_bits(bit_length) == value
    reader.align_to(8)
    for value, bit_length in chunks_after_alignment:
        assert reader.read_bits(bit_length) == value


def _unittest_serdes_branch_coverage_tests() -> None:
    test_serialize_delimited_with_header()
    test_deserialize_delimited_with_header()
    test_serialize_plain_composite_via_api()
    test_deserialize_plain_composite_via_api()

    test_primitive_float16()
    for special in [float("nan"), float("inf"), float("-inf")]:
        test_primitive_float_saturated_special_values(special)
    test_primitive_float_truncated_mode()
    test_primitive_bool_from_float(1.0, True, False)
    test_primitive_bool_from_float(0.0, False, False)
    test_primitive_bool_from_float(float("nan"), None, True)
    test_primitive_signed_truncated_mode()
    test_primitive_float_to_int_coercion()
    test_primitive_unknown_type_error()
    test_primitive_invalid_float_bit_length_paths()
    test_primitive_input_validation_errors()
    for width in [16, 32, 64]:
        test_float_widths_parametrized(width)
    for width in [2, 3, 5, 8, 16, 32, 64]:
        for cast_mode in [CM.SATURATED, CM.TRUNCATED]:
            test_unsigned_integer_widths_and_cast_modes_parametrized(width, cast_mode)

    test_array_byte_from_list_input([104, 105])
    test_array_byte_from_list_input((104, 105))
    test_array_byte_type_error()
    test_array_utf8_type_error()
    test_array_unknown_type_error()
    test_array_deserialized_length_overflow()
    test_array_composite_elements()
    test_array_nested_array_elements()
    test_element_unknown_type_error()

    test_composite_union_non_dict_error()
    test_composite_service_type_error()
    test_composite_unknown_type_error()
    test_composite_delimited_in_composite()
    test_composite_deserialized_delimited_truncated()
    test_composite_deserialize_union_invalid_tag()
    test_composite_struct_padding_field()
    test_field_value_unknown_type_error()
    test_field_value_composite_in_struct()
    test_field_value_array_in_struct()
    test_default_value_all_types()
    test_default_value_struct_with_missing_fields()

    test_bit_writer_align_to_zero()
    test_bit_reader_align_to_zero()
    test_bit_reader_remaining_bits_with_limit()
    test_bit_io_aligned_roundtrip()
    test_bit_io_aligned_non_multiple_of_byte()
    test_bit_io_unaligned_sequence()
    test_bit_io_mixed_aligned_unaligned_sequence()
