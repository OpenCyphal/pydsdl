#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os
import typing
import tempfile
from textwrap import dedent
from . import _expression
from . import _error
from . import _parser
from . import _data_type_builder
from . import _dsdl_definition
from . import _serializable
from . import _namespace


# Type annotation disabled here because MyPy is misbehaving, reporting these nonsensical error messages:
#   pydsdl/_test.py:18: error: Missing type parameters for generic type
#   pydsdl/_test.py: note: In function "_in_n_out":
#   pydsdl/_test.py:18: error: Missing type parameters for generic type
_DIRECTORY = None       # type : typing.Optional[tempfile.TemporaryDirectory]


def _parse_definition(definition:         _dsdl_definition.DSDLDefinition,
                      lookup_definitions: typing.Sequence[_dsdl_definition.DSDLDefinition]) \
        -> _serializable.CompositeType:
    return definition.read(lookup_definitions,
                           print_output_handler=lambda *_: None,
                           allow_unregulated_fixed_port_id=False)


def _define(rel_path: str, text: str) -> _dsdl_definition.DSDLDefinition:
    assert _DIRECTORY
    path = os.path.join(_DIRECTORY.name, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)

    root_namespace_path = os.path.join(_DIRECTORY.name, rel_path.strip(os.sep).split(os.sep)[0])
    out = _dsdl_definition.DSDLDefinition(path, root_namespace_path)
    print('New definition:', out, 'Root NS:', root_namespace_path)
    return out


def _in_n_out(test: typing.Callable[[], None]) -> typing.Callable[[], None]:
    def decorator() -> None:
        global _DIRECTORY
        _DIRECTORY = tempfile.TemporaryDirectory(prefix='pydsdl-test-')
        try:
            test()
        finally:
            _DIRECTORY = None   # Preserving the contents for future inspection if needed

    return decorator


@_in_n_out
def _unittest_define() -> None:
    # I DON'T ALWAYS WRITE UNIT TESTS
    d = _define('uavcan/test/65000.Message.1.2.uavcan', '# empty')
    assert _DIRECTORY is not None
    assert d.full_name == 'uavcan.test.Message'
    assert d.version == (1, 2)
    assert d.fixed_port_id == 65000
    assert d.file_path == os.path.join(_DIRECTORY.name, 'uavcan/test/65000.Message.1.2.uavcan')
    assert open(d.file_path).read() == '# empty'

    # BUT WHEN I DO, I WRITE UNIT TESTS FOR MY UNIT TESTS
    d = _define('uavcan/Service.255.254.uavcan', '# empty 2')
    assert d.full_name == 'uavcan.Service'
    assert d.version == (255, 254)
    assert d.fixed_port_id is None
    assert d.file_path == os.path.join(_DIRECTORY.name, 'uavcan/Service.255.254.uavcan')
    assert open(d.file_path).read() == '# empty 2'


