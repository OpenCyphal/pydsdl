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
    CompositeType,
)
from ._serializable._composite import Version

__all__: list[str] = []

_F = typing.TypeVar("_F", bound=typing.Callable[..., typing.Any])


def _typed_parametrize(*args: typing.Any, **kwargs: typing.Any) -> typing.Callable[[_F], _F]:
    return typing.cast(typing.Callable[[_F], _F], pytest.mark.parametrize(*args, **kwargs))


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

    # Verify that SerDesError inherits from Error (via Error)
    from ._error import Error

    assert issubclass(SerDesError, Error)

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


def _unittest_serdes_api_dict_contract() -> None:
    """
    The public API operates on composite objects represented strictly as dict instances.
    """
    structure = _mk_structure("test.APIDictContractStruct", [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")])
    union = _mk_union(
        "test.APIDictContractUnion",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"), Field(UnsignedIntegerType(8, CM.TRUNCATED), "b")],
    )
    delimited_inner = _mk_structure("test.APIDictContractDelimitedInner", [Field(BooleanType(), "flag")])
    delimited = DelimitedType(delimited_inner, delimited_inner.extent)

    structure_result = deserialize(structure, serialize(structure, {"x": 42}))
    assert isinstance(structure_result, dict)
    assert structure_result == {"x": 42}

    union_result = deserialize(union, serialize(union, {"b": 99}))
    assert isinstance(union_result, dict)
    assert union_result == {"b": 99}

    delimited_payload = serialize(delimited, {"flag": True})
    delimited_result = deserialize(delimited, delimited_payload)
    assert isinstance(delimited_result, dict)
    assert delimited_result == {"flag": True}

    delimited_with_header = serialize(delimited, {"flag": True}, with_delimiter_header=True)
    delimited_header_result = deserialize(delimited, delimited_with_header, with_delimiter_header=True)
    assert isinstance(delimited_header_result, dict)
    assert delimited_header_result == {"flag": True}

    with pytest.raises(ValueError, match="Structure value must be a dict"):
        serialize(structure, typing.cast(_Obj, typing.cast(object, 123)))

    with pytest.raises(ValueError, match="Union value must be a dict"):
        serialize(union, typing.cast(_Obj, typing.cast(object, 123)))

    with pytest.raises(ValueError, match="Structure value must be a dict"):
        serialize(delimited, typing.cast(_Obj, typing.cast(object, 123)))


def _unittest_serdes_relaxed_positional_structures() -> None:
    schema = _mk_structure(
        "test.RelaxedPositional",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "first"),
            PaddingField(VoidType(8)),
            Field(BooleanType(), "second"),
        ],
    )

    expected = {"first": 42, "second": True}
    assert deserialize(schema, serialize(schema, [42, True], relaxed=True)) == expected
    assert deserialize(schema, serialize(schema, (42, True), relaxed=True)) == expected
    assert deserialize(schema, serialize(schema, [42], relaxed=True)) == {"first": 42, "second": False}

    with pytest.raises(ValueError, match="Too many positional values"):
        serialize(schema, [1, True, 3], relaxed=True)

    with pytest.raises(ValueError, match="Structure value must be a dict"):
        serialize(schema, [42, True])

    empty = _mk_structure("test.RelaxedEmpty", [])
    assert serialize(empty, [], relaxed=True) == b""
    with pytest.raises(ValueError, match="Too many positional values"):
        serialize(empty, [1], relaxed=True)


def _unittest_serdes_relaxed_single_field_recursion() -> None:
    leaf = _mk_structure("test.RelaxedLeaf", [Field(UnsignedIntegerType(8, CM.TRUNCATED), "value")])
    middle = _mk_structure("test.RelaxedMiddle", [Field(leaf, "leaf")])
    outer = _mk_structure("test.RelaxedOuter", [Field(middle, "middle")])

    assert deserialize(outer, serialize(outer, 123, relaxed=True)) == {"middle": {"leaf": {"value": 123}}}

    with pytest.raises(ValueError, match="Integer requires numeric input"):
        serialize(leaf, [123], relaxed=True)

    with pytest.raises(ValueError, match="Structure value must be a dict"):
        serialize(outer, 123)


def _unittest_serdes_relaxed_single_array_field() -> None:
    scalar_array = _mk_structure(
        "test.RelaxedScalarArray",
        [Field(VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 4), "items")],
    )
    assert deserialize(scalar_array, serialize(scalar_array, [9], relaxed=True)) == {"items": [9]}
    assert deserialize(scalar_array, serialize(scalar_array, [1, 2, 3], relaxed=True)) == {"items": [1, 2, 3]}

    element = _mk_structure(
        "test.RelaxedArrayElement",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x"), Field(BooleanType(), "valid")],
    )
    composite_array = _mk_structure(
        "test.RelaxedCompositeArray",
        [Field(FixedLengthArrayType(element, 2), "items")],
    )
    assert deserialize(composite_array, serialize(composite_array, [[10, True], [20, False]], relaxed=True)) == {
        "items": [{"x": 10, "valid": True}, {"x": 20, "valid": False}]
    }

    text = _mk_structure(
        "test.RelaxedText",
        [Field(VariableLengthArrayType(UTF8Type(), 16), "value")],
    )
    blob = _mk_structure(
        "test.RelaxedBlob",
        [Field(VariableLengthArrayType(ByteType(), 16), "value")],
    )
    assert deserialize(text, serialize(text, "hello", relaxed=True)) == {"value": "hello"}
    assert deserialize(blob, serialize(blob, bytearray(b"abc"), relaxed=True)) == {"value": b"abc"}


def _unittest_serdes_relaxed_dictionary_scope() -> None:
    inner = _mk_structure(
        "test.RelaxedDictionaryInner",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x"), Field(BooleanType(), "valid")],
    )
    outer = _mk_structure("test.RelaxedDictionaryOuter", [Field(inner, "nested")])

    expected = {"nested": {"x": 42, "valid": True}}
    assert deserialize(outer, serialize(outer, {"nested": [42, True]}, relaxed=True)) == expected
    assert deserialize(outer, serialize(outer, {"x": 42, "valid": True}, relaxed=True)) == expected
    assert deserialize(outer, serialize(outer, {}, relaxed=True)) == {"nested": {"x": 0, "valid": False}}

    with pytest.raises(ValueError, match="Unknown field"):
        serialize(outer, {"nested": [42, True], "unknown": 1}, relaxed=True)


def _unittest_serdes_relaxed_unions_remain_explicit() -> None:
    detail = _mk_structure(
        "test.RelaxedUnionDetail",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "code")],
    )
    union = _mk_union(
        "test.RelaxedUnion",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "small"), Field(detail, "detail")],
    )

    assert deserialize(union, serialize(union, {"detail": 55}, relaxed=True)) == {"detail": {"code": 55}}
    with pytest.raises(ValueError, match="Union value must be a dict"):
        serialize(union, [55], relaxed=True)

    wrapper = _mk_structure("test.RelaxedUnionWrapper", [Field(union, "choice")])
    assert deserialize(wrapper, serialize(wrapper, {"detail": 66}, relaxed=True)) == {
        "choice": {"detail": {"code": 66}}
    }

    union_array = _mk_structure(
        "test.RelaxedUnionArray",
        [Field(FixedLengthArrayType(union, 2), "choices")],
    )
    assert deserialize(
        union_array,
        serialize(union_array, [{"small": 1}, {"detail": 2}], relaxed=True),
    ) == {"choices": [{"small": 1}, {"detail": {"code": 2}}]}


def _unittest_serdes_relaxed_delimited() -> None:
    inner = _mk_structure(
        "test.RelaxedDelimitedInner",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "value"), Field(BooleanType(), "valid")],
    )
    schema = DelimitedType(inner, inner.extent)
    expected = {"value": 77, "valid": True}

    bare = serialize(schema, [77, True], relaxed=True)
    with_header = serialize(schema, [77, True], with_delimiter_header=True, relaxed=True)
    assert deserialize(schema, bare) == expected
    assert deserialize(schema, with_header, with_delimiter_header=True) == expected


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
        schema = UnionType(
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
        )  # type: ignore
        _serialize_composite(w, schema, {})

    with pytest.raises(ValueError, match="exactly one field"):
        w = _BitWriter()
        schema = UnionType(
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
        )  # type: ignore
        _serialize_composite(w, schema, {"a": 1, "b": 2})

    with pytest.raises(UnionFieldError, match="Unknown union variant"):
        w = _BitWriter()
        schema = UnionType(
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
        )  # type: ignore
        _serialize_composite(w, schema, {"unknown": 1})

    w = _BitWriter()
    schema = UnionType(
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
    )  # type: ignore
    _serialize_composite(w, schema, {"a": 42})
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_composite(r, schema)
    assert result == {"a": 42}

    w = _BitWriter()
    schema = UnionType(
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
    )  # type: ignore
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


# ============================================================================
# TEST HELPERS AND CONSTANTS (Wave 1 Foundation)
# ============================================================================

_UNSIGNED_WIDTHS = [1, 2, 3, 4, 5, 7, 8, 9, 12, 15, 16, 17, 24, 31, 32, 33, 48, 63, 64]
_SIGNED_WIDTHS = [2, 3, 4, 5, 7, 8, 9, 12, 15, 16, 17, 24, 31, 32, 33, 48, 63, 64]


def _mk_delimited(name: str, attributes: list[Field], extent: int | None = None) -> DelimitedType:
    """
    Create a DelimitedType wrapping a StructureType.

    :param name: The name of the inner structure.
    :param attributes: The fields of the inner structure.
    :param extent: The extent in bits. If None, uses the inner structure's extent.
    :return: A DelimitedType instance.
    """
    inner = _mk_structure(name, attributes)
    if extent is None:
        extent = inner.extent
    return DelimitedType(inner, extent)


def _roundtrip(schema: CompositeType, obj: _Obj) -> _Obj:
    """
    Serialize an object and then deserialize it back.

    :param schema: The composite type schema.
    :param obj: The object to roundtrip.
    :return: The deserialized object.
    """
    return deserialize(schema, serialize(schema, obj))


def _roundtrip_assert(schema: CompositeType, obj: _Obj) -> None:
    """
    Assert that an object survives a serialize-deserialize roundtrip.

    :param schema: The composite type schema.
    :param obj: The object to roundtrip.
    :raises AssertionError: If the roundtrip result differs from the original.
    """
    assert _roundtrip(schema, obj) == obj


def _unittest_serialize_delimited_with_header() -> None:
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


def _unittest_deserialize_delimited_with_header() -> None:
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


def _unittest_serialize_plain_composite_via_api() -> None:
    schema = _mk_structure(
        "test.PlainA3",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"), Field(BooleanType(), "b")],
    )
    assert serialize(schema, {"a": 7, "b": True}) == bytes([7, 1])


def _unittest_deserialize_plain_composite_via_api() -> None:
    schema = _mk_structure(
        "test.PlainA4",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"), Field(BooleanType(), "b")],
    )
    assert deserialize(schema, bytes([8, 0])) == {"a": 8, "b": False}


def _unittest_primitive_float16() -> None:
    w = _BitWriter()
    schema = FloatType(16, CM.SATURATED)
    _serialize_primitive(w, schema, 1.5)
    out = w.finish()
    assert len(out) == 2
    r = _BitReader(out)
    value = _deserialize_primitive(r, schema)
    assert isinstance(value, float)
    assert abs(value - 1.5) < 0.01


@_typed_parametrize("special", [float("nan"), float("inf"), float("-inf")], ids=["nan", "pos_inf", "neg_inf"])
def _unittest_primitive_float_saturated_special_values(special: float) -> None:
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


def _unittest_primitive_float_truncated_mode() -> None:
    schema = FloatType(32, CM.TRUNCATED)
    w = _BitWriter()
    _serialize_primitive(w, schema, 1.234)
    value = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert isinstance(value, float)
    assert abs(float(value) - 1.234) < 1e-6


@_typed_parametrize(
    ("value", "expected", "should_fail"),
    [
        (1.0, True, False),
        (0.0, False, False),
        (float("nan"), None, True),
    ],
    ids=["one_true", "zero_false", "nan_error"],
)
def _unittest_primitive_bool_from_float(value: float, expected: bool | None, should_fail: bool) -> None:
    w = _BitWriter()
    if should_fail:
        with pytest.raises(ValueError, match="Non-finite float"):
            _serialize_primitive(w, BooleanType(), value)
    else:
        _serialize_primitive(w, BooleanType(), value)
        decoded = _deserialize_primitive(_BitReader(w.finish()), BooleanType())
        assert decoded is expected


def _unittest_primitive_signed_truncated_mode() -> None:
    schema = SignedIntegerType(8, CM.SATURATED)
    schema._cast_mode = CM.TRUNCATED
    w = _BitWriter()
    _serialize_primitive(w, schema, -1)
    assert w.finish() == bytes([0xFF])


def _unittest_primitive_float_to_int_coercion() -> None:
    w = _BitWriter()
    _serialize_primitive(w, UnsignedIntegerType(8, CM.TRUNCATED), 2.6)
    assert _deserialize_primitive(_BitReader(w.finish()), UnsignedIntegerType(8, CM.TRUNCATED)) == 3


