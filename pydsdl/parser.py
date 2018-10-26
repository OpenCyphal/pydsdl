#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import re
import typing
import logging
from .error import ParseError, InternalError, DSDLSyntaxError, DSDLSemanticError, UndefinedDataTypeError
from .dsdl_definition import DSDLDefinition
from .data_type import BooleanType, SignedIntegerType, UnsignedIntegerType, FloatType, VoidType, DataType
from .data_type import StaticArrayType, DynamicArrayType, CompoundType, UnionType, StructureType, ServiceType
from .data_type import Attribute, Field, PaddingField, Constant, PrimitiveType, Version
from .port_id_ranges import is_valid_regulated_service_id, is_valid_regulated_subject_id
from .regular_grammar_matcher import RegularGrammarMatcher, InvalidGrammarError


_logger = logging.getLogger(__name__)


def parse_definition(definition: DSDLDefinition,
                     lookup_definitions: typing.List[DSDLDefinition]) -> CompoundType:
    pass


def _construct_type(cast_mode: typing.Optional[str],
                    type_name: str,
                    allow_compound: bool,
                    lookup_definitions: typing.List[DSDLDefinition]) -> DataType:
    def get_cast_mode() -> PrimitiveType.CastMode:
        return {
            'truncated': PrimitiveType.CastMode.TRUNCATED,
            'saturated': PrimitiveType.CastMode.SATURATED,
            None:        PrimitiveType.CastMode.SATURATED,
        }[cast_mode]

    def construct_compound(name: str, v_major: int, v_minor: typing.Optional[int]) -> CompoundType:
        if cast_mode is not None:
            raise DSDLSemanticError('Cast mode cannot be specified for compound data types')

        matching_name = list(filter(lambda x: x.name == name, lookup_definitions))
        if not matching_name:
            raise UndefinedDataTypeError('No type named ' + name)

        matching_major = list(filter(lambda x: x.version.major == v_major, matching_name))
        if not matching_major:
            raise UndefinedDataTypeError('No suitable major version of %r could be found. '
                                         'Requested version %d, found: %r' % (name, v_major, matching_name))

        if v_minor is None:
            matching_minor = list(sorted(matching_major, key=lambda d: -d.version.minor))[:1]
            _logger.info('Minor version auto-selection: requested type %s.%d, selected %r among %r',
                         name, v_major, matching_minor[0], matching_major)
        else:
            matching_minor = list(filter(lambda x: x.version.minor == v_minor, matching_major))
            if not matching_minor:
                raise UndefinedDataTypeError('No suitable minor version of %r could be found. '
                                             'Requested minor version %d, found: %r' %
                                             (name, v_minor, matching_major))

        if len(matching_minor) != 1:
            raise InternalError('Unexpected ambiguity: %r' % matching_minor)

        definition = matching_minor[0]
        return parse_definition(definition, lookup_definitions)

    g = RegularGrammarMatcher()
    g.add_rule(r'bool$', lambda: BooleanType(get_cast_mode()))
    g.add_rule(r'void(\d\d?)$', lambda bw: VoidType(int(bw)))
    g.add_rule(r'float(\d\d?)$', lambda bw: FloatType(int(bw), get_cast_mode()))
    g.add_rule(r'int(\d\d?)$', lambda bw: SignedIntegerType(int(bw), get_cast_mode()))
    g.add_rule(r'uint(\d\d?)$', lambda bw: UnsignedIntegerType(int(bw), get_cast_mode()))

    if allow_compound:
        g.add_rule(r'([a-zA-Z0-9_\.]+?)\.(\d+)(?:.(\d+))?$',
                   lambda name, v_mj, v_mn:
                       construct_compound(name, int(v_mj), None if v_mn is None else int(v_mn)))

    try:
        return g.match(type_name)
    except InvalidGrammarError:
        raise DSDLSyntaxError('Invalid type declaration: ' + type_name)


class _AttributeCollection:
    def __init__(self) -> None:
        self.attributes = []   # type: typing.List[Attribute]
        self.is_union = False


