# Copyright (c) 2018 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations

import struct
import typing

from ._serializable import (
    CompositeType, PrimitiveType, BooleanType, SignedIntegerType, UnsignedIntegerType, FloatType, VoidType,
    ArrayType, FixedLengthArrayType, VariableLengthArrayType, UTF8Type, ByteType,
    StructureType, UnionType, ServiceType, DelimitedType, Field, PaddingField
)


# ============================================================================
# ERROR HIERARCHY
# ============================================================================


class SerDesError(Exception):
    """
    Root exception for serialization/deserialization errors.
    This is raised when serialization or deserialization operations fail.
    """

    pass


class ArrayLengthError(SerDesError):
    """
    Raised when an array length constraint is violated during serialization or deserialization.
    """

    pass


class UnionFieldError(SerDesError):
    """
    Raised when a union field is invalid or missing during serialization or deserialization.
    """

    pass


class UnionTagError(SerDesError):
    """
    Raised when a union tag is invalid or out of range during deserialization.
    """

    pass


class DelimiterHeaderError(SerDesError):
    """
    Raised when a delimiter header is malformed or invalid during deserialization.
    """

    pass


# ============================================================================
# TYPE ALIASES
# ============================================================================

_Value = bool | int | float | str | bytes | dict[str, typing.Any] | list[typing.Any] | tuple[typing.Any, ...] | None
_Obj = dict[str, typing.Any]

_DEFAULT_SENTINEL = object()


# ============================================================================
# SERIALIZATION/DESERIALIZATION FUNCTIONS
# ============================================================================


def serialize(_schema: CompositeType, _obj: _Obj, *, _with_delimiter_header: bool = False) -> bytes:
    """
    Serialize a Python object to bytes according to the given schema.

    Args:
        _schema: The composite type schema defining the structure.
        _obj: The Python object to serialize (typically a dict).
        _with_delimiter_header: If True, prepend a delimiter header to the output.

    Returns:
        The serialized bytes.

    Raises:
        SerDesError: If serialization fails.
    """
    ...


def deserialize(
    _schema: CompositeType, _data: bytes | bytearray | memoryview, *, _with_delimiter_header: bool = False
) -> _Obj:
    """
    Deserialize bytes to a Python object according to the given schema.

    Args:
        schema: The composite type schema defining the structure.
        data: The bytes to deserialize.
        with_delimiter_header: If True, expect and parse a delimiter header from the input.

    Returns:
        The deserialized Python object (typically a dict).

    Raises:
        SerDesError: If deserialization fails.
    """
    ...


# ============================================================================
# BIT-LEVEL INFRASTRUCTURE
# ============================================================================


class _BitWriter:
    """
    Writes bits to a byte buffer with LSB-first ordering within each byte.
    Multi-byte values are little-endian.
    """

    def __init__(self) -> None:
        self._buffer: bytearray = bytearray()
        self._bit_offset: int = 0

    def write_bits(self, value: int, bit_length: int) -> None:
        """
        Write bit_length bits from value to the buffer.
        Bits are written LSB-first within each byte, little-endian for multi-byte values.
        """
        for i in range(bit_length):
            bit = (value >> i) & 1
            byte_index = (self._bit_offset + i) // 8
            bit_index = (self._bit_offset + i) % 8

            if byte_index >= len(self._buffer):
                self._buffer.append(0)

            if bit:
                self._buffer[byte_index] |= 1 << bit_index
            else:
                self._buffer[byte_index] &= ~(1 << bit_index)

        self._bit_offset += bit_length

    def align_to(self, bit_alignment: int) -> None:
        """
        Write zero pad bits until bit_offset is a multiple of bit_alignment.
        """
        if bit_alignment <= 0:
            return
        remainder = self._bit_offset % bit_alignment
        if remainder != 0:
            pad_bits = bit_alignment - remainder
            self.write_bits(0, pad_bits)

    def finish(self) -> bytes:
        """
        Return immutable bytes from the internal buffer.
        """
        return bytes(self._buffer)

    @property
    def bit_offset(self) -> int:
        """Current write position in bits."""
        return self._bit_offset