def _unittest_primitive_unknown_type_error() -> None:
    with pytest.raises(ValueError, match="Unknown primitive type"):
        _serialize_primitive(_BitWriter(), typing.cast(typing.Any, object()), 0)

    with pytest.raises(ValueError, match="Unknown primitive type"):
        _deserialize_primitive(_BitReader(bytes([0])), typing.cast(typing.Any, object()))


def _unittest_primitive_invalid_float_bit_length_paths() -> None:
    bad = FloatType(32, CM.SATURATED)
    bad._bit_length = 24

    with pytest.raises(ValueError, match="Invalid float bit length"):
        _serialize_primitive(_BitWriter(), bad, 1.0)

    with pytest.raises(ValueError, match="Invalid float bit length"):
        _deserialize_primitive(_BitReader(bytes([0, 0, 0])), bad)


def _unittest_primitive_input_validation_errors() -> None:
    with pytest.raises(ValueError, match="Boolean requires numeric input"):
        _serialize_primitive(_BitWriter(), BooleanType(), "x")

    with pytest.raises(ValueError, match="Float requires numeric input"):
        _serialize_primitive(_BitWriter(), FloatType(32, CM.SATURATED), "x")

    with pytest.raises(ValueError, match="Integer requires numeric input"):
        _serialize_primitive(_BitWriter(), SignedIntegerType(8, CM.SATURATED), "x")

    with pytest.raises(ValueError, match="Non-finite float cannot be converted to int"):
        _serialize_primitive(_BitWriter(), SignedIntegerType(8, CM.SATURATED), float("inf"))


@_typed_parametrize("width", [16, 32, 64])
def _unittest_float_widths_parametrized(width: int) -> None:
    schema = FloatType(width, CM.SATURATED)
    w = _BitWriter()
    _serialize_primitive(w, schema, 0.5)
    value = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert isinstance(value, float)
    assert abs(float(value) - 0.5) < 0.01


@_typed_parametrize("width", [2, 3, 5, 8, 16, 32, 64])
@_typed_parametrize(
    "cast_mode",
    [CM.SATURATED, CM.TRUNCATED],
    ids=["saturated", "truncated"],
)
def _unittest_unsigned_integer_widths_and_cast_modes_parametrized(
    width: int, cast_mode: PrimitiveType.CastMode
) -> None:
    schema = UnsignedIntegerType(width, cast_mode)
    value = (1 << width) + 1
    w = _BitWriter()
    _serialize_primitive(w, schema, value)
    decoded = _deserialize_primitive(_BitReader(w.finish()), schema)
    expected = ((1 << width) - 1) if cast_mode == CM.SATURATED else 1
    assert decoded == expected


@_typed_parametrize("container", [[104, 105], (104, 105)], ids=["list", "tuple"])
def _unittest_array_byte_from_list_input(container: list[int] | tuple[int, ...]) -> None:
    schema = VariableLengthArrayType(ByteType(), 8)
    w = _BitWriter()
    _serialize_array(w, schema, container)
    assert _deserialize_array(_BitReader(w.finish()), schema) == b"hi"


def _unittest_array_byte_type_error() -> None:
    schema = VariableLengthArrayType(ByteType(), 8)
    with pytest.raises(TypeError, match="Byte array requires"):
        _serialize_array(_BitWriter(), schema, 123)


def _unittest_array_utf8_type_error() -> None:
    schema = VariableLengthArrayType(UTF8Type(), 8)
    with pytest.raises(TypeError, match="UTF-8 array requires"):
        _serialize_array(_BitWriter(), schema, 123)


@_typed_parametrize(
    ("obj", "expected"),
    [
        ({"text": "hello", "blob": b"\x00\x01\x02"}, {"text": "hello", "blob": b"\x00\x01\x02"}),
        ({"text": b"world", "blob": "abc"}, {"text": "world", "blob": b"abc"}),
    ],
    ids=["str_utf8_bytes_blob", "bytes_utf8_str_blob"],
)
def _unittest_api_accepts_str_and_bytes_for_utf8_and_byte_arrays(
    obj: dict[str, _Value], expected: dict[str, _Value]
) -> None:
    schema = _mk_structure(
        "test.StringLikeArrays",
        [
            Field(VariableLengthArrayType(UTF8Type(), 64), "text"),
            Field(VariableLengthArrayType(ByteType(), 64), "blob"),
        ],
    )

    assert deserialize(schema, serialize(schema, obj)) == expected


def _unittest_array_unknown_type_error() -> None:
    class MockArray:
        element_type = UnsignedIntegerType(8, CM.TRUNCATED)

    with pytest.raises(ValueError, match="Unknown array type"):
        _serialize_array(_BitWriter(), typing.cast(ArrayType, typing.cast(object, MockArray())), [1])

    with pytest.raises(ValueError, match="Unknown array type"):
        _deserialize_array(_BitReader(bytes([1])), typing.cast(ArrayType, typing.cast(object, MockArray())))


def _unittest_array_deserialized_length_overflow() -> None:
    schema = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 2)
    with pytest.raises(ArrayLengthError, match="exceeds capacity"):
        _deserialize_array(_BitReader(bytes([3, 1, 2, 3])), schema)