@_in_n_out
def _unittest_simple() -> None:
    abc = _define(
        'vendor/nested/29000.Abc.1.2.uavcan',
        dedent('''
        @deprecated
        uint8 CHARACTER = '#'
        int8 a
        saturated int64[<33] b
        ''')
    )
    assert abc.fixed_port_id == 29000
    assert abc.full_name == 'vendor.nested.Abc'
    assert abc.version == (1, 2)

    p = _parse_definition(abc, [])
    print('Parsed:', p)
    assert isinstance(p, _serializable.StructureType)
    assert p.full_name == 'vendor.nested.Abc'
    assert p.source_file_path.endswith('vendor/nested/29000.Abc.1.2.uavcan')
    assert p.source_file_path == abc.file_path
    assert p.fixed_port_id == 29000
    assert p.deprecated
    assert p.version == (1, 2)
    assert min(p.bit_length_set) == 14
    assert max(p.bit_length_set) == 14 + 64 * 32
    assert len(p.attributes) == 3
    assert len(p.fields) == 2
    assert str(p.fields[0].data_type) == 'saturated int8'
    assert p.fields[0].name == 'a'
    assert str(p.fields[1].data_type) == 'saturated int64[<=32]'      # Note: normalized representation
    assert p.fields[1].name == 'b'
    assert len(p.constants) == 1
    assert str(p.constants[0].data_type) == 'saturated uint8'
    assert p.constants[0].name == 'CHARACTER'
    assert isinstance(p.constants[0].value, _expression.Rational)
    assert p.constants[0].value == _expression.Rational(ord('#'))

    t = p.fields[1].data_type
    assert isinstance(t, _serializable.ArrayType)
    assert str(t.element_type) == 'saturated int64'

    empty_new = _define(
        'vendor/nested/Empty.255.255.uavcan',
        ''''''
    )

    empty_old = _define(
        'vendor/nested/Empty.255.254.uavcan',
        ''''''
    )

    constants = _define(
        'another/Constants.5.0.uavcan',
        dedent('''
        float64 PI = 3.1415926535897932384626433
        ''')
    )

    service = _define(
        'another/300.Service.0.1.uavcan',
        dedent('''
        @union
        @deprecated
        vendor.nested.Empty.255.255 new_empty_implicit
        vendor.nested.Empty.255.255 new_empty_explicit
        vendor.nested.Empty.255.254 old_empty
        -----------------------------------
        Constants.5.0 constants      # RELATIVE REFERENCE
        vendor.nested.Abc.1.2 abc
        ''')
    )

    p = _parse_definition(service, [
        abc,
        empty_new,
        empty_old,
        constants,
    ])
    print('Parsed:', p)
    assert isinstance(p, _serializable.ServiceType)
    assert p.full_name == 'another.Service'
    assert p.fixed_port_id == 300
    assert p.deprecated
    assert p.version == (0, 1)
    assert not p.constants

    assert len(p.fields) == 2
    assert p.fields[0].name == 'request'
    assert p.fields[1].name == 'response'
    req, res = [x.data_type for x in p.fields]
    assert isinstance(req, _serializable.UnionType)
    assert isinstance(res, _serializable.StructureType)
    assert req.full_name == 'another.Service.Request'
    assert res.full_name == 'another.Service.Response'
    assert req is p.request_type
    assert res is p.response_type

    assert len(req.constants) == 0
    assert len(req.fields) == 3
    assert req.number_of_variants == 3
    assert req.deprecated
    assert not req.has_fixed_port_id
    assert req.version == (0, 1)
    assert req.bit_length_set == 2   # Remember this is a union
    assert [x.name for x in req.fields] == ['new_empty_implicit', 'new_empty_explicit', 'old_empty']

    t = req.fields[0].data_type
    assert isinstance(t, _serializable.StructureType)
    assert t.full_name == 'vendor.nested.Empty'
    assert t.version == (255, 255)          # Selected implicitly

    t = req.fields[1].data_type
    assert isinstance(t, _serializable.StructureType)
    assert t.full_name == 'vendor.nested.Empty'
    assert t.version == (255, 255)          # Selected explicitly

    t = req.fields[2].data_type
    assert isinstance(t, _serializable.StructureType)
    assert t.full_name == 'vendor.nested.Empty'
    assert t.version == (255, 254)          # Selected explicitly

    assert len(res.constants) == 0
    assert len(res.fields) == 2
    assert res.deprecated
    assert not res.has_fixed_port_id
    assert res.version == (0, 1)
    assert min(res.bit_length_set) == 14
    assert max(res.bit_length_set) == 14 + 64 * 32

    t = res.fields[0].data_type
    assert isinstance(t, _serializable.StructureType)
    assert t.full_name == 'another.Constants'
    assert t.version == (5, 0)

    t = res.fields[1].data_type
    assert isinstance(t, _serializable.StructureType)
    assert t.full_name == 'vendor.nested.Abc'
    assert t.version == (1, 2)

    union = _define(
        'another/Union.5.9.uavcan',
        dedent('''
        @union
        truncated float16 PI = 3.1415926535897932384626433
        uint8 a
        vendor.nested.Empty.255.255[5] b
        saturated bool [ <= 255 ] c
        ''')
    )

    p = _parse_definition(union, [
        empty_old,
        empty_new,
    ])

    assert p.full_name == 'another.Union'
    assert p.version == (5, 9)
    assert p.fixed_port_id is None
    assert not p.has_fixed_port_id
    assert not p.deprecated
    assert isinstance(p, _serializable.UnionType)
    assert p.number_of_variants == 3
    assert len(p.constants) == 1
    assert p.constants[0].name == 'PI'
    assert str(p.constants[0].data_type) == 'truncated float16'
    assert min(p.bit_length_set) == 2
    assert max(p.bit_length_set) == 2 + 8 + 255
    assert len(p.fields) == 3
    assert str(p.fields[0]) == 'saturated uint8 a'
    assert str(p.fields[1]) == 'vendor.nested.Empty.255.255[5] b'
    assert str(p.fields[2]) == 'saturated bool[<=255] c'