class _BitReader:
    """
    Reads bits from a byte buffer with LSB-first ordering within each byte.
    Multi-byte values are little-endian.
    Out-of-bounds reads return zeros (implicit zero extension).
    """

    def __init__(
        self, data: bytes | bytearray | memoryview, bit_offset: int = 0, bit_limit: int | None = None
    ) -> None:
        self._data: bytes = bytes(data) if isinstance(data, (bytearray, memoryview)) else data
        self._bit_offset: int = bit_offset
        self._bit_limit: int | None = bit_limit

    def read_bits(self, bit_length: int) -> int:
        """
        Read bit_length bits from current position with LSB-first ordering.
        Out-of-bounds bits return zeros (implicit zero extension).
        """
        result = 0
        for i in range(bit_length):
            byte_index = (self._bit_offset + i) // 8
            bit_index = (self._bit_offset + i) % 8

            if byte_index < len(self._data):
                bit = (self._data[byte_index] >> bit_index) & 1
            else:
                bit = 0

            result |= bit << i

        self._bit_offset += bit_length
        return result

    def align_to(self, bit_alignment: int) -> None:
        """
        Skip bits until position is a multiple of bit_alignment.
        """
        if bit_alignment <= 0:
            return
        remainder = self._bit_offset % bit_alignment
        if remainder != 0:
            skip_bits = bit_alignment - remainder
            self._bit_offset += skip_bits

    def bounded_subreader(self, bit_count: int) -> _BitReader:
        """
        Create a reader limited to bit_count bits from current position.
        Advances the parent reader past those bits.
        """
        subreader = _BitReader(self._data, self._bit_offset, bit_count)
        self._bit_offset += bit_count
        return subreader

    @property
    def remaining_bits(self) -> int:
         """Bits remaining before limit (or end of data if no limit)."""
         if self._bit_limit is not None:
             return max(0, self._bit_limit - (self._bit_offset - (self._bit_offset - self._bit_limit)))
         else:
             return max(0, len(self._data) * 8 - self._bit_offset)

    @property
    def bit_offset(self) -> int:
        """Current read position in bits."""
        return self._bit_offset


# ============================================================================
# PRIMITIVE CODEC
# ============================================================================


def _serialize_primitive(writer: _BitWriter, schema: PrimitiveType | VoidType, value: _Value) -> None:
    """
    Serialize a primitive value to bits according to the schema.
    Handles input coercion, cast-mode handling, and encoding.
    """
    if isinstance(schema, BooleanType):
        if not isinstance(value, (bool, int, float)):
            raise ValueError(f"Boolean requires numeric input, got {type(value).__name__}")
        if isinstance(value, float):
            if not (-float('inf') < value < float('inf')):
                raise ValueError(f"Non-finite float cannot be converted to bool")
        bit_value = 1 if value else 0
        writer.write_bits(bit_value, 1)

    elif isinstance(schema, FloatType):
        if not isinstance(value, (bool, int, float)):
            raise ValueError(f"Float requires numeric input, got {type(value).__name__}")
        float_value = float(value)

        if schema.cast_mode == PrimitiveType.CastMode.SATURATED:
            range_val = schema.inclusive_value_range
            min_bound = float(range_val.min)
            max_bound = float(range_val.max)
            if float_value != float_value:
                pass
            elif float_value == float('inf'):
                pass
            elif float_value == float('-inf'):
                pass
            else:
                float_value = max(min_bound, min(max_bound, float_value))

        if schema.bit_length == 16:
            packed = struct.pack('<e', float_value)
        elif schema.bit_length == 32:
            packed = struct.pack('<f', float_value)
        elif schema.bit_length == 64:
            packed = struct.pack('<d', float_value)
        else:
            raise ValueError(f"Invalid float bit length: {schema.bit_length}")

        for byte_val in packed:
            writer.write_bits(byte_val, 8)

    elif isinstance(schema, SignedIntegerType):
        if not isinstance(value, (bool, int, float)):
            raise ValueError(f"Integer requires numeric input, got {type(value).__name__}")
        if isinstance(value, float):
            if not (-float('inf') < value < float('inf')):
                raise ValueError(f"Non-finite float cannot be converted to int")
            int_value = int(round(value))
        else:
            int_value = int(value)

        if schema.cast_mode == PrimitiveType.CastMode.SATURATED:
            range_val = schema.inclusive_value_range
            min_bound = int(range_val.min)
            max_bound = int(range_val.max)
            int_value = max(min_bound, min(max_bound, int_value))
        else:
            mask = (1 << schema.bit_length) - 1
            int_value = int_value & mask

        raw_value = int_value & ((1 << schema.bit_length) - 1)
        writer.write_bits(raw_value, schema.bit_length)

    elif isinstance(schema, UnsignedIntegerType):
        if not isinstance(value, (bool, int, float)):
            raise ValueError(f"Integer requires numeric input, got {type(value).__name__}")
        if isinstance(value, float):
            if not (-float('inf') < value < float('inf')):
                raise ValueError(f"Non-finite float cannot be converted to int")
            int_value = int(round(value))
        else:
            int_value = int(value)

        if schema.cast_mode == PrimitiveType.CastMode.SATURATED:
            range_val = schema.inclusive_value_range
            min_bound = int(range_val.min)
            max_bound = int(range_val.max)
            int_value = max(min_bound, min(max_bound, int_value))
        else:
            mask = (1 << schema.bit_length) - 1
            int_value = int_value & mask

        writer.write_bits(int_value, schema.bit_length)

    elif isinstance(schema, VoidType):
        writer.write_bits(0, schema.bit_length)

    else:
        raise ValueError(f"Unknown primitive type: {type(schema).__name__}")