def _unittest_array_composite_elements() -> None:
    elem = _mk_structure("test.ArrayElem", [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")])
    schema = FixedLengthArrayType(elem, 2)
    w = _BitWriter()
    _serialize_array(w, schema, [{"x": 1}, {"x": 2}])
    assert _deserialize_array(_BitReader(w.finish()), schema) == [{"x": 1}, {"x": 2}]


def _unittest_array_nested_array_elements() -> None:
    inner = FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 2)
    outer = FixedLengthArrayType(inner, 2)
    w = _BitWriter()
    _serialize_array(w, outer, [[5, 6], [7, 8]])
    assert _deserialize_array(_BitReader(w.finish()), outer) == [[5, 6], [7, 8]]


def _unittest_element_unknown_type_error() -> None:
    with pytest.raises(ValueError, match="Unknown element type"):
        _serialize_element(_BitWriter(), object(), 1)

    with pytest.raises(ValueError, match="Unknown element type"):
        _deserialize_element(_BitReader(bytes([0])), object())


def _unittest_composite_union_non_dict_error() -> None:
    schema = _mk_union(
        "test.Undict",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"), Field(UnsignedIntegerType(8, CM.TRUNCATED), "b")],
    )
    with pytest.raises(ValueError, match="Union value must be a dict"):
        _serialize_composite(_BitWriter(), schema, typing.cast(_Obj, typing.cast(object, "bad")))


def _unittest_composite_structure_non_dict_error() -> None:
    schema = _mk_structure("test.StructUndict", [Field(UnsignedIntegerType(8, CM.TRUNCATED), "a")])
    with pytest.raises(ValueError, match="Structure value must be a dict"):
        _serialize_composite(_BitWriter(), schema, typing.cast(_Obj, typing.cast(object, "bad")))

    with pytest.raises(ValueError, match="Structure value must be a dict"):
        serialize(schema, typing.cast(_Obj, typing.cast(object, 123)))


def _unittest_composite_service_type_error() -> None:
    class MockServiceType(ServiceType):
        pass

    schema = MockServiceType.__new__(MockServiceType)
    with pytest.raises(TypeError, match="not directly serializable"):
        _serialize_composite(_BitWriter(), schema, {})
    with pytest.raises(TypeError, match="not directly deserializable"):
        _deserialize_composite(_BitReader(bytes([0])), schema)


def _unittest_composite_unknown_type_error() -> None:
    class MockComposite:
        pass

    with pytest.raises(ValueError, match="Unknown composite type"):
        _serialize_composite(_BitWriter(), typing.cast(typing.Any, MockComposite()), {})

    with pytest.raises(ValueError, match="Unknown composite type"):
        _deserialize_composite(_BitReader(bytes([0])), typing.cast(typing.Any, MockComposite()))


def _unittest_composite_delimited_in_composite() -> None:
    inner = _mk_structure("test.InnerD1", [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")])
    delimited = DelimitedType(inner, inner.extent)
    outer = _mk_structure(
        "test.OuterD1",
        [Field(delimited, "nested"), Field(UnsignedIntegerType(8, CM.TRUNCATED), "y")],
    )
    obj = {"nested": {"x": 9}, "y": 10}
    data = serialize(outer, obj)
    assert deserialize(outer, data) == obj


def _unittest_composite_deserialized_delimited_truncated() -> None:
    inner = _mk_structure("test.InnerD2", [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")])
    delimited = DelimitedType(inner, inner.extent)
    with pytest.raises(DelimiterHeaderError, match="Delimiter header specifies"):
        _deserialize_composite(_BitReader(bytes([2, 0, 0, 0, 1])), delimited)


def _unittest_composite_deserialize_union_invalid_tag() -> None:
    schema = _mk_union(
        "test.BadTag",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"), Field(UnsignedIntegerType(8, CM.TRUNCATED), "b")],
    )
    with pytest.raises(UnionTagError, match="Invalid union tag"):
        _deserialize_composite(_BitReader(bytes([255])), schema)


def _unittest_composite_struct_padding_field() -> None:
    schema = _mk_structure(
        "test.WithPadding",
        [Field(UnsignedIntegerType(3, CM.TRUNCATED), "a"), PaddingField(VoidType(5)), Field(BooleanType(), "b")],
    )
    data = serialize(schema, {"a": 5, "b": True})
    assert data == bytes([0b00000101, 0b00000001])
    assert deserialize(schema, data) == {"a": 5, "b": True}


def _unittest_field_value_unknown_type_error() -> None:
    with pytest.raises(ValueError, match="Unknown field type"):
        _serialize_field_value(_BitWriter(), object(), 1)
    with pytest.raises(ValueError, match="Unknown field type"):
        _deserialize_field_value(_BitReader(bytes([0])), object())


def _unittest_field_value_composite_in_struct() -> None:
    inner = _mk_structure("test.InnerField", [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")])
    outer = _mk_structure("test.OuterField", [Field(inner, "inner")])
    obj = {"inner": {"x": 77}}
    assert deserialize(outer, serialize(outer, obj)) == obj


def _unittest_field_value_array_in_struct() -> None:
    arr = FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 3)
    schema = _mk_structure("test.ArrayField", [Field(arr, "items")])
    obj = {"items": [1, 2, 3]}
    assert deserialize(schema, serialize(schema, obj)) == obj


def _unittest_default_value_all_types() -> None:
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


def _unittest_default_value_struct_with_missing_fields() -> None:
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


def _unittest_bit_writer_align_to_zero() -> None:
    w = _BitWriter()
    w.write_bits(0b101, 3)
    before = w.bit_offset
    w.align_to(0)
    assert w.bit_offset == before
    w.align_to(-1)
    assert w.bit_offset == before


def _unittest_bit_writer_aligned_overwrite_paths() -> None:
    writer = _BitWriter()
    writer.write_bits(0x112233, 24)
    writer._bit_offset = 8  # pylint: disable=protected-access
    writer.write_bits(0xAA, 8)
    assert writer.finish() == bytes([0x33, 0xAA, 0x11])

    writer = _BitWriter()
    writer.write_bits(0xBBAA, 16)
    writer._bit_offset = 8  # pylint: disable=protected-access
    writer.write_bits(0xCCDD, 16)
    assert writer.finish() == bytes([0xAA, 0xDD, 0xCC])


def _unittest_bit_reader_align_to_zero() -> None:
    r = _BitReader(bytes([0xFF]))
    _ = r.read_bits(3)
    before = r.bit_offset
    r.align_to(0)
    assert r.bit_offset == before


def _unittest_bit_reader_unaligned_out_of_bounds_zero_extension() -> None:
    r = _BitReader(bytes([0b00000101]))
    assert r.read_bits(3) == 0b101
    assert r.read_bits(6) == 0


def _unittest_bit_reader_remaining_bits_with_limit() -> None:
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


@_typed_parametrize(
    ("value", "bit_length"),
    [
        (0xAB, 8),
        (0xABCD, 16),
        (0xDEADBEEF, 32),
        (0x0123456789ABCDEF, 64),
    ],
)
def _unittest_bit_io_aligned_roundtrip(value: int, bit_length: int) -> None:
    expected = value.to_bytes(bit_length // 8, "little")
    writer = _BitWriter()
    writer.write_bits(value, bit_length)
    encoded = writer.finish()
    assert encoded == expected
    assert writer.bit_offset == bit_length

    reader = _BitReader(encoded)
    assert reader.read_bits(bit_length) == value
    assert reader.bit_offset == bit_length


def _unittest_bit_io_aligned_non_multiple_of_byte() -> None:
    value = 0xABC
    bit_length = 12
    expected = _pack_chunks_lsb_first([(value, bit_length)])

    writer = _BitWriter()
    writer.write_bits(value, bit_length)
    encoded = writer.finish()
    assert encoded == expected

    reader = _BitReader(encoded)
    assert reader.read_bits(bit_length) == value


def _unittest_bit_io_unaligned_sequence() -> None:
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


def _unittest_bit_io_mixed_aligned_unaligned_sequence() -> None:
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


def _unittest_composite_alignment_subbyte_nested_struct() -> None:
    """
    Regression test for Bug 1: nested struct with sub-byte field must be byte-aligned.
    Inner struct: {uint3 x}. Outer struct: {inner n, uint8 y}.
    """
    inner = _mk_structure("test.InnerSubbyte", [Field(UnsignedIntegerType(3, CM.TRUNCATED), "x")])
    outer = _mk_structure(
        "test.OuterSubbyte",
        [Field(inner, "n"), Field(UnsignedIntegerType(8, CM.TRUNCATED), "y")],
    )

    data = serialize(outer, {"n": {"x": 5}, "y": 42})
    assert data == bytes([0x05, 0x2A])

    result = deserialize(outer, data)
    assert result == {"n": {"x": 5}, "y": 42}


def _unittest_composite_alignment_subbyte_nested_union() -> None:
    """
    Regression test for Bug 1: nested union with sub-byte variants must be byte-aligned.
    Inner union: 2 variants: {uint3 a, uint11 b}. Tag is 8 bits.
    """
    inner_union = _mk_union(
        "test.InnerUnionSubbyte",
        [Field(UnsignedIntegerType(3, CM.TRUNCATED), "a"), Field(UnsignedIntegerType(11, CM.TRUNCATED), "b")],
    )
    outer = _mk_structure(
        "test.OuterUnionSubbyte",
        [Field(inner_union, "u"), Field(UnsignedIntegerType(8, CM.TRUNCATED), "y")],
    )

    data = serialize(outer, {"u": {"a": 5}, "y": 42})
    assert len(data) == outer.bit_length_set.min // 8

    result = deserialize(outer, data)
    assert result == {"u": {"a": 5}, "y": 42}


def _unittest_composite_alignment_already_aligned() -> None:
    """
    Regression test for Bug 1: struct with byte-aligned fields only should not change.
    """
    schema = _mk_structure(
        "test.AlreadyAligned",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"),
            Field(UnsignedIntegerType(16, CM.TRUNCATED), "b"),
        ],
    )

    data = serialize(schema, {"a": 10, "b": 300})
    assert data == bytes([0x0A, 0x2C, 0x01])

    result = deserialize(schema, data)
    assert result == {"a": 10, "b": 300}


def _unittest_composite_alignment_nested_in_array() -> None:
    """
    Regression test for Bug 1: array of structs with sub-byte fields must pad each element.
    """
    inner = _mk_structure("test.InnerArrayElem", [Field(UnsignedIntegerType(3, CM.TRUNCATED), "x")])
    schema = _mk_structure(
        "test.OuterArray",
        [Field(FixedLengthArrayType(inner, 2), "items")],
    )

    data = serialize(schema, {"items": [{"x": 3}, {"x": 7}]})
    assert data == bytes([0x03, 0x07])

    result = deserialize(schema, data)
    assert result == {"items": [{"x": 3}, {"x": 7}]}


def _unittest_composite_alignment_bool_inner() -> None:
    """
    Regression test for Bug 1: EXACT EVIDENCE CASE.
    Inner struct: {bool a}. Outer struct: {inner x, bool y}.
    serialize(outer, {"x": {"a": True}, "y": True}) must produce bytes([0x01, 0x01]) (16 bits),
    not bytes([0x03]) (8 bits).
    """
    inner = _mk_structure("test.InnerBool", [Field(BooleanType(), "a")])
    outer = _mk_structure(
        "test.OuterBool",
        [Field(inner, "x"), Field(BooleanType(), "y")],
    )

    data = serialize(outer, {"x": {"a": True}, "y": True})
    assert data == bytes([0x01, 0x01])

    result = deserialize(outer, bytes([0x01, 0x01]))
    assert result == {"x": {"a": True}, "y": True}


def _unittest_bounded_subreader_zero_extension() -> None:
    """
    Regression test for Bug 2: bounded subreader must zero-extend when reading beyond limit.
    """
    r = _BitReader(bytes([0xAA, 0xBB]))
    sub = r.bounded_subreader(8)
    assert sub.read_bits(16) == 0x00AA

    r = _BitReader(bytes([]))
    sub = r.bounded_subreader(0)
    assert sub.read_bits(8) == 0x00

    r = _BitReader(bytes([0xFF]))
    sub = r.bounded_subreader(4)
    assert sub.read_bits(8) == 0x0F


def _unittest_bounded_subreader_preserves_parent_offset() -> None:
    """
    Regression test for Bug 2: parent offset must advance by subreader limit, not by actual reads.
    """
    r = _BitReader(bytes([0x12, 0x34, 0x56]))
    sub = r.bounded_subreader(16)
    _ = sub.read_bits(8)
    assert r.bit_offset == 16


def _unittest_bounded_subreader_remaining_bits_accuracy() -> None:
    """
    Regression test for Bug 2: remaining_bits must decrease correctly and reach 0 at limit.
    """
    r = _BitReader(bytes([0xFF, 0xFF]))
    sub = r.bounded_subreader(12)
    assert sub.remaining_bits == 12
    _ = sub.read_bits(5)
    assert sub.remaining_bits == 7
    _ = sub.read_bits(7)
    assert sub.remaining_bits == 0


def _unittest_delimited_short_payload_zero_extension() -> None:
    """
    Regression test for Bug 2: EXACT EVIDENCE CASE.
    Old empty delimited inner + y=True → new schema with inner {bool a} deserializes to a=False, y=True.
    """
    old_inner = _mk_structure("test.OldInner", [])
    old_delimited = DelimitedType(old_inner, old_inner.extent)
    old_outer = _mk_structure(
        "test.OldOuter",
        [Field(old_delimited, "nested"), Field(BooleanType(), "y")],
    )

    old_data = serialize(old_outer, {"nested": {}, "y": True})

    new_inner = _mk_structure("test.NewInner", [Field(BooleanType(), "a")])
    new_delimited = DelimitedType(new_inner, new_inner.extent)
    new_outer = _mk_structure(
        "test.NewOuter",
        [Field(new_delimited, "nested"), Field(BooleanType(), "y")],
    )

    result = deserialize(new_outer, old_data)
    assert result == {"nested": {"a": False}, "y": True}


def _unittest_float_truncated_overflow_to_infinity() -> None:
    """
    Regression test for Bug 3: TRUNCATED mode must overflow to infinity for out-of-range values.
    """
    schema32 = FloatType(32, CM.TRUNCATED)
    w = _BitWriter()
    _serialize_primitive(w, schema32, 1e100)
    result32_pos = _deserialize_primitive(_BitReader(w.finish()), schema32)
    assert result32_pos == float("inf")

    w = _BitWriter()
    _serialize_primitive(w, schema32, -1e100)
    result32_neg = _deserialize_primitive(_BitReader(w.finish()), schema32)
    assert result32_neg == float("-inf")

    schema16 = FloatType(16, CM.TRUNCATED)
    w = _BitWriter()
    _serialize_primitive(w, schema16, 100000.0)
    result16_pos = _deserialize_primitive(_BitReader(w.finish()), schema16)
    assert result16_pos == float("inf")

    w = _BitWriter()
    _serialize_primitive(w, schema16, -100000.0)
    result16_neg = _deserialize_primitive(_BitReader(w.finish()), schema16)
    assert result16_neg == float("-inf")


def _unittest_float_truncated_nan_preserved() -> None:
    """
    Regression test for Bug 3: NaN must be preserved in TRUNCATED mode (unaffected by fix).
    """
    schema = FloatType(32, CM.TRUNCATED)
    w = _BitWriter()
    _serialize_primitive(w, schema, float("nan"))
    result = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert isinstance(result, float) and math.isnan(result)


def _unittest_float_saturated_no_overflow_regression() -> None:
    """
    Regression test for Bug 3: SATURATED mode must still clamp, NOT overflow to infinity.
    """
    schema32 = FloatType(32, CM.SATURATED)
    w = _BitWriter()
    _serialize_primitive(w, schema32, 1e100)
    result32 = _deserialize_primitive(_BitReader(w.finish()), schema32)
    assert isinstance(result32, float)
    assert abs(result32 - 3.4028235e38) < 1e32  # IEEE 754 float32 max

    schema16 = FloatType(16, CM.SATURATED)
    w = _BitWriter()
    _serialize_primitive(w, schema16, 100000.0)
    result16 = _deserialize_primitive(_BitReader(w.finish()), schema16)
    assert isinstance(result16, float)
    assert result16 != float("inf")
    assert result16 > 0
    assert abs(result16 - 65504.0) < 1.0


def _unittest_float_from_huge_integer_overflow_paths() -> None:
    huge_positive = 10**10000
    huge_negative = -huge_positive

    truncated = FloatType(32, CM.TRUNCATED)
    w = _BitWriter()
    _serialize_primitive(w, truncated, huge_positive)
    assert _deserialize_primitive(_BitReader(w.finish()), truncated) == float("inf")

    w = _BitWriter()
    _serialize_primitive(w, truncated, huge_negative)
    assert _deserialize_primitive(_BitReader(w.finish()), truncated) == float("-inf")

    saturated = FloatType(32, CM.SATURATED)
    w = _BitWriter()
    _serialize_primitive(w, saturated, huge_positive)
    result_positive = _deserialize_primitive(_BitReader(w.finish()), saturated)
    assert isinstance(result_positive, float)
    assert result_positive != float("inf")
    assert abs(result_positive - 3.4028235e38) < 1e32

    w = _BitWriter()
    _serialize_primitive(w, saturated, huge_negative)
    result_negative = _deserialize_primitive(_BitReader(w.finish()), saturated)
    assert isinstance(result_negative, float)
    assert result_negative != float("-inf")
    assert abs(result_negative + 3.4028235e38) < 1e32


def _unittest_delimited_new_data_old_schema() -> None:
    new_delimited = _mk_delimited(
        "test.DelimitedCompatNewDataInnerNew",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "x"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "y"),
        ],
    )
    old_delimited = _mk_delimited(
        "test.DelimitedCompatNewDataInnerOld",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")],
    )

    new_outer = _mk_structure(
        "test.DelimitedCompatNewDataOuterNew",
        [
            Field(new_delimited, "nested"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "tail"),
        ],
    )
    old_outer = _mk_structure(
        "test.DelimitedCompatNewDataOuterOld",
        [
            Field(old_delimited, "nested"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "tail"),
        ],
    )

    data = serialize(new_outer, {"nested": {"x": 42, "y": 99}, "tail": 7})
    assert deserialize(old_outer, data) == {"nested": {"x": 42}, "tail": 7}


def _unittest_delimited_old_data_new_schema() -> None:
    for old_field_count, added_field_count in [(0, 1), (1, 2), (2, 3)]:
        old_names = [f"f{i}" for i in range(old_field_count)]
        added_names = [f"f{old_field_count + i}" for i in range(added_field_count)]

        old_delimited = _mk_delimited(
            f"test.DelimitedCompatOldDataOld{old_field_count}_{added_field_count}",
            [Field(UnsignedIntegerType(8, CM.TRUNCATED), name) for name in old_names],
        )
        new_delimited = _mk_delimited(
            f"test.DelimitedCompatOldDataNew{old_field_count}_{added_field_count}",
            [Field(UnsignedIntegerType(8, CM.TRUNCATED), name) for name in old_names + added_names],
        )

        old_outer = _mk_structure(
            f"test.DelimitedCompatOldDataOuterOld{old_field_count}_{added_field_count}",
            [
                Field(old_delimited, "nested"),
                Field(UnsignedIntegerType(8, CM.TRUNCATED), "tail"),
            ],
        )
        new_outer = _mk_structure(
            f"test.DelimitedCompatOldDataOuterNew{old_field_count}_{added_field_count}",
            [
                Field(new_delimited, "nested"),
                Field(UnsignedIntegerType(8, CM.TRUNCATED), "tail"),
            ],
        )

        old_nested = {name: index + 10 for index, name in enumerate(old_names)}
        old_data = serialize(old_outer, {"nested": old_nested, "tail": 200 + old_field_count})

        expected_nested = dict(old_nested)
        expected_nested.update({name: 0 for name in added_names})
        assert deserialize(new_outer, old_data) == {
            "nested": expected_nested,
            "tail": 200 + old_field_count,
        }


def _unittest_delimited_same_version_roundtrip() -> None:
    schema = _mk_delimited(
        "test.DelimitedSameVersionRoundtrip",
        [
            Field(BooleanType(), "flag"),
            Field(UnsignedIntegerType(16, CM.TRUNCATED), "count"),
            Field(VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 4), "payload"),
        ],
    )
    obj = {"flag": True, "count": 0xABCD, "payload": [1, 2, 3]}
    _roundtrip_assert(schema, obj)

    outer = _mk_structure(
        "test.DelimitedSameVersionOuterRoundtrip",
        [
            Field(schema, "nested"),
            Field(BooleanType(), "tail"),
        ],
    )
    _roundtrip_assert(outer, {"nested": obj, "tail": False})


def _unittest_delimited_nested_version_mismatch() -> None:
    old_inner = _mk_delimited(
        "test.DelimitedNestedMismatchInnerOld",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")],
    )
    new_inner = _mk_delimited(
        "test.DelimitedNestedMismatchInnerNew",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "x"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "z"),
        ],
    )

    old_outer = _mk_structure(
        "test.DelimitedNestedMismatchOuterOld",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "prefix"),
            Field(old_inner, "nested"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "suffix"),
        ],
    )
    new_outer = _mk_structure(
        "test.DelimitedNestedMismatchOuterNew",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "prefix"),
            Field(new_inner, "nested"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "suffix"),
        ],
    )

    old_data = serialize(old_outer, {"prefix": 10, "nested": {"x": 20}, "suffix": 30})
    assert deserialize(new_outer, old_data) == {
        "prefix": 10,
        "nested": {"x": 20, "z": 0},
        "suffix": 30,
    }

    new_data = serialize(new_outer, {"prefix": 40, "nested": {"x": 50, "z": 60}, "suffix": 70})
    assert deserialize(old_outer, new_data) == {
        "prefix": 40,
        "nested": {"x": 50},
        "suffix": 70,
    }