class _Parser:
    def __init__(self, lookup_definitions: typing.List[DSDLDefinition]) -> None:
        self._attribute_collections = [_AttributeCollection()]
        self._lookup_definitions = list(lookup_definitions)

        self._grammar = RegularGrammarMatcher()
        self._grammar.add_rule(_REGEXP_SCALAR_FIELD, self._at_scalar_field)
        self._grammar.add_rule(_REGEXP_ARRAY_FIELD, self._at_array_field)
        self._grammar.add_rule(_REGEXP_PADDING_FIELD, self._at_padding_field)
        self._grammar.add_rule(_REGEXP_CONSTANT, self._at_constant)
        self._grammar.add_rule(_REGEXP_SERVICE_RESPONSE_MARKER, self._at_service_response_marker)
        self._grammar.add_rule(_REGEXP_DIRECTIVE, self._at_directive)
        self._grammar.add_rule(_REGEXP_EMPTY, lambda: None)

    def run(self, text: str) -> typing.List[_AttributeCollection]:
        for line_index, line_text in enumerate(text.splitlines(keepends=False)):
            line_number = line_index + 1
            try:
                self._grammar.match(line_text)
            except ParseError as ex:  # pragma: no cover
                ex.set_error_location_if_unknown(line=line_number)
                raise
            except Exception as ex:  # pragma: no cover
                raise InternalError(culprit=ex, line=line_number)

        pass

    def _add_attribute(self, a: Attribute) -> None:
        self._attribute_collections[-1].attributes.append(a)

    def _at_scalar_field(self,
                         cast_mode: typing.Optional[str],
                         type_name: str,
                         field_name: str) -> None:
        t = _construct_type(cast_mode=cast_mode,
                            type_name=type_name,
                            allow_compound=True,
                            lookup_definitions=self._lookup_definitions)
        f = Field(t, field_name)
        self._add_attribute(f)

    def _at_array_field(self,
                        cast_mode: typing.Optional[str],
                        type_name: str,
                        mode_specifier: typing.Optional[str],
                        size_specifier: str,
                        field_name: str) -> None:
        e = _construct_type(cast_mode=cast_mode,
                            type_name=type_name,
                            allow_compound=True,
                            lookup_definitions=self._lookup_definitions)
        try:
            size = int(size_specifier)
        except ValueError:
            raise DSDLSyntaxError('Invalid array size specifier')

        if not mode_specifier:
            t = StaticArrayType(element_type=e, size=size)
        elif mode_specifier == '<':
            t = DynamicArrayType(element_type=e, max_size=size - 1)
        elif mode_specifier == '<=':
            t = DynamicArrayType(element_type=e, max_size=size)
        else:
            raise InternalError('Choo choo bitches')

        f = Field(t, field_name)
        self._add_attribute(f)

    def _at_padding_field(self, bit_length: str) -> None:
        t = VoidType(int(bit_length))
        f = PaddingField(t)
        self._add_attribute(f)

    def _at_constant(self,
                     cast_mode: typing.Optional[str],
                     type_name: str,
                     constant_name: str,
                     initialization_expression: str) -> None:
        t = _construct_type(cast_mode=cast_mode,
                            type_name=type_name,
                            allow_compound=False,                       # Compound types can't be constants
                            lookup_definitions=self._lookup_definitions)
        try:
            value = _evaluate_expression(initialization_expression)
        except Exception as ex:
            raise DSDLSyntaxError('Could not evaluate the constant initialization expression: %s' % ex)

        if not isinstance(value, (int, float, str)):
            raise DSDLSyntaxError('Constant initialization expression yields unsupported type: %r' % value)

        if isinstance(value, str) and len(value) != 1:
            raise DSDLSyntaxError('Invalid constant character: %r' % value)

        c = Constant(data_type=t,
                     name=constant_name,
                     value=value,
                     initialization_expression=initialization_expression)

        self._add_attribute(c)

    def _at_service_response_marker(self) -> None:
        if len(self._attribute_collections) > 1:
            raise DSDLSyntaxError('Duplicate service response marker')

        assert len(self._attribute_collections) == 1
        self._attribute_collections.append(_AttributeCollection())

    def _at_directive(self,
                      directive_name: str,
                      directive_expression: str) -> None:
        pass


def _evaluate_expression(expression: str) -> typing.Any:
    env = {
        'locals': None,
        'globals': None,
        '__builtins__': None,
        'true': 1,
        'false': 0,
    }
    return eval(expression, env)


_REGEXP_SCALAR_FIELD = (
    r'\s*(?:(saturated|truncated)\s+)?'         # Cast mode
    r'([a-zA-Z_][a-zA-Z0-9_\.]*)\s+'            # Type name
    r'([a-zA-Z_][a-zA-Z0-9_]*)'                 # Field name
    r'\s*(?:#.*)?$'                             # End of the line
)

_REGEXP_ARRAY_FIELD = (
    r'\s*(?:(saturated|truncated)\s+)?'         # Cast mode
    r'([a-zA-Z_][a-zA-Z0-9_\.]*)\s*'            # Type name
    r'\[\s*(<=?)?\s*(\d+)\s*\]\s+'              # Mode/size specifier
    r'([a-zA-Z_][a-zA-Z0-9_]*)'                 # Field name
    r'\s*(?:#.*)?$'                             # End of the line
)