def _deserialize_primitive(reader: _BitReader, schema: PrimitiveType | VoidType) -> _Value:
    """
    Deserialize a primitive value from bits according to the schema.
    """
    if isinstance(schema, BooleanType):
        bit_value = reader.read_bits(1)
        return bool(bit_value)

    elif isinstance(schema, FloatType):
        if schema.bit_length == 16:
            fmt = '<e'
        elif schema.bit_length == 32:
            fmt = '<f'
        elif schema.bit_length == 64:
            fmt = '<d'
        else:
            raise ValueError(f"Invalid float bit length: {schema.bit_length}")

        byte_count = schema.bit_length // 8
        bytes_data = bytearray()
        for _ in range(byte_count):
            bytes_data.append(reader.read_bits(8))

        return struct.unpack(fmt, bytes(bytes_data))[0]

    elif isinstance(schema, SignedIntegerType):
        raw_value = reader.read_bits(schema.bit_length)
        if raw_value >= (1 << (schema.bit_length - 1)):
            result = raw_value - (1 << schema.bit_length)
        else:
            result = raw_value
        return result

    elif isinstance(schema, UnsignedIntegerType):
        return reader.read_bits(schema.bit_length)

    elif isinstance(schema, VoidType):
        _ = reader.read_bits(schema.bit_length)
        return None

    else:
        raise ValueError(f"Unknown primitive type: {type(schema).__name__}")


# ============================================================================
# ARRAY CODEC
# ============================================================================


def _serialize_array(writer: _BitWriter, schema: ArrayType, value: _Value) -> None:
    """
    Serialize an array value to bits according to the schema.
    Handles fixed-length and variable-length arrays with special cases for UTF-8 and byte arrays.
    """
    if isinstance(schema.element_type, UTF8Type):
        if isinstance(value, str):
            value = value.encode('utf-8')
        elif isinstance(value, (bytes, bytearray)):
            _ = value.decode('utf-8')
        else:
            raise TypeError(f"UTF-8 array requires str, bytes, or bytearray input, got {type(value).__name__}")
        value = list(value)

    elif isinstance(schema.element_type, ByteType):
        if isinstance(value, str):
            value = value.encode('utf-8')
        elif isinstance(value, (bytes, bytearray)):
            value = list(value)
        elif isinstance(value, (list, tuple)):
            pass
        else:
            raise TypeError(f"Byte array requires list, tuple, bytes, bytearray, or str input, got {type(value).__name__}")

    elif isinstance(value, (list, tuple)):
        pass
    else:
        raise TypeError(f"Array requires list or tuple input, got {type(value).__name__}")

    if isinstance(schema, FixedLengthArrayType):
        if len(value) != schema.capacity:
            raise ArrayLengthError(f"Fixed-length array requires exactly {schema.capacity} elements, got {len(value)}")

        for element in value:
            _serialize_element(writer, schema.element_type, element)

    elif isinstance(schema, VariableLengthArrayType):
        if not (0 <= len(value) <= schema.capacity):
            raise ArrayLengthError(f"Variable-length array length {len(value)} exceeds capacity {schema.capacity}")

        writer.write_bits(len(value), schema.length_field_type.bit_length)

        for element in value:
            _serialize_element(writer, schema.element_type, element)

    else:
        raise ValueError(f"Unknown array type: {type(schema).__name__}")