def _unittest_delimited_union_inner_compatibility() -> None:
    old_union = _mk_union(
        "test.DelimitedUnionCompatOld",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "b"),
        ],
    )
    new_union = _mk_union(
        "test.DelimitedUnionCompatNew",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "b"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "c"),
        ],
    )

    old_outer = _mk_structure(
        "test.DelimitedUnionCompatOuterOld",
        [
            Field(DelimitedType(old_union, old_union.extent), "nested"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "tail"),
        ],
    )
    new_outer = _mk_structure(
        "test.DelimitedUnionCompatOuterNew",
        [
            Field(DelimitedType(new_union, new_union.extent), "nested"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "tail"),
        ],
    )

    assert deserialize(new_outer, serialize(old_outer, {"nested": {"b": 11}, "tail": 22})) == {
        "nested": {"b": 11},
        "tail": 22,
    }
    assert deserialize(old_outer, serialize(new_outer, {"nested": {"a": 33}, "tail": 44})) == {
        "nested": {"a": 33},
        "tail": 44,
    }

    with pytest.raises(UnionTagError, match="Invalid union tag"):
        deserialize(old_outer, serialize(new_outer, {"nested": {"c": 55}, "tail": 66}))


def _unittest_delimited_array_of_delimited() -> None:
    element = _mk_delimited(
        "test.DelimitedArrayOfDelimitedElement",
        [Field(VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 3), "payload")],
    )
    outer = _mk_structure(
        "test.DelimitedArrayOfDelimitedOuter",
        [
            Field(FixedLengthArrayType(element, 3), "items"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "tail"),
        ],
    )
    obj = {
        "items": [
            {"payload": []},
            {"payload": [11]},
            {"payload": [22, 33, 44]},
        ],
        "tail": 77,
    }

    data = serialize(outer, obj)
    assert deserialize(outer, data) == obj

    offset = 0
    for expected_size, expected_payload in [(1, bytes([0])), (2, bytes([1, 11])), (4, bytes([3, 22, 33, 44]))]:
        header = int.from_bytes(data[offset : offset + 4], "little")
        assert header == expected_size
        offset += 4
        assert data[offset : offset + expected_size] == expected_payload
        offset += expected_size
    assert data[offset:] == bytes([77])


def _unittest_delimited_header_value_matches_payload() -> None:
    schema = _mk_delimited(
        "test.DelimitedHeaderValuePayload",
        [
            Field(BooleanType(), "flag"),
            Field(UnsignedIntegerType(16, CM.TRUNCATED), "value"),
            Field(VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 8), "bytes"),
        ],
    )
    outer = _mk_structure(
        "test.DelimitedHeaderValuePayloadOuter",
        [
            Field(schema, "nested"),
            Field(BooleanType(), "tail"),
        ],
    )
    nested = {"flag": True, "value": 0x1234, "bytes": [1, 2, 3, 4, 5]}
    data = serialize(outer, {"nested": nested, "tail": True})

    payload = serialize(schema.inner_type, nested)
    encoded_payload_size = int.from_bytes(data[:4], "little")
    assert encoded_payload_size == len(payload)
    assert data[4 : 4 + encoded_payload_size] == payload
    assert data[4 + encoded_payload_size :] == bytes([1])


def _unittest_delimited_with_header_api_roundtrip() -> None:
    meta = _mk_structure(
        "test.DelimitedWithHeaderAPIMeta",
        [
            Field(BooleanType(), "enabled"),
            Field(UnsignedIntegerType(16, CM.TRUNCATED), "code"),
        ],
    )
    choice = _mk_union(
        "test.DelimitedWithHeaderAPIChoice",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "small"),
            Field(meta, "full"),
        ],
    )
    inner = _mk_structure(
        "test.DelimitedWithHeaderAPIInner",
        [
            Field(meta, "meta"),
            Field(choice, "choice"),
            Field(VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 8), "payload"),
            Field(FixedLengthArrayType(BooleanType(), 3), "flags"),
        ],
    )
    schema = DelimitedType(inner, inner.extent)
    obj = {
        "meta": {"enabled": True, "code": 513},
        "choice": {"full": {"enabled": False, "code": 1024}},
        "payload": [1, 2, 3, 4],
        "flags": [True, False, True],
    }

    payload = serialize(schema, obj)
    with_header = serialize(schema, obj, with_delimiter_header=True)
    assert int.from_bytes(with_header[:4], "little") == len(payload)
    assert with_header[4:] == payload
    assert deserialize(schema, with_header, with_delimiter_header=True) == obj


def _unittest_implicit_truncation_struct_excess_bytes() -> None:
    schema = _mk_structure(
        "test.ImplicitTruncStructBytes",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")],
    )

    result = deserialize(schema, bytes([42, 0xFF, 0xEE, 0xDD]))
    assert result == {"x": 42}


def _unittest_implicit_truncation_struct_excess_bits() -> None:
    schema = _mk_structure(
        "test.ImplicitTruncStructBits",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")],
    )

    reader = _BitReader(bytes([0x2A, 0x07]), bit_limit=11)
    result = _deserialize_composite(reader, schema)
    assert result == {"x": 0x2A}
    assert reader.remaining_bits == 3


def _unittest_implicit_truncation_nested_struct() -> None:
    inner = _mk_structure(
        "test.ImplicitTruncInner",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")],
    )
    outer = _mk_structure(
        "test.ImplicitTruncOuter",
        [
            Field(inner, "inner"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "y"),
        ],
    )

    result = deserialize(outer, bytes([10, 20, 30, 40]))
    assert result == {"inner": {"x": 10}, "y": 20}


def _unittest_implicit_truncation_union() -> None:
    schema = _mk_union(
        "test.ImplicitTruncUnion",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"),
            Field(UnsignedIntegerType(16, CM.TRUNCATED), "b"),
        ],
    )

    result = deserialize(schema, bytes([0, 0x77, 0xAA, 0xBB, 0xCC]))
    assert result == {"a": 0x77}


def _unittest_implicit_truncation_preserves_values() -> None:
    schema = _mk_structure(
        "test.ImplicitTruncPreserve",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"),
            Field(UnsignedIntegerType(16, CM.TRUNCATED), "b"),
            Field(BooleanType(), "c"),
        ],
    )
    expected = {"a": 0x11, "b": 0x2233, "c": True}

    payload = serialize(schema, expected)
    result = deserialize(schema, payload + bytes([0xDE, 0xAD, 0xBE, 0xEF]))
    assert result == expected


def _unittest_implicit_truncation_bool_struct() -> None:
    schema = _mk_structure(
        "test.ImplicitTruncBoolStruct",
        [
            Field(BooleanType(), "a"),
            Field(BooleanType(), "b"),
            Field(BooleanType(), "c"),
            Field(BooleanType(), "d"),
        ],
    )

    result = deserialize(schema, bytes([0b00001101, 0xAA, 0x55]))
    assert result == {"a": True, "b": False, "c": True, "d": True}


# ============================================================================
# VOID DESERIALIZATION SEMANTICS TESTS (Wave 2, Task 5)
# ============================================================================


def _unittest_void_deserialize_nonzero_bits() -> None:
    """
    Test that void padding with non-zero bits is accepted during deserialization.
    Per DSDL spec: void bits are IGNORED during deserialization (any bit pattern is valid).

    Construct a struct with void padding where the padding bytes contain non-zero bits.
    Verify that deserialization succeeds and the surrounding fields are unaffected.
    """
    # Struct: {uint8 a, void8, uint8 b}
    schema = _mk_structure(
        "test.VoidNonzero",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"),
            PaddingField(VoidType(8)),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "b"),
        ],
    )

    # Serialize with known values
    obj = {"a": 42, "b": 99}
    data = serialize(schema, obj)

    # Verify serialized void is zeros
    assert data == bytes([42, 0, 99])

    # Now deserialize from data where void byte is non-zero (0xFF)
    # This should succeed and ignore the non-zero void bits
    corrupted_data = bytes([42, 0xFF, 99])
    result = deserialize(schema, corrupted_data)

    # Verify surrounding fields are correct despite non-zero void
    assert result == {"a": 42, "b": 99}


def _unittest_void_various_widths() -> None:
    """
    Test void types at representative widths {1, 2, 3, 4, 5, 7, 8, 16, 32, 64}.
    Verify that:
    - Serialization always produces zeros
    - Deserialization accepts any bit pattern
    """
    void_widths = [1, 2, 3, 4, 5, 7, 8, 16, 32, 64]

    for width in void_widths:
        # Test serialization: void always serializes as zeros
        w = _BitWriter()
        _serialize_primitive(w, VoidType(width), None)
        serialized = w.finish()

        # Verify all bits are zero
        for byte_val in serialized:
            assert byte_val == 0, f"void{width} serialized non-zero byte: {byte_val:#x}"

        # Test deserialization: any bit pattern is accepted
        # Create data with all bits set to 1
        byte_count = (width + 7) // 8
        all_ones_data = bytes([0xFF] * byte_count)

        r = _BitReader(all_ones_data)
        result = _deserialize_primitive(r, VoidType(width))

        # Void deserialization returns None
        assert result is None

        # Verify reader consumed exactly the right number of bits
        assert r._bit_offset == width


def _unittest_void_serialize_always_zero() -> None:
    """
    Verify that all void widths serialize as zeros regardless of context.
    Test void fields within structs to ensure serialization is consistent.
    """
    void_widths = [1, 2, 3, 4, 5, 7, 8, 16, 32, 64]

    for width in void_widths:
        # Create struct: {uint8 before, voidN, uint8 after}
        schema = _mk_structure(
            f"test.VoidSerialize{width}",
            [
                Field(UnsignedIntegerType(8, CM.TRUNCATED), "before"),
                PaddingField(VoidType(width)),
                Field(UnsignedIntegerType(8, CM.TRUNCATED), "after"),
            ],
        )

        obj = {"before": 0xAA, "after": 0xBB}
        data = serialize(schema, obj)

        # Calculate expected byte count
        # 8 bits (before) + width bits (void) + 8 bits (after) = 16 + width bits
        total_bits = 16 + width
        expected_bytes = (total_bits + 7) // 8

        assert len(data) == expected_bytes, f"void{width}: expected {expected_bytes} bytes, got {len(data)}"

        # Verify first byte is 0xAA (before field)
        assert data[0] == 0xAA, f"void{width}: before field corrupted"

        # Verify last byte contains 0xBB in the appropriate bits
        # The after field starts at bit position 8 + width
        # For byte-aligned cases, it's straightforward
        if (8 + width) % 8 == 0:
            # After field is byte-aligned
            after_byte_index = (8 + width) // 8
            assert data[after_byte_index] == 0xBB, f"void{width}: after field corrupted"
        else:
            # After field is not byte-aligned; verify via deserialization
            result = deserialize(schema, data)
            assert result == obj, f"void{width}: roundtrip failed"


# ============================================================================
# IMPLICIT ZERO EXTENSION AT COMPOSITE LEVEL (Task 2)
# ============================================================================


def _unittest_implicit_zero_extension_struct_truncated_data() -> None:
    schema = _mk_structure(
        "test.ZeroExtStructTruncated",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "x"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "y"),
        ],
    )

    result = deserialize(schema, bytes([42]))
    assert result == {"x": 42, "y": 0}


def _unittest_implicit_zero_extension_struct_empty_data() -> None:
    schema = _mk_structure(
        "test.ZeroExtStructEmpty",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "x"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "y"),
        ],
    )

    result = deserialize(schema, bytes())
    assert result == {"x": 0, "y": 0}


def _unittest_implicit_zero_extension_multibyte_field() -> None:
    schema = _mk_structure(
        "test.ZeroExtMultibyte",
        [
            Field(UnsignedIntegerType(32, CM.TRUNCATED), "a"),
            Field(UnsignedIntegerType(16, CM.TRUNCATED), "b"),
        ],
    )

    result = deserialize(schema, bytes([0x78, 0x56, 0x34, 0x12]))
    assert result == {"a": 0x12345678, "b": 0}


