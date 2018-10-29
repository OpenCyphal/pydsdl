#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import re
import typing
import logging
import inspect
from .parse_error import ParseError, InternalError, InvalidDefinitionError
from .dsdl_definition import DSDLDefinition
from .data_type import BooleanType, SignedIntegerType, UnsignedIntegerType, FloatType, VoidType, DataType
from .data_type import ArrayType, StaticArrayType, DynamicArrayType, CompoundType, UnionType, StructureType
from .data_type import ServiceType, Attribute, Field, PaddingField, Constant, PrimitiveType
from .data_type import TypeParameterError
from .port_id_ranges import is_valid_regulated_service_id, is_valid_regulated_subject_id
from .regular_grammar_matcher import RegularGrammarMatcher, InvalidGrammarError, GrammarConstructHandler


class DSDLSyntaxError(InvalidDefinitionError):
    pass


class SemanticError(InvalidDefinitionError):
    pass


class UndefinedDataTypeError(SemanticError):
    pass


_GrammarRule = typing.NamedTuple('GrammarRule', [
    ('regexp', str),
    ('handler', GrammarConstructHandler)
])


# Accepts raw unevaluated expression as string if specified
_DirectiveHandler = typing.Union[
    typing.Callable[[], None],
    typing.Callable[[str], None],
]


_COMPOUND_ATTRIBUTE_TYPE_REGEXP = r'((?:[a-zA-Z_][a-zA-Z0-9_]*?\.)+?)(\d{1,3})(?:.(\d{1,3}))?$'


class _AttributeCollection:
    def __init__(self) -> None:
        self.attributes = []   # type: typing.List[Attribute]
        self.is_union = False


_logger = logging.getLogger(__name__)


def parse_definition(definition:         DSDLDefinition,
                     lookup_definitions: typing.Sequence[DSDLDefinition]) -> CompoundType:
    if len(inspect.stack()) > 100:
        raise SemanticError('Circular dependency')

    _logger.info('Parsing definition %r', definition)

    attribute_collections = [_AttributeCollection()]
    is_deprecated = False

    def mark_as_union() -> None:
        attribute_collections[-1].is_union = True

    def mark_deprecated() -> None:
        nonlocal is_deprecated
        is_deprecated = True

    def assert_expression(directive_expression: str) -> None:
        # TODO: IMPLEMENT
        raise NotImplementedError('Assertion directives are not yet implemented')

    directive_handlers = {
        'union':      mark_as_union,
        'deprecated': mark_deprecated,
        'assert':     assert_expression,
    }   # type: typing.Dict[str, _DirectiveHandler]

    try:
        _evaluate(definition,
                  attribute_collections,
                  list(lookup_definitions),
                  directive_handlers)
    except ParseError as ex:  # pragma: no cover
        ex.set_error_location_if_unknown(path=definition.file_path)
        raise
    except Exception as ex:  # pragma: no cover
        raise InternalError(culprit=ex, path=definition.file_path)

    try:
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
    except TypeParameterError as ex:
        raise SemanticError(str(ex), path=definition.file_path)


def _evaluate(definition:               DSDLDefinition,
              attribute_collections:    typing.List[_AttributeCollection],
              lookup_definitions:       typing.List[DSDLDefinition],
              directive_handlers:       typing.Dict[str, _DirectiveHandler]) -> None:
    ns = definition.namespace

    grammar = RegularGrammarMatcher()
    grammar.add_rule(*_make_scalar_field_rule(ns, lookup_definitions))
    grammar.add_rule(*_make_array_field_rule(ns, lookup_definitions))
    grammar.add_rule(*_make_constant_rule(ns, lookup_definitions))
    grammar.add_rule(*_make_padding_rule())
    grammar.add_rule(*_make_service_response_marker_rule(attribute_collections))
    grammar.add_rule(*_make_directive_rule(directive_handlers))
    grammar.add_rule(*_make_empty_rule())

    for line_index, line_text in enumerate(definition.text.splitlines(keepends=False)):
        line_number = line_index + 1
        try:
            output = grammar.match(line_text)
            if isinstance(output, Attribute):
                attribute_collections[-1].attributes.append(output)
                _logger.debug('Attribute constructed successfully: %r --> %r', line_text, output)
            elif output is None:
                pass
            else:       # pragma: no cover
                assert False
        except InvalidGrammarError:
            raise DSDLSyntaxError('Syntax error',
                                  path=definition.file_path,
                                  line=line_number)
        except TypeParameterError as ex:
            raise SemanticError(str(ex),
                                path=definition.file_path,
                                line=line_number)
        except ParseError as ex:  # pragma: no cover
            ex.set_error_location_if_unknown(path=definition.file_path,
                                             line=line_number)
            raise
        except Exception as ex:  # pragma: no cover
            raise InternalError(culprit=ex,
                                path=definition.file_path,
                                line=line_number)