def _deserialize_array(reader: _BitReader, schema: ArrayType) -> _Value:
    """
    Deserialize an array value from bits according to the schema.
    Returns str for UTF-8 arrays, bytes for byte arrays, and list for other arrays.
    """
    if isinstance(schema, FixedLengthArrayType):
        length = schema.capacity
    elif isinstance(schema, VariableLengthArrayType):
        length = reader.read_bits(schema.length_field_type.bit_length)
        if length > schema.capacity:
            raise ArrayLengthError(f"Variable-length array length {length} exceeds capacity {schema.capacity}")
    else:
        raise ValueError(f"Unknown array type: {type(schema).__name__}")

    elements = []
    for _ in range(length):
        element = _deserialize_element(reader, schema.element_type)
        elements.append(element)

    if isinstance(schema.element_type, UTF8Type):
        return bytes(elements).decode('utf-8')
    elif isinstance(schema.element_type, ByteType):
        return bytes(elements)
    else:
        return elements


def _serialize_element(writer: _BitWriter, element_type: typing.Any, value: _Value) -> None:
    """
    Serialize a single array element based on its type.
    """
    if isinstance(element_type, (PrimitiveType, VoidType)):
        _serialize_primitive(writer, element_type, value)  # type: ignore
    elif isinstance(element_type, ArrayType):
        _serialize_array(writer, element_type, value)
    elif isinstance(element_type, CompositeType):
        _serialize_composite(writer, element_type, typing.cast(_Obj, value))
    else:
        raise ValueError(f"Unknown element type: {type(element_type).__name__}")


def _deserialize_element(reader: _BitReader, element_type: typing.Any) -> _Value:
    """
    Deserialize a single array element based on its type.
    """
    if isinstance(element_type, (PrimitiveType, VoidType)):
        return _deserialize_primitive(reader, element_type)  # type: ignore
    elif isinstance(element_type, ArrayType):
        return _deserialize_array(reader, element_type)
    elif isinstance(element_type, CompositeType):
        return _deserialize_composite(reader, element_type)  # type: ignore
    else:
        raise ValueError(f"Unknown element type: {type(element_type).__name__}")


# ============================================================================
# COMPOSITE CODEC
# ============================================================================


