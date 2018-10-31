#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os
import typing
import tempfile
from .dsdl_parser import parse_definition, SemanticError, DSDLSyntaxError
from .dsdl_parser import UndefinedDataTypeError, AssertionCheckFailureError
from .dsdl_definition import DSDLDefinition, FileNameFormatError
from .data_type import CompoundType, StructureType, UnionType, ServiceType, ArrayType
from .namespace_parser import parse_namespace, RegulatedPortIDCollisionError, VersionsOfDifferentKindError
from .namespace_parser import MinorVersionsNotBitCompatibleError, MultipleDefinitionsUnderSameVersionError
from .namespace_parser import MinorVersionRegulatedPortIDError, NestedRootNamespaceError, NamespaceNameCollisionError


_DIRECTORY = None       # type: typing.Optional[tempfile.TemporaryDirectory]


def _define(rel_path: str, text: str) -> DSDLDefinition:
    assert _DIRECTORY
    path = os.path.join(_DIRECTORY.name, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)

    root_namespace_path = os.path.join(_DIRECTORY.name, rel_path.strip(os.sep).split(os.sep)[0])
    out = DSDLDefinition(path, root_namespace_path)
    print('New definition:', out, 'Root NS:', root_namespace_path)
    return out


def _in_n_out(test: typing.Callable[[], None]) -> typing.Callable[[], None]:
    def decorator() -> None:
        global _DIRECTORY
        _DIRECTORY = tempfile.TemporaryDirectory()
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
    assert d.name == 'uavcan.test.Message'
    assert d.version == (1, 2)
    assert d.regulated_port_id == 65000
    assert d.file_path == os.path.join(_DIRECTORY.name, 'uavcan/test/65000.Message.1.2.uavcan')
    assert open(d.file_path).read() == '# empty'

    # BUT WHEN I DO, I WRITE UNIT TESTS FOR MY UNIT TESTS
    d = _define('uavcan/Service.255.254.uavcan', '# empty 2')
    assert d.name == 'uavcan.Service'
    assert d.version == (255, 254)
    assert d.regulated_port_id is None
    assert d.file_path == os.path.join(_DIRECTORY.name, 'uavcan/Service.255.254.uavcan')
    assert open(d.file_path).read() == '# empty 2'