@_in_n_out
def _unittest_error() -> None:
    from pytest import raises

    def standalone(rel_path: str, definition: str, allow_unregulated: bool = False) -> _serializable.CompositeType:
        return _define(rel_path, definition + '\n').read([], lambda *_: None, allow_unregulated)  # pragma: no branch

    with raises(_error.InvalidDefinitionError, match='(?i).*port ID.*'):
        standalone('vendor/10000.InvalidRegulatedSubjectID.1.0.uavcan', 'uint2 value')

    with raises(_error.InvalidDefinitionError, match='(?i).*port ID.*'):
        standalone('vendor/10.InvalidRegulatedServiceID.1.0.uavcan', 'uint2 v1\n---\nint64 v2')

    with raises(_error.InvalidDefinitionError, match='(?i).*subject ID.*'):
        standalone('vendor/100000.InvalidRegulatedSubjectID.1.0.uavcan', 'uint2 value')

    with raises(_error.InvalidDefinitionError, match='(?i).*service ID.*'):
        standalone('vendor/1000.InvalidRegulatedServiceID.1.0.uavcan', 'uint2 v1\n---\nint64 v2')

    with raises(_error.InvalidDefinitionError, match='(?i).*multiple attributes under the same name.*'):
        standalone('vendor/AttributeNameCollision.1.0.uavcan', 'uint2 value\nint64 value')

    with raises(_error.InvalidDefinitionError, match='(?i).*tagged union cannot contain fewer than.*'):
        standalone('vendor/SmallUnion.1.0.uavcan', '@union\nuint2 value')

    assert standalone('vendor/invalid_constant_value/A.1.0.uavcan',
                      'bool BOOLEAN = false').constants[0].name == 'BOOLEAN'
    with raises(_error.InvalidDefinitionError, match='.*Invalid value for boolean constant.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', 'bool BOOLEAN = 0')   # Should be false

    with raises(_error.InvalidDefinitionError, match='.*undefined_identifier.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', 'bool BOOLEAN = undefined_identifier')

    with raises(_parser.DSDLSyntaxError):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', 'bool BOOLEAN = -')

    with raises(_error.InvalidDefinitionError, match='(?i).*exceeds the range.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', 'uint10 INTEGRAL = 2000')

    with raises(_error.InvalidDefinitionError, match='(?i).*character.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', "uint8 CH = '\u0451'")

    with raises(_error.InvalidDefinitionError, match='.*uint8.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', "uint9 CH = 'q'")

    with raises(_error.InvalidDefinitionError, match='.*uint8.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', "int8 CH = 'q'")

    with raises(_error.InvalidDefinitionError, match='.*integer constant.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', "int8 CH = 1.1")

    with raises(_error.InvalidDefinitionError, match='(?i).*type.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', "float32 CH = true")

    with raises(_error.InvalidDefinitionError, match='(?i).*type.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', "float32 CH = 't'")

    with raises(_parser.DSDLSyntaxError):
        standalone('vendor/syntax_error/A.1.0.uavcan', 'bool array[10]')

    with raises(_error.InvalidDefinitionError, match='(?i).*array capacity.*'):
        standalone('vendor/array_size/A.1.0.uavcan', 'bool[0] array')

    with raises(_error.InvalidDefinitionError, match='(?i).*array capacity.*'):
        standalone('vendor/array_size/A.1.0.uavcan', 'bool[<1] array')

    with raises(_error.InvalidDefinitionError, match='(?i).*array capacity.*'):
        standalone('vendor/array_size/A.1.0.uavcan', 'bool[true] array')

    with raises(_error.InvalidDefinitionError, match='(?i).*array capacity.*'):
        standalone('vendor/array_size/A.1.0.uavcan', 'bool["text"] array')

    with raises(_error.InvalidDefinitionError, match='(?i).*service response marker.*'):
        standalone('vendor/service/A.1.0.uavcan', 'bool request\n---\nbool response\n---\nbool again')

    with raises(_error.InvalidDefinitionError, match='(?i).*unknown directive.*'):
        standalone('vendor/directive/A.1.0.uavcan', '@sho_tse_take')

    with raises(_error.InvalidDefinitionError, match='(?i).*requires an expression.*'):
        standalone('vendor/directive/A.1.0.uavcan', '@assert')

    with raises(_error.InvalidDefinitionError, match='(?i).*does not expect an expression.*'):
        standalone('vendor/directive/A.1.0.uavcan', '@union true || false')

    with raises(_error.InvalidDefinitionError, match='(?i).*does not expect an expression.*'):
        standalone('vendor/directive/A.1.0.uavcan', '@deprecated true || false')

    with raises(_error.InvalidDefinitionError, match='(?i).*version number.*'):
        standalone('vendor/version/A.0.0.uavcan', '')

    with raises(_error.InvalidDefinitionError, match='(?i).*version number.*'):
        standalone('vendor/version/A.0.256.uavcan', '')

    with raises(_dsdl_definition.FileNameFormatError):
        standalone('vendor/version/A.0..256.uavcan', '')

    with raises(_error.InvalidDefinitionError, match='(?i).*version number.*'):
        standalone('vendor/version/A.256.0.uavcan', '')

    with raises(_parser.DSDLSyntaxError):
        standalone('vendor/types/A.1.0.uavcan', 'truncated uavcan.node.Heartbeat.1.0 field')

    with raises(_serializable.InvalidCastModeError):
        standalone('vendor/types/A.1.0.uavcan', 'truncated bool foo')

    with raises(_serializable.InvalidCastModeError):
        standalone('vendor/types/A.1.0.uavcan', 'truncated int8 foo')

    with raises(_data_type_builder.UndefinedDataTypeError, match=r'(?i).*nonexistent.TypeName.*1\.0.*'):
        standalone('vendor/types/A.1.0.uavcan', 'nonexistent.TypeName.1.0 field')

    with raises(_error.InvalidDefinitionError, match=r'(?i).*not defined for.*'):
        standalone('vendor/types/A.1.0.uavcan',
                   dedent('''
                   @union
                   int8 a
                   @assert _offset_.count >= 1
                   int16 b
                   '''))

    with raises(_error.InvalidDefinitionError, match=r'(?i).*field offset is not defined for unions.*'):
        standalone('vendor/types/A.1.0.uavcan',
                   dedent('''
                   @union
                   int8 a
                   int16 b
                   @assert _offset_.count >= 1
                   int8 c
                   '''))

    with raises(_data_type_builder.UndefinedDataTypeError, match=r'.*ns.Type_.*1\.0'):
        _parse_definition(
            _define('vendor/types/A.1.0.uavcan', 'ns.Type_.1.0 field'),
            [
                _define('ns/Type_.2.0.uavcan', ''),
            ]
        )

    with raises(_error.InvalidDefinitionError, match='(?i).*Bit length cannot exceed.*'):
        _parse_definition(
            _define('vendor/types/A.1.0.uavcan', 'int128 field'),
            [
                _define('ns/Type_.2.0.uavcan', ''),
                _define('ns/Type_.1.1.uavcan', ''),
            ]
        )

    with raises(_error.InvalidDefinitionError, match='(?i).*type.*'):
        _parse_definition(
            _define('vendor/invalid_constant_value/A.1.0.uavcan', 'ns.Type_.1.1 VALUE = 123'),
            [
                _define('ns/Type_.2.0.uavcan', ''),
                _define('ns/Type_.1.1.uavcan', ''),
            ]
        )

    with raises(_data_type_builder.UndefinedDataTypeError):
        defs = [
            _define('vendor/circular_dependency/A.1.0.uavcan', 'B.1.0 b'),
            _define('vendor/circular_dependency/B.1.0.uavcan', 'A.1.0 b'),
        ]
        _parse_definition(defs[0], defs)

    with raises(_error.InvalidDefinitionError, match='(?i).*union directive.*'):
        _parse_definition(
            _define('vendor/misplaced_directive/A.1.0.uavcan', 'ns.Type_.2.0 field\n@union'),
            [
                _define('ns/Type_.2.0.uavcan', ''),
            ]
        )

    with raises(_error.InvalidDefinitionError, match='(?i).*deprecated directive.*'):
        _parse_definition(
            _define('vendor/misplaced_directive/A.1.0.uavcan', 'ns.Type_.2.0 field\n@deprecated'),
            [
                _define('ns/Type_.2.0.uavcan', ''),
            ]
        )

    with raises(_error.InvalidDefinitionError, match='(?i).*deprecated directive.*'):
        _parse_definition(
            _define('vendor/misplaced_directive/A.1.0.uavcan', 'ns.Type_.2.0 field\n---\n@deprecated'),
            [
                _define('ns/Type_.2.0.uavcan', ''),
            ]
        )

    try:
        standalone('vendor/types/A.1.0.uavcan',
                   dedent('''
                   int8 a  # Comment
                   # Empty
                   @assert false  # Will error here, line number 4
                   # Blank
                   '''))
    except _error.FrontendError as ex:
        assert ex.path and ex.path.endswith('vendor/types/A.1.0.uavcan')
        assert ex.line and ex.line == 4
    else:  # pragma: no cover
        assert False

    standalone('vendor/types/1.A.1.0.uavcan', '', allow_unregulated=True)
    with raises(_serializable.InvalidFixedPortIDError, match=r'.*allow_unregulated_fixed_port_id.*'):
        standalone('vendor/types/1.A.1.0.uavcan', '')

    standalone('vendor/types/1.A.1.0.uavcan', '---', allow_unregulated=True)
    with raises(_serializable.InvalidFixedPortIDError, match=r'.*allow_unregulated_fixed_port_id.*'):
        standalone('vendor/types/1.A.1.0.uavcan', '---')


