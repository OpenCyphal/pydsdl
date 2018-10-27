#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import re
import typing
import logging
import inspect
from .error import ParseError, InternalError, DSDLSyntaxError, DSDLSemanticError, UndefinedDataTypeError
from .dsdl_definition import DSDLDefinition
from .data_type import BooleanType, SignedIntegerType, UnsignedIntegerType, FloatType, VoidType, DataType
from .data_type import ArrayType, StaticArrayType, DynamicArrayType, CompoundType, UnionType, StructureType
from .data_type import ServiceType, Attribute, Field, PaddingField, Constant, PrimitiveType, Version
from .port_id_ranges import is_valid_regulated_service_id, is_valid_regulated_subject_id
from .regular_grammar_matcher import RegularGrammarMatcher, InvalidGrammarError, GrammarConstructHandler


_GrammarRule = typing.NamedTuple('GrammarRule', [
    ('regexp', str),
    ('handler', GrammarConstructHandler)
])


# Accepts raw unevaluated expression as string if specified
_DirectiveHandler = typing.Union[
    typing.Callable[[], None],
    typing.Callable[[str], None],
]


class _AttributeCollection:
    def __init__(self) -> None:
        self.attributes = []   # type: typing.List[Attribute]
        self.is_union = False


_logger = logging.getLogger(__name__)


def parse_definition(definition: DSDLDefinition,
                     lookup_definitions: typing.List[DSDLDefinition]) -> CompoundType:
    attribute_collections = [_AttributeCollection()]
    is_deprecated = False

    def on_union() -> None:
        attribute_collections[-1].is_union = True

    def on_deprecated() -> None:
        nonlocal is_deprecated
        is_deprecated = True

    def on_assert(directive_expression: str) -> None:
        raise NotImplementedError('Assertion directives are not yet implemented')

    directive_handlers = {
        'union':      on_union,
        'deprecated': on_deprecated,
        'assert':     on_assert,
    }   # type: typing.Dict[str, _DirectiveHandler]

    _evaluate(definition.text,
              attribute_collections,
              lookup_definitions,
              directive_handlers)

    if len(attribute_collections) == 1:
        ac = attribute_collections[-1]
        if ac.is_union:
            return UnionType(name=definition.name,
                             version=definition.version,
                             attributes=ac.attributes,
                             deprecated=is_deprecated,
                             regulated_port_id=definition.regulated_port_id)
        else:
            return StructureType(name=definition.name,
                                 version=definition.version,
                                 attributes=ac.attributes,
                                 deprecated=is_deprecated,
                                 regulated_port_id=definition.regulated_port_id)
    else:
        req, resp = attribute_collections       # type: _AttributeCollection, _AttributeCollection
        return ServiceType(name=definition.name,
                           version=definition.version,
                           request_attributes=req.attributes,
                           response_attributes=resp.attributes,
                           request_is_union=req.is_union,
                           response_is_union=resp.is_union,
                           deprecated=is_deprecated,
                           regulated_port_id=definition.regulated_port_id)


def _evaluate(definition_text:          str,
              attribute_collections:    typing.List[_AttributeCollection],
              lookup_definitions:       typing.List[DSDLDefinition],
              directive_handlers:       typing.Dict[str, _DirectiveHandler]) -> None:
    grammar = RegularGrammarMatcher()
    grammar.add_rule(*_make_scalar_field_rule(lookup_definitions))
    grammar.add_rule(*_make_array_field_rule(lookup_definitions))
    grammar.add_rule(*_make_constant_rule(lookup_definitions))
    grammar.add_rule(*_make_padding_rule())
    grammar.add_rule(*_make_service_response_marker_rule(attribute_collections))
    grammar.add_rule(*_make_directive_rule(directive_handlers))
    grammar.add_rule(*_make_empty_rule())

    for line_index, line_text in enumerate(definition_text.splitlines(keepends=False)):
        line_number = line_index + 1
        try:
            output = grammar.match(line_text)
            if isinstance(output, Attribute):
                attribute_collections[-1].attributes.append(output)
            elif output is None:
                pass
            else:
                assert False
        except ParseError as ex:  # pragma: no cover
            ex.set_error_location_if_unknown(line=line_number)
            raise
        except Exception as ex:  # pragma: no cover
            raise InternalError(culprit=ex, line=line_number)