@_in_n_out
def _unittest_simple() -> None:
    abc = _define(
        'vendor/nested/58000.Abc.1.2.uavcan',
        '''
        @deprecated
        uint8 CHARACTER = '#'
        int8 a
        truncated int64[<33] b
        '''
    )
    assert abc.regulated_port_id == 58000
    assert abc.name == 'vendor.nested.Abc'
    assert abc.version == (1, 2)

    p = parse_definition(abc, [])
    print('Parsed:', p)
    assert isinstance(p, StructureType)
    assert p.name == 'vendor.nested.Abc'
    assert p.source_file_path.endswith('vendor/nested/58000.Abc.1.2.uavcan')
    assert p.source_file_path == abc.file_path
    assert p.regulated_port_id == 58000
    assert p.deprecated
    assert p.version == (1, 2)
    assert p.bit_length_range == (14, 14 + 64 * 32)
    assert len(p.attributes) == 3
    assert len(p.fields) == 2
    assert str(p.fields[0].data_type) == 'saturated int8'
    assert p.fields[0].name == 'a'
    assert str(p.fields[1].data_type) == 'truncated int64[<=32]'      # Note: normalized representation
    assert p.fields[1].name == 'b'
    assert len(p.constants) == 1
    assert str(p.constants[0].data_type) == 'saturated uint8'
    assert p.constants[0].name == 'CHARACTER'
    assert p.constants[0].initialization_expression == "'#'"
    assert isinstance(p.constants[0].value, int)
    assert p.constants[0].value == ord('#')

    t = p.fields[1].data_type
    assert isinstance(t, ArrayType)
    assert str(t.element_type) == 'truncated int64'

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
        '''
        float64 PI = 3.1415926535897932384626433
        '''
    )

    service = _define(
        'another/300.Service.0.1.uavcan',
        '''
        @union
        @deprecated
        vendor.nested.Empty.255     new_empty_implicit
        vendor.nested.Empty.255.255 new_empty_explicit
        vendor.nested.Empty.255.254 old_empty
        ---#---#---#---#---#---#---#---#---
        Constants.5 constants      # RELATIVE REFERENCE
        vendor.nested.Abc.1.2 abc
        '''
    )

    p = parse_definition(service, [
        abc,
        empty_new,
        empty_old,
        constants,
    ])
    print('Parsed:', p)
    assert isinstance(p, ServiceType)
    assert p.name == 'another.Service'
    assert p.regulated_port_id == 300
    assert p.deprecated
    assert p.version == (0, 1)
    assert not p.constants

    assert len(p.fields) == 2
    assert p.fields[0].name == 'request'
    assert p.fields[1].name == 'response'
    req, res = [x.data_type for x in p.fields]
    assert isinstance(req, UnionType)
    assert isinstance(res, StructureType)
    assert req.name == 'another.Service.Request'
    assert res.name == 'another.Service.Response'
    assert req is p.request_type
    assert res is p.response_type

    assert len(req.constants) == 0
    assert len(req.fields) == 3
    assert req.number_of_variants == 3
    assert req.deprecated
    assert not req.has_regulated_port_id
    assert req.version == (0, 1)
    assert req.bit_length_range == (2, 2)   # Remember this is a union
    assert [x.name for x in req.fields] == ['new_empty_implicit', 'new_empty_explicit', 'old_empty']

    t = req.fields[0].data_type
    assert isinstance(t, StructureType)
    assert t.name == 'vendor.nested.Empty'
    assert t.version == (255, 255)          # Selected implicitly

    t = req.fields[1].data_type
    assert isinstance(t, StructureType)
    assert t.name == 'vendor.nested.Empty'
    assert t.version == (255, 255)          # Selected explicitly

    t = req.fields[2].data_type
    assert isinstance(t, StructureType)
    assert t.name == 'vendor.nested.Empty'
    assert t.version == (255, 254)          # Selected explicitly

    assert len(res.constants) == 0
    assert len(res.fields) == 2
    assert res.deprecated
    assert not res.has_regulated_port_id
    assert res.version == (0, 1)
    assert res.bit_length_range == (14, 14 + 64 * 32)

    t = res.fields[0].data_type
    assert isinstance(t, StructureType)
    assert t.name == 'another.Constants'
    assert t.version == (5, 0)

    t = res.fields[1].data_type
    assert isinstance(t, StructureType)
    assert t.name == 'vendor.nested.Abc'
    assert t.version == (1, 2)

    union = _define(
        'another/Union.5.9.uavcan',
        '''
        @union
        truncated float16 PI = 3.1415926535897932384626433
        uint8 a
        vendor.nested.Empty.255[5] b
        truncated bool [ <= 255 ] c
        '''
    )

    p = parse_definition(union, [
        empty_old,
        empty_new,
    ])

    assert p.name == 'another.Union'
    assert p.version == (5, 9)
    assert p.regulated_port_id is None
    assert not p.has_regulated_port_id
    assert not p.deprecated
    assert isinstance(p, UnionType)
    assert p.number_of_variants == 3
    assert len(p.constants) == 1
    assert p.constants[0].name == 'PI'
    assert str(p.constants[0].data_type) == 'truncated float16'
    assert p.bit_length_range == (2, 2 + 8 + 255)
    assert len(p.fields) == 3
    assert str(p.fields[0]) == 'saturated uint8 a'
    assert str(p.fields[1]) == 'vendor.nested.Empty.255.255[5] b'
    assert str(p.fields[2]) == 'truncated bool[<=255] c'