def _make_scalar_field_rule(referer_namespace:  str,
                            lookup_definitions: typing.List[DSDLDefinition]) -> _GrammarRule:
    def constructor(cast_mode: typing.Optional[str],
                    type_name: str,
                    field_name: str) -> Field:
        t = _construct_type(referer_namespace=referer_namespace,
                            cast_mode=cast_mode,
                            type_name=type_name,
                            lookup_definitions=lookup_definitions)
        return Field(t, field_name)

    return _GrammarRule(r'\s*(?:(saturated|truncated)\s+)?'         # Cast mode
                        r'([a-zA-Z_][a-zA-Z0-9_\.]*)\s+'            # Type name
                        r'([a-zA-Z_][a-zA-Z0-9_]*)'                 # Field name
                        r'\s*(?:#.*)?$',                            # End of the line
                        constructor)


def _make_array_field_rule(referer_namespace:  str,
                           lookup_definitions: typing.List[DSDLDefinition]) -> _GrammarRule:
    def constructor(cast_mode: typing.Optional[str],
                    type_name: str,
                    mode_specifier: typing.Optional[str],
                    size_specifier: str,
                    field_name: str) -> Field:
        e = _construct_type(referer_namespace=referer_namespace,
                            cast_mode=cast_mode,
                            type_name=type_name,
                            lookup_definitions=lookup_definitions)
        # The size specifier is guaranteed to be a valid integer, see the regular expression
        size = int(size_specifier, 0)

        if not mode_specifier:
            t = StaticArrayType(element_type=e, size=size)              # type: ArrayType
        elif mode_specifier == '<':
            t = DynamicArrayType(element_type=e, max_size=size - 1)
        elif mode_specifier == '<=':
            t = DynamicArrayType(element_type=e, max_size=size)
        else:   # pragma: no cover
            raise InternalError('Choo choo bitches')

        return Field(t, field_name)

    return _GrammarRule(r'\s*(?:(saturated|truncated)\s+)?'         # Cast mode
                        r'([a-zA-Z_][a-zA-Z0-9_\.]*)\s*'            # Type name
                        r'\[\s*(<=?)?\s*(\d+)\s*\]\s+'              # Mode/size specifier
                        r'([a-zA-Z_][a-zA-Z0-9_]*)'                 # Field name
                        r'\s*(?:#.*)?$',                            # End of the line
                        constructor)


def _make_constant_rule(referer_namespace:  str,
                        lookup_definitions: typing.List[DSDLDefinition]) -> _GrammarRule:
    def constructor(cast_mode: typing.Optional[str],
                    type_name: str,
                    constant_name: str,
                    initialization_expression: str) -> Constant:
        t = _construct_type(referer_namespace=referer_namespace,
                            cast_mode=cast_mode,
                            type_name=type_name,
                            lookup_definitions=lookup_definitions)
        try:
            value = _evaluate_expression(initialization_expression)
        except SyntaxError as ex:
            raise DSDLSyntaxError('Malformed initialization expression: %s' % ex)
        except Exception as ex:
            raise SemanticError('Could not evaluate the constant initialization expression: %s' % ex)

        return Constant(data_type=t,
                        name=constant_name,
                        value=value,
                        initialization_expression=initialization_expression)

    return _GrammarRule(r'\s*(?:(saturated|truncated)\s+)?'         # Cast mode
                        r'([a-zA-Z_][a-zA-Z0-9_\.]*)\s+'            # Type name
                        r'([a-zA-Z_][a-zA-Z0-9_]*)'                 # Constant name
                        r'\s*=\s*'                                  # Assignment
                        r"((?:'[^']')|(?:[+\-\.0-9a-zA-Z_]+))"      # Initialization expression
                        r'\s*(?:#.*)?$',                            # End of the line
                        constructor)


def _make_padding_rule() -> _GrammarRule:
    return _GrammarRule(r'\s*void(\d\d?)\s*(?:#.*)?$',
                        lambda bw: PaddingField(VoidType(int(bw))))


def _make_service_response_marker_rule(attribute_collections: typing.List[_AttributeCollection]) -> _GrammarRule:
    def process() -> None:
        if len(attribute_collections) > 1:
            raise SemanticError('Duplicate service response marker')
        else:
            attribute_collections.append(_AttributeCollection())
            assert len(attribute_collections) == 2

    return _GrammarRule(r'\s*---\s*(?:#.*)?$',
                        process)