_REGEXP_CONSTANT = (
    r'\s*(?:(saturated|truncated)\s+)?'         # Cast mode
    r'([a-zA-Z_][a-zA-Z0-9_\.]*)\s+'            # Type name
    r'([a-zA-Z_][a-zA-Z0-9_]*)'                 # Constant name
    r'\s*=\s*'                                  # Assignment
    r"((?:'[^']')|(?:[+\-\.0-9a-fA-Fox]+))"     # Initialization expression: integers, strings, floats
    r'\s*(?:#.*)?$'                             # End of the line
)

_REGEXP_PADDING_FIELD = r'\s*void(\d\d?)\s*(?:#.*)?$'

_REGEXP_SERVICE_RESPONSE_MARKER = r'---\s*(?:#.*)?$'

_REGEXP_DIRECTIVE = r'\s*@([a-zA-Z0-9_]+)\s*'  # TODO: finalize

_REGEXP_EMPTY = r'\s*(?:#.*)?$'


def _unittest_regexp() -> None:
    def validate(pattern: str,
                 text: str,
                 expected_output: typing.Optional[typing.Sequence[typing.Optional[str]]]) -> None:
        match = re.match(pattern, text)
        if expected_output is not None:
            assert match
            assert list(expected_output) == list(match.groups())
        else:
            assert match is None

    validate(_REGEXP_SCALAR_FIELD,
             'saturated uint8 value',
             ('saturated', 'uint8', 'value'))

    # This is not the intended behavior, but a side effect of the regular grammar we're using
    validate(_REGEXP_SCALAR_FIELD,
             'saturated uint8',
             (None, 'saturated', 'uint8'))

    validate(_REGEXP_SCALAR_FIELD,
             ' namespace.nested.TypeName.0.1  _0  # comment',
             (None, 'namespace.nested.TypeName.0.1', '_0'))

    validate(_REGEXP_ARRAY_FIELD,
             'namespace.nested.TypeName.0.1[123] _0',
             (None, 'namespace.nested.TypeName.0.1', None, '123', '_0'))

    validate(_REGEXP_ARRAY_FIELD,
             '  namespace.nested.TypeName.0.1  [   123  ]  _# comment',
             (None, 'namespace.nested.TypeName.0.1', None, '123', '_'))

    validate(_REGEXP_ARRAY_FIELD,
             'truncated type[<123] _0',
             ('truncated', 'type', '<', '123', '_0'))

    validate(_REGEXP_ARRAY_FIELD,
             'truncated type[<=123] _0',
             ('truncated', 'type', '<=', '123', '_0'))

    validate(_REGEXP_ARRAY_FIELD,
             ' truncated type  [ <= 123 ] _0',
             ('truncated', 'type', '<=', '123', '_0'))

    validate(_REGEXP_PADDING_FIELD, 'void1', ('1',))
    validate(_REGEXP_PADDING_FIELD, ' void64 ', ('64',))

    validate(_REGEXP_CONSTANT,
             'uint8 NAME = 123',
             (None, 'uint8', 'NAME', '123'))

    validate(_REGEXP_CONSTANT,
             'uint8 NAME = +123.456e+123',
             (None, 'uint8', 'NAME', '+123.456e+123'))

    validate(_REGEXP_CONSTANT,
             'uint8 NAME = -0xabcdef',
             (None, 'uint8', 'NAME', '-0xabcdef'))

    validate(_REGEXP_CONSTANT,
             'uint8 NAME = -0o123456',
             (None, 'uint8', 'NAME', '-0o123456'))

    validate(_REGEXP_CONSTANT,
             ' uint8 NAME=123#comment',
             (None, 'uint8', 'NAME', '123'))

    validate(_REGEXP_CONSTANT,
             " uint8 NAME='#'",
             (None, 'uint8', 'NAME', "'#'"))

    validate(_REGEXP_CONSTANT,
             "\tuint8 NAME = '#'# comment",
             (None, 'uint8', 'NAME', "'#'"))

    validate(_REGEXP_EMPTY, '', ())
    validate(_REGEXP_EMPTY, ' ', ())
    validate(_REGEXP_EMPTY, ' \t ', ())
    validate(_REGEXP_EMPTY, ' \t # Whatever! 987g13eh_bv-0o%e5tjkn rtgb-y562254-/*986+', ())
    validate(_REGEXP_EMPTY, '### Whatever! 987g13eh_bv-0o%e5tjkn rtgb-y562254-/*986+', ())
    validate(_REGEXP_EMPTY, '132', None)
    validate(_REGEXP_EMPTY, ' abc', None)
    validate(_REGEXP_EMPTY, ' "#" ', None)
    validate(_REGEXP_EMPTY, '"#"', None)
    validate(_REGEXP_EMPTY, "'#'", None)