@_in_n_out
def _unittest_error() -> None:
    from pytest import raises

    def standalone(rel_path: str, definition: str) -> CompoundType:
        return parse_definition(_define(rel_path, definition), [])

    with raises(SemanticError, match='(?i).*subject ID.*'):
        standalone('vendor/10000.InvalidRegulatedSubjectID.1.0.uavcan', 'uint2 value')

    with raises(SemanticError, match='(?i).*service ID.*'):
        standalone('vendor/10000.InvalidRegulatedServiceID.1.0.uavcan', 'uint2 v1\n---\nint64 v2')

    with raises(SemanticError, match='(?i).*multiple attributes under the same name.*'):
        standalone('vendor/AttributeNameCollision.1.0.uavcan', 'uint2 value\nint64 value')

    with raises(SemanticError, match='(?i).*tagged union cannot contain less than.*'):
        standalone('vendor/SmallUnion.1.0.uavcan', '@union\nuint2 value')

    assert standalone('vendor/invalid_constant_value/A.1.0.uavcan',
                      'bool BOOLEAN = false').constants[0].name == 'BOOLEAN'
    with raises(SemanticError, match='.*Invalid value for boolean constant.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', 'bool BOOLEAN = 0')   # Should be false

    with raises(SemanticError, match='(?i).*could not evaluate.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', 'bool BOOLEAN = undefined_identifier')

    with raises(DSDLSyntaxError):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', 'bool BOOLEAN = -')

    with raises(SemanticError, match='(?i).*exceeds the range.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', 'uint10 INTEGRAL = 2000')

    with raises(SemanticError, match='(?i).*character.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', "uint8 CH = '\u0451'")

    with raises(SemanticError, match='.*uint8.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', "uint9 CH = 'q'")

    with raises(SemanticError, match='.*uint8.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', "int8 CH = 'q'")

    with raises(SemanticError, match='(?i).*type.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', "int8 CH = 1.0")

    with raises(SemanticError, match='(?i).*type.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', "float32 CH = true")

    with raises(SemanticError, match='(?i).*type.*'):
        standalone('vendor/invalid_constant_value/A.1.0.uavcan', "float32 CH = 't'")

    with raises(DSDLSyntaxError):
        standalone('vendor/syntax_error/A.1.0.uavcan', 'bool array[10]')

    with raises(SemanticError, match='(?i).*array size.*'):
        standalone('vendor/array_size/A.1.0.uavcan', 'bool[0] array')

    with raises(SemanticError, match='(?i).*array size.*'):
        standalone('vendor/array_size/A.1.0.uavcan', 'bool[<1] array')

    with raises(SemanticError, match='(?i).*service response marker.*'):
        standalone('vendor/service/A.1.0.uavcan', 'bool request\n---\nbool response\n---\nbool again')

    with raises(SemanticError, match='(?i).*unknown directive.*'):
        standalone('vendor/directive/A.1.0.uavcan', '@sho_tse_take')

    with raises(SemanticError, match='(?i).*requires an expression.*'):
        standalone('vendor/directive/A.1.0.uavcan', '@assert')

    with raises(SemanticError, match='(?i).*does not expect an expression.*'):
        standalone('vendor/directive/A.1.0.uavcan', '@union worker')

    with raises(SemanticError, match='(?i).*version number.*'):
        standalone('vendor/version/A.0.0.uavcan', '')

    with raises(SemanticError, match='(?i).*version number.*'):
        standalone('vendor/version/A.0.256.uavcan', '')

    with raises(FileNameFormatError):
        standalone('vendor/version/A.0..256.uavcan', '')

    with raises(SemanticError, match='(?i).*version number.*'):
        standalone('vendor/version/A.256.0.uavcan', '')

    with raises(SemanticError, match='(?i).*cannot be specified for compound.*'):
        standalone('vendor/types/A.1.0.uavcan', 'truncated uavcan.node.Heartbeat.1.0 field')

    with raises(UndefinedDataTypeError, match='(?i).*no type named.*'):
        standalone('vendor/types/A.1.0.uavcan', 'nonexistent.TypeName.1.0 field')

    with raises(UndefinedDataTypeError, match='(?i).*no suitable major version'):
        parse_definition(
            _define('vendor/types/A.1.0.uavcan', 'ns.Type.1.0 field'),
            [
                _define('ns/Type.2.0.uavcan', ''),
            ]
        )

    with raises(UndefinedDataTypeError, match='(?i).*no suitable minor version'):
        parse_definition(
            _define('vendor/types/A.1.0.uavcan', 'ns.Type.1.0 field'),
            [
                _define('ns/Type.2.0.uavcan', ''),
                _define('ns/Type.1.1.uavcan', ''),
            ]
        )

    with raises(DSDLSyntaxError, match='(?i).*Invalid type declaration.*'):
        parse_definition(
            _define('vendor/types/A.1.0.uavcan', 'int128 field'),
            [
                _define('ns/Type.2.0.uavcan', ''),
                _define('ns/Type.1.1.uavcan', ''),
            ]
        )

    with raises(SemanticError, match='(?i).*type.*'):
        parse_definition(
            _define('vendor/invalid_constant_value/A.1.0.uavcan', 'ns.Type.1 VALUE = 123'),
            [
                _define('ns/Type.2.0.uavcan', ''),
                _define('ns/Type.1.1.uavcan', ''),
            ]
        )

    with raises(UndefinedDataTypeError):
        defs = [
            _define('vendor/circular_dependency/A.1.0.uavcan', 'B.1 b'),
            _define('vendor/circular_dependency/B.1.0.uavcan', 'A.1 b'),
        ]
        parse_definition(defs[0], defs)

    with raises(SemanticError, match='(?i).*union directive.*'):
        parse_definition(
            _define('vendor/misplaced_directive/A.1.0.uavcan', 'ns.Type.2 field\n@union'),
            [
                _define('ns/Type.2.0.uavcan', ''),
            ]
        )

    with raises(SemanticError, match='(?i).*deprecated directive.*'):
        parse_definition(
            _define('vendor/misplaced_directive/A.1.0.uavcan', 'ns.Type.2 field\n@deprecated'),
            [
                _define('ns/Type.2.0.uavcan', ''),
            ]
        )

    with raises(SemanticError, match='(?i).*deprecated directive.*'):
        parse_definition(
            _define('vendor/misplaced_directive/A.1.0.uavcan', 'ns.Type.2 field\n---\n@deprecated'),
            [
                _define('ns/Type.2.0.uavcan', ''),
            ]
        )