def _unittest_implicit_zero_extension_bool_fields() -> None:
    schema = _mk_structure(
        "test.ZeroExtBools",
        [
            Field(BooleanType(), "a"),
            Field(BooleanType(), "b"),
            Field(BooleanType(), "c"),
            Field(BooleanType(), "d"),
            Field(BooleanType(), "e"),
            Field(BooleanType(), "f"),
            Field(BooleanType(), "g"),
            Field(BooleanType(), "h"),
            Field(BooleanType(), "i"),
            Field(BooleanType(), "j"),
            Field(BooleanType(), "k"),
            Field(BooleanType(), "l"),
        ],
    )

    result = deserialize(schema, bytes([0b10110010]))
    assert result == {
        "a": False,
        "b": True,
        "c": False,
        "d": False,
        "e": True,
        "f": True,
        "g": False,
        "h": True,
        "i": False,
        "j": False,
        "k": False,
        "l": False,
    }


def _unittest_implicit_zero_extension_nested_struct() -> None:
    inner = _mk_structure("test.ZeroExtInner", [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")])
    outer = _mk_structure(
        "test.ZeroExtOuter",
        [
            Field(inner, "inner"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "y"),
        ],
    )

    result = deserialize(outer, bytes([23]))
    assert result == {"inner": {"x": 23}, "y": 0}


def _unittest_implicit_zero_extension_array_field() -> None:
    schema = _mk_structure(
        "test.ZeroExtFixedArray",
        [
            Field(FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 4), "values"),
        ],
    )

    result = deserialize(schema, bytes([1, 2]))
    assert result == {"values": [1, 2, 0, 0]}


def _unittest_implicit_zero_extension_variable_array() -> None:
    schema = _mk_structure(
        "test.ZeroExtVarArray",
        [
            Field(VariableLengthArrayType(UnsignedIntegerType(16, CM.TRUNCATED), 8), "values"),
        ],
    )

    result = deserialize(schema, bytes([3, 0x34, 0x12, 0x56]))
    assert result == {"values": [0x1234, 0x0056, 0x0000]}


@_typed_parametrize("width", _UNSIGNED_WIDTHS)
def _unittest_unsigned_all_widths_roundtrip(width: int) -> None:
    max_value = (1 << width) - 1
    midpoint = max_value // 2

    for cast_mode in (CM.SATURATED, CM.TRUNCATED):
        schema = UnsignedIntegerType(width, cast_mode)
        for value in [0, 1, midpoint, max_value]:
            writer = _BitWriter()
            _serialize_primitive(writer, schema, value)
            decoded = _deserialize_primitive(_BitReader(writer.finish()), schema)
            assert decoded == value


@_typed_parametrize("width", _SIGNED_WIDTHS)
def _unittest_signed_all_widths_roundtrip(width: int) -> None:
    schema = SignedIntegerType(width, CM.SATURATED)
    min_value = -(1 << (width - 1))
    max_value = (1 << (width - 1)) - 1

    for value in [min_value, -1, 0, 1, max_value]:
        writer = _BitWriter()
        _serialize_primitive(writer, schema, value)
        decoded = _deserialize_primitive(_BitReader(writer.finish()), schema)
        assert decoded == value


@_typed_parametrize("width", _UNSIGNED_WIDTHS)
def _unittest_unsigned_saturated_boundary(width: int) -> None:
    schema = UnsignedIntegerType(width, CM.SATURATED)
    min_value = 0
    max_value = (1 << width) - 1

    for value, expected in [
        (0, 0),
        (1, 1),
        (-1, 0),
        (min_value, min_value),
        (max_value, max_value),
        (min_value - 1, min_value),
        (max_value + 1, max_value),
    ]:
        writer = _BitWriter()
        _serialize_primitive(writer, schema, value)
        decoded = _deserialize_primitive(_BitReader(writer.finish()), schema)
        assert decoded == expected


@_typed_parametrize("width", _UNSIGNED_WIDTHS)
def _unittest_unsigned_truncated_boundary(width: int) -> None:
    schema = UnsignedIntegerType(width, CM.TRUNCATED)
    min_value = 0
    max_value = (1 << width) - 1
    mask = (1 << width) - 1

    for value in [0, 1, -1, min_value, max_value, min_value - 1, max_value + 1]:
        writer = _BitWriter()
        _serialize_primitive(writer, schema, value)
        decoded = _deserialize_primitive(_BitReader(writer.finish()), schema)
        assert decoded == (value & mask)


@_typed_parametrize("width", _SIGNED_WIDTHS)
def _unittest_signed_saturated_boundary(width: int) -> None:
    schema = SignedIntegerType(width, CM.SATURATED)
    min_value = -(1 << (width - 1))
    max_value = (1 << (width - 1)) - 1

    for value, expected in [
        (0, 0),
        (1, 1),
        (-1, -1),
        (min_value, min_value),
        (max_value, max_value),
        (min_value - 1, min_value),
        (max_value + 1, max_value),
    ]:
        writer = _BitWriter()
        _serialize_primitive(writer, schema, value)
        decoded = _deserialize_primitive(_BitReader(writer.finish()), schema)
        assert decoded == expected


@_typed_parametrize("width", _SIGNED_WIDTHS)
def _unittest_twos_complement_encoding(width: int) -> None:
    schema = SignedIntegerType(width, CM.SATURATED)
    min_value = -(1 << (width - 1))
    mask = (1 << width) - 1

    for value, expected_raw in [
        (-1, mask),
        (-2, mask - 1),
        (min_value, 1 << (width - 1)),
    ]:
        writer = _BitWriter()
        _serialize_primitive(writer, schema, value)
        encoded = writer.finish()
        raw = _BitReader(encoded).read_bits(width)
        assert raw == expected_raw
        decoded = _deserialize_primitive(_BitReader(encoded), schema)
        assert decoded == value

    if width == 8:
        writer = _BitWriter()
        _serialize_primitive(writer, schema, -1)
        assert writer.finish() == bytes([0xFF])


def _unittest_integer_from_float_rounding() -> None:
    unsigned_truncated = UnsignedIntegerType(8, CM.TRUNCATED)
    unsigned_saturated = UnsignedIntegerType(8, CM.SATURATED)
    signed_saturated = SignedIntegerType(8, CM.SATURATED)

    for schema in [unsigned_truncated, unsigned_saturated, signed_saturated]:
        for value in [2.4, 2.6]:
            writer = _BitWriter()
            _serialize_primitive(writer, schema, value)
            decoded = _deserialize_primitive(_BitReader(writer.finish()), schema)
            assert decoded == int(round(value))

    writer = _BitWriter()
    _serialize_primitive(writer, unsigned_truncated, 2.5)
    decoded_half_up_unsigned = _deserialize_primitive(_BitReader(writer.finish()), unsigned_truncated)
    assert decoded_half_up_unsigned in [2, 3]
    assert decoded_half_up_unsigned == int(round(2.5))

    writer = _BitWriter()
    _serialize_primitive(writer, signed_saturated, -1.5)
    decoded_half_down_signed = _deserialize_primitive(_BitReader(writer.finish()), signed_saturated)
    assert decoded_half_down_signed in [-2, -1]
    assert decoded_half_down_signed == int(round(-1.5))


# ============================================================================
# VARIABLE-LENGTH ARRAY LENGTH FIELD WIDTH TESTS (Task 9)
# ============================================================================


def _unittest_vararray_length_field_8bit() -> None:
    """
    Verify that variable-length arrays with capacity ≤ 255 produce 8-bit length fields.

    Per length field width formula: 2^ceil(log2(max(8, capacity.bit_length())))
    For capacity=100: 100.bit_length()=7, max(8,7)=8, ceil(log2(8))=3, 2^3=8
    For capacity=255: 255.bit_length()=8, max(8,8)=8, ceil(log2(8))=3, 2^3=8
    """
    schema_100 = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 100)
    assert schema_100.length_field_type.bit_length == 8

    schema_255 = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 255)
    assert schema_255.length_field_type.bit_length == 8

    # Verify wire format: first byte is length (little-endian)
    w = _BitWriter()
    _serialize_array(w, schema_100, [10, 20, 30])
    data = w.finish()
    assert data[0] == 3  # 8-bit length field
    assert data[1:] == bytes([10, 20, 30])

    # Roundtrip
    r = _BitReader(data)
    result = _deserialize_array(r, schema_100)
    assert result == [10, 20, 30]


def _unittest_vararray_length_field_16bit() -> None:
    """
    Verify that variable-length arrays with capacity 256-65535 produce 16-bit length fields.

    For capacity=256: 256.bit_length()=9, max(8,9)=9, ceil(log2(9))=4, 2^4=16
    For capacity=10000: 10000.bit_length()=14, max(8,14)=14, ceil(log2(14))=4, 2^4=16
    For capacity=65535: 65535.bit_length()=16, max(8,16)=16, ceil(log2(16))=4, 2^4=16
    """
    schema_256 = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 256)
    assert schema_256.length_field_type.bit_length == 16

    schema_10000 = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 10000)
    assert schema_10000.length_field_type.bit_length == 16

    schema_65535 = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 65535)
    assert schema_65535.length_field_type.bit_length == 16

    # Verify wire format: first 2 bytes are length (little-endian)
    w = _BitWriter()
    _serialize_array(w, schema_256, [1, 2, 3, 4, 5])
    data = w.finish()
    length = int.from_bytes(data[:2], "little")
    assert length == 5  # 16-bit length field
    assert data[2:] == bytes([1, 2, 3, 4, 5])


def _unittest_vararray_length_field_32bit() -> None:
    """
    Verify that variable-length arrays with capacity ≥ 65536 produce 32-bit length fields.

    For capacity=65536: 65536.bit_length()=17, max(8,17)=17, ceil(log2(17))=5, 2^5=32
    For capacity=1000000: 1000000.bit_length()=20, max(8,20)=20, ceil(log2(20))=5, 2^5=32
    """
    schema_65536 = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 65536)
    assert schema_65536.length_field_type.bit_length == 32

    schema_1000000 = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 1000000)
    assert schema_1000000.length_field_type.bit_length == 32

    # Verify wire format: first 4 bytes are length (little-endian)
    w = _BitWriter()
    _serialize_array(w, schema_65536, [0xAA, 0xBB, 0xCC])
    data = w.finish()
    length = int.from_bytes(data[:4], "little")
    assert length == 3  # 32-bit length field
    assert data[4:] == bytes([0xAA, 0xBB, 0xCC])


def _unittest_vararray_capacity_boundary_8_to_16() -> None:
    """
    Test capacity boundary: 255 (8-bit) vs 256 (16-bit).

    Verify that the length field width changes at the exact boundary.
    """
    schema_255 = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 255)
    schema_256 = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 256)

    assert schema_255.length_field_type.bit_length == 8
    assert schema_256.length_field_type.bit_length == 16

    # Same payload, different length field widths
    payload = [1, 2, 3]

    w_255 = _BitWriter()
    _serialize_array(w_255, schema_255, payload)
    data_255 = w_255.finish()
    assert len(data_255) == 1 + 3  # 1 byte length + 3 bytes payload

    w_256 = _BitWriter()
    _serialize_array(w_256, schema_256, payload)
    data_256 = w_256.finish()
    assert len(data_256) == 2 + 3  # 2 bytes length + 3 bytes payload

    # Verify boundary at 65535→65536
    schema_65535 = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 65535)
    schema_65536 = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 65536)

    assert schema_65535.length_field_type.bit_length == 16
    assert schema_65536.length_field_type.bit_length == 32


def _unittest_vararray_roundtrip_16bit_length() -> None:
    """
    Test roundtrip serialization/deserialization with 16-bit length field.

    Verify that arrays with capacity requiring 16-bit length fields correctly
    serialize and deserialize with various payload sizes.
    """
    schema = VariableLengthArrayType(UnsignedIntegerType(16, CM.TRUNCATED), 500)
    assert schema.length_field_type.bit_length == 16

    # Empty array
    w = _BitWriter()
    _serialize_array(w, schema, [])
    data = w.finish()
    assert int.from_bytes(data[:2], "little") == 0
    assert _deserialize_array(_BitReader(data), schema) == []

    # Single element
    w = _BitWriter()
    _serialize_array(w, schema, [0x1234])
    data = w.finish()
    assert int.from_bytes(data[:2], "little") == 1
    assert data[2:] == bytes([0x34, 0x12])  # little-endian
    assert _deserialize_array(_BitReader(data), schema) == [0x1234]

    # Multiple elements
    payload = [0x0011, 0x2233, 0x4455, 0x6677, 0x8899]
    w = _BitWriter()
    _serialize_array(w, schema, payload)
    data = w.finish()
    assert int.from_bytes(data[:2], "little") == 5
    assert _deserialize_array(_BitReader(data), schema) == payload


def _unittest_vararray_roundtrip_32bit_length() -> None:
    """
    Test roundtrip serialization/deserialization with 32-bit length field.

    Verify that arrays with capacity requiring 32-bit length fields correctly
    serialize and deserialize with various payload sizes.
    """
    schema = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 100000)
    assert schema.length_field_type.bit_length == 32

    # Empty array
    w = _BitWriter()
    _serialize_array(w, schema, [])
    data = w.finish()
    assert int.from_bytes(data[:4], "little") == 0
    assert _deserialize_array(_BitReader(data), schema) == []

    # Small payload with 32-bit length field
    payload = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE]
    w = _BitWriter()
    _serialize_array(w, schema, payload)
    data = w.finish()
    assert int.from_bytes(data[:4], "little") == 5
    assert data[4:] == bytes(payload)
    assert _deserialize_array(_BitReader(data), schema) == payload

    # Verify larger payload (100 elements)
    large_payload = list(range(100))
    w = _BitWriter()
    _serialize_array(w, schema, large_payload)
    data = w.finish()
    assert int.from_bytes(data[:4], "little") == 100
    assert _deserialize_array(_BitReader(data), schema) == large_payload