def _make_directive_rule(handlers: typing.Dict[str, _DirectiveHandler]) -> _GrammarRule:
    def process(directive_name: str,
                directive_expression: typing.Optional[str]) -> None:
        try:
            han = handlers[directive_name]
        except KeyError:
            raise SemanticError('Unknown directive: %r' % directive_name)

        num_parameters = len(inspect.signature(han).parameters)
        assert 0 <= num_parameters <= 1, 'Invalid directive handler'
        expression_required = num_parameters > 0

        if expression_required and not directive_expression:
            raise SemanticError('Directive %r requires an expression' % directive_name)

        if directive_expression and not expression_required:
            raise SemanticError('Directive %r does not expect an expression' % directive_name)

        _logger.debug('Executing directive %r with expression %r', directive_name, directive_expression)
        if expression_required:
            assert directive_expression
            han(directive_expression)       # type: ignore
        else:
            han()                           # type: ignore

    # The fact that the DSDL grammar is so simple allows us to get by with ridiculously simple expressions here.
    # We just take everything between the directive itself and either the end of the line or the first comment
    # and treat it as the expression (to be handled later). Strings are not allowed inside the expression,
    # which simplifies handling greatly.
    return _GrammarRule(r'\s*@([a-zA-Z0-9_]+)\s*([^#]+?)?\s*(?:#.*)?$',
                        process)


def _make_empty_rule() -> _GrammarRule:
    return _GrammarRule(r'\s*(?:#.*)?$', lambda: None)


def _construct_type(referer_namespace:  str,
                    cast_mode:          typing.Optional[str],
                    type_name:          str,
                    lookup_definitions: typing.List[DSDLDefinition]) -> DataType:
    assert referer_namespace == referer_namespace.strip().strip(CompoundType.NAME_COMPONENT_SEPARATOR).strip()

    def get_cast_mode() -> PrimitiveType.CastMode:
        return {
            'truncated': PrimitiveType.CastMode.TRUNCATED,
            'saturated': PrimitiveType.CastMode.SATURATED,
            None:        PrimitiveType.CastMode.SATURATED,
        }[cast_mode]

    def construct_compound(name: str, v_major: int, v_minor: typing.Optional[int]) -> CompoundType:
        if cast_mode is not None:
            raise SemanticError('Cast mode cannot be specified for compound data types')

        if CompoundType.NAME_COMPONENT_SEPARATOR not in name:
            # Namespace not specified, this means that we're using relative reference
            absolute_name = CompoundType.NAME_COMPONENT_SEPARATOR.join([referer_namespace, name])  # type: str
            _logger.debug('Relative reference: %r --> %r', name, absolute_name)
            name = absolute_name

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

        if len(matching_minor) != 1:    # pragma: no cover
            raise InternalError('Unexpected ambiguity: %r' % matching_minor)

        definition = matching_minor[0]
        return parse_definition(definition, lookup_definitions)

    g = RegularGrammarMatcher()
    g.add_rule(r'bool$', lambda: BooleanType(get_cast_mode()))
    g.add_rule(r'void(\d\d?)$', lambda bw: VoidType(int(bw)))
    g.add_rule(r'float(\d\d?)$', lambda bw: FloatType(int(bw), get_cast_mode()))
    g.add_rule(r'int(\d\d?)$', lambda bw: SignedIntegerType(int(bw), get_cast_mode()))
    g.add_rule(r'uint(\d\d?)$', lambda bw: UnsignedIntegerType(int(bw), get_cast_mode()))
    g.add_rule(_COMPOUND_ATTRIBUTE_TYPE_REGEXP,
               lambda name, v_mj, v_mn: construct_compound(name.strip('.'),
                                                           int(v_mj),
                                                           None if v_mn is None else int(v_mn)))
    try:
        t = g.match(type_name)
    except InvalidGrammarError:
        raise DSDLSyntaxError('Invalid type declaration: ' + type_name)
    else:
        assert isinstance(t, DataType)
        _logger.debug('Type constructed successfully: %r --> %r', type_name, t)
        return t