@_in_n_out
def _unittest_print() -> None:
    printed_items = None  # type: typing.Optional[typing.Tuple[int, str]]

    def print_handler(line_number: int, text: str) -> None:
        nonlocal printed_items
        printed_items = line_number, text

    _define(
        'ns/A.1.0.uavcan',
        '# line number 1\n'
        '# line number 2\n'
        '@print 2 + 2 == 4   # line number 3\n'
        '# line number 4\n'
    ).read([], print_handler, False)

    assert printed_items
    assert printed_items[0] == 3
    assert printed_items[1] == 'true'

    _define('ns/B.1.0.uavcan', '@print false').read([], print_handler, False)
    assert printed_items
    assert printed_items[0] == 1
    assert printed_items[1] == 'false'

    _define(
        'ns/Offset.1.0.uavcan',
        '@print _offset_    # Not recorded\n'
        'uint8 a\n'
        '@print _offset_\n'
    ).read([], print_handler, False)
    assert printed_items
    assert printed_items[0] == 3
    assert printed_items[1] == "{8}"


@_in_n_out
def _unittest_assert() -> None:
    from pytest import raises

    _parse_definition(
        _define(
            'ns/A.1.0.uavcan',
            dedent('''
            @assert _offset_ == {0}
            @assert _offset_.min == _offset_.max
            Array.1.0[2] bar
            @assert _offset_ == {4, 12, 20, 28, 36}
            @assert _offset_.min == 4
            @assert _offset_.max == 36
            @assert _offset_ % 4 == {0}
            @assert _offset_ % 8 == {4}
            @assert _offset_ % 10 == {4, 2, 0, 8, 6}
            @assert _offset_ * 2 == {8, 24, 40, 56, 72}
            @assert 2 * _offset_ == {8, 24, 40, 56, 72}
            @assert _offset_ / 4 == {1, 3, 5, 7, 9}
            @assert _offset_ - 4 == {0, 8, 16, 24, 32}
            @assert _offset_ + 4 == {8, 16, 24, 32, 40}
            uint64 big
            @assert _offset_ - 64 == {4, 12, 20, 28, 36}
            @assert _offset_.min == 68
            @assert _offset_.max == 100  # 36 + 64
            @assert _offset_.max <= 100
            @assert _offset_.max < 101
            @assert _offset_ == _offset_
            @assert truncated uint64._bit_length_ == {64}
            @assert uint64._bit_length_ == {64}
            @assert Array.1.0._bit_length_.max == 2 + 8 + 8
            ''')),
        [
            _define('ns/Array.1.0.uavcan', 'uint8[<=2] foo')
        ]
    )

    with raises(_error.InvalidDefinitionError, match='(?i).*operator is not defined.*'):
        _parse_definition(
            _define(
                'ns/C.1.0.uavcan',
                dedent('''
                uint64 big
                @assert _offset_ == 64
                ''')),
            []
        )

    with raises(_expression.UndefinedAttributeError):
        _parse_definition(
            _define('ns/C.1.0.uavcan', '@print Service.1.0._bit_length_'),
            [
                _define('ns/Service.1.0.uavcan', 'uint8 a\n---\nuint16 b')
            ]
        )

    with raises(_expression.UndefinedAttributeError):
        _parse_definition(
            _define(
                'ns/C.1.0.uavcan',
                '''uint64 LENGTH = uint64.nonexistent_attribute'''),
            []
        )

    with raises(_error.InvalidDefinitionError, match='(?i).*void.*'):
        _parse_definition(
            _define(
                'ns/C.1.0.uavcan',
                'void2 name'),
            []
        )

    with raises(_serializable.InvalidConstantValueError):
        _parse_definition(_define('ns/C.1.0.uavcan', 'int8 name = true'), [])

    with raises(_error.InvalidDefinitionError, match='.*value.*'):
        _parse_definition(
            _define(
                'ns/C.1.0.uavcan',
                'int8 name = {1, 2, 3}'),
            []
        )

    _parse_definition(
        _define(
            'ns/D.1.0.uavcan',
            dedent('''
            @union
            float32 a
            uint64 b
            @assert _offset_ == {33, 65}
            ''')),
        []
    )

    _parse_definition(
        _define(
            'ns/E.1.0.uavcan',
            dedent('''
            @union
            uint8 A = 0
            float32 a
            uint8 B = 1
            uint64 b
            uint8 C = 2
            @assert _offset_ == {33, 65}
            uint8 D = 3
            ''')),
        []
    )

    with raises(_error.InvalidDefinitionError):
        _parse_definition(
            _define(
                'ns/F.1.0.uavcan',
                dedent('''
                @union
                @assert _offset_.min == 33
                float32 a
                uint64 b
                @assert _offset_ == {33, 65}
                ''')),
            []
        )

    with raises(_data_type_builder.AssertionCheckFailureError):
        _parse_definition(
            _define(
                'ns/G.1.0.uavcan',
                dedent('''
                float32 a
                @assert _offset_.min == 8
                ''')),
            []
        )

    with raises(_error.InvalidDefinitionError, match='(?i).*yield a boolean.*'):
        _parse_definition(
            _define(
                'ns/H.1.0.uavcan',
                dedent('''
                float32 a
                @assert _offset_.min
                ''')),
            []
        )