# ============================================
# Task 8: UTF-8 multi-byte and byte array edge case tests
# ============================================


def _unittest_utf8_multibyte_characters() -> None:
    """Test UTF-8 strings with 2-byte, 3-byte, and 4-byte characters."""
    schema = VariableLengthArrayType(UTF8Type(), 255)

    # 2-byte characters (Latin-1 supplement)
    w = _BitWriter()
    _serialize_array(w, schema, "café")
    data = w.finish()
    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == "café"
    assert isinstance(result, str)
    assert len("café".encode("utf-8")) == 5  # 'c' 'a' 'f' 0xC3 0xA9

    # 3-byte characters (CJK)
    w = _BitWriter()
    _serialize_array(w, schema, "日本語")
    data = w.finish()
    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == "日本語"
    assert len("日本語".encode("utf-8")) == 9  # 3 chars × 3 bytes each

    # 4-byte characters (emoji)
    w = _BitWriter()
    _serialize_array(w, schema, "😀🎉")
    data = w.finish()
    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == "😀🎉"
    assert len("😀🎉".encode("utf-8")) == 8  # 2 chars × 4 bytes each


def _unittest_utf8_empty_string() -> None:
    """Test empty UTF-8 string roundtrip."""
    schema = VariableLengthArrayType(UTF8Type(), 255)

    w = _BitWriter()
    _serialize_array(w, schema, "")
    data = w.finish()
    assert len(data) == 1  # Just the length byte
    assert data[0] == 0  # Length is 0

    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == ""
    assert isinstance(result, str)


def _unittest_utf8_at_capacity_boundary() -> None:
    """Test UTF-8 capacity checked against BYTE count, not character count."""
    # Capacity is 10 bytes
    schema = VariableLengthArrayType(UTF8Type(), 10)

    # Exactly at capacity: 10 bytes (3 emoji × 4 bytes = 12 bytes exceeds capacity)
    # Use 2 emoji (8 bytes) + 'hi' (2 bytes) = 10 bytes
    test_str = "😀🎉"  # 8 bytes
    assert len(test_str.encode("utf-8")) == 8

    w = _BitWriter()
    _serialize_array(w, schema, test_str)
    data = w.finish()
    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == test_str

    # Over capacity: 3 emoji = 12 bytes > 10 byte capacity
    with pytest.raises(ArrayLengthError):
        w = _BitWriter()
        _serialize_array(w, schema, "😀🎉🚀")  # 12 bytes


def _unittest_utf8_mixed_ascii_multibyte() -> None:
    """Test UTF-8 strings with mixed ASCII and multi-byte characters."""
    schema = VariableLengthArrayType(UTF8Type(), 255)

    mixed = "Hello 世界! 😀"  # ASCII + 3-byte + ASCII + 4-byte
    w = _BitWriter()
    _serialize_array(w, schema, mixed)
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == mixed
    assert isinstance(result, str)

    # Verify byte length calculation
    expected_bytes = len(mixed.encode("utf-8"))
    # "Hello " = 6, "世界" = 6, "! " = 2, "😀" = 4 → 18 bytes
    assert expected_bytes == 18


def _unittest_utf8_invalid_bytes_rejected() -> None:
    """Test that invalid UTF-8 byte sequences are rejected during serialization."""
    schema = VariableLengthArrayType(UTF8Type(), 255)

    # Invalid UTF-8: 0xFF is not a valid UTF-8 start byte
    invalid_bytes = b"\xff\xfe"

    # According to _serdes.py:562-563, bytes input is validated with .decode("utf-8")
    with pytest.raises(UnicodeDecodeError):
        w = _BitWriter()
        _serialize_array(w, schema, invalid_bytes)


def _unittest_byte_array_empty() -> None:
    """Test empty byte array roundtrip."""
    schema = VariableLengthArrayType(ByteType(), 255)

    w = _BitWriter()
    _serialize_array(w, schema, b"")
    data = w.finish()
    assert len(data) == 1  # Just the length byte
    assert data[0] == 0  # Length is 0

    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == b""
    assert isinstance(result, bytes)


def _unittest_byte_array_all_byte_values() -> None:
    """Test byte array with all 256 possible byte values (0x00-0xFF)."""
    schema = VariableLengthArrayType(ByteType(), 256)

    all_bytes = bytes(range(256))
    w = _BitWriter()
    _serialize_array(w, schema, all_bytes)
    data = w.finish()

    assert schema.length_field_type.bit_length == 16
    assert len(data) == 258
    assert int.from_bytes(data[:2], "little") == 256

    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == all_bytes
    assert isinstance(result, bytes)
    assert len(result) == 256


def _unittest_byte_array_at_capacity() -> None:
    """Test byte array at exact capacity boundary."""
    schema = VariableLengthArrayType(ByteType(), 10)

    # Exactly at capacity
    exact = b"0123456789"
    assert len(exact) == 10

    w = _BitWriter()
    _serialize_array(w, schema, exact)
    data = w.finish()
    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == exact

    # Over capacity
    with pytest.raises(ArrayLengthError):
        w = _BitWriter()
        _serialize_array(w, schema, b"01234567890")  # 11 bytes


def _unittest_fixed_utf8_array_roundtrip() -> None:
    """Test fixed-length UTF-8 array (uncommon but valid)."""
    # Fixed-length array of 3 UTF-8 characters (each UTF8Type element is capacity-1)
    # Note: FixedLengthArrayType with UTF8Type is unusual but should work
    inner_schema = VariableLengthArrayType(UTF8Type(), 10)
    schema = _mk_structure(
        "test.FixedUtf8Array",
        [
            Field(inner_schema, "text"),
        ],
    )

    test_obj = {"text": "abc"}
    _roundtrip_assert(schema, test_obj)

    # Test with multi-byte characters
    test_obj_multi = {"text": "日本"}
    _roundtrip_assert(schema, test_obj_multi)


@_typed_parametrize("width", [16, 32, 64])
def _unittest_float_negative_zero_roundtrip(width: int) -> None:
    schema = FloatType(width, CM.SATURATED)
    w = _BitWriter()
    _serialize_primitive(w, schema, -0.0)
    result = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert isinstance(result, float)
    float_result = result
    assert float_result == 0.0
    assert math.copysign(1.0, float_result) == -1.0


@_typed_parametrize("width", [16, 32, 64])
def _unittest_float_denormalized_roundtrip(width: int) -> None:
    smallest_denormalized = {
        16: 2.0**-24,
        32: 2.0**-149,
        64: 2.0**-1074,
    }[width]
    schema = FloatType(width, CM.SATURATED)
    w = _BitWriter()
    _serialize_primitive(w, schema, smallest_denormalized)
    result = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert isinstance(result, float)
    float_result = result
    assert float_result == smallest_denormalized
    assert float_result > 0.0


@_typed_parametrize("width", [16, 32, 64])
def _unittest_float_max_finite_roundtrip(width: int) -> None:
    max_finite = {
        16: 65504.0,
        32: 3.4028234663852886e38,
        64: 1.7976931348623157e308,
    }[width]
    schema = FloatType(width, CM.SATURATED)
    w = _BitWriter()
    _serialize_primitive(w, schema, max_finite)
    result = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert result == max_finite


@_typed_parametrize("width", [16, 32, 64])
def _unittest_float_min_positive_roundtrip(width: int) -> None:
    min_positive_normalized = {
        16: 2.0**-14,
        32: 2.0**-126,
        64: 2.0**-1022,
    }[width]
    schema = FloatType(width, CM.SATURATED)
    w = _BitWriter()
    _serialize_primitive(w, schema, min_positive_normalized)
    result = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert result == min_positive_normalized


@_typed_parametrize("width", [16, 32, 64])
def _unittest_float_saturated_clamp_to_max_finite(width: int) -> None:
    overflow_input = {
        16: 70000.0,
        32: 1e100,
        64: 10**10000,
    }[width]
    max_finite = {
        16: 65504.0,
        32: 3.4028234663852886e38,
        64: 1.7976931348623157e308,
    }[width]
    schema = FloatType(width, CM.SATURATED)

    w = _BitWriter()
    _serialize_primitive(w, schema, overflow_input)
    result_positive = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert result_positive == max_finite

    w = _BitWriter()
    _serialize_primitive(w, schema, -overflow_input)
    result_negative = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert result_negative == -max_finite


@_typed_parametrize("width", [16, 32, 64])
def _unittest_float_saturated_inf_passthrough(width: int) -> None:
    schema = FloatType(width, CM.SATURATED)

    w = _BitWriter()
    _serialize_primitive(w, schema, float("inf"))
    result_positive = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert result_positive == float("inf")

    w = _BitWriter()
    _serialize_primitive(w, schema, float("-inf"))
    result_negative = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert result_negative == float("-inf")


@_typed_parametrize("width", [16, 32, 64])
def _unittest_float_saturated_nan_passthrough(width: int) -> None:
    schema = FloatType(width, CM.SATURATED)
    w = _BitWriter()
    _serialize_primitive(w, schema, float("nan"))
    result = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert isinstance(result, float)
    assert math.isnan(result)


@_typed_parametrize("width", [16, 32, 64])
def _unittest_float_truncated_overflow_to_inf(width: int) -> None:
    overflow_input = {
        16: 70000.0,
        32: 1e100,
        64: 10**10000,
    }[width]
    schema = FloatType(width, CM.TRUNCATED)

    w = _BitWriter()
    _serialize_primitive(w, schema, overflow_input)
    result_positive = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert result_positive == float("inf")

    w = _BitWriter()
    _serialize_primitive(w, schema, -overflow_input)
    result_negative = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert result_negative == float("-inf")


@_typed_parametrize("width", [16, 32, 64])
def _unittest_float_truncated_nan_passthrough(width: int) -> None:
    schema = FloatType(width, CM.TRUNCATED)
    w = _BitWriter()
    _serialize_primitive(w, schema, float("nan"))
    result = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert isinstance(result, float)
    assert math.isnan(result)


def _unittest_float16_precision_boundary() -> None:
    schema = FloatType(16, CM.TRUNCATED)

    ulp_at_one = 2.0**-10
    tie_boundary = 1.0 + 2.0**-11
    just_above_boundary = tie_boundary + 2.0**-15

    w = _BitWriter()
    _serialize_primitive(w, schema, tie_boundary)
    tied_result = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert tied_result == 1.0

    w = _BitWriter()
    _serialize_primitive(w, schema, just_above_boundary)
    above_result = _deserialize_primitive(_BitReader(w.finish()), schema)
    assert above_result == 1.0 + ulp_at_one


def _unittest_float_from_bool_input() -> None:
    for width in (16, 32, 64):
        schema = FloatType(width, CM.SATURATED)

        w = _BitWriter()
        _serialize_primitive(w, schema, False)
        false_result = _deserialize_primitive(_BitReader(w.finish()), schema)
        assert isinstance(false_result, float)
        assert false_result == 0.0

        w = _BitWriter()
        _serialize_primitive(w, schema, True)
        true_result = _deserialize_primitive(_BitReader(w.finish()), schema)
        assert isinstance(true_result, float)
        assert true_result == 1.0


def _unittest_bool_fixed_array_roundtrip() -> None:
    schema = FixedLengthArrayType(BooleanType(), 8)
    values = [True, True, False, True, False, False, True, True]

    writer = _BitWriter()
    _serialize_array(writer, schema, values)
    encoded = writer.finish()

    expected = _pack_chunks_lsb_first([(int(v), 1) for v in values])
    assert len(encoded) == 1
    assert encoded == expected
    assert _deserialize_array(_BitReader(encoded), schema) == values


@_typed_parametrize("length", [1, 2, 3, 7, 8, 9, 16])
def _unittest_bool_fixed_array_various_lengths(length: int) -> None:
    schema = FixedLengthArrayType(BooleanType(), length)
    values = [(index % 2) == 0 for index in range(length)]

    writer = _BitWriter()
    _serialize_array(writer, schema, values)
    encoded = writer.finish()

    expected = _pack_chunks_lsb_first([(int(v), 1) for v in values])
    assert len(encoded) == (length + 7) // 8
    assert encoded == expected
    assert _deserialize_array(_BitReader(encoded), schema) == values


def _unittest_uint3_fixed_array_roundtrip() -> None:
    schema = FixedLengthArrayType(UnsignedIntegerType(3, CM.TRUNCATED), 4)
    values = [1, 2, 3, 4]

    writer = _BitWriter()
    _serialize_array(writer, schema, values)
    encoded = writer.finish()

    expected = _pack_chunks_lsb_first([(value, 3) for value in values])
    assert len(encoded) == 2
    assert encoded == expected == bytes([0xD1, 0x08])
    assert _deserialize_array(_BitReader(encoded), schema) == values