@_in_n_out
def _unittest_print() -> None:
    printed_items = None    # type: typing.Optional[typing.Tuple[DSDLDefinition, int, typing.Any]]

    def print_handler(definition: DSDLDefinition, line_number: int, value: typing.Any) -> None:
        nonlocal printed_items
        printed_items = definition, line_number, value

    parse_definition(
        _define(
            'ns/A.1.0.uavcan',
            '''# line number 1
            # line number 2
            @print 2 + 2 == 4   # line number 3
            # line number 4
            '''),
        [],
        print_handler=print_handler
    )
    assert printed_items
    assert printed_items[0].name == 'ns.A'
    assert printed_items[1] == 3
    assert printed_items[2]

    parse_definition(_define('ns/B.1.0.uavcan', '@print false'), [], print_handler=print_handler)
    assert printed_items
    assert printed_items[0].name == 'ns.B'
    assert printed_items[1] == 1
    assert not printed_items[2]

    parse_definition(
        _define(
            'ns/Offset.1.0.uavcan',
            '''@print offset    # Not recorded
            uint8 a
            @print offset
            '''),
        [],
        print_handler=print_handler
    )
    assert printed_items
    assert printed_items[0].name == 'ns.Offset'
    assert printed_items[1] == 3
    assert printed_items[2] == {8}

    # The nested type has the following set: {2, 10, 18}.
    # We can have up to two elements of that type, so what we get can be expressed graphically as follows:
    #    A   B | +
    # ---------+------
    #    2   2 |  4
    #   10   2 | 12
    #   18   2 | 20
    #    2  10 | 12
    #   10  10 | 20
    #   18  10 | 28
    #    2  18 | 20
    #   10  18 | 28
    #   18  18 | 36
    # If we were to remove duplicates, we end up with: {4, 12, 20, 28, 36}
    parse_definition(
        _define(
            'ns/ComplexOffset.1.0.uavcan',
            '''
            Array.1[2] bar
            @print offset
            '''),
        [
            _define('ns/Array.1.0.uavcan', 'uint8[<=2] foo')
        ],
        print_handler=print_handler
    )
    assert printed_items
    assert printed_items[0].name == 'ns.ComplexOffset'
    assert printed_items[1] == 3
    assert printed_items[2] == {4, 12, 20, 28, 36}