def _unittest_parse_namespace() -> None:
    from pytest import raises
    directory = tempfile.TemporaryDirectory()

    print_output = None  # type: typing.Optional[typing.Tuple[str, int, str]]

    def print_handler(d: str, line: int, text: str) -> None:
        nonlocal print_output
        print_output = d, line, text

    # noinspection PyShadowingNames
    def _define(rel_path: str, text: str) -> None:
        path = os.path.join(directory.name, rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(text)

    _define(
        'zubax/First.1.0.uavcan',
        dedent("""
        uint8[<256] a
        @assert _offset_.min == 8
        @assert _offset_.max == 2048
        """)
    )

    _define(
        'zubax/29001.Message.1.0.uavcan',
        dedent("""
        void6
        zubax.First.1.0[<=2] a
        @assert _offset_.min == 8
        @assert _offset_.max == 4104
        """)
    )

    _define(
        'zubax/nested/300.Spartans.30.0.uavcan',
        dedent("""
        @deprecated
        @union
        float16 small
        float32 just_right
        float64 woah
        ---
        @print _offset_     # Will print zero {0}
        """)
    )

    _define('zubax/nested/300.Spartans.30.0.txt', 'completely unrelated stuff')
    _define('zubax/300.Spartans.30.0', 'completely unrelated stuff')

    parsed = _namespace.read_namespace(
        os.path.join(directory.name, 'zubax'),
        [],
        print_handler
    )
    print(parsed)
    assert len(parsed) == 3
    assert 'zubax.First' in [x.full_name for x in parsed]
    assert 'zubax.Message' in [x.full_name for x in parsed]
    assert 'zubax.nested.Spartans' in [x.full_name for x in parsed]

    _define(
        'zubax/colliding/300.Iceberg.30.0.uavcan',
        dedent("""
        ---
        """)
    )

    with raises(_namespace.FixedPortIDCollisionError):
        _namespace.read_namespace(
            os.path.join(directory.name, 'zubax'),
            [],
            print_handler
        )

    assert print_output is not None
    assert '300.Spartans' in print_output[0]
    assert print_output[1] == 8
    assert print_output[2] == '{0}'

    _define(
        'zubax/colliding/iceberg/300.Ice.30.0.uavcan',
        dedent("""
        ---
        """)
    )
    with raises(_namespace.DataTypeNameCollisionError):
        _namespace.read_namespace(os.path.join(directory.name, 'zubax'), [
            os.path.join(directory.name, 'zubax'),
        ])

    os.unlink(os.path.join(directory.name, 'zubax/colliding/iceberg/300.Ice.30.0.uavcan'))
    _define(
        'zubax/COLLIDING/300.Iceberg.30.0.uavcan',
        dedent("""
        ---
        """)
    )
    with raises(_namespace.DataTypeNameCollisionError, match='.*letter case.*'):
        _namespace.read_namespace(os.path.join(directory.name, 'zubax'), [
            os.path.join(directory.name, 'zubax'),
        ])


def _unittest_parse_namespace_versioning() -> None:
    from pytest import raises
    import glob
    directory = tempfile.TemporaryDirectory()

    # noinspection PyShadowingNames
    def _define(rel_path: str, text: str) -> None:
        path = os.path.join(directory.name, rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(text)

    def _undefine_glob(rel_path_glob: str) -> None:
        path = os.path.join(directory.name, rel_path_glob)
        for g in glob.glob(path):
            os.remove(g)

    _define(
        'ns/Spartans.30.0.uavcan',
        dedent("""
        @deprecated
        @union
        float16 small
        float32 just_right
        float64 woah
        ---
        """)
    )

    _define(
        'ns/Spartans.30.1.uavcan',
        dedent("""
        @deprecated
        @union
        uint16 small
        int32 just_right
        float64[1] woah
        ---
        """)
    )

    parsed = _namespace.read_namespace(
        os.path.join(directory.name, 'ns'),
        []
    )
    print(parsed)
    assert len(parsed) == 2

    _define(
        'ns/Spartans.30.2.uavcan',
        dedent("""
        @deprecated
        @union
        uint16 small
        int32 just_right
        float64[<=1] woah
        ---
        """)
    )

    with raises(_namespace.MinorVersionsNotBitCompatibleError):
        _namespace.read_namespace(
            os.path.join(directory.name, 'ns'),
            []
        )

    _define(
        'ns/Spartans.30.2.uavcan',
        dedent("""
        @deprecated
        @union
        uint16 small
        int32 just_right
        float64[1] woah
        """)
    )

    with raises(_namespace.VersionsOfDifferentKindError):
        _namespace.read_namespace(
            os.path.join(directory.name, 'ns'),
            []
        )

    _undefine_glob('ns/Spartans.30.[01].uavcan')

    _define(
        'ns/Spartans.30.0.uavcan',
        dedent("""
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        """)
    )

    parsed = _namespace.read_namespace(
        os.path.join(directory.name, 'ns'),
        []
    )
    print(parsed)
    assert len(parsed) == 2

    _define(
        'ns/Spartans.30.1.uavcan',
        dedent("""
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[<=1] woah
        """)
    )

    with raises(_namespace.MinorVersionsNotBitCompatibleError):
        _namespace.read_namespace(
            os.path.join(directory.name, 'ns'),
            []
        )

    _define(
        'ns/Spartans.30.1.uavcan',
        dedent("""
        @deprecated
        @union
        uint16 small
        float32 just_right
        int64 woah
        """)
    )

    _define(
        'ns/28700.Spartans.30.2.uavcan',
        dedent("""
        @deprecated
        @union
        uint16 small
        int32 just_right
        float64[1] woah
        """)
    )

    with raises(_namespace.MultipleDefinitionsUnderSameVersionError):
        _namespace.read_namespace(os.path.join(directory.name, 'ns'), [])

    _undefine_glob('ns/Spartans.30.2.uavcan')

    parsed = _namespace.read_namespace(
        os.path.join(directory.name, 'ns'),
        []
    )
    assert len(parsed) == 3

    _undefine_glob('ns/Spartans.30.0.uavcan')
    _define(
        'ns/28700.Spartans.30.0.uavcan',
        dedent("""
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        """)
    )

    with raises(_namespace.MinorVersionFixedPortIDError):
        _namespace.read_namespace(os.path.join(directory.name, 'ns'), [])

    _undefine_glob('ns/Spartans.30.1.uavcan')
    _define(
        'ns/28700.Spartans.30.1.uavcan',
        dedent("""
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        """)
    )

    parsed = _namespace.read_namespace(
        os.path.join(directory.name, 'ns'),
        []
    )
    assert len(parsed) == 3

    _undefine_glob('ns/28700.Spartans.30.1.uavcan')
    _define(
        'ns/28701.Spartans.30.1.uavcan',
        dedent("""
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        """)
    )

    with raises(_namespace.MinorVersionFixedPortIDError):
        _namespace.read_namespace(os.path.join(directory.name, 'ns'), [])

    # Adding new major version under the same FPID
    _undefine_glob('ns/28701.Spartans.30.1.uavcan')
    _define(
        'ns/28700.Spartans.31.0.uavcan',
        dedent("""
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        """)
    )

    with raises(_namespace.FixedPortIDCollisionError):
        _namespace.read_namespace(os.path.join(directory.name, 'ns'), [])

    # Major version zero allows us to re-use the same FPID under a different (non-zero) major version
    _undefine_glob('ns/28700.Spartans.31.0.uavcan')
    _define(
        'ns/28700.Spartans.0.1.uavcan',
        dedent("""
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        """)
    )

    # These are needed to ensure full branch coverage, see the checking code.
    _define('ns/Empty.1.0.uavcan', '')
    _define('ns/Empty.1.1.uavcan', '')
    _define('ns/Empty.2.0.uavcan', '')
    _define('ns/28800.Empty.3.0.uavcan', '')
    _define('ns/28801.Empty.4.0.uavcan', '')

    parsed = _namespace.read_namespace(os.path.join(directory.name, 'ns'), [])     # no error
    assert len(parsed) == 8

    # Check ordering - the definitions must be sorted properly by name (lexicographically) and version (newest first).
    assert list(map(str, parsed)) == [
        'ns.Empty.4.0',         # Newest first
        'ns.Empty.3.0',
        'ns.Empty.2.0',
        'ns.Empty.1.1',
        'ns.Empty.1.0',
        'ns.Spartans.30.2',     # Newest first
        'ns.Spartans.30.0',
        'ns.Spartans.0.1',
    ]


def _unittest_parse_namespace_faults() -> None:
    try:
        _namespace.read_namespace('/foo/bar/baz', ['/bat/wot', '/foo/bar/baz/bad'])
    except _namespace.NestedRootNamespaceError as ex:
        print(ex)
    else:               # pragma: no cover
        assert False

    try:
        _namespace.read_namespace('/foo/bar/baz', ['/foo/bar/zoo', '/foo/bar/doo/roo/BAZ'])  # Notice the letter case
    except _namespace.RootNamespaceNameCollisionError as ex:
        print(ex)
    else:               # pragma: no cover
        assert False
    try:
        _namespace.read_namespace('/foo/bar/baz', ['/foo/bar/zoo', '/foo/bar/doo/roo/zoo', '/foo/bar/doo/roo/baz'])
    except _namespace.RootNamespaceNameCollisionError as ex:
        print(ex)
    else:               # pragma: no cover
        assert False


@_in_n_out
def _unittest_inconsistent_deprecation() -> None:
    from pytest import raises

    _parse_definition(
        _define('ns/A.1.0.uavcan', ''),
        [
            _define('ns/B.1.0.uavcan',
                    dedent('''
                    @deprecated
                    A.1.0 a
                    '''))
        ]
    )

    with raises(_error.InvalidDefinitionError, match='(?i).*depend.*deprecated.*'):
        _parse_definition(
            _define(
                'ns/C.1.0.uavcan',
                dedent('''
                X.1.0 b
                ''')
            ),
            [
                _define('ns/X.1.0.uavcan', '@deprecated')
            ]
        )

    _parse_definition(
        _define('ns/D.1.0.uavcan',
                dedent('''
                @deprecated
                X.1.0 b
                ''')),
        [
            _define('ns/X.1.0.uavcan', '@deprecated')
        ]
    )


@_in_n_out
def _unittest_repeated_directives() -> None:
    from pytest import raises

    _parse_definition(
        _define('ns/A.1.0.uavcan',
                dedent('''
                @union
                @deprecated
                int8 a
                float16 b
                ''')),
        []
    )

    with raises(_error.InvalidDefinitionError, match='(?i).*deprecated.*'):
        _parse_definition(
            _define('ns/A.1.0.uavcan',
                    dedent('''
                    @deprecated
                    @deprecated
                    ''')),
            []
        )

    with raises(_error.InvalidDefinitionError, match='(?i).*deprecated.*'):
        _parse_definition(
            _define('ns/A.1.0.uavcan',
                    dedent('''
                    @deprecated
                    ---
                    @deprecated
                    ''')),
            []
        )

    _parse_definition(
        _define('ns/A.1.0.uavcan',
                dedent('''
                @union
                int8 a
                float16 b
                ---
                @union
                int8 a
                float16 b
                ''')),
        []
    )

    with raises(_error.InvalidDefinitionError, match='(?i).*union.*'):
        _parse_definition(
            _define('ns/A.1.0.uavcan',
                    dedent('''
                    @union
                    @union
                    int8 a
                    float16 b
                    ''')),
            []
        )


@_in_n_out
def _unittest_dsdl_parser_basics() -> None:
    # This is how you can run one test only for development needs:
    #   pytest pydsdl -k _unittest_dsdl_parser_basics --capture=no
    # noinspection SpellCheckingInspection
    _parse_definition(
        _define('ns/A.1.0.uavcan',
                dedent(r'''
                @deprecated
                void16
                int8           [<=123+456] array_inclusive
                truncated uint8[< 123+456] array_exclusive
                saturated int8 [  123+456] array_fixed
                #ns.Bar.1.23 field
                float64 a = +10 * (-2 / -3) / 4 % 5
                bool    b = !true
                float32 c = (123456 + 0x_ab_cd_ef) / 0b1111_1111 ** 2 - 0o123_456 * 2.7
                @print "Hello\r\nworld!"
                @print
                @assert true
                @assert ns.Foo.1.0.THE_CONSTANT == 42
                @assert ns.Bar.1.23.B == ns.Bar.1.23.A + 1
                ''')),
        [
            _define('ns/Foo.1.0.uavcan', 'int8 THE_CONSTANT = 42\n'),
            _define('ns/Bar.1.23.uavcan', 'int8 the_field\nint8 A = 0xA\nint8 B = 0xB'),
        ]
    )


@_in_n_out
def _unittest_dsdl_parser_expressions() -> None:
    from pytest import raises

    def throws(definition: str, exc: typing.Type[Exception] = _expression.InvalidOperandError) -> None:
        with raises(exc):
            _parse_definition(_define('ns/Throws.0.1.uavcan', dedent(definition)), [])

    throws('bool R = true && 0')
    throws('bool R = true || 0')
    throws('bool R = 0 || true')
    throws('bool R = 0 == true')
    throws('bool R = {0} & true')
    throws('bool R = true ^ {0}')
    throws('bool R = 0 ^ true')
    throws('int8 R = 1 / 0')
    throws('bool R = "S" == 0')
    throws('bool R = {0} != {}')
    throws('bool R = {0, true, "S"}')
    throws('bool R = {0} == {"s"}')
    throws('bool R = {0} <= "s"')
    throws('bool R = {0} >= "s"')
    throws('bool R = {0} > "s"')
    throws('bool R = {0} < "s"')
    throws('bool R = {0} | "s"')
    throws('bool R = {0} & "s"')
    throws('bool R = {0} ^ "s"')
    throws('bool R = {0}.nonexistent_attribute')
    throws('bool R = {0} / {1}')
    throws('bool R = !1')
    throws('bool R = +true')
    throws('bool R = -"1"')
    throws('bool R = true | false')
    throws('bool R = true & false')
    throws('bool R = true + "0"')
    throws('bool R = true - "0"')
    throws('bool R = true * "0"')
    throws('bool R = true / "0"')
    throws('bool R = true % "0"')
    throws('bool R = true ** "0"')

    _parse_definition(
        _define('ns/A.1.0.uavcan',
                dedent(r'''
                float64 PI = 3.141592653589793
                float64 E  = 2.718281828459045
                @assert (PI ** E > 22.4) && (PI ** E < 22.5)
                @assert 'moments of eternity'     != "strangers stealing someone else's dreams"  # I've seen it all
                @assert 'hunting for the mystery' != 'running for your life in times like these' # I've seen it all
                @assert "I remember the time once it a life" != 'oh baby'  # got you here in my head, here in my head
                @assert false == ('oh' == 'maybe')
                @assert true
                @assert 1 == 2 - 1
                @assert -10 == +20 / -2
                @assert {10, 15, 20} % 5 == {0}
                @assert {10, 15, 20} % 5 == {1, 2, 3} * 0
                @assert {10, 15, 20} / 5 == {2, 3, 4} * 10 / 5 / 2
                @assert {1} < {1, 2}
                @assert {1} <= {1}
                @assert {1} != {1, 2}
                @assert {1} >= {1}
                @assert {1, 2} > {1, 2} == false
                @assert {1, 2, 3} > {1, 2}
                @assert {1, 5/2} == {-5/-2, 2.5, 1}
                @assert {1, 2, 3} == {1} | {2} | {3} | {1}
                @assert {1, 2, 3} == {1, 2, 3, 4, 5} & {1, 2, 3, 8, 9}
                @assert {4, 5, 8, 9} == {1, 2, 3, 4, 5} ^ {1, 2, 3, 8, 9}
                @assert 1 - {1, 2, 3} == {0, -1, -2}
                @assert 1 / {1, 2, 3} == {1, 1/2, 1/3}
                @assert 8 % {1, 2, 3} == {0, 2}
                @assert 2 ** {1, 2, 3} == {2, 4, 8}
                @assert {1, 2, 3} ** 2 == {1, 4, 9}
                @assert "Hello" + ' ' + 'world' == 'Hello world'
                @assert 'Hello'+' '+'world' != ''
                @assert '\u00e9' == '\u0065\u0301'  # e with accent
                @assert '\ufb03' != 'ffi'           # ffi ligature is not decomposed by NFC
                @assert true != ('A' == "a")
                @assert true && true
                @assert ! (true && false)
                @assert true||false
                @assert !false
                @assert ! 5 < 3
                @assert 4 | 2 == 6
                @assert 4 & 2 == 0
                @assert 3 & 2 == 2
                @assert 0xFF_00 & 0x00_FF == 0x0000
                @assert 0xFF_00 | 0x00_FF == 0xFFFF
                @assert 0xFF_00 ^ 0x0F_FF == 0xF0FF
                ''')),
        []
    )


def _collect_descendants(cls: typing.Type[object]) -> typing.Iterable[typing.Type[object]]:
    # noinspection PyArgumentList
    for t in cls.__subclasses__():
        yield t
        yield from _collect_descendants(t)


def _unittest_collect_descendants() -> None:  # Unit test for my unit test.
    class A:
        pass

    class B(A):
        pass

    class C(B):
        pass

    class D(A):
        pass

    assert set(_collect_descendants(A)) == {B, C, D}
    assert set(_collect_descendants(D)) == set()
    assert bool in set(_collect_descendants(int))


def _unittest_public_api() -> None:
    import pydsdl

    # Ensure that all descendants of the specified classes are exported from the library.
    # If this test fails, you probably forgot to update __init__.py.
    public_roots = [
        _serializable.SerializableType,
        _serializable.Attribute,
        _expression.Any,
    ]

    for root in public_roots:
        expected_types = {root} | set(_collect_descendants(root))
        for t in expected_types:
            assert t.__name__ in dir(pydsdl), 'Data type %r is not exported' % t