def _serialize_composite(writer: _BitWriter, schema: CompositeType, obj: _Obj) -> None:
    """
    Serialize a composite value to bits according to the schema.
    Handles structures, unions, and delimited types with proper alignment and field ordering.
    """
    if isinstance(schema, DelimitedType):
        temp_writer = _BitWriter()
        _serialize_composite(temp_writer, schema.inner_type, obj)
        inner_bytes = temp_writer.finish()
        writer.write_bits(len(inner_bytes), schema.delimiter_header_type.bit_length)
        for byte_val in inner_bytes:
            writer.write_bits(byte_val, 8)

    elif isinstance(schema, UnionType):
        if not isinstance(obj, dict):
            raise ValueError("Union value must be a dict")
        if len(obj) == 0:
            raise ValueError("Union must have exactly one field, got none")
        if len(obj) > 1:
            raise ValueError("Union must have exactly one field, got multiple")

        key = next(iter(obj.keys()))
        value = obj[key]

        tag_index = None
        field = None
        for idx, f in enumerate(schema.fields):
            if f.name == key:
                tag_index = idx
                field = f
                break

        if tag_index is None:
            raise UnionFieldError(f"Unknown union variant: {key}")

        assert field is not None
        writer.write_bits(tag_index, schema.tag_field_type.bit_length)
        _serialize_field_value(writer, field.data_type, value)

    elif isinstance(schema, StructureType):
        valid_fields = {f.name for f in schema.fields_except_padding}
        for key in obj.keys():
            if key not in valid_fields:
                raise ValueError(f"Unknown field: {key}")

        for field in schema.fields:
            writer.align_to(field.data_type.alignment_requirement)

            if isinstance(field, PaddingField):
                void_type = typing.cast(VoidType, field.data_type)
                writer.write_bits(0, void_type.bit_length)
            else:
                value = obj.get(field.name, _DEFAULT_SENTINEL)
                if value is _DEFAULT_SENTINEL:
                    value = _default_value(field.data_type)
                _serialize_field_value(writer, field.data_type, value)

    elif isinstance(schema, ServiceType):
        raise TypeError("Service types are not directly serializable")

    else:
        raise ValueError(f"Unknown composite type: {type(schema).__name__}")


def _deserialize_composite(reader: _BitReader, schema: CompositeType) -> _Obj:
    """
    Deserialize a composite value from bits according to the schema.
    Returns a dict with field names as keys and deserialized values.
    """
    if isinstance(schema, DelimitedType):
        payload_byte_length = reader.read_bits(schema.delimiter_header_type.bit_length)
        payload_bit_length = payload_byte_length * 8
        
        if payload_bit_length > reader.remaining_bits:
            raise DelimiterHeaderError(
                f"Delimiter header specifies {payload_byte_length} bytes ({payload_bit_length} bits) "
                + f"but only {reader.remaining_bits} bits remain"
            )
        
        sub_reader = reader.bounded_subreader(payload_bit_length)
        return _deserialize_composite(sub_reader, schema.inner_type)

    elif isinstance(schema, UnionType):
        tag = reader.read_bits(schema.tag_field_type.bit_length)
        if tag >= len(schema.fields):
            raise UnionTagError(f"Invalid union tag: {tag}")

        field = schema.fields[tag]
        value = _deserialize_field_value(reader, field.data_type)
        return {field.name: value}

    elif isinstance(schema, StructureType):
        result = {}
        for field in schema.fields:
            reader.align_to(field.data_type.alignment_requirement)

            if isinstance(field, PaddingField):
                void_type = typing.cast(VoidType, field.data_type)
                _ = reader.read_bits(void_type.bit_length)
            else:
                value = _deserialize_field_value(reader, field.data_type)
                result[field.name] = value

        return result

    elif isinstance(schema, ServiceType):
        raise TypeError("Service types are not directly deserializable")

    else:
        raise ValueError(f"Unknown composite type: {type(schema).__name__}")


def _serialize_field_value(writer: _BitWriter, field_type: typing.Any, value: _Value) -> None:
    """
    Serialize a single field value based on its type.
    """
    if isinstance(field_type, (PrimitiveType, VoidType)):
        _serialize_primitive(writer, field_type, value)  # type: ignore
    elif isinstance(field_type, ArrayType):
        _serialize_array(writer, field_type, value)
    elif isinstance(field_type, CompositeType):
        _serialize_composite(writer, field_type, typing.cast(_Obj, value))
    else:
        raise ValueError(f"Unknown field type: {type(field_type).__name__}")


def _deserialize_field_value(reader: _BitReader, field_type: typing.Any) -> _Value:
    """
    Deserialize a single field value based on its type.
    """
    if isinstance(field_type, (PrimitiveType, VoidType)):
        return _deserialize_primitive(reader, field_type)  # type: ignore
    elif isinstance(field_type, ArrayType):
        return _deserialize_array(reader, field_type)
    elif isinstance(field_type, CompositeType):
        return _deserialize_composite(reader, field_type)  # type: ignore
    else:
        raise ValueError(f"Unknown field type: {type(field_type).__name__}")