def _make_scalar_field_rule(lookup_definitions: typing.List[DSDLDefinition]) -> _GrammarRule:
    def constructor(cast_mode: typing.Optional[str],
                    type_name: str,
                    field_name: str) -> Field:
        t = _construct_type(cast_mode=cast_mode,
                            type_name=type_name,
                            allow_compound=True,
                            lookup_definitions=lookup_definitions)
        return Field(t, field_name)

    return _GrammarRule(r'\s*(?:(saturated|truncated)\s+)?'         # Cast mode
                        r'([a-zA-Z_][a-zA-Z0-9_\.]*)\s+'            # Type name
                        r'([a-zA-Z_][a-zA-Z0-9_]*)'                 # Field name
                        r'\s*(?:#.*)?$',                            # End of the line
                        constructor)


def _make_array_field_rule(lookup_definitions: typing.List[DSDLDefinition]) -> _GrammarRule:
    def constructor(cast_mode: typing.Optional[str],
                    type_name: str,
                    mode_specifier: typing.Optional[str],
                    size_specifier: str,
                    field_name: str) -> Field:
        e = _construct_type(cast_mode=cast_mode,
                            type_name=type_name,
                            allow_compound=True,
                            lookup_definitions=lookup_definitions)
        try:
            size = int(size_specifier)
        except ValueError:
            raise DSDLSyntaxError('Invalid array size specifier')

        if not mode_specifier:
            t = StaticArrayType(element_type=e, size=size)              # type: ArrayType
        elif mode_specifier == '<':
            t = DynamicArrayType(element_type=e, max_size=size - 1)
        elif mode_specifier == '<=':
            t = DynamicArrayType(element_type=e, max_size=size)
        else:
            raise InternalError('Choo choo bitches')

        return Field(t, field_name)

    return _GrammarRule(r'\s*(?:(saturated|truncated)\s+)?'         # Cast mode
                        r'([a-zA-Z_][a-zA-Z0-9_\.]*)\s*'            # Type name
                        r'\[\s*(<=?)?\s*(\d+)\s*\]\s+'              # Mode/size specifier
                        r'([a-zA-Z_][a-zA-Z0-9_]*)'                 # Field name
                        r'\s*(?:#.*)?$',                            # End of the line
                        constructor)


def _make_constant_rule(lookup_definitions: typing.List[DSDLDefinition]) -> _GrammarRule:
    def constructor(cast_mode: typing.Optional[str],
                    type_name: str,
                    constant_name: str,
                    initialization_expression: str) -> Constant:
        t = _construct_type(cast_mode=cast_mode,
                            type_name=type_name,
                            allow_compound=False,                       # Compound types can't be constants
                            lookup_definitions=lookup_definitions)
        try:
            value = _evaluate_expression(initialization_expression)
        except Exception as ex:
            raise DSDLSyntaxError('Could not evaluate the constant initialization expression: %s' % ex)

        if not isinstance(value, (int, float, str)):
            raise DSDLSyntaxError('Constant initialization expression yields unsupported type: %r' % value)

        if isinstance(value, str) and len(value) != 1:
            raise DSDLSyntaxError('Invalid constant character: %r' % value)

        # TODO: enforce type compatibility, check ranges
        return Constant(data_type=t,
                        name=constant_name,
                        value=value,
                        initialization_expression=initialization_expression)

    return _GrammarRule(r'\s*(?:(saturated|truncated)\s+)?'         # Cast mode
                        r'([a-zA-Z_][a-zA-Z0-9_\.]*)\s+'            # Type name
                        r'([a-zA-Z_][a-zA-Z0-9_]*)'                 # Constant name
                        r'\s*=\s*'                                  # Assignment
                        r"((?:'[^']')|(?:[+\-\.0-9a-fA-Fox]+))"     # Initialization expression: int, str, float
                        r'\s*(?:#.*)?$',                            # End of the line
                        constructor)


def _make_padding_rule() -> _GrammarRule:
    return _GrammarRule(r'\s*void(\d\d?)\s*(?:#.*)?$',
                        lambda bw: PaddingField(VoidType(int(bw))))


def _make_service_response_marker_rule(attribute_collections: typing.List[_AttributeCollection]) -> _GrammarRule:
    def process() -> None:
        if len(attribute_collections) > 1:
            raise DSDLSemanticError('Duplicate service response marker')
        else:
            attribute_collections.append(_AttributeCollection())
            assert len(attribute_collections) == 2

    return _GrammarRule(r'---\s*(?:#.*)?$',
                        process)


def _make_directive_rule(handlers: typing.Dict[str, _DirectiveHandler]) -> _GrammarRule:
    def process(directive_name: str,
                directive_expression: typing.Optional[str]) -> None:
        try:
            han = handlers[directive_name]
        except KeyError:
            raise DSDLSemanticError('Unknown directive: %r' % directive_name)

        num_parameters = len(inspect.signature(han).parameters)
        assert 0 <= num_parameters <= 1, 'Invalid directive handler'
        expression_required = num_parameters > 0

        if expression_required and not directive_expression:
            raise DSDLSemanticError('Directive %r requires an expression' % directive_name)

        if directive_expression and not expression_required:
            raise DSDLSemanticError('Directive %r does not expect an expression' % directive_name)

        if expression_required:
            assert directive_expression
            han(directive_expression)       # type: ignore
        else:
            han()                           # type: ignore

    return _GrammarRule(r'\s*@([a-zA-Z0-9_]+)\s*',  # TODO: finalize
                        process)