@_in_n_out
def _unittest_assert() -> None:
    from pytest import raises

    parse_definition(
        _define(
            'ns/A.1.0.uavcan',
            '''
            @assert offset == {0}
            @assert offset.min == offset.max
            Array.1[2] bar
            @assert offset == {4, 12, 20, 28, 36}
            @assert offset.min == 4
            @assert offset.max == 36
            @assert offset % 4 == {0}
            @assert offset % 8 == {4}
            @assert offset % 10 == {4, 2, 0, 8, 6}
            @assert offset * 2 == {8, 24, 40, 56, 72}
            @assert 2 * offset == {8, 24, 40, 56, 72}
            @assert offset / 4 == {1, 3, 5, 7, 9}
            @assert offset - 4 == {0, 8, 16, 24, 32}
            @assert offset + 4 == {8, 16, 24, 32, 40}
            uint64 big
            @assert offset - 64 == {4, 12, 20, 28, 36}
            @assert offset.min == 68
            @assert offset.max == 100  # 36 + 64
            @assert offset.max <= 100
            @assert offset.max < 101
            @assert offset <= 100
            @assert offset < 101
            @assert offset >= 68
            @assert offset > 67
            @assert offset == offset
            '''),
        [
            _define('ns/Array.1.0.uavcan', 'uint8[<=2] foo')
        ]
    )

    with raises(SemanticError, match='(?i).*invalid operand.*'):
        parse_definition(
            _define(
                'ns/B.1.0.uavcan',
                '''
                uint64 big
                @assert offset == {64}
                @assert offset + 1.0 == {64}
                '''),
            []
        )

    with raises(SemanticError, match='(?i).*cannot be compared.*'):
        parse_definition(
            _define(
                'ns/C.1.0.uavcan',
                '''
                uint64 big
                @assert offset == 64
                '''),
            []
        )

    parse_definition(
        _define(
            'ns/D.1.0.uavcan',
            '''
            @union
            float32 a
            uint64 b
            @assert offset == {33, 65}
            '''),
        []
    )

    parse_definition(
        _define(
            'ns/E.1.0.uavcan',
            '''
            @union
            uint8 A = 0
            float32 a
            uint8 B = 1
            uint64 b
            uint8 C = 2
            @assert offset == {33, 65}
            uint8 D = 3
            '''),
        []
    )

    with raises(SemanticError, match='(?i).*unions.*'):
        parse_definition(
            _define(
                'ns/F.1.0.uavcan',
                '''
                @union
                @assert offset.min == 33
                float32 a
                uint64 b
                @assert offset == {33, 65}
                '''),
            []
        )

    with raises(AssertionCheckFailureError):
        parse_definition(
            _define(
                'ns/G.1.0.uavcan',
                '''
                float32 a
                @assert offset.min == 8
                '''),
            []
        )

    with raises(SemanticError, match='(?i).*yield a boolean.*'):
        parse_definition(
            _define(
                'ns/H.1.0.uavcan',
                '''
                float32 a
                @assert offset.min
                '''),
            []
        )


