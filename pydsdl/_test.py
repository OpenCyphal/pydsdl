# Copyright (c) 2018 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

# cSpell: words iceb
# pylint: disable=global-statement,protected-access,too-many-statements,consider-using-with,redefined-outer-name

from __future__ import annotations
import tempfile
from typing import Sequence, Type, Iterable
from pathlib import Path
from textwrap import dedent
import pytest  # This is only safe to import in test files!
from . import _expression
from . import _error
from . import _parser
from . import _data_type_builder
from . import _dsdl_definition
from . import _serializable
from . import _namespace

__all__ = []  # type: ignore


class Workspace:
    def __init__(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory(prefix="pydsdl-test-")

    @property
    def directory(self) -> Path:
        return Path(self._tmp_dir.name)

    def new(self, rel_path: str | Path, text: str) -> None:
        """
        Simply creates a new DSDL source file with the given contents at the specified path inside the workspace.
        """
        rel_path = Path(rel_path)
        path = self.directory / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf8")

    def parse_new(self, rel_path: str | Path, text: str) -> _dsdl_definition.DSDLDefinition:
        """
        Creates a new DSDL source file with the given contents at the specified path inside the workspace,
        then parses it and returns the resulting definition object.
        """
        rel_path = Path(rel_path)
        self.new(rel_path, text)
        path = self.directory / rel_path
        root_namespace_path = self.directory / rel_path.parts[0]
        out = _dsdl_definition.DSDLDefinition(path, root_namespace_path)
        return out

    def drop(self, rel_path_glob: str) -> None:
        """
        Deletes all files matching the specified glob pattern.
        """
        for g in self.directory.glob(rel_path_glob):
            g.unlink()


def parse_definition(
    definition: _dsdl_definition.DSDLDefinition, lookup_definitions: Sequence[_dsdl_definition.DSDLDefinition]
) -> _serializable.CompositeType:
    return definition.read(
        lookup_definitions,
        [],
        print_output_handler=lambda line, text: print("Output from line %d:" % line, text),
        allow_unregulated_fixed_port_id=False,
    )


@pytest.fixture()  # type: ignore
def wrkspc() -> Workspace:
    return Workspace()


def _unittest_define(wrkspc: Workspace) -> None:
    d = wrkspc.parse_new("uavcan/test/5000.Message.1.2.dsdl", "# empty")
    assert d.full_name == "uavcan.test.Message"
    assert d.version == (1, 2)
    assert d.fixed_port_id == 5000
    assert d.file_path.samefile(Path(wrkspc.directory, "uavcan", "test", "5000.Message.1.2.dsdl"))
    assert d.root_namespace_path.samefile(wrkspc.directory / "uavcan")
    assert d.file_path.read_text() == "# empty"

    d = wrkspc.parse_new("uavcan/Service.255.254.dsdl", "# empty 2")
    assert d.full_name == "uavcan.Service"
    assert d.version == (255, 254)
    assert d.fixed_port_id is None
    assert d.file_path.samefile(Path(wrkspc.directory, "uavcan", "Service.255.254.dsdl"))
    assert d.root_namespace_path.samefile(wrkspc.directory / "uavcan")
    assert d.file_path.read_text() == "# empty 2"


def _unittest_simple(wrkspc: Workspace) -> None:
    abc = wrkspc.parse_new(
        "vendor/nested/7000.Abc.1.2.dsdl",
        dedent(
            """
        @deprecated
        uint8 CHARACTER = '#'
        int8 a
        saturated int64[<33] b
        @extent 1024 * 8
        """
        ),
    )
    assert abc.fixed_port_id == 7000
    assert abc.full_name == "vendor.nested.Abc"
    assert abc.version == (1, 2)

    p = parse_definition(abc, [])
    print("Parsed:", p)
    assert isinstance(p, _serializable.DelimitedType)
    assert isinstance(p.inner_type, _serializable.StructureType)
    assert p.full_name == "vendor.nested.Abc"
    assert p.source_file_path.parts[-3:] == ("vendor", "nested", "7000.Abc.1.2.dsdl")
    assert p.source_file_path.samefile(abc.file_path)
    assert p.fixed_port_id == 7000
    assert p.deprecated
    assert p.version == (1, 2)
    assert min(p.inner_type.bit_length_set) == 16
    assert max(p.inner_type.bit_length_set) == 16 + 64 * 32
    assert min(p.bit_length_set) == 32
    assert max(p.bit_length_set) == 32 + 1024 * 8
    assert len(p.attributes) == 3
    assert len(p.fields) == 2
    assert str(p.fields[0].data_type) == "saturated int8"
    assert p.fields[0].name == "a"
    assert str(p.fields[1].data_type) == "saturated int64[<=32]"  # Note: normalized representation
    assert p.fields[1].name == "b"
    assert len(p.constants) == 1
    assert str(p.constants[0].data_type) == "saturated uint8"
    assert p.constants[0].name == "CHARACTER"
    assert isinstance(p.constants[0].value, _expression.Rational)
    assert p.constants[0].value == _expression.Rational(ord("#"))

    t = p.fields[1].data_type
    assert isinstance(t, _serializable.ArrayType)
    assert str(t.element_type) == "saturated int64"

    empty_new = wrkspc.parse_new("vendor/nested/Empty.255.255.dsdl", """@sealed""")

    empty_old = wrkspc.parse_new("vendor/nested/Empty.255.254.dsdl", """@sealed""")

    constants = wrkspc.parse_new(
        "another/Constants.5.0.dsdl",
        dedent(
            """
        @sealed
        float64 PI = 3.1415926535897932384626433
        """
        ),
    )

    service = wrkspc.parse_new(
        "another/300.Service.0.1.dsdl",
        dedent(
            """
        @union
        @deprecated
        vendor.nested.Empty.255.255 new_empty_implicit
        vendor.nested.Empty.255.255 new_empty_explicit
        vendor.nested.Empty.255.254 old_empty
        @extent 32
        -----------------------------------
        @sealed                      # RESPONSE SEALED REQUEST NOT
        Constants.5.0 constants      # RELATIVE REFERENCE
        vendor.nested.Abc.1.2 abc
        """
        ),
    )

    p = parse_definition(
        service,
        [
            abc,
            empty_new,
            empty_old,
            constants,
        ],
    )
    print("Parsed:", p)
    assert isinstance(p, _serializable.ServiceType)
    assert p.full_name == "another.Service"
    assert p.fixed_port_id == 300
    assert p.deprecated
    assert p.version == (0, 1)
    assert not p.constants
    assert p == p  # pylint: disable=comparison-with-itself
    assert p != empty_new

    assert len(p.fields) == 2
    assert p.fields[0].name == "request"
    assert p.fields[1].name == "response"
    req, res = [x.data_type for x in p.fields]
    assert isinstance(req, _serializable.DelimitedType)
    assert isinstance(req.inner_type, _serializable.UnionType)
    assert isinstance(res, _serializable.StructureType)
    assert req.full_name == "another.Service.Request"
    assert res.full_name == "another.Service.Response"
    assert req is p.request_type
    assert res is p.response_type
    assert req.has_parent_service
    assert req.inner_type.has_parent_service
    assert res.has_parent_service

    assert len(req.constants) == 0
    assert len(req.fields) == 3
    # noinspection PyUnresolvedReferences
    assert req.inner_type.number_of_variants == 3
    assert req.deprecated
    assert not req.has_fixed_port_id
    assert req.version == (0, 1)
    assert req.bit_length_set == {32, 32 + 8, 32 + 16, 32 + 24, 32 + 32}  # Delimited container, @extent
    assert req.inner_type.bit_length_set == 8  # Remember this is a union
    assert [x.name for x in req.fields] == ["new_empty_implicit", "new_empty_explicit", "old_empty"]

    t = req.fields[0].data_type
    assert isinstance(t, _serializable.StructureType)
    assert t.full_name == "vendor.nested.Empty"
    assert t.version == (255, 255)  # Selected implicitly

    t = req.fields[1].data_type
    assert isinstance(t, _serializable.StructureType)
    assert t.full_name == "vendor.nested.Empty"
    assert t.version == (255, 255)  # Selected explicitly

    t = req.fields[2].data_type
    assert isinstance(t, _serializable.StructureType)
    assert t.full_name == "vendor.nested.Empty"
    assert t.version == (255, 254)  # Selected explicitly

    assert len(res.constants) == 0
    assert len(res.fields) == 2
    assert res.deprecated
    assert not res.has_fixed_port_id
    assert res.version == (0, 1)
    # This is a sealed type, so we get the real BLS, but we mustn't forget about the non-sealed nested field!
    assert min(res.bit_length_set) == 32  # Just the delimiter header
    assert max(res.bit_length_set) == 32 + 1024 * 8

    t = res.fields[0].data_type
    assert isinstance(t, _serializable.StructureType)
    assert t.full_name == "another.Constants"
    assert t.version == (5, 0)

    t = res.fields[1].data_type
    assert isinstance(t, _serializable.DelimitedType)
    assert isinstance(t.inner_type, _serializable.StructureType)
    assert t.full_name == "vendor.nested.Abc"
    assert t.version == (1, 2)

    p2 = parse_definition(
        abc,
        [
            service,
            empty_new,
            empty_old,
            constants,
        ],
    )
    assert hash(p2) == hash(p2)
    assert hash(p2) != hash(p)
    assert hash(p) == hash(p)

    union = wrkspc.parse_new(
        "another/Union.5.9.dsdl",
        dedent(
            """
        @union
        @sealed
        truncated float16 PI = 3.1415926535897932384626433
        uint8 a
        vendor.nested.Empty.255.255[5] b
        saturated bool [ <= 255 ] c
        """
        ),
    )

    p = parse_definition(
        union,
        [
            empty_old,
            empty_new,
        ],
    )

    assert p.full_name == "another.Union"
    assert p.version == (5, 9)
    assert p.fixed_port_id is None
    assert not p.has_fixed_port_id
    assert not p.deprecated
    assert isinstance(p, _serializable.UnionType)
    assert p.number_of_variants == 3
    assert len(p.constants) == 1
    assert p.constants[0].name == "PI"
    assert str(p.constants[0].data_type) == "truncated float16"
    assert min(p.bit_length_set) == 8
    assert max(p.bit_length_set) == 8 + 8 + 255 + 1  # The last +1 is the padding to byte.
    assert len(p.fields) == 3
    assert str(p.fields[0]) == "saturated uint8 a"
    assert str(p.fields[1]) == "vendor.nested.Empty.255.255[5] b"
    assert str(p.fields[2]) == "saturated bool[<=255] c"


def _unittest_comments(wrkspc: Workspace) -> None:
    abc = wrkspc.parse_new(
        "vendor/nested/7000.Abc.1.2.dsdl",
        dedent(
            """\
        # header comment here
        # multiline

        # this should be ignored

        uint8 CHARACTER = '#' # comment on constant
        int8 a # comment on field
        int8 a_prime
        @assert 1 == 1 # toss one in for confusion
        void2 # comment on padding field
        saturated int64[<33] b
        # comment on array
        # and another
        @extent 1024 * 8
        """
        ),
    )

    p = parse_definition(abc, [])
    print("Parsed:", p)
    print(p.doc.__repr__())
    # assert p.doc == "header comment here\nmultiline"
    assert p.constants[0].doc == "comment on constant"
    assert p.fields[0].doc == "comment on field"
    assert p.fields[2].doc == "comment on padding field"
    assert p.fields[3].doc == "comment on array\nand another"

    empty_new = wrkspc.parse_new("vendor/nested/Empty.255.255.dsdl", """@sealed""")

    empty_old = wrkspc.parse_new("vendor/nested/Empty.255.254.dsdl", """@sealed""")

    constants = wrkspc.parse_new(
        "another/Constants.5.0.dsdl",
        dedent(
            """
        @sealed
        float64 PI = 3.1415926535897932384626433 # no header comment
        """
        ),
    )

    p = parse_definition(constants, [])
    assert p.doc == ""
    assert p.constants[0].doc == "no header comment"

    service = wrkspc.parse_new(
        "another/300.Service.0.1.dsdl",
        dedent(
            """\
        # first header comment here
        # multiline
        @union
        @deprecated
        vendor.nested.Empty.255.255 new_empty_implicit
        vendor.nested.Empty.255.255 new_empty_explicit
        vendor.nested.Empty.255.254 old_empty
        @extent 32 # make sure no leaks
        -----------------------------------
        # second header comment here
        # multiline
        @sealed                      # RESPONSE SEALED REQUEST NOT
        Constants.5.0 constants      # RELATIVE REFERENCE
        vendor.nested.Abc.1.2 abc
        """
        ),
    )

    p = parse_definition(
        service,
        [
            abc,
            empty_new,
            empty_old,
            constants,
        ],
    )
    print("Parsed:", p)
    req, res = [x.data_type for x in p.fields]
    assert req.doc == "first header comment here\nmultiline"  # type: ignore
    assert res.doc == "second header comment here\nmultiline"  # type: ignore

    union = wrkspc.parse_new(
        "another/Union.5.9.dsdl",
        dedent(
            """
        @union
        # sandwiched comment has no effect
        @sealed
        truncated float16 PI = 3.1415926535897932384626433
        uint8 a
        vendor.nested.Empty.255.255[5] b
        saturated bool [ <= 255 ] c
        """
        ),
    )

    p = parse_definition(
        union,
        [
            empty_old,
            empty_new,
        ],
    )

    assert p.constants[0].doc == ""


# noinspection PyProtectedMember,PyProtectedMember


def _unittest_error(wrkspc: Workspace) -> None:
    from pytest import raises

    def standalone(rel_path: str, definition: str, allow_unregulated: bool = False) -> _serializable.CompositeType:
        return wrkspc.parse_new(rel_path, definition + "\n").read(
            [], [], lambda *_: None, allow_unregulated
        )  # pragma: no branch

    with raises(_error.InvalidDefinitionError, match="(?i).*port ID.*"):
        standalone("vendor/1000.InvalidRegulatedSubjectID.1.0.dsdl", "uint2 value\n@sealed")

    with raises(_error.InvalidDefinitionError, match="(?i).*port ID.*"):
        standalone("vendor/10.InvalidRegulatedServiceID.1.0.dsdl", "uint2 v1\n@sealed\n---\nint64 v2\n@sealed")

    with raises(_error.InvalidDefinitionError, match="(?i).*subject ID.*"):
        standalone("vendor/100000.InvalidRegulatedSubjectID.1.0.dsdl", "uint2 value\n@sealed")

    with raises(_error.InvalidDefinitionError, match="(?i).*service ID.*"):
        standalone("vendor/1000.InvalidRegulatedServiceID.1.0.dsdl", "uint2 v1\n@sealed\n---\nint64 v2\n@sealed")

    with raises(_error.InvalidDefinitionError, match="(?i).*multiple attributes under the same name.*"):
        standalone("vendor/AttributeNameCollision.1.0.dsdl", "uint2 value\n@sealed\nint64 value")

    with raises(_error.InvalidDefinitionError, match="(?i).*tagged union cannot contain fewer than.*"):
        standalone("vendor/SmallUnion.1.0.dsdl", "@union\nuint2 value\n@sealed")

    assert (
        standalone("vendor/invalid_constant_value/A.1.0.dsdl", "bool BOOLEAN = false\n@sealed").constants[0].name
        == "BOOLEAN"
    )
    with raises(_error.InvalidDefinitionError, match=".*Invalid value for boolean constant.*"):
        standalone("vendor/invalid_constant_value/A.1.0.dsdl", "bool BOOLEAN = 0\n@extent 0")  # Should be false

    with raises(_error.InvalidDefinitionError, match=".*undefined_identifier.*"):
        standalone("vendor/invalid_constant_value/A.1.0.dsdl", "bool BOOLEAN = undefined_identifier\n@extent 0")

    with raises(_parser.DSDLSyntaxError):
        standalone("vendor/invalid_constant_value/A.1.0.dsdl", "bool BOOLEAN = -\n@extent 0")

    with raises(_error.InvalidDefinitionError, match="(?i).*exceeds the range.*"):
        standalone("vendor/invalid_constant_value/A.1.0.dsdl", "uint10 INTEGRAL = 2000\n@extent 0")

    with raises(_error.InvalidDefinitionError, match="(?i).*character.*"):
        standalone("vendor/invalid_constant_value/A.1.0.dsdl", "uint8 CH = '\u0451'\n@extent 0")

    with raises(_error.InvalidDefinitionError, match=".*uint8.*"):
        standalone("vendor/invalid_constant_value/A.1.0.dsdl", "uint9 CH = 'q'\n@extent 0")

    with raises(_error.InvalidDefinitionError, match=".*uint8.*"):
        standalone("vendor/invalid_constant_value/A.1.0.dsdl", "int8 CH = 'q'\n@extent 0")

    with raises(_error.InvalidDefinitionError, match=".*integer constant.*"):
        standalone("vendor/invalid_constant_value/A.1.0.dsdl", "int8 CH = 1.1\n@extent 0")

    with raises(_error.InvalidDefinitionError, match="(?i).*type.*"):
        standalone("vendor/invalid_constant_value/A.1.0.dsdl", "float32 CH = true\n@extent 0")

    with raises(_error.InvalidDefinitionError, match="(?i).*type.*"):
        standalone("vendor/invalid_constant_value/A.1.0.dsdl", "float32 CH = 't'\n@extent 0")

    with raises(_parser.DSDLSyntaxError):
        standalone("vendor/syntax_error/A.1.0.dsdl", "bool array[10]\n@sealed")

    with raises(_error.InvalidDefinitionError, match="(?i).*array capacity.*"):
        standalone("vendor/array_size/A.1.0.dsdl", "bool[0] array\n@sealed")

    with raises(_error.InvalidDefinitionError, match="(?i).*array capacity.*"):
        standalone("vendor/array_size/A.1.0.dsdl", "bool[<1] array\n@sealed")

    with raises(_error.InvalidDefinitionError, match="(?i).*array capacity.*"):
        standalone("vendor/array_size/A.1.0.dsdl", "bool[true] array\n@sealed")

    with raises(_error.InvalidDefinitionError, match="(?i).*array capacity.*"):
        standalone("vendor/array_size/A.1.0.dsdl", 'bool["text"] array\n@sealed')

    with raises(_error.InvalidDefinitionError, match="(?i).*service response marker.*"):
        standalone(
            "vendor/service/A.1.0.dsdl",
            "bool request\n@sealed\n---\nbool response\n@sealed\n---\nbool again\n@sealed",
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*unknown directive.*"):
        standalone("vendor/directive/A.1.0.dsdl", "@sho_tse_take\n@sealed")

    with raises(_error.InvalidDefinitionError, match="(?i).*requires an expression.*"):
        standalone("vendor/directive/A.1.0.dsdl", "@assert\n@sealed")

    with raises(_error.InvalidDefinitionError, match="(?i).*does not expect an expression.*"):
        standalone("vendor/directive/A.1.0.dsdl", "@union true || false\n@sealed")

    with raises(_error.InvalidDefinitionError, match="(?i).*does not expect an expression.*"):
        standalone("vendor/directive/A.1.0.dsdl", "@deprecated true || false\n@sealed")

    with raises(_error.InvalidDefinitionError, match="(?i).*version number.*"):
        standalone("vendor/version/A.0.0.dsdl", "@sealed")

    with raises(_error.InvalidDefinitionError, match="(?i).*version number.*"):
        standalone("vendor/version/A.0.256.dsdl", "@sealed")

    with raises(_dsdl_definition.FileNameFormatError):
        standalone("vendor/version/A.0..256.dsdl", "@sealed")

    with raises(_error.InvalidDefinitionError, match="(?i).*version number.*"):
        standalone("vendor/version/A.256.0.dsdl", "@sealed")

    with raises(_parser.DSDLSyntaxError):
        standalone("vendor/types/A.1.0.dsdl", "truncated uavcan.node.Heartbeat.1.0 field\n@sealed")

    with raises(_serializable._primitive.InvalidCastModeError):
        standalone("vendor/types/A.1.0.dsdl", "truncated bool foo\n@sealed")

    with raises(_serializable._primitive.InvalidCastModeError):
        standalone("vendor/types/A.1.0.dsdl", "truncated int8 foo\n@sealed")

    with raises(_data_type_builder.UndefinedDataTypeError, match=r"(?i).*nonexistent.TypeName.*1\.0.*"):
        standalone("vendor/types/A.1.0.dsdl", "nonexistent.TypeName.1.0 field\n@sealed")

    with raises(_data_type_builder.UndefinedDataTypeError, match=r"(?i).*vendor[/\\]+types instead of .*vendor.*"):
        standalone("vendor/types/A.1.0.dsdl", "types.Nonexistent.1.0 field\n@sealed")

    with raises(_error.InvalidDefinitionError, match=r"(?i).*not defined for.*"):
        standalone(
            "vendor/types/A.1.0.dsdl",
            dedent(
                """
                   @union
                   int8 a
                   @assert _offset_.count >= 1
                   int16 b
                   @sealed
                   """
            ),
        )

    with raises(_error.InvalidDefinitionError, match=r"(?i).*field offset is not defined for unions.*"):
        standalone(
            "vendor/types/A.1.0.dsdl",
            dedent(
                """
                   @union
                   int8 a
                   int16 b
                   @assert _offset_.count >= 1
                   int8 c
                   @sealed
                   """
            ),
        )

    with raises(_data_type_builder.UndefinedDataTypeError, match=r".*ns.Type_.*1\.0"):
        parse_definition(
            wrkspc.parse_new("vendor/types/A.1.0.dsdl", "ns.Type_.1.0 field\n@sealed"),
            [
                wrkspc.parse_new("ns/Type_.2.0.dsdl", "@sealed"),
            ],
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*Bit length cannot exceed.*"):
        parse_definition(
            wrkspc.parse_new("vendor/types/A.1.0.dsdl", "int128 field\n@sealed"),
            [
                wrkspc.parse_new("ns/Type_.2.0.dsdl", "@sealed"),
                wrkspc.parse_new("ns/Type_.1.1.dsdl", "@sealed"),
            ],
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*type.*"):
        parse_definition(
            wrkspc.parse_new("vendor/invalid_constant_value/A.1.0.dsdl", "ns.Type_.1.1 VALUE = 123\n@sealed"),
            [
                wrkspc.parse_new("ns/Type_.2.0.dsdl", "@sealed"),
                wrkspc.parse_new("ns/Type_.1.1.dsdl", "@sealed"),
            ],
        )

    with raises(_data_type_builder.UndefinedDataTypeError):
        defs = [
            wrkspc.parse_new("vendor/circular_dependency/A.1.0.dsdl", "B.1.0 b\n@sealed"),
            wrkspc.parse_new("vendor/circular_dependency/B.1.0.dsdl", "A.1.0 b\n@sealed"),
        ]
        parse_definition(defs[0], defs)

    with raises(_error.InvalidDefinitionError, match="(?i).*union directive.*"):
        parse_definition(
            wrkspc.parse_new("vendor/misplaced_directive/A.1.0.dsdl", "ns.Type_.2.0 field\n@union\n@sealed"),
            [
                wrkspc.parse_new("ns/Type_.2.0.dsdl", "@sealed"),
            ],
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*deprecated directive.*"):
        parse_definition(
            wrkspc.parse_new("vendor/misplaced_directive/A.1.0.dsdl", "ns.Type_.2.0 field\n@deprecated\n@sealed"),
            [
                wrkspc.parse_new("ns/Type_.2.0.dsdl", "@sealed"),
            ],
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*deprecated directive.*"):
        parse_definition(
            wrkspc.parse_new(
                "vendor/misplaced_directive/A.1.0.dsdl", "ns.Type_.2.0 field\n@sealed\n---\n@deprecated\n@sealed"
            ),
            [
                wrkspc.parse_new("ns/Type_.2.0.dsdl", "@sealed"),
            ],
        )

    try:
        standalone(
            "vendor/types/A.1.0.dsdl",
            dedent(
                """
                   int8 a  # Comment
                   # Empty
                   @assert false  # Will error here, line number 4
                   # Blank
                   @sealed
                   """
            ),
        )
    except _error.FrontendError as ex:
        assert ex.path and ex.path.parts[-3:] == ("vendor", "types", "A.1.0.dsdl")
        assert ex.line and ex.line == 4
    else:  # pragma: no cover
        assert False

    standalone("vendor/types/1.A.1.0.dsdl", "@sealed", allow_unregulated=True)
    with raises(_data_type_builder.UnregulatedFixedPortIDError, match=r".*allow_unregulated_fixed_port_id.*"):
        standalone("vendor/types/1.A.1.0.dsdl", "@sealed")

    standalone("vendor/types/1.A.1.0.dsdl", "@sealed\n---\n@sealed", allow_unregulated=True)
    with raises(_data_type_builder.UnregulatedFixedPortIDError, match=r".*allow_unregulated_fixed_port_id.*"):
        standalone("vendor/types/1.A.1.0.dsdl", "@sealed\n---\n@sealed")

    with raises(_error.InvalidDefinitionError, match="(?i).*seal.*"):
        standalone(
            "vendor/sealing/A.1.0.dsdl",
            dedent(
                """
                   int8 a
                   @extent 128
                   @sealed
                   """
            ),
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*extent.*"):
        standalone(
            "vendor/sealing/A.1.0.dsdl",
            dedent(
                """
                   int8 a
                   @sealed
                   @extent 128
                   """
            ),
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*sealed.*expression.*"):
        standalone(
            "vendor/sealing/A.1.0.dsdl",
            dedent(
                """
                   int8 a
                   @sealed 12345678
                   """
            ),
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*extent.*expression.*"):
        standalone(
            "vendor/sealing/A.1.0.dsdl",
            dedent(
                """
                   int8 a
                   @extent
                   """
            ),
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*extent.*"):
        standalone(
            "vendor/sealing/A.1.0.dsdl",
            dedent(
                """
                   int16 a
                   @extent 8  # Too small
                   """
            ),
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*extent.*"):
        standalone(
            "vendor/sealing/A.1.0.dsdl",
            dedent(
                """
                   int16 a
                   @extent {16}  # Wrong type
                   """
            ),
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*extent.*"):
        standalone(
            "vendor/sealing/A.1.0.dsdl",
            dedent(
                """
                   int16 a
                   @extent 64
                   int8 b
                   """
            ),
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*extent.*"):  # Neither extent nor sealed are specified.
        standalone(
            "vendor/sealing/A.1.0.dsdl",
            dedent(
                """
                   int16 a
                   int8 b
                   """
            ),
        )


def _unittest_print(wrkspc: Workspace) -> None:
    printed_items = None  # type: tuple[int, str] | None

    def print_handler(line_number: int, text: str) -> None:
        nonlocal printed_items
        printed_items = line_number, text

    wrkspc.parse_new(
        "ns/A.1.0.dsdl",
        "# line number 1\n" "# line number 2\n" "@print 2 + 2 == 4   # line number 3\n" "# line number 4\n" "@sealed\n",
    ).read([], [], print_handler, False)

    assert printed_items
    assert printed_items[0] == 3
    assert printed_items[1] == "true"

    wrkspc.parse_new("ns/B.1.0.dsdl", "@print false\n@sealed").read([], [], print_handler, False)
    assert printed_items
    assert printed_items[0] == 1
    assert printed_items[1] == "false"

    wrkspc.parse_new(
        "ns/Offset.1.0.dsdl", "@print _offset_    # Not recorded\n" "uint8 a\n" "@print _offset_\n" "@extent 800\n"
    ).read([], [], print_handler, False)
    assert printed_items
    assert printed_items[0] == 3
    assert printed_items[1] == "{8}"


# noinspection PyProtectedMember


def _unittest_assert(wrkspc: Workspace) -> None:
    from pytest import raises

    parse_definition(
        wrkspc.parse_new(
            "ns/A.1.0.dsdl",
            dedent(
                """
            @assert _offset_ == {0}
            @assert _offset_.min == _offset_.max
            Array.1.0[2] bar
            @assert _offset_ == {16, 24, 32, 40, 48}
            @assert _offset_.min == 16
            @assert _offset_.max == 48
            @assert _offset_ % 8 == {0}
            @assert _offset_ % 10 == {6, 4, 2, 0, 8}
            @assert _offset_ * 2 == {32, 48, 64, 80, 96}
            @assert 2 * _offset_ == {32, 48, 64, 80, 96}
            @assert _offset_ / 4 == {4, 6, 8, 10, 12}
            @assert _offset_ - 4 == {12, 20, 28, 36, 44}
            @assert _offset_ + 4 == {20, 28, 36, 44, 52}
            uint64 big
            @assert _offset_ - 64 == {16, 24, 32, 40, 48}
            @assert _offset_.min == 80
            @assert _offset_.max == 112
            @assert _offset_.max <= 112
            @assert _offset_.max < 113
            @assert _offset_ == _offset_
            @assert truncated uint64._bit_length_ == {64}
            @assert uint64._bit_length_ == {64}
            @assert Array.1.0._bit_length_.max == 8 + 8 + 8
            @assert Array.1.0._extent_ == 8 + 8 + 8
            @assert Array.1.0._extent_ == Array.1.0._bit_length_.max
            @sealed
            """
            ),
        ),
        [wrkspc.parse_new("ns/Array.1.0.dsdl", "uint8[<=2] foo\n@sealed")],
    )

    with raises(_error.InvalidDefinitionError, match="(?i).*operator is not defined.*"):
        parse_definition(
            wrkspc.parse_new(
                "ns/C.1.0.dsdl",
                dedent(
                    """
                uint64 big
                @assert _offset_ == 64
                @sealed
                """
                ),
            ),
            [],
        )

    with raises(_expression.UndefinedAttributeError):
        parse_definition(
            wrkspc.parse_new("ns/C.1.0.dsdl", "@print Service.1.0._bit_length_"),
            [wrkspc.parse_new("ns/Service.1.0.dsdl", "uint8 a\n@sealed\n---\nuint16 b\n@sealed")],
        )

    with raises(_expression.UndefinedAttributeError):
        parse_definition(
            wrkspc.parse_new("ns/C.1.0.dsdl", """uint64 LENGTH = uint64.nonexistent_attribute\n@extent 0"""), []
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*void.*"):
        parse_definition(wrkspc.parse_new("ns/C.1.0.dsdl", "void2 name\n@sealed"), [])

    with raises(_serializable._attribute.InvalidConstantValueError):
        parse_definition(wrkspc.parse_new("ns/C.1.0.dsdl", "int8 name = true\n@sealed"), [])

    with raises(_error.InvalidDefinitionError, match=".*value.*"):
        parse_definition(wrkspc.parse_new("ns/C.1.0.dsdl", "int8 name = {1, 2, 3}\n@sealed"), [])

    parse_definition(
        wrkspc.parse_new(
            "ns/D.1.0.dsdl",
            dedent(
                """
            @union
            float32 a
            uint64 b
            @assert _offset_ == {40, 72}
            @sealed
            """
            ),
        ),
        [],
    )

    parse_definition(
        wrkspc.parse_new(
            "ns/E.1.0.dsdl",
            dedent(
                """
            @union
            uint8 A = 0
            float32 a
            uint8 B = 1
            uint64 b
            uint8 C = 2
            @assert _offset_ == {40, 72}
            uint8 D = 3
            @sealed
            """
            ),
        ),
        [],
    )

    with raises(_error.InvalidDefinitionError):
        parse_definition(
            wrkspc.parse_new(
                "ns/F.1.0.dsdl",
                dedent(
                    """
                @union
                @assert _offset_.min == 33
                float32 a
                uint64 b
                @assert _offset_ == {40, 72}
                @sealed
                """
                ),
            ),
            [],
        )

    with raises(_data_type_builder.AssertionCheckFailureError):
        parse_definition(
            wrkspc.parse_new(
                "ns/G.1.0.dsdl",
                dedent(
                    """
                float32 a
                @assert _offset_.min == 8
                @sealed
                """
                ),
            ),
            [],
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*yield a boolean.*"):
        parse_definition(
            wrkspc.parse_new(
                "ns/H.1.0.dsdl",
                dedent(
                    """
                float32 a
                @assert _offset_.min
                @sealed
                """
                ),
            ),
            [],
        )

    # Extent verification
    parse_definition(
        wrkspc.parse_new(
            "ns/I.1.0.dsdl",
            dedent(
                """
            @assert J.1.0._extent_ == 64
            @assert J.1.0._bit_length_ == {0, 1, 2, 3, 4, 5, 6, 7, 8} * 8 + 32
            @assert K.1.0._extent_ == 8
            @assert K.1.0._bit_length_ == {8}
            @sealed
            """
            ),
        ),
        [
            wrkspc.parse_new("ns/J.1.0.dsdl", "uint8 foo\n@extent 64"),
            wrkspc.parse_new("ns/K.1.0.dsdl", "uint8 foo\n@sealed"),
        ],
    )

    # Alignment
    parse_definition(
        wrkspc.parse_new(
            "ns/L.1.0.dsdl",
            dedent(
                """
            @assert _offset_ == {0}
            uint3 a
            @assert _offset_ == {3}
            N.1.0 nothing
            @print _offset_
            @assert _offset_ == {8}   # Aligned!
            uint5 b
            @assert _offset_ == {13}
            N.1.0[3] array_of_nothing
            @assert _offset_ == {16}  # Aligned!
            bool c
            @assert _offset_ == {17}
            M.1.0 variable
            @assert _offset_ == 32 + {24, 32, 40}  # Aligned; variability due to extensibility (non-sealing)
            @sealed
            """
            ),
        ),
        [
            wrkspc.parse_new("ns/M.1.0.dsdl", "@extent 16"),
            wrkspc.parse_new("ns/N.1.0.dsdl", "@sealed"),
        ],
    )


def _unittest_parse_namespace(wrkspc: Workspace) -> None:
    from pytest import raises

    print_output = None  # type: tuple[str, int, str] | None

    def print_handler(d: Path, line: int, text: str) -> None:
        nonlocal print_output
        print_output = str(d), line, text

    # Empty namespace.
    assert [] == _namespace.read_namespace(wrkspc.directory)

    wrkspc.new(
        "zubax/First.1.0.dsdl",
        dedent(
            """
        uint8[<256] a
        @assert _offset_.min == 8
        @assert _offset_.max == 2048
        @sealed
        """
        ),
    )

    wrkspc.new(
        "zubax/7001.Message.1.0.dsdl",
        dedent(
            """
        zubax.First.1.0[<=2] a
        @assert _offset_.min == 8
        @assert _offset_.max == 4104
        @extent _offset_.max * 8
        """
        ),
    )

    wrkspc.new(
        "zubax/nested/300.Spartans.30.0.dsdl",
        dedent(
            """
        @deprecated
        @union
        float16 small
        float32 just_right
        float64 woah
        @extent _offset_.max * 8
        ---
        @print _offset_     # Will print zero {0}
        @sealed
        """
        ),
    )

    wrkspc.new("zubax/nested/300.Spartans.30.0.txt", "completely unrelated stuff")
    wrkspc.new("zubax/300.Spartans.30.0", "completely unrelated stuff")

    parsed = _namespace.read_namespace(
        wrkspc.directory / "zubax",
        [Path(wrkspc.directory, "zubax", ".")],  # Intentional duplicate
        print_handler,
    )
    print(parsed)
    assert len(parsed) == 3
    assert "zubax.First" in [x.full_name for x in parsed]
    assert "zubax.Message" in [x.full_name for x in parsed]
    assert "zubax.nested.Spartans" in [x.full_name for x in parsed]

    # try again with minimal arguments to read_namespace
    parsed_minimal_args = _namespace.read_namespace(wrkspc.directory / "zubax")
    assert len(parsed_minimal_args) == 3

    wrkspc.new(
        "zubax/colliding/300.Iceberg.30.0.dsdl",
        dedent(
            """
        @extent 1024
        ---
        @extent 1024
        """
        ),
    )

    with raises(_namespace.FixedPortIDCollisionError):
        _namespace.read_namespace(wrkspc.directory / "zubax", [], print_handler)

    with raises(TypeError):  # Invalid usage: expected path-like object, not bytes.
        _namespace.read_namespace(wrkspc.directory / "zubax", b"/my/path")  # type: ignore

    with raises(TypeError):  # Invalid usage: expected path-like object, not bytes.
        # noinspection PyTypeChecker
        _namespace.read_namespace(wrkspc.directory / "zubax", [b"/my/path"])  # type: ignore

    assert print_output is not None
    assert "300.Spartans" in print_output[0]
    assert print_output[1] == 9
    assert print_output[2] == "{0}"

    wrkspc.new(
        "zubax/colliding/iceberg/300.Ice.30.0.dsdl",
        dedent(
            """
        @sealed
        ---
        @sealed
        """
        ),
    )
    with raises(_namespace.DataTypeNameCollisionError):
        _namespace.read_namespace(
            wrkspc.directory / "zubax",
            [
                wrkspc.directory / "zubax",
            ],
        )

    # Do again to test single lookup-directory override
    with raises(_namespace.DataTypeNameCollisionError):
        _namespace.read_namespace(wrkspc.directory / "zubax", wrkspc.directory / "zubax")

    try:
        (wrkspc.directory / "zubax/colliding/iceberg/300.Ice.30.0.dsdl").unlink()
        wrkspc.new(
            "zubax/COLLIDING/300.Iceberg.30.0.dsdl",
            dedent(
                """
            @extent 1024
            ---
            @extent 1024
            """
            ),
        )
        with raises(_namespace.DataTypeNameCollisionError, match=".*letter case.*"):
            _namespace.read_namespace(
                wrkspc.directory / "zubax",
                [
                    wrkspc.directory / "zubax",
                ],
            )
    except _namespace.FixedPortIDCollisionError:  # pragma: no cover
        pass  # We're running on a platform where paths are not case-sensitive.

    # Test namespace can intersect with type name
    (wrkspc.directory / "zubax/COLLIDING/300.Iceberg.30.0.dsdl").unlink()
    try:
        ((wrkspc.directory / "zubax/colliding/300.Iceberg.30.0.dsdl")).unlink()
    except FileNotFoundError:  # pragma: no cover
        pass  # We're running on a platform where paths are not case-sensitive.
    wrkspc.new(
        "zubax/noncolliding/iceberg/Ice.1.0.dsdl",
        dedent(
            """
        @extent 1024
        ---
        @extent 1024
        """
        ),
    )
    wrkspc.new(
        "zubax/noncolliding/Iceb.1.0.dsdl",
        dedent(
            """
        @extent 1024
        ---
        @extent 1024
        """
        ),
    )
    parsed = _namespace.read_namespace(wrkspc.directory / "zubax", wrkspc.directory / "zubax")
    assert "zubax.noncolliding.iceberg.Ice" in [x.full_name for x in parsed]
    assert "zubax.noncolliding.Iceb" in [x.full_name for x in parsed]


def _unittest_parse_namespace_versioning(wrkspc: Workspace) -> None:
    from pytest import raises

    wrkspc.new(
        "ns/Spartans.30.0.dsdl",
        dedent(
            """
        @deprecated
        @union
        float16 small
        float32 just_right
        float64 woah
        @extent 1024
        ---
        @extent 1024
        """
        ),
    )

    wrkspc.new(
        "ns/Spartans.30.1.dsdl",
        dedent(
            """
        @deprecated
        @union
        uint16 small
        int32 just_right
        float64[1] woah
        @extent 1024
        ---
        @extent 1024
        """
        ),
    )

    parsed = _namespace.read_namespace((wrkspc.directory / "ns"), [])
    print(parsed)
    assert len(parsed) == 2

    wrkspc.new(
        "ns/Spartans.30.2.dsdl",
        dedent(
            """
        @deprecated
        @union
        uint16 small
        int32 just_right
        float64[1] woah
        @extent 1024
        """
        ),
    )

    with raises(_namespace.VersionsOfDifferentKindError):
        _namespace.read_namespace((wrkspc.directory / "ns"), [])

    wrkspc.drop("ns/Spartans.30.[01].dsdl")

    wrkspc.new(
        "ns/Spartans.30.0.dsdl",
        dedent(
            """
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        @extent 1024
        """
        ),
    )

    parsed = _namespace.read_namespace((wrkspc.directory / "ns"), [])
    print(parsed)
    assert len(parsed) == 2

    wrkspc.new(
        "ns/Spartans.30.1.dsdl",
        dedent(
            """
        @deprecated
        @union
        uint16 small
        float32 just_right
        int64 woah
        @extent 1024
        """
        ),
    )

    wrkspc.new(
        "ns/6700.Spartans.30.2.dsdl",
        dedent(
            """
        @deprecated
        @union
        uint16 small
        int32 just_right
        float64[1] woah
        @extent 1024
        """
        ),
    )

    with raises(_namespace.DataTypeCollisionError):
        _namespace.read_namespace((wrkspc.directory / "ns"), [])

    wrkspc.drop("ns/Spartans.30.2.dsdl")

    parsed = _namespace.read_namespace((wrkspc.directory / "ns"), [])
    assert len(parsed) == 3

    wrkspc.drop("ns/Spartans.30.0.dsdl")
    wrkspc.new(
        "ns/6700.Spartans.30.0.dsdl",
        dedent(
            """
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        @extent 1024
        """
        ),
    )

    with raises(_namespace.MinorVersionFixedPortIDError):
        _namespace.read_namespace((wrkspc.directory / "ns"), [])

    wrkspc.drop("ns/Spartans.30.1.dsdl")
    wrkspc.new(
        "ns/6700.Spartans.30.1.dsdl",
        dedent(
            """
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        @extent 1024
        """
        ),
    )

    parsed = _namespace.read_namespace((wrkspc.directory / "ns"), [])
    assert len(parsed) == 3

    wrkspc.drop("ns/6700.Spartans.30.1.dsdl")
    wrkspc.new(
        "ns/6701.Spartans.30.1.dsdl",
        dedent(
            """
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        @extent 1024
        """
        ),
    )

    with raises(_namespace.MinorVersionFixedPortIDError):
        _namespace.read_namespace((wrkspc.directory / "ns"), [])

    # Adding new major version under the same FPID
    wrkspc.drop("ns/6701.Spartans.30.1.dsdl")
    wrkspc.new(
        "ns/6700.Spartans.31.0.dsdl",
        dedent(
            """
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        @extent 1024
        """
        ),
    )

    with raises(_namespace.FixedPortIDCollisionError):
        _namespace.read_namespace((wrkspc.directory / "ns"), [])

    # Major version zero allows us to re-use the same FPID under a different (non-zero) major version
    wrkspc.drop("ns/6700.Spartans.31.0.dsdl")
    wrkspc.new(
        "ns/6700.Spartans.0.1.dsdl",
        dedent(
            """
        @deprecated
        @union
        uint16 small
        float32 just_right
        float64[1] woah
        @extent 1024
        """
        ),
    )

    # These are needed to ensure full branch coverage, see the checking code.
    wrkspc.new("ns/Empty.1.0.dsdl", "@extent 0")
    wrkspc.new("ns/Empty.1.1.dsdl", "@extent 0")
    wrkspc.new("ns/Empty.2.0.dsdl", "@extent 0")
    wrkspc.new("ns/6800.Empty.3.0.dsdl", "@extent 0")
    wrkspc.new("ns/6801.Empty.4.0.dsdl", "@extent 0")

    parsed = _namespace.read_namespace((wrkspc.directory / "ns"), [])  # no error
    assert len(parsed) == 8

    # Check ordering - the definitions must be sorted properly by name (lexicographically) and version (newest first).
    assert list(map(str, parsed)) == [
        "ns.Empty.4.0",  # Newest first
        "ns.Empty.3.0",
        "ns.Empty.2.0",
        "ns.Empty.1.1",
        "ns.Empty.1.0",
        "ns.Spartans.30.2",  # Newest first
        "ns.Spartans.30.0",
        "ns.Spartans.0.1",
    ]

    # Extent consistency -- non-service type
    wrkspc.new("ns/Consistency.1.0.dsdl", "uint8 a\n@extent 128")
    wrkspc.new("ns/Consistency.1.1.dsdl", "uint8 a\nuint8 b\n@extent 128")
    parsed = _namespace.read_namespace((wrkspc.directory / "ns"), [])  # no error
    assert len(parsed) == 10
    wrkspc.new("ns/Consistency.1.2.dsdl", "uint8 a\nuint8 b\nuint8 c\n@extent 256")
    with raises(
        _namespace.ExtentConsistencyError, match=r"(?i).*extent of ns\.Consistency\.1\.2 is 256 bits.*"
    ) as ei_extent:
        _namespace.read_namespace((wrkspc.directory / "ns"), [])
    print(ei_extent.value)
    assert ei_extent.value.path and "Consistency.1" in str(ei_extent.value.path)
    wrkspc.drop("ns/Consistency*")

    # Extent consistency -- non-service type, zero major version
    wrkspc.new("ns/Consistency.0.1.dsdl", "uint8 a\n@extent 128")
    wrkspc.new("ns/Consistency.0.2.dsdl", "uint8 a\nuint8 b\n@extent 128")
    parsed = _namespace.read_namespace((wrkspc.directory / "ns"), [])  # no error
    assert len(parsed) == 10
    wrkspc.new("ns/Consistency.0.3.dsdl", "uint8 a\nuint8 b\nuint8 c\n@extent 256")  # no error
    _namespace.read_namespace((wrkspc.directory / "ns"), [])
    wrkspc.drop("ns/Consistency*")

    # Extent consistency -- request
    wrkspc.new(
        "ns/Consistency.1.0.dsdl",
        dedent(
            """
            uint8 a
            @extent 128
            ---
            uint8 a
            @extent 128
            """
        ),
    )
    wrkspc.new(
        "ns/Consistency.1.1.dsdl",
        dedent(
            """
            uint8 a
            uint8 b
            @extent 128
            ---
            uint8 a
            @extent 128
            """
        ),
    )
    parsed = _namespace.read_namespace((wrkspc.directory / "ns"), [])  # no error
    assert len(parsed) == 10
    wrkspc.new(
        "ns/Consistency.1.2.dsdl",
        dedent(
            """
            uint8 a
            uint8 b
            @extent 256
            ---
            uint8 a
            @extent 128
            """
        ),
    )
    with raises(
        _namespace.ExtentConsistencyError, match=r"(?i).*extent of ns\.Consistency.* is 256 bits.*"
    ) as ei_extent:
        _namespace.read_namespace((wrkspc.directory / "ns"), [])
    print(ei_extent.value)
    assert ei_extent.value.path and "Consistency.1" in str(ei_extent.value.path)
    wrkspc.drop("ns/Consistency*")

    # Extent consistency -- response
    wrkspc.new(
        "ns/Consistency.1.0.dsdl",
        dedent(
            """
            uint8 a
            @extent 128
            ---
            uint8 a
            @extent 128
            """
        ),
    )
    wrkspc.new(
        "ns/Consistency.1.1.dsdl",
        dedent(
            """
            uint8 a
            @extent 128
            ---
            uint8 a
            uint8 b
            @extent 128
            """
        ),
    )
    parsed = _namespace.read_namespace((wrkspc.directory / "ns"), [])  # no error
    assert len(parsed) == 10
    wrkspc.new(
        "ns/Consistency.1.2.dsdl",
        dedent(
            """
            uint8 a
            @extent 128
            ---
            uint8 a
            @extent 256
            """
        ),
    )
    with raises(
        _namespace.ExtentConsistencyError, match=r"(?i).*extent of ns\.Consistency.* is 256 bits.*"
    ) as ei_extent:
        _namespace.read_namespace((wrkspc.directory / "ns"), [])
    print(ei_extent.value)
    assert ei_extent.value.path and "Consistency.1" in str(ei_extent.value.path)
    wrkspc.drop("ns/Consistency*")

    # Sealing consistency -- non-service type
    wrkspc.new("ns/Consistency.1.0.dsdl", "uint64 a\n@extent 64")
    wrkspc.new("ns/Consistency.1.1.dsdl", "uint64 a\n@extent 64")
    parsed = _namespace.read_namespace((wrkspc.directory / "ns"), [])  # no error
    assert len(parsed) == 10
    wrkspc.new("ns/Consistency.1.2.dsdl", "uint64 a\n@sealed")
    with raises(_namespace.SealingConsistencyError, match=r"(?i).*ns\.Consistency\.1\.2 is sealed.*") as ei_sealing:
        _namespace.read_namespace((wrkspc.directory / "ns"), [])
    print(ei_sealing.value)
    assert ei_sealing.value.path and "Consistency.1" in str(ei_sealing.value.path)
    wrkspc.drop("ns/Consistency*")

    # Sealing consistency -- request
    wrkspc.new(
        "ns/Consistency.1.0.dsdl",
        dedent(
            """
            uint64 a
            @extent 64
            ---
            uint64 a
            @extent 64
            """
        ),
    )
    wrkspc.new(
        "ns/Consistency.1.1.dsdl",
        dedent(
            """
            uint64 a
            @extent 64
            ---
            uint64 a
            @extent 64
            """
        ),
    )
    parsed = _namespace.read_namespace((wrkspc.directory / "ns"), [])  # no error
    assert len(parsed) == 10
    wrkspc.new(
        "ns/Consistency.1.2.dsdl",
        dedent(
            """
            uint64 a
            @sealed
            ---
            uint64 a
            @extent 64
            """
        ),
    )
    with raises(_namespace.SealingConsistencyError, match=r"(?i).*ns\.Consistency.* is sealed.*") as ei_sealing:
        _namespace.read_namespace((wrkspc.directory / "ns"), [])
    print(ei_sealing.value)
    assert ei_sealing.value.path and "Consistency.1" in str(ei_sealing.value.path)
    wrkspc.drop("ns/Consistency*")

    # Sealing consistency -- response
    wrkspc.new(
        "ns/Consistency.1.0.dsdl",
        dedent(
            """
            uint64 a
            @extent 64
            ---
            uint64 a
            @extent 64
            """
        ),
    )
    wrkspc.new(
        "ns/Consistency.1.1.dsdl",
        dedent(
            """
            uint64 a
            @extent 64
            ---
            uint64 a
            @extent 64
            """
        ),
    )
    parsed = _namespace.read_namespace((wrkspc.directory / "ns"), [])  # no error
    assert len(parsed) == 10
    wrkspc.new(
        "ns/Consistency.1.2.dsdl",
        dedent(
            """
            uint64 a
            @extent 64
            ---
            uint64 a
            @sealed
            """
        ),
    )
    with raises(_namespace.SealingConsistencyError, match=r"(?i).*ns\.Consistency.* is sealed.*") as ei_sealing:
        _namespace.read_namespace((wrkspc.directory / "ns"), [])
    print(ei_sealing.value)
    assert ei_sealing.value.path and "Consistency.1" in str(ei_sealing.value.path)
    wrkspc.drop("ns/Consistency*")


def _unittest_issue94(wrkspc: Workspace) -> None:
    from pytest import raises

    wrkspc.new("outer_a/ns/Foo.1.0.dsdl", "@sealed")
    wrkspc.new("outer_b/ns/Foo.1.0.dsdl", "@sealed")  # Conflict!
    wrkspc.new("outer_a/ns/Bar.1.0.dsdl", "Foo.1.0 fo\n@sealed")  # Which Foo.1.0?

    with raises(_namespace.DataTypeCollisionError):
        _namespace.read_namespace(
            wrkspc.directory / "outer_a" / "ns",
            [wrkspc.directory / "outer_b" / "ns"],
        )

    wrkspc.drop("outer_b/ns/Foo.1.0.dsdl")  # Clear the conflict.
    defs = _namespace.read_namespace(
        wrkspc.directory / "outer_a" / "ns",
        [wrkspc.directory / "outer_b" / "ns"],
    )
    assert len(defs) == 2


def _unittest_parse_namespace_faults() -> None:
    from pytest import raises

    with tempfile.TemporaryDirectory() as tmp_dir:
        di = Path(tmp_dir)
        (di / "foo/bar/baz").mkdir(parents=True)
        (di / "bat/wot").mkdir(parents=True)
        (di / "foo/bar/baz/bad").mkdir(parents=True)
        (di / "foo/bar/zoo").mkdir(parents=True)
        (di / "foo/bar/doo/roo/BAZ").mkdir(parents=True)
        (di / "foo/bar/doo/roo/zoo").mkdir(parents=True)
        (di / "foo/bar/doo/roo/baz").mkdir(parents=True, exist_ok=True)
        with raises(_namespace.NestedRootNamespaceError):
            _namespace.read_namespace(
                di / "foo/bar/baz",
                [di / "bat/wot", di / "foo/bar/baz/bad"],
            )
        with raises(_namespace.RootNamespaceNameCollisionError):
            _namespace.read_namespace(
                di / "foo/bar/baz",
                [di / "foo/bar/zoo", di / "foo/bar/doo/roo/BAZ"],  # Notice the letter case
                allow_root_namespace_name_collision=False,
            )
        with raises(_namespace.RootNamespaceNameCollisionError):
            _namespace.read_namespace(
                di / "foo/bar/baz",
                [di / "foo/bar/zoo", di / "foo/bar/doo/roo/zoo", di / "foo/bar/doo/roo/baz"],
                allow_root_namespace_name_collision=False,
            )


def _unittest_inconsistent_deprecation(wrkspc: Workspace) -> None:
    from pytest import raises

    parse_definition(
        wrkspc.parse_new("ns/A.1.0.dsdl", "@sealed"),
        [
            wrkspc.parse_new(
                "ns/B.1.0.dsdl",
                dedent(
                    """
                    @deprecated
                    A.1.0 a
                    @sealed
                    """
                ),
            )
        ],
    )

    with raises(_error.InvalidDefinitionError, match="(?i).*depend.*deprecated.*"):
        parse_definition(
            wrkspc.parse_new(
                "ns/C.1.0.dsdl",
                dedent(
                    """
                X.1.0 b
                @sealed
                """
                ),
            ),
            [wrkspc.parse_new("ns/X.1.0.dsdl", "@deprecated\n@sealed")],
        )

    parse_definition(
        wrkspc.parse_new(
            "ns/D.1.0.dsdl",
            dedent(
                """
                @deprecated
                X.1.0 b
                @sealed
                """
            ),
        ),
        [wrkspc.parse_new("ns/X.1.0.dsdl", "@deprecated\n@sealed")],
    )


def _unittest_repeated_directives(wrkspc: Workspace) -> None:
    from pytest import raises

    parse_definition(
        wrkspc.parse_new(
            "ns/A.1.0.dsdl",
            dedent(
                """
                @union
                @deprecated
                int8 a
                float16 b
                @sealed
                """
            ),
        ),
        [],
    )

    with raises(_error.InvalidDefinitionError, match="(?i).*deprecated.*"):
        parse_definition(
            wrkspc.parse_new(
                "ns/A.1.0.dsdl",
                dedent(
                    """
                    @deprecated
                    @deprecated
                    @sealed
                    """
                ),
            ),
            [],
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*deprecated.*"):
        parse_definition(
            wrkspc.parse_new(
                "ns/A.1.0.dsdl",
                dedent(
                    """
                    @deprecated
                    @sealed
                    ---
                    @deprecated
                    @sealed
                    """
                ),
            ),
            [],
        )

    parse_definition(
        wrkspc.parse_new(
            "ns/A.1.0.dsdl",
            dedent(
                """
                @union
                int8 a
                float16 b
                @sealed
                ---
                @union
                int8 a
                float16 b
                @sealed
                """
            ),
        ),
        [],
    )

    with raises(_error.InvalidDefinitionError, match="(?i).*union.*"):
        parse_definition(
            wrkspc.parse_new(
                "ns/A.1.0.dsdl",
                dedent(
                    """
                    @union
                    @union
                    int8 a
                    float16 b
                    @sealed
                    """
                ),
            ),
            [],
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*sealed.*"):
        parse_definition(
            wrkspc.parse_new(
                "ns/A.1.0.dsdl",
                dedent(
                    """
                    @sealed
                    @sealed
                    int8 a
                    float16 b
                    @sealed
                    """
                ),
            ),
            [],
        )

    with raises(_error.InvalidDefinitionError, match="(?i).*extent.*already set.*"):
        parse_definition(
            wrkspc.parse_new(
                "ns/A.1.0.dsdl",
                dedent(
                    """
                    int8 a
                    float16 b
                    @extent 256
                    @extent 800
                    @sealed
                    """
                ),
            ),
            [],
        )


def _unittest_dsdl_parser_basics(wrkspc: Workspace) -> None:
    # This is how you can run one test only for development needs:
    #   pytest pydsdl -k _unittest_dsdl_parser_basics --capture=no
    # noinspection SpellCheckingInspection
    parse_definition(
        wrkspc.parse_new(
            "ns/A.1.0.dsdl",
            dedent(
                r"""
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
                @extent 32 * 1024 * 8
                """
            ),
        ),
        [
            wrkspc.parse_new("ns/Foo.1.0.dsdl", "int8 THE_CONSTANT = 42\n@extent 1024"),
            wrkspc.parse_new("ns/Bar.1.23.dsdl", "int8 the_field\nint8 A = 0xA\nint8 B = 0xB\n@extent 1024"),
        ],
    )


def _unittest_dsdl_parser_expressions(wrkspc: Workspace) -> None:
    from pytest import raises

    def throws(definition: str, exc: Type[Exception] = _expression.InvalidOperandError) -> None:
        with raises(exc):
            parse_definition(wrkspc.parse_new("ns/Throws.0.1.dsdl", dedent(definition + "\n@sealed")), [])

    throws("bool R = true && 0")
    throws("bool R = true || 0")
    throws("bool R = 0 || true")
    throws("bool R = 0 == true")
    throws("bool R = {0} & true")
    throws("bool R = true ^ {0}")
    throws("bool R = 0 ^ true")
    throws("int8 R = 1 / 0")
    throws('bool R = "S" == 0')
    throws("bool R = {0} != {}")
    throws('bool R = {0, true, "S"}')
    throws('bool R = {0} == {"s"}')
    throws('bool R = {0} <= "s"')
    throws('bool R = {0} >= "s"')
    throws('bool R = {0} > "s"')
    throws('bool R = {0} < "s"')
    throws('bool R = {0} | "s"')
    throws('bool R = {0} & "s"')
    throws('bool R = {0} ^ "s"')
    throws("bool R = {0}.nonexistent_attribute")
    throws("bool R = {0} / {1}")
    throws("bool R = !1")
    throws("bool R = +true")
    throws('bool R = -"1"')
    throws("bool R = true | false")
    throws("bool R = true & false")
    throws('bool R = true + "0"')
    throws('bool R = true - "0"')
    throws('bool R = true * "0"')
    throws('bool R = true / "0"')
    throws('bool R = true % "0"')
    throws('bool R = true ** "0"')

    parse_definition(
        wrkspc.parse_new(
            "ns/A.1.0.dsdl",
            dedent(
                r"""
                float64 PI = 3.141592653589793
                float64 E  = 2.718281828459045
                @assert (PI ** E > 22.4) && (PI ** E < 22.5)
                @assert 'moments of eternity'     != "strangers stealing someone else's dreams"  # I've seen it all
                @assert 'hunting for the mystery' != 'running for your life in times like these' # I've seen it all
                @assert "I remember the time once in a life" != 'oh baby'  # got you here in my head, here in my head
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
                @sealed
                """
            ),
        ),
        [],
    )


def _unittest_pickle(wrkspc: Workspace) -> None:
    import pickle

    p = parse_definition(
        wrkspc.parse_new(
            "ns/A.1.0.dsdl",
            dedent(
                r"""
                float64 PI = 3.141592653589793
                float64 big_pi
                @sealed
                ---
                float16 small_pi
                @extent 1024 * 8
                """
            ),
        ),
        [],
    )
    assert isinstance(p, _serializable.ServiceType)
    assert p.request_type.has_parent_service
    assert p.response_type.has_parent_service
    assert not p.has_parent_service

    pp = pickle.loads(pickle.dumps(p))
    assert isinstance(pp, _serializable.ServiceType)
    assert pp.request_type.has_parent_service
    assert pp.response_type.has_parent_service
    assert not pp.has_parent_service
    assert str(pp) == str(p)
    assert repr(pp) == repr(p)


def _collect_descendants(cls: Type[object]) -> Iterable[Type[object]]:
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
            assert t.__name__ in dir(pydsdl), "Data type %r is not exported" % t