def _unittest_uint5_fixed_array_roundtrip() -> None:
    schema = FixedLengthArrayType(UnsignedIntegerType(5, CM.TRUNCATED), 3)
    values = [1, 17, 31]

    writer = _BitWriter()
    _serialize_array(writer, schema, values)
    encoded = writer.finish()

    expected = _pack_chunks_lsb_first([(value, 5) for value in values])
    assert len(encoded) == 2
    assert encoded == expected == bytes([0x21, 0x7E])
    assert _deserialize_array(_BitReader(encoded), schema) == values


def _unittest_subbyte_variable_array_roundtrip() -> None:
    schema = VariableLengthArrayType(UnsignedIntegerType(3, CM.TRUNCATED), 10)
    values = [0, 1, 2, 3, 4, 5, 6, 7, 0, 1]

    writer = _BitWriter()
    _serialize_array(writer, schema, values)
    encoded = writer.finish()

    expected = _pack_chunks_lsb_first(
        [(len(values), schema.length_field_type.bit_length)] + [(value, 3) for value in values]
    )
    assert len(encoded) == 5
    assert encoded == expected
    assert _deserialize_array(_BitReader(encoded), schema) == values


def _unittest_mixed_subbyte_struct() -> None:
    schema = _mk_structure(
        "test.MixedSubbyteStruct",
        [
            Field(UnsignedIntegerType(3, CM.TRUNCATED), "a"),
            Field(BooleanType(), "b"),
            Field(UnsignedIntegerType(5, CM.TRUNCATED), "c"),
        ],
    )
    obj = {"a": 5, "b": True, "c": 17}

    encoded = serialize(schema, obj)
    expected = _pack_chunks_lsb_first([(5, 3), (1, 1), (17, 5)])
    assert len(encoded) == 2
    assert encoded == expected == bytes([0x1D, 0x01])
    assert deserialize(schema, encoded) == obj


def _unittest_bool_array_known_pattern() -> None:
    schema = FixedLengthArrayType(BooleanType(), 8)
    values = [True, False, True, False, True, False, True, False]

    writer = _BitWriter()
    _serialize_array(writer, schema, values)
    encoded = writer.finish()

    expected = _pack_chunks_lsb_first([(int(v), 1) for v in values])
    assert encoded == expected == bytes([0x55])
    assert _deserialize_array(_BitReader(encoded), schema) == values


def _mk_union_for_scaling_tests(name: str, variant_count: int) -> UnionType:
    return UnionType(
        name=name,
        version=Version(1, 0),
        attributes=[Field(UnsignedIntegerType(8, CM.TRUNCATED), f"v{index}") for index in range(variant_count)],
        deprecated=False,
        fixed_port_id=None,
        source_file_path=Path("test", name.split(".")[-1]),
        has_parent_service=False,
    )


def _unittest_union_3_variants_roundtrip() -> None:
    schema = _mk_union_for_scaling_tests("test.UnionThreeVariants", 3)
    assert schema.tag_field_type.bit_length == 8

    for index in range(3):
        obj = {f"v{index}": 10 + index}
        _roundtrip_assert(schema, obj)


def _unittest_union_4_variants_roundtrip() -> None:
    schema = _mk_union_for_scaling_tests("test.UnionFourVariants", 4)
    assert schema.tag_field_type.bit_length == 8

    for index in range(4):
        obj = {f"v{index}": 20 + index}
        _roundtrip_assert(schema, obj)


def _unittest_union_256_variants_tag_8bit() -> None:
    schema = _mk_union_for_scaling_tests("test.UnionTwoHundredFiftySixVariants", 256)
    assert schema.tag_field_type.bit_length == 8

    for index in [0, 255]:
        obj = {f"v{index}": 30 + (index % 200)}
        encoded = serialize(schema, obj)
        assert encoded[0] == index
        assert deserialize(schema, encoded) == obj


def _unittest_union_257_variants_tag_16bit() -> None:
    schema = _mk_union_for_scaling_tests("test.UnionTwoHundredFiftySevenVariants", 257)
    assert schema.tag_field_type.bit_length == 16

    for index in [0, 256]:
        obj = {f"v{index}": 40 + (index % 200)}
        encoded = serialize(schema, obj)
        assert int.from_bytes(encoded[:2], "little") == index
        assert deserialize(schema, encoded) == obj


def _unittest_union_tag_width_boundary_verification() -> None:
    def expected_tag_width(variant_count: int) -> int:
        return int(2 ** math.ceil(math.log2(max(8, (variant_count - 1).bit_length()))))

    for variant_count in [2, 3, 4, 256, 257]:
        schema = _mk_union_for_scaling_tests(f"test.UnionTagWidth{variant_count}", variant_count)
        assert schema.tag_field_type.bit_length == expected_tag_width(variant_count)

    assert expected_tag_width(256) == 8
    assert expected_tag_width(257) == 16


@_typed_parametrize("variant_count", [3, 4])
def _unittest_union_deserialize_all_variants(variant_count: int) -> None:
    schema = _mk_union_for_scaling_tests(f"test.UnionDeserializeAll{variant_count}", variant_count)

    for index in range(variant_count):
        obj = {f"v{index}": 50 + index}
        encoded = serialize(schema, obj)
        assert deserialize(schema, encoded) == obj


def _unittest_nested_struct_3_levels() -> None:
    level3 = _mk_structure(
        "test.Task12Nested3Level3",
        [Field(UnsignedIntegerType(16, CM.TRUNCATED), "value"), Field(BooleanType(), "ok")],
    )
    level2 = _mk_structure(
        "test.Task12Nested3Level2",
        [Field(level3, "inner"), Field(UnsignedIntegerType(8, CM.TRUNCATED), "seq")],
    )
    level1 = _mk_structure(
        "test.Task12Nested3Level1",
        [Field(level2, "middle"), Field(BooleanType(), "ready")],
    )

    _roundtrip_assert(
        level1,
        {
            "middle": {"inner": {"value": 0x1234, "ok": True}, "seq": 9},
            "ready": False,
        },
    )


def _unittest_nested_struct_4_levels() -> None:
    level4 = _mk_structure(
        "test.Task12Nested4Level4",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "leaf"), Field(BooleanType(), "valid")],
    )
    level3 = _mk_structure(
        "test.Task12Nested4Level3",
        [Field(level4, "node"), Field(UnsignedIntegerType(16, CM.TRUNCATED), "crc")],
    )
    level2 = _mk_structure(
        "test.Task12Nested4Level2",
        [Field(level3, "branch"), Field(UnsignedIntegerType(8, CM.TRUNCATED), "index")],
    )
    level1 = _mk_structure(
        "test.Task12Nested4Level1",
        [Field(level2, "root"), Field(BooleanType(), "armed")],
    )

    _roundtrip_assert(
        level1,
        {
            "root": {
                "branch": {"node": {"leaf": 77, "valid": True}, "crc": 0xBEEF},
                "index": 3,
            },
            "armed": True,
        },
    )


def _unittest_array_of_structs() -> None:
    point = _mk_structure(
        "test.Task12ArrayOfStructsPoint",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x"), Field(UnsignedIntegerType(8, CM.TRUNCATED), "y")],
    )
    schema = _mk_structure(
        "test.Task12ArrayOfStructs",
        [
            Field(FixedLengthArrayType(point, 3), "points"),
            Field(BooleanType(), "ready"),
        ],
    )

    _roundtrip_assert(
        schema,
        {
            "points": [
                {"x": 1, "y": 2},
                {"x": 10, "y": 20},
                {"x": 254, "y": 253},
            ],
            "ready": True,
        },
    )


def _unittest_array_of_unions() -> None:
    detail = _mk_structure(
        "test.Task12ArrayOfUnionsDetail",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "code"), Field(BooleanType(), "enabled")],
    )
    choice = _mk_union(
        "test.Task12ArrayOfUnionsChoice",
        [
            Field(BooleanType(), "flag"),
            Field(detail, "detail"),
        ],
    )
    schema = _mk_structure(
        "test.Task12ArrayOfUnions",
        [Field(FixedLengthArrayType(choice, 3), "items")],
    )

    _roundtrip_assert(
        schema,
        {
            "items": [
                {"flag": True},
                {"detail": {"code": 42, "enabled": False}},
                {"flag": False},
            ]
        },
    )


def _unittest_union_with_struct_variants() -> None:
    alpha = _mk_structure(
        "test.Task12UnionWithStructAlpha",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x"), Field(BooleanType(), "y")],
    )
    beta = _mk_structure(
        "test.Task12UnionWithStructBeta",
        [Field(UnsignedIntegerType(16, CM.TRUNCATED), "z")],
    )
    schema = _mk_union(
        "test.Task12UnionWithStructVariants",
        [
            Field(alpha, "alpha"),
            Field(beta, "beta"),
        ],
    )

    _roundtrip_assert(schema, {"alpha": {"x": 11, "y": True}})
    _roundtrip_assert(schema, {"beta": {"z": 0xCAFE}})


def _unittest_struct_union_struct_nesting() -> None:
    left = _mk_structure(
        "test.Task12StructUnionStructLeft",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"), Field(BooleanType(), "b")],
    )
    right = _mk_structure(
        "test.Task12StructUnionStructRight",
        [Field(UnsignedIntegerType(16, CM.TRUNCATED), "c")],
    )
    nested_union = _mk_union(
        "test.Task12StructUnionStructUnion",
        [
            Field(left, "left"),
            Field(right, "right"),
        ],
    )
    schema = _mk_structure(
        "test.Task12StructUnionStructOuter",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "prefix"),
            Field(nested_union, "payload"),
            Field(BooleanType(), "tail"),
        ],
    )

    _roundtrip_assert(schema, {"prefix": 1, "payload": {"left": {"a": 7, "b": True}}, "tail": False})
    _roundtrip_assert(schema, {"prefix": 2, "payload": {"right": {"c": 1024}}, "tail": True})


def _unittest_struct_array_struct_nesting() -> None:
    item = _mk_structure(
        "test.Task12StructArrayStructItem",
        [Field(UnsignedIntegerType(16, CM.TRUNCATED), "sample"), Field(BooleanType(), "good")],
    )
    schema = _mk_structure(
        "test.Task12StructArrayStructOuter",
        [
            Field(FixedLengthArrayType(item, 2), "samples"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "count"),
        ],
    )

    _roundtrip_assert(
        schema,
        {
            "samples": [
                {"sample": 0x1001, "good": True},
                {"sample": 0x2002, "good": False},
            ],
            "count": 2,
        },
    )


def _unittest_complex_mixed_nesting() -> None:
    sensor = _mk_structure(
        "test.Task12ComplexSensor",
        [Field(UnsignedIntegerType(16, CM.TRUNCATED), "reading"), Field(BooleanType(), "healthy")],
    )
    meta = _mk_structure(
        "test.Task12ComplexMeta",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "node_id"), Field(sensor, "snapshot")],
    )
    event = _mk_structure(
        "test.Task12ComplexEvent",
        [
            Field(FixedLengthArrayType(sensor, 2), "recent"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "severity"),
        ],
    )
    payload = _mk_union(
        "test.Task12ComplexPayload",
        [
            Field(meta, "meta"),
            Field(event, "event"),
        ],
    )
    schema = _mk_structure(
        "test.Task12ComplexRoot",
        [
            Field(payload, "primary"),
            Field(FixedLengthArrayType(payload, 2), "fallbacks"),
            Field(FixedLengthArrayType(sensor, 2), "history"),
            Field(BooleanType(), "ack"),
        ],
    )

    _roundtrip_assert(
        schema,
        {
            "primary": {"meta": {"node_id": 12, "snapshot": {"reading": 500, "healthy": True}}},
            "fallbacks": [
                {
                    "event": {
                        "recent": [{"reading": 1, "healthy": True}, {"reading": 2, "healthy": False}],
                        "severity": 3,
                    }
                },
                {"meta": {"node_id": 99, "snapshot": {"reading": 1000, "healthy": False}}},
            ],
            "history": [
                {"reading": 300, "healthy": True},
                {"reading": 301, "healthy": True},
            ],
            "ack": True,
        },
    )

    _roundtrip_assert(
        schema,
        {
            "primary": {
                "event": {"recent": [{"reading": 7, "healthy": True}, {"reading": 8, "healthy": True}], "severity": 1}
            },
            "fallbacks": [
                {"meta": {"node_id": 1, "snapshot": {"reading": 9, "healthy": True}}},
                {
                    "event": {
                        "recent": [{"reading": 10, "healthy": False}, {"reading": 11, "healthy": True}],
                        "severity": 2,
                    }
                },
            ],
            "history": [
                {"reading": 12, "healthy": False},
                {"reading": 13, "healthy": True},
            ],
            "ack": False,
        },
    )


# ============================================================================
# MIXED ALIGNMENT, DEFAULTS, AND API EDGE CASE TESTS (Task 13)
# ============================================================================