def _evaluate_expression(expression: str) -> typing.Any:
    env = {
        'locals': None,
        'globals': None,
        '__builtins__': None,
        'true': True,
        'false': False,
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

    validate(_make_scalar_field_rule('', []).regexp,
             'saturated uint8 value',
             ('saturated', 'uint8', 'value'))

    # This is not the intended behavior, but a side effect of the regular grammar we're using
    validate(_make_scalar_field_rule('', []).regexp,
             'saturated uint8',
             (None, 'saturated', 'uint8'))

    validate(_make_scalar_field_rule('', []).regexp,
             ' namespace.nested.TypeName.0.1  _0  # comment',
             (None, 'namespace.nested.TypeName.0.1', '_0'))

    validate(_make_array_field_rule('', []).regexp,
             'namespace.nested.TypeName.0.1[123] _0',
             (None, 'namespace.nested.TypeName.0.1', None, '123', '_0'))

    validate(_make_array_field_rule('', []).regexp,
             '  namespace.nested.TypeName.0.1  [   123  ]  _# comment',
             (None, 'namespace.nested.TypeName.0.1', None, '123', '_'))

    validate(_make_array_field_rule('', []).regexp,
             'truncated type[<123] _0',
             ('truncated', 'type', '<', '123', '_0'))

    validate(_make_array_field_rule('', []).regexp,
             'truncated type[<=123] _0',
             ('truncated', 'type', '<=', '123', '_0'))

    validate(_make_array_field_rule('', []).regexp,
             ' truncated type  [ <= 123 ] _0',
             ('truncated', 'type', '<=', '123', '_0'))

    validate(_make_padding_rule().regexp, 'void1', ('1',))
    validate(_make_padding_rule().regexp, ' void64 ', ('64',))

    validate(_make_constant_rule('', []).regexp,
             'uint8 NAME = 123',
             (None, 'uint8', 'NAME', '123'))

    validate(_make_constant_rule('', []).regexp,
             'uint8 NAME = +123.456e+123',
             (None, 'uint8', 'NAME', '+123.456e+123'))

    validate(_make_constant_rule('', []).regexp,
             'uint8 NAME = -0xabcdef',
             (None, 'uint8', 'NAME', '-0xabcdef'))

    validate(_make_constant_rule('', []).regexp,
             'uint8 NAME = -0o123456',
             (None, 'uint8', 'NAME', '-0o123456'))

    validate(_make_constant_rule('', []).regexp,
             ' uint8 NAME=123#comment',
             (None, 'uint8', 'NAME', '123'))

    validate(_make_constant_rule('', []).regexp,
             " uint8 NAME='#'",
             (None, 'uint8', 'NAME', "'#'"))

    validate(_make_constant_rule('', []).regexp,
             "\tuint8 NAME = '#'# comment",
             (None, 'uint8', 'NAME', "'#'"))

    validate(_make_directive_rule({}).regexp,
             "@directive",
             ('directive', None))

    validate(_make_directive_rule({}).regexp,
             " @directive # hello world",
             ('directive', None))

    validate(_make_directive_rule({}).regexp,
             " @directive a + b == c # hello world",
             ('directive', 'a + b == c'))

    validate(_make_directive_rule({}).regexp,
             " @directive a+b==c#hello world",
             ('directive', 'a+b==c'))

    validate(_make_directive_rule({}).regexp,
             " @directive a+b==c",
             ('directive', 'a+b==c'))

    validate(_make_service_response_marker_rule([]).regexp, "---", ())
    validate(_make_service_response_marker_rule([]).regexp, "\t---", ())
    validate(_make_service_response_marker_rule([]).regexp, "---  ", ())
    validate(_make_service_response_marker_rule([]).regexp, " ---  # whatever", ())
    validate(_make_service_response_marker_rule([]).regexp, "---#whatever", ())

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

    validate(_COMPOUND_ATTRIBUTE_TYPE_REGEXP,
             'uavcan.node.Heartbeat.1.2',
             ('uavcan.node.Heartbeat.', '1', '2'))

    validate(_COMPOUND_ATTRIBUTE_TYPE_REGEXP,
             'uavcan.node.Heartbeat.1',
             ('uavcan.node.Heartbeat.', '1', None))

    validate(_COMPOUND_ATTRIBUTE_TYPE_REGEXP,
             'Heartbeat.1',
             ('Heartbeat.', '1', None))

    validate(_COMPOUND_ATTRIBUTE_TYPE_REGEXP,
             'a1.123',
             ('a1.', '123', None))

    validate(_COMPOUND_ATTRIBUTE_TYPE_REGEXP,
             'a1.123.234',
             ('a1.', '123', '234'))

    validate(_COMPOUND_ATTRIBUTE_TYPE_REGEXP,
             'uavcan.1node.Heartbeat.1.2',
             None)

    validate(_COMPOUND_ATTRIBUTE_TYPE_REGEXP,
             'uavcan.node..Heartbeat.1.2',
             None)

    validate(_COMPOUND_ATTRIBUTE_TYPE_REGEXP,
             'uavcan.node.Heartbeat..1.2',
             None)

    validate(_COMPOUND_ATTRIBUTE_TYPE_REGEXP,
             'uavcan.node.Heartbeat.1..2',
             None)

    validate(_COMPOUND_ATTRIBUTE_TYPE_REGEXP,
             'uavcan.node.Heartbeat.1.2.',
             None)

    validate(_COMPOUND_ATTRIBUTE_TYPE_REGEXP,
             'uavcan.node-Heartbeat.1.2',
             None)