def _default_value(schema: typing.Any) -> _Value:
    """
    Recursively compute default values for a given type.
    """
    if isinstance(schema, BooleanType):
        return False
    elif isinstance(schema, (SignedIntegerType, UnsignedIntegerType)):
        return 0
    elif isinstance(schema, FloatType):
        return 0.0
    elif isinstance(schema, VoidType):
        return None
    elif isinstance(schema, FixedLengthArrayType):
        return [_default_value(schema.element_type) for _ in range(schema.capacity)]
    elif isinstance(schema, VariableLengthArrayType):
        if isinstance(schema.element_type, UTF8Type):
            return ""
        elif isinstance(schema.element_type, ByteType):
            return b""
        else:
            return []
    elif isinstance(schema, StructureType):
        result = {}
        for field in schema.fields_except_padding:
            result[field.name] = _default_value(field.data_type)
        return result
    elif isinstance(schema, UnionType):
        first_field = schema.fields[0]
        return {first_field.name: _default_value(first_field.data_type)}
    elif isinstance(schema, DelimitedType):
        return _default_value(schema.inner_type)
    else:
        raise ValueError(f"Unknown type for default value: {type(schema).__name__}")


# ============================================================================
# UNIT TESTS
# ============================================================================


def _unittest_serdes_delimited() -> None:
    """
    Test delimited composite handling with nested structures and unions.
    """
    from pathlib import Path
    from pydsdl._serializable._composite import Version

    CM = PrimitiveType.CastMode

    inner = StructureType(
        name='test.Inner', version=Version(1, 0),
        attributes=[Field(UnsignedIntegerType(8, CM.TRUNCATED), 'x')],
        deprecated=False, fixed_port_id=None,
        source_file_path=Path('test', 'Inner'), has_parent_service=False)
    delimited_inner = DelimitedType(inner, inner.extent)

    outer = StructureType(
        name='test.Outer', version=Version(1, 0),
        attributes=[
            Field(delimited_inner, 'nested'),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), 'y'),
        ],
        deprecated=False, fixed_port_id=None,
        source_file_path=Path('test', 'Outer'), has_parent_service=False)

    w = _BitWriter()
    _serialize_composite(w, outer, {'nested': {'x': 42}, 'y': 99})
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_composite(r, outer)
    assert result == {'nested': {'x': 42}, 'y': 99}

    w = _BitWriter()
    inner_union = UnionType(
        name='test.InnerU', version=Version(1, 0),
        attributes=[
            Field(UnsignedIntegerType(8, CM.TRUNCATED), 'a'),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), 'b'),
        ],
        deprecated=False, fixed_port_id=None,
        source_file_path=Path('test', 'InnerU'), has_parent_service=False)
    delimited_union = DelimitedType(inner_union, inner_union.extent)

    outer_with_union = StructureType(
        name='test.OuterU', version=Version(1, 0),
        attributes=[
            Field(delimited_union, 'nested'),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), 'y'),
        ],
        deprecated=False, fixed_port_id=None,
        source_file_path=Path('test', 'OuterU'), has_parent_service=False)

    w = _BitWriter()
    _serialize_composite(w, outer_with_union, {'nested': {'a': 42}, 'y': 99})
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_composite(r, outer_with_union)
    assert result == {'nested': {'a': 42}, 'y': 99}

    try:
        w = _BitWriter()
        _serialize_composite(w, outer, {'nested': {'x': 42}, 'y': 99})
        data = w.finish()
        
        r = _BitReader(data[:3])
        _ = _deserialize_composite(r, outer)
        assert False, "Should have raised DelimiterHeaderError"
    except DelimiterHeaderError:
        pass

    print("_unittest_serdes_delimited passed")