def _unittest_parse_namespace() -> None:
    from pytest import raises
    import tempfile
    directory = tempfile.TemporaryDirectory()

    def _define(rel_path: str, text: str) -> None:
        path = os.path.join(directory.name, rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(text)

    _define(
        'zubax/First.1.0.uavcan',
        """
        uint8[<256] a
        @assert offset.min == 8
        @assert offset.max == 2048
        """
    )

    _define(
        'zubax/58001.Message.1.0.uavcan',
        """
        void6
        zubax.First.1[<=2] a
        @assert offset.min == 8
        @assert offset.max == 4104
        """
    )

    _define(
        'zubax/nested/300.Spartans.30.0.uavcan',
        """
        @deprecated
        @union
        float16 small
        float32 just_right
        float64 woah
        ---
        """
    )

    _define('zubax/nested/300.Spartans.30.0.txt', 'completely unrelated stuff')
    _define('zubax/300.Spartans.30.0', 'completely unrelated stuff')

    parsed = parse_namespace(
        os.path.join(directory.name, 'zubax'),
        []
    )
    print(parsed)
    assert len(parsed) == 3
    assert 'zubax.First' in [x.name for x in parsed]
    assert 'zubax.Message' in [x.name for x in parsed]
    assert 'zubax.nested.Spartans' in [x.name for x in parsed]

    _define(
        'zubax/colliding/300.Iceberg.30.0.uavcan',
        """
        ---
        """
    )

    with raises(RegulatedPortIDCollisionError):
        parse_namespace(
            os.path.join(directory.name, 'zubax'),
            []
        )


def _unittest_parse_namespace_versioning() -> None:
    from pytest import raises
    import tempfile
    import glob
    directory = tempfile.TemporaryDirectory()

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
        """
        @deprecated
        @union
        float16 small
        float32 just_right
        float64 woah
        ---
        """
    )

    _define(
        'ns/Spartans.30.1.uavcan',
        """
        @deprecated
        @union
        uint16 small
        int32 just_right
        float64[1] woah
        ---
        """
    )

    parsed = parse_namespace(
        os.path.join(directory.name, 'ns'),
        []
    )
    print(parsed)
    assert len(parsed) == 2

    _define(
        'ns/Spartans.30.2.uavcan',
        """
        @deprecated
        @union
        uint16 small
        int32 just_right
        float64[<=1] woah
        ---
        """
    )

    with raises(MinorVersionsNotBitCompatibleError):
        parse_namespace(
            os.path.join(directory.name, 'ns'),
            []
        )

    _define(
        'ns/Spartans.30.2.uavcan',
        """
        @deprecated
        @union
        uint16 small
        int32 just_right
        float64[1] woah
        """
    )

    with raises(VersionsOfDifferentKindError):
        parse_namespace(
            os.path.join(directory.name, 'ns'),
            []
        )

    _undefine_glob('ns/Spartans.30.[01].uavcan')

    _define(
        'ns/Spartans.30.0.uavcan',
        """
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        """
    )

    parsed = parse_namespace(
        os.path.join(directory.name, 'ns'),
        []
    )
    print(parsed)
    assert len(parsed) == 2

    _define(
        'ns/Spartans.30.1.uavcan',
        """
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[<=1] woah
        """
    )

    with raises(MinorVersionsNotBitCompatibleError):
        parse_namespace(
            os.path.join(directory.name, 'ns'),
            []
        )

    _define(
        'ns/Spartans.30.1.uavcan',
        """
        @deprecated
        @union
        uint16 small
        float32 just_right
        int64 woah
        """
    )

    _define(
        'ns/59000.Spartans.30.2.uavcan',
        """
        @deprecated
        @union
        uint16 small
        int32 just_right
        float64[1] woah
        """
    )

    with raises(MultipleDefinitionsUnderSameVersionError):
        parse_namespace(os.path.join(directory.name, 'ns'), [])

    _undefine_glob('ns/Spartans.30.2.uavcan')

    parsed = parse_namespace(
        os.path.join(directory.name, 'ns'),
        []
    )
    assert len(parsed) == 3

    _undefine_glob('ns/Spartans.30.0.uavcan')
    _define(
        'ns/59000.Spartans.30.0.uavcan',
        """
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        """
    )

    with raises(MinorVersionRegulatedPortIDError):
        parse_namespace(os.path.join(directory.name, 'ns'), [])

    _undefine_glob('ns/Spartans.30.1.uavcan')
    _define(
        'ns/59000.Spartans.30.1.uavcan',
        """
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        """
    )

    parsed = parse_namespace(
        os.path.join(directory.name, 'ns'),
        []
    )
    assert len(parsed) == 3

    _undefine_glob('ns/59000.Spartans.30.1.uavcan')
    _define(
        'ns/59001.Spartans.30.1.uavcan',
        """
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        """
    )

    with raises(MinorVersionRegulatedPortIDError):
        parse_namespace(os.path.join(directory.name, 'ns'), [])

    # Adding new major version under the same RPID
    _undefine_glob('ns/59001.Spartans.30.1.uavcan')
    _define(
        'ns/59000.Spartans.31.0.uavcan',
        """
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        """
    )

    with raises(RegulatedPortIDCollisionError):
        parse_namespace(os.path.join(directory.name, 'ns'), [])


def _unittest_parse_namespace_faults() -> None:
    try:
        parse_namespace('/foo/bar/baz', ['/bat/wot', '/foo/bar/baz/bad'])
    except NestedRootNamespaceError as ex:
        print(ex)
    else:               # pragma: no cover
        assert False

    try:
        parse_namespace('/foo/bar/baz', ['/foo/bar/zoo', '/foo/bar/doo/roo/baz'])
    except NamespaceNameCollisionError as ex:
        print(ex)
    else:               # pragma: no cover
        assert False
    try:
        parse_namespace('/foo/bar/baz', ['/foo/bar/zoo', '/foo/bar/doo/roo/zoo', '/foo/bar/doo/roo/baz'])
    except NamespaceNameCollisionError as ex:
        print(ex)
    else:               # pragma: no cover
        assert False