def _make_empty_rule() -> _GrammarRule:
    return _GrammarRule(r'\s*(?:#.*)?$', lambda: None)


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
        # TODO: match only correct names, add tests
        g.add_rule(r'([a-zA-Z0-9_\.]+?)\.(\d{1,3})(?:.(\d{1,3}))?$',
                   lambda name, v_mj, v_mn:
                       construct_compound(name, int(v_mj), None if v_mn is None else int(v_mn)))

    try:
        t = g.match(type_name)
        assert isinstance(t, DataType)
        return t
    except InvalidGrammarError:
        raise DSDLSyntaxError('Invalid type declaration: ' + type_name)


def _evaluate_expression(expression: str) -> typing.Any:
    env = {
        'locals': None,
        'globals': None,
        '__builtins__': None,
        'true': 1,
        'false': 0,
        'offset': None,             # TODO: offset
    }
    return eval(expression, env)


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

    validate(_make_scalar_field_rule([]).regexp,
             'saturated uint8 value',
             ('saturated', 'uint8', 'value'))

    # This is not the intended behavior, but a side effect of the regular grammar we're using
    validate(_make_scalar_field_rule([]).regexp,
             'saturated uint8',
             (None, 'saturated', 'uint8'))

    validate(_make_scalar_field_rule([]).regexp,
             ' namespace.nested.TypeName.0.1  _0  # comment',
             (None, 'namespace.nested.TypeName.0.1', '_0'))

    validate(_make_array_field_rule([]).regexp,
             'namespace.nested.TypeName.0.1[123] _0',
             (None, 'namespace.nested.TypeName.0.1', None, '123', '_0'))

    validate(_make_array_field_rule([]).regexp,
             '  namespace.nested.TypeName.0.1  [   123  ]  _# comment',
             (None, 'namespace.nested.TypeName.0.1', None, '123', '_'))

    validate(_make_array_field_rule([]).regexp,
             'truncated type[<123] _0',
             ('truncated', 'type', '<', '123', '_0'))

    validate(_make_array_field_rule([]).regexp,
             'truncated type[<=123] _0',
             ('truncated', 'type', '<=', '123', '_0'))

    validate(_make_array_field_rule([]).regexp,
             ' truncated type  [ <= 123 ] _0',
             ('truncated', 'type', '<=', '123', '_0'))

    validate(_make_padding_rule().regexp, 'void1', ('1',))
    validate(_make_padding_rule().regexp, ' void64 ', ('64',))

    validate(_make_constant_rule([]).regexp,
             'uint8 NAME = 123',
             (None, 'uint8', 'NAME', '123'))

    validate(_make_constant_rule([]).regexp,
             'uint8 NAME = +123.456e+123',
             (None, 'uint8', 'NAME', '+123.456e+123'))

    validate(_make_constant_rule([]).regexp,
             'uint8 NAME = -0xabcdef',
             (None, 'uint8', 'NAME', '-0xabcdef'))

    validate(_make_constant_rule([]).regexp,
             'uint8 NAME = -0o123456',
             (None, 'uint8', 'NAME', '-0o123456'))

    validate(_make_constant_rule([]).regexp,
             ' uint8 NAME=123#comment',
             (None, 'uint8', 'NAME', '123'))

    validate(_make_constant_rule([]).regexp,
             " uint8 NAME='#'",
             (None, 'uint8', 'NAME', "'#'"))

    validate(_make_constant_rule([]).regexp,
             "\tuint8 NAME = '#'# comment",
             (None, 'uint8', 'NAME', "'#'"))

    re_empty = _make_empty_rule().regexp
    validate(re_empty, '', ())
    validate(re_empty, ' ', ())
    validate(re_empty, ' \t ', ())
    validate(re_empty, ' \t # Whatever! 987g13eh_bv-0o%e5tjkn rtgb-y562254-/*986+', ())
    validate(re_empty, '### Whatever! 987g13eh_bv-0o%e5tjkn rtgb-y562254-/*986+', ())
    validate(re_empty, '132', None)
    validate(re_empty, ' abc', None)
    validate(re_empty, ' "#" ', None)
    validate(re_empty, '"#"', None)
    validate(re_empty, "'#'", None)