def _unittest_serdes_composite_codec() -> None:
    """
    Test composite codec with structures, unions, alignment, and default initialization.
    """
    from pathlib import Path
    from pydsdl._serializable._composite import Version

    CM = PrimitiveType.CastMode

    w = _BitWriter()
    schema = StructureType(
        name='test.S', version=Version(1, 0),
        attributes=[Field(UnsignedIntegerType(8, CM.TRUNCATED), 'x')],
        deprecated=False, fixed_port_id=None,
        source_file_path=Path('test', 'S'), has_parent_service=False)
    _serialize_composite(w, schema, {'x': 42})
    assert w.finish() == bytes([0x2A])

    r = _BitReader(bytes([0x2A]))
    result = _deserialize_composite(r, schema)
    assert result == {'x': 42}

    w = _BitWriter()
    schema = StructureType(
        name='test.S2', version=Version(1, 0),
        attributes=[
            Field(UnsignedIntegerType(8, CM.TRUNCATED), 'x'),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), 'y'),
        ],
        deprecated=False, fixed_port_id=None,
        source_file_path=Path('test', 'S2'), has_parent_service=False)
    _serialize_composite(w, schema, {'x': 1, 'y': 2})
    data = w.finish()
    assert data == bytes([0x01, 0x02])

    r = _BitReader(data)
    result = _deserialize_composite(r, schema)
    assert result == {'x': 1, 'y': 2}

    try:
        w = _BitWriter()
        schema = StructureType(
            name='test.S3', version=Version(1, 0),
            attributes=[Field(UnsignedIntegerType(8, CM.TRUNCATED), 'x')],
            deprecated=False, fixed_port_id=None,
            source_file_path=Path('test', 'S3'), has_parent_service=False)
        _serialize_composite(w, schema, {'x': 1, 'unknown': 2})
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown field" in str(e)

    w = _BitWriter()
    schema = StructureType(
        name='test.S4', version=Version(1, 0),
        attributes=[Field(UnsignedIntegerType(8, CM.TRUNCATED), 'x')],
        deprecated=False, fixed_port_id=None,
        source_file_path=Path('test', 'S4'), has_parent_service=False)
    _serialize_composite(w, schema, {})
    data = w.finish()
    assert data == bytes([0x00])

    try:
        w = _BitWriter()
        schema = UnionType(
            name='test.U', version=Version(1, 0),
            attributes=[
                Field(UnsignedIntegerType(8, CM.TRUNCATED), 'a'),
                Field(UnsignedIntegerType(8, CM.TRUNCATED), 'b'),
            ],
            deprecated=False, fixed_port_id=None,
            source_file_path=Path('test', 'U'), has_parent_service=False)
        _serialize_composite(w, schema, {})
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "exactly one field" in str(e)

    try:
        w = _BitWriter()
        schema = UnionType(
            name='test.U2', version=Version(1, 0),
            attributes=[
                Field(UnsignedIntegerType(8, CM.TRUNCATED), 'a'),
                Field(UnsignedIntegerType(8, CM.TRUNCATED), 'b'),
            ],
            deprecated=False, fixed_port_id=None,
            source_file_path=Path('test', 'U2'), has_parent_service=False)
        _serialize_composite(w, schema, {'a': 1, 'b': 2})
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "exactly one field" in str(e)

    try:
        w = _BitWriter()
        schema = UnionType(
            name='test.U3', version=Version(1, 0),
            attributes=[
                Field(UnsignedIntegerType(8, CM.TRUNCATED), 'a'),
                Field(UnsignedIntegerType(8, CM.TRUNCATED), 'b'),
            ],
            deprecated=False, fixed_port_id=None,
            source_file_path=Path('test', 'U3'), has_parent_service=False)
        _serialize_composite(w, schema, {'unknown': 1})
        assert False, "Should have raised UnionFieldError"
    except UnionFieldError as e:
        assert "Unknown union variant" in str(e)

    w = _BitWriter()
    schema = UnionType(
        name='test.U4', version=Version(1, 0),
        attributes=[
            Field(UnsignedIntegerType(8, CM.TRUNCATED), 'a'),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), 'b'),
        ],
        deprecated=False, fixed_port_id=None,
        source_file_path=Path('test', 'U4'), has_parent_service=False)
    _serialize_composite(w, schema, {'a': 42})
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_composite(r, schema)
    assert result == {'a': 42}

    w = _BitWriter()
    schema = UnionType(
        name='test.U5', version=Version(1, 0),
        attributes=[
            Field(UnsignedIntegerType(8, CM.TRUNCATED), 'a'),
            Field(UnsignedIntegerType(8, CM.TRUNCATED), 'b'),
        ],
        deprecated=False, fixed_port_id=None,
        source_file_path=Path('test', 'U5'), has_parent_service=False)
    _serialize_composite(w, schema, {'b': 99})
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_composite(r, schema)
    assert result == {'b': 99}

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

    print("_unittest_serdes_composite_codec passed")


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
    schema = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 255)
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

    try:
        w = _BitWriter()
        schema = FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 3)
        _serialize_array(w, schema, [1, 2])
        assert False, "Should have raised ArrayLengthError"
    except ArrayLengthError:
        pass

    try:
        w = _BitWriter()
        schema = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 3)
        _serialize_array(w, schema, [1, 2, 3, 4])
        assert False, "Should have raised ArrayLengthError"
    except ArrayLengthError:
        pass

    w = _BitWriter()
    schema = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 255)
    _serialize_array(w, schema, [])
    data = w.finish()
    assert data[0] == 0

    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == []

    w = _BitWriter()
    schema = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 255)
    _serialize_array(w, schema, list(range(255)))
    data = w.finish()
    assert data[0] == 255

    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert isinstance(result, list) and len(result) == 255

    w = _BitWriter()
    schema = VariableLengthArrayType(UTF8Type(), 255)
    _serialize_array(w, schema, "hello")
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == "hello"
    assert isinstance(result, str)

    w = _BitWriter()
    schema = VariableLengthArrayType(UTF8Type(), 255)
    _serialize_array(w, schema, b"hello")
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == "hello"

    w = _BitWriter()
    schema = VariableLengthArrayType(ByteType(), 255)
    _serialize_array(w, schema, b"hello")
    data = w.finish()

    r = _BitReader(data)
    result = _deserialize_array(r, schema)
    assert result == b"hello"
    assert isinstance(result, bytes)

    w = _BitWriter()
    schema = VariableLengthArrayType(ByteType(), 255)
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

    try:
        w = _BitWriter()
        schema = VariableLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 255)
        _serialize_array(w, schema, "invalid")
        assert False, "Should have raised TypeError"
    except TypeError:
        pass

    try:
        w = _BitWriter()
        schema = FixedLengthArrayType(UnsignedIntegerType(8, CM.TRUNCATED), 3)
        _serialize_array(w, schema, 123)
        assert False, "Should have raised TypeError"
    except TypeError:
        pass

    print("_unittest_serdes_array_codec passed")


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

    try:
        w = _BitWriter()
        _serialize_primitive(w, UnsignedIntegerType(8, CM.TRUNCATED), "invalid")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass

    try:
        w = _BitWriter()
        _serialize_primitive(w, BooleanType(), float('inf'))
        assert False, "Should have raised ValueError"
    except ValueError:
        pass

    try:
        w = _BitWriter()
        _serialize_primitive(w, UnsignedIntegerType(8, CM.TRUNCATED), float('nan'))
        assert False, "Should have raised ValueError"
    except ValueError:
        pass

    w = _BitWriter()
    from pydsdl._serializable import VoidType
    _serialize_primitive(w, VoidType(8), None)
    assert w.finish() == bytes([0x00])

    r = _BitReader(bytes([0x00]))
    assert _deserialize_primitive(r, VoidType(8)) is None

    print("_unittest_serdes_primitive_codec passed")


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

    print("_unittest_serdes_bit_writer passed")


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
    _ = r.align_to(8)
    assert r.bit_offset == 8

    r = _BitReader(bytes([0xFF]))
    _ = r.read_bits(3)
    _ = r.align_to(8)
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

    print("_unittest_serdes_bit_reader passed")


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

    # Verify that SerDesError does NOT inherit from FrontendError
    from ._error import FrontendError

    assert not issubclass(SerDesError, FrontendError)

    # Verify that type aliases are defined
    assert _Value is not None
    assert _Obj is not None

    # Verify that functions are defined with correct signatures
    assert callable(serialize)
    assert callable(deserialize)

    print("_unittest_serdes_module passed")