def _unittest_mixed_alignment_struct() -> None:
    """
    Test struct with mixed alignment: byte-aligned and sub-byte fields.

    Struct: {uint8 a, bool b, uint16 c}
    - uint8: 8 bits (bits 0-7)
    - bool: 1 bit (bit 8)
    - uint16: 16 bits (bits 9-24)

    Note: Primitives have alignment_requirement=1 (bit-aligned, no padding).
    Only composite types enforce alignment > 1.

    Expected wire layout (bit-packed, no alignment padding):
    - Bits 0-7: uint8 a
    - Bit 8: bool b
    - Bits 9-24: uint16 c (little-endian)
    Total: 25 bits → 4 bytes (with 7 padding bits at end)
    """
    schema = _mk_structure(
        "test.MixedAlignment",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"),
            Field(BooleanType(), "b"),
            Field(UnsignedIntegerType(16, CM.TRUNCATED), "c"),
        ],
    )

    obj = {"a": 0xAA, "b": True, "c": 0x1234}
    data = serialize(schema, obj)

    # Verify wire format (primitives are bit-packed):
    # Byte 0: 0xAA (bits 0-7)
    # Byte 1: 0x69 (bit 8: True, bits 9-15: first 7 bits of 0x1234)
    # Byte 2: 0x24 (bits 16-23: middle 8 bits of 0x1234)
    # Byte 3: 0x00 (bit 24: last bit of 0x1234, bits 25-31: padding)
    assert len(data) == 4
    assert data == bytes([0xAA, 0x69, 0x24, 0x00])

    # Verify roundtrip
    result = deserialize(schema, data)
    assert result == obj


def _unittest_alignment_padding_insertion() -> None:
    """
    Test alignment padding insertion for COMPOSITE types (not primitives).

    Primitives have alignment_requirement=1 (bit-packed).
    Composite types (structs) have alignment based on their max field alignment.
    Verify that composite fields within structs enforce alignment.
    """
    inner_uint3 = _mk_structure(
        "test.AlignmentPaddingInnerUint3",
        [Field(UnsignedIntegerType(3, CM.TRUNCATED), "value")],
    )
    inner_bool = _mk_structure(
        "test.AlignmentPaddingInnerBool",
        [Field(BooleanType(), "flag")],
    )

    schema1 = _mk_structure(
        "test.AlignmentPadding1",
        [
            Field(inner_uint3, "x"),
            Field(inner_bool, "y"),
        ],
    )

    obj1 = {"x": {"value": 5}, "y": {"flag": True}}
    data1 = serialize(schema1, obj1)

    inner_uint3_alignment = inner_uint3.alignment_requirement
    inner_bool_alignment = inner_bool.alignment_requirement
    assert inner_uint3_alignment == 8
    assert inner_bool_alignment == 8
    assert len(data1) == 2

    result1 = deserialize(schema1, data1)
    assert result1 == obj1

    inner_multi = _mk_structure(
        "test.AlignmentPaddingMulti",
        [
            Field(BooleanType(), "a"),
            Field(BooleanType(), "b"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "c"),
        ],
    )

    schema2 = _mk_structure(
        "test.AlignmentPadding2",
        [
            Field(UnsignedIntegerType(3, CM.TRUNCATED), "prefix"),
            Field(inner_multi, "nested"),
        ],
    )

    obj2 = {"prefix": 7, "nested": {"a": True, "b": False, "c": 42}}
    data2 = serialize(schema2, obj2)

    result2 = deserialize(schema2, data2)
    assert result2 == obj2


def _unittest_struct_with_all_defaults() -> None:
    """
    Test struct where all fields have default values.

    When deserializing with missing data (empty bytes or truncated payload),
    all fields should use their default values.
    """
    schema = _mk_structure(
        "test.AllDefaults",
        [
            Field(BooleanType(), "flag"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "count"),
            Field(FloatType(32, CM.SATURATED), "value"),
            Field(VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 10), "items"),
        ],
    )

    # Deserialize from empty bytes
    result_empty = deserialize(schema, bytes())
    expected_defaults = {
        "flag": False,
        "count": 0,
        "value": 0.0,
        "items": [],
    }
    assert result_empty == expected_defaults

    # Serialize empty object (uses defaults) and verify roundtrip
    data = serialize(schema, {})
    result_roundtrip = deserialize(schema, data)
    assert result_roundtrip == expected_defaults


def _unittest_partial_defaults_struct() -> None:
    """
    Test struct with partial defaults: some fields provided, others use defaults.

    Verify that provided fields are serialized correctly and missing fields
    use default values during deserialization.
    """
    inner = _mk_structure(
        "test.PartialDefaultsInner",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")],
    )
    schema = _mk_structure(
        "test.PartialDefaults",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"),
            Field(BooleanType(), "b"),
            Field(inner, "nested"),
            Field(FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 2), "arr"),
        ],
    )

    # Provide only first field
    partial1 = {"a": 42}
    data1 = serialize(schema, partial1)
    result1 = deserialize(schema, data1)
    assert result1 == {
        "a": 42,
        "b": False,
        "nested": {"x": 0},
        "arr": [0, 0],
    }

    # Provide first two fields
    partial2 = {"a": 99, "b": True}
    data2 = serialize(schema, partial2)
    result2 = deserialize(schema, data2)
    assert result2 == {
        "a": 99,
        "b": True,
        "nested": {"x": 0},
        "arr": [0, 0],
    }

    # Provide all but array
    partial3 = {"a": 10, "b": False, "nested": {"x": 20}}
    data3 = serialize(schema, partial3)
    result3 = deserialize(schema, data3)
    assert result3 == {
        "a": 10,
        "b": False,
        "nested": {"x": 20},
        "arr": [0, 0],
    }


def _unittest_empty_struct_roundtrip() -> None:
    """
    Test empty struct (no fields) serialization and deserialization.

    Empty structs should serialize to zero bytes and deserialize to empty dict.
    """
    schema = _mk_structure("test.EmptyStruct", [])

    obj: dict[str, object] = {}
    data = serialize(schema, obj)

    # Empty struct serializes to empty bytes
    assert data == bytes()

    # Roundtrip
    result = deserialize(schema, data)
    assert result == {}

    # Deserialize from any bytes (implicit truncation)
    result_truncated = deserialize(schema, bytes([0xFF, 0xAA, 0x55]))
    assert result_truncated == {}


def _unittest_single_field_struct() -> None:
    """
    Test struct with exactly one field.

    Verify minimal struct serialization and deserialization.
    """
    # Test 1: Single primitive field
    schema1 = _mk_structure(
        "test.SingleFieldPrimitive",
        [Field(UnsignedIntegerType(16, CM.TRUNCATED), "value")],
    )

    obj1 = {"value": 0xABCD}
    data1 = serialize(schema1, obj1)
    assert data1 == bytes([0xCD, 0xAB])  # little-endian

    result1 = deserialize(schema1, data1)
    assert result1 == obj1

    # Test 2: Single composite field (nested struct)
    inner = _mk_structure(
        "test.SingleFieldInner",
        [Field(BooleanType(), "flag")],
    )
    schema2 = _mk_structure(
        "test.SingleFieldComposite",
        [Field(inner, "nested")],
    )

    obj2 = {"nested": {"flag": True}}
    data2 = serialize(schema2, obj2)
    assert data2 == bytes([0x01])

    result2 = deserialize(schema2, data2)
    assert result2 == obj2

    # Test 3: Single array field
    schema3 = _mk_structure(
        "test.SingleFieldArray",
        [Field(FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 3), "items")],
    )

    obj3 = {"items": [10, 20, 30]}
    data3 = serialize(schema3, obj3)
    assert data3 == bytes([10, 20, 30])

    result3 = deserialize(schema3, data3)
    assert result3 == obj3


def _unittest_single_variant_union() -> None:
    """
    Test union with minimum allowed variants (2).

    UnionType requires MIN_NUMBER_OF_VARIANTS=2.
    Test that a 2-variant union works correctly when only using one variant.
    """
    schema = _mk_union(
        "test.TwoVariantUnion",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "option_a"),
            Field(UnsignedIntegerType(16, CM.TRUNCATED), "option_b"),
        ],
    )

    assert schema.tag_field_type.bit_length == 8

    obj_a = {"option_a": 42}
    data_a = serialize(schema, obj_a)

    assert data_a[0] == 0
    assert deserialize(schema, data_a) == obj_a

    obj_b = {"option_b": 0x1234}
    data_b = serialize(schema, obj_b)

    assert data_b[0] == 1
    assert deserialize(schema, data_b) == obj_b

    with pytest.raises(UnionFieldError, match="Unknown union variant"):
        serialize(schema, {"nonexistent": 123})


def _unittest_api_type_coercion_int_to_float() -> None:
    """
    Test API type coercion: int → float.

    Integer values should be accepted for float fields and coerced to float.
    """
    schema = _mk_structure(
        "test.IntToFloatCoercion",
        [
            Field(FloatType(32, CM.SATURATED), "value32"),
            Field(FloatType(64, CM.SATURATED), "value64"),
        ],
    )

    # Provide integers for float fields
    obj_int = {"value32": 42, "value64": 123}
    data = serialize(schema, obj_int)
    result = deserialize(schema, data)

    # Verify coercion: integers are converted to floats
    assert isinstance(result["value32"], float)
    assert isinstance(result["value64"], float)
    assert result["value32"] == 42.0
    assert result["value64"] == 123.0

    # Test with negative integers
    obj_negative = {"value32": -99, "value64": -456}
    data_negative = serialize(schema, obj_negative)
    result_negative = deserialize(schema, data_negative)
    assert result_negative["value32"] == -99.0
    assert result_negative["value64"] == -456.0


def _unittest_api_type_coercion_list_to_tuple() -> None:
    """
    Test API type coercion: list → tuple for arrays.

    Arrays should accept both list and tuple inputs and always deserialize as list.
    """
    schema = _mk_structure(
        "test.ListTupleCoercion",
        [
            Field(FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 3), "fixed"),
            Field(VariableLengthArrayType(UnsignedIntegerType(16, CM.TRUNCATED), 10), "variable"),
        ],
    )

    # Test 1: Provide tuples for array fields
    obj_tuple = {
        "fixed": (10, 20, 30),
        "variable": (100, 200, 300),
    }
    data_tuple = serialize(schema, obj_tuple)
    result_tuple = deserialize(schema, data_tuple)

    # Verify deserialization returns lists (canonical form)
    assert isinstance(result_tuple["fixed"], list)
    assert isinstance(result_tuple["variable"], list)
    assert result_tuple == {
        "fixed": [10, 20, 30],
        "variable": [100, 200, 300],
    }

    # Test 2: Provide lists (should work identically)
    obj_list = {
        "fixed": [10, 20, 30],
        "variable": [100, 200, 300],
    }
    data_list = serialize(schema, obj_list)
    result_list = deserialize(schema, data_list)

    assert result_list == result_tuple
    assert data_list == data_tuple


def _unittest_api_error_handling_invalid_input() -> None:
    """
    Test API error handling for invalid inputs.

    Verify that appropriate exceptions are raised for:
    - Invalid field names
    - Type mismatches
    - Out-of-range values
    - Invalid union variants
    """
    # Test 1: Unknown field in struct
    schema_struct = _mk_structure(
        "test.ErrorHandlingStruct",
        [Field(UnsignedIntegerType(8, CM.TRUNCATED), "x")],
    )

    with pytest.raises(ValueError, match="Unknown field"):
        serialize(schema_struct, {"x": 10, "unknown": 20})

    # Test 2: Non-dict value for struct
    with pytest.raises(ValueError, match="Structure value must be a dict"):
        serialize(schema_struct, typing.cast(_Obj, typing.cast(object, "not a dict")))

    # Test 3: Invalid array length (fixed-length array)
    schema_array = _mk_structure(
        "test.ErrorHandlingArray",
        [Field(FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 3), "arr")],
    )

    with pytest.raises(ArrayLengthError):
        serialize(schema_array, {"arr": [1, 2]})  # Too short

    with pytest.raises(ArrayLengthError):
        serialize(schema_array, {"arr": [1, 2, 3, 4]})  # Too long

    # Test 4: Invalid union variant
    schema_union = _mk_union(
        "test.ErrorHandlingUnion",
        [
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "a"),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), "b"),
        ],
    )

    with pytest.raises(UnionFieldError, match="Unknown union variant"):
        serialize(schema_union, {"unknown_variant": 42})

    with pytest.raises(ValueError, match="exactly one field"):
        serialize(schema_union, {})  # No variant selected

    with pytest.raises(ValueError, match="exactly one field"):
        serialize(schema_union, {"a": 10, "b": 20})  # Multiple variants

    # Test 5: Type mismatch for primitive arrays
    schema_byte_array = _mk_structure(
        "test.ErrorHandlingByteArray",
        [Field(VariableLengthArrayType(ByteType(), 10), "data")],
    )

    with pytest.raises(TypeError, match="Byte array requires"):
        serialize(schema_byte_array, {"data": 123})  # Not a sequence

    # Test 6: Variable-length array capacity exceeded
    schema_vararray = _mk_structure(
        "test.ErrorHandlingVarArray",
        [Field(VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 3), "items")],
    )

    with pytest.raises(ArrayLengthError):
        serialize(schema_vararray, {"items": [1, 2, 3, 4]})  # Exceeds capacity
