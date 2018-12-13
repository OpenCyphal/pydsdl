#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import re
import typing
import logging
import inspect
import operator
from .parse_error import ParseError, InternalError, InvalidDefinitionError
from .dsdl_definition import DSDLDefinition
from .data_type import BooleanType, SignedIntegerType, UnsignedIntegerType, FloatType, VoidType, DataType
from .data_type import ArrayType, StaticArrayType, DynamicArrayType, CompoundType, UnionType, StructureType
from .data_type import ServiceType, Attribute, Field, PaddingField, Constant, PrimitiveType
from .data_type import TypeParameterError, InvalidFixedPortIDError
from .regular_grammar_matcher import RegularGrammarMatcher, InvalidGrammarError, GrammarConstructHandler
from .port_id_ranges import is_valid_regulated_subject_id, is_valid_regulated_service_id


class DSDLSyntaxError(InvalidDefinitionError):
    pass


class SemanticError(InvalidDefinitionError):
    pass


class AssertionCheckFailureError(SemanticError):
    pass


class UndefinedDataTypeError(SemanticError):
    pass


# Arguments: emitting definition, line number, value to print
# The lines are numbered starting from one
PrintDirectiveOutputHandler = typing.Callable[[DSDLDefinition, int, typing.Any], None]


class ConfigurationOptions:
    def __init__(self) -> None:
        self.print_handler = None                       # type: typing.Optional[PrintDirectiveOutputHandler]
        self.allow_unregulated_fixed_port_id = False
        self.skip_assertion_checks = False


_GrammarRule = typing.NamedTuple('GrammarRule', [
    ('regexp', str),
    ('handler', GrammarConstructHandler)
])


class _ServiceResponseMarkerPlaceholder:
    pass


class _DirectivePlaceholder:
    def __init__(self,
                 directive: str,
                 expression: typing.Optional[str]) -> None:
        self.directive = directive
        self.expression = expression


_COMPOUND_ATTRIBUTE_TYPE_REGEXP = r'((?:[a-zA-Z_][a-zA-Z0-9_]*?\.)+?)(\d{1,3})\.(\d{1,3})$'


class _AttributeCollection:
    class _PostponedExpression:
        def __init__(self,
                     next_attribute_index: int,
                     expression_text: str,
                     validator: typing.Callable[[typing.Any], None]):
            self.next_attribute_index = int(next_attribute_index)
            self.expression_text = str(expression_text)
            self.validator = validator
            _logger.debug('Registering new postponed assertion check before attribute #%d: %s',
                          self.next_attribute_index, self.expression_text)

    def __init__(self) -> None:
        self.attributes = []    # type: typing.List[Attribute]
        self.is_union = False
        self._expressions = []  # type: typing.List['_AttributeCollection._PostponedExpression']

    def add_postponed_expression(self,
                                 expression_text: str,
                                 validator: typing.Callable[[typing.Any], None]) -> None:
        self._expressions.append(self._PostponedExpression(len(self.attributes),
                                                           expression_text,
                                                           validator))

    def execute_postponed_expressions(self, data_type: typing.Union[StructureType, UnionType]) -> None:
        for pe in self._expressions:
            offset = _OffsetValue(data_type, pe.next_attribute_index)
            result = _evaluate_expression(pe.expression_text, offset=offset)
            pe.validator(result)


_logger = logging.getLogger(__name__)


def parse_definition(definition:            DSDLDefinition,
                     lookup_definitions:    typing.Sequence[DSDLDefinition],
                     configuration_options: ConfigurationOptions) -> CompoundType:
    _logger.info('Parsing definition %r', definition)

    attribute_collections = [_AttributeCollection()]
    is_deprecated = False

    def mark_as_union() -> None:
        if len(attribute_collections[-1].attributes) > 0:
            raise SemanticError('Union directive must be placed before the first attribute declaration')

        attribute_collections[-1].is_union = True

    def mark_deprecated() -> None:
        nonlocal is_deprecated
        if (len(attribute_collections) > 1) or (len(attribute_collections[-1].attributes) > 0):
            raise SemanticError('Deprecated directive must be placed near the beginning of the type definition')

        is_deprecated = True

    def assert_expression(expression: str) -> None:
        def validator(result: typing.Any) -> None:
            if isinstance(result, bool):
                if not result:
                    raise AssertionCheckFailureError('Assertion check failed on %r' % expression)
            else:
                raise SemanticError('Assertion check expressions must yield a boolean; %r yields %r' %
                                    (expression, result))

        if not configuration_options.skip_assertion_checks:
            attribute_collections[-1].add_postponed_expression(expression, validator)

    def make_print_expression_handler(ln: int) -> typing.Callable[[str], None]:
        # An extra closure is needed to capture the line number
        def fun(expression: str) -> None:
            def validator(result: typing.Any) -> None:
                _logger.info('@print: %s:%d: %r' % (definition.file_path, ln, result))
                if configuration_options.print_handler:
                    configuration_options.print_handler(definition, ln, result)

            attribute_collections[-1].add_postponed_expression(expression, validator)

        return fun

    try:
        for line_number, output in _evaluate(definition,
                                             list(lookup_definitions),
                                             configuration_options):
            if isinstance(output, Attribute):
                attribute_collections[-1].attributes.append(output)

            elif isinstance(output, _ServiceResponseMarkerPlaceholder):
                if len(attribute_collections) > 1:
                    raise SemanticError('Duplicate service response marker')
                else:
                    attribute_collections.append(_AttributeCollection())
                    assert len(attribute_collections) == 2

            elif isinstance(output, _DirectivePlaceholder):
                try:
                    handler = {
                        'union':      mark_as_union,
                        'deprecated': mark_deprecated,
                        'assert':     assert_expression,
                        'print':      make_print_expression_handler(line_number),
                    }[output.directive]
                except KeyError:
                    raise SemanticError('Unknown directive: %r' % output.directive)
                else:
                    num_parameters = len(inspect.signature(handler).parameters)  # type: ignore
                    assert 0 <= num_parameters <= 1, 'Invalid directive handler'
                    expression_required = num_parameters > 0

                    if expression_required and not output.expression:
                        raise SemanticError('Directive %r requires an expression' % output.directive)

                    if output.expression and not expression_required:
                        raise SemanticError('Directive %r does not expect an expression' % output.directive)

                    _logger.debug('Executing directive %r with expression %r',
                                  output.directive, output.expression)
                    if expression_required:
                        assert output.expression
                        handler(output.expression)  # type: ignore
                    else:
                        handler()  # type: ignore

            elif output is None:
                pass

            else:   # pragma: no cover
                assert False, 'Unexpected output'

    except ParseError as ex:  # pragma: no cover
        ex.set_error_location_if_unknown(path=definition.file_path)
        raise

    except Exception as ex:  # pragma: no cover
        raise InternalError(culprit=ex, path=definition.file_path)

    try:
        if len(attribute_collections) == 1:
            ac = attribute_collections[-1]
            if ac.is_union:
                tout = UnionType(name=definition.full_name,
                                 version=definition.version,
                                 attributes=ac.attributes,
                                 deprecated=is_deprecated,
                                 fixed_port_id=definition.fixed_port_id,
                                 source_file_path=definition.file_path)    # type: CompoundType
            else:
                tout = StructureType(name=definition.full_name,
                                     version=definition.version,
                                     attributes=ac.attributes,
                                     deprecated=is_deprecated,
                                     fixed_port_id=definition.fixed_port_id,
                                     source_file_path=definition.file_path)

            assert isinstance(tout, (StructureType, UnionType))
            ac.execute_postponed_expressions(tout)
        else:
            req, res = attribute_collections       # type: _AttributeCollection, _AttributeCollection
            tout = ServiceType(name=definition.full_name,
                               version=definition.version,
                               request_attributes=req.attributes,
                               response_attributes=res.attributes,
                               request_is_union=req.is_union,
                               response_is_union=res.is_union,
                               deprecated=is_deprecated,
                               fixed_port_id=definition.fixed_port_id,
                               source_file_path=definition.file_path)

            assert isinstance(tout, ServiceType)
            for ac, dt in [
                (req, tout.request_type),
                (res, tout.response_type),
            ]:
                assert isinstance(dt, (StructureType, UnionType))
                ac.execute_postponed_expressions(dt)

        # Regulated fixed port ID check
        if not configuration_options.allow_unregulated_fixed_port_id:
            port_id = tout.fixed_port_id
            if port_id is not None:
                f = is_valid_regulated_service_id if isinstance(tout, ServiceType) else is_valid_regulated_subject_id
                if not f(port_id, tout.root_namespace):
                    raise InvalidFixedPortIDError('Regulated port ID %r is not valid.'
                                                  'Consider using allow_unregulated_fixed_port_id.' % port_id)

        assert isinstance(tout, CompoundType)
        return tout
    except TypeParameterError as ex:
        raise SemanticError(str(ex), path=definition.file_path)
    except ParseError as ex:  # pragma: no cover
        ex.set_error_location_if_unknown(path=definition.file_path)
        raise


def _evaluate(definition: DSDLDefinition,
              lookup_definitions: typing.List[DSDLDefinition],
              configuration_options: ConfigurationOptions) -> \
        typing.Iterable[typing.Tuple[int, typing.Union[None,
                                                       Attribute,
                                                       _ServiceResponseMarkerPlaceholder,
                                                       _DirectivePlaceholder]]]:
    ns = definition.namespace

    grammar = RegularGrammarMatcher()
    grammar.add_rule(*_make_scalar_field_rule(ns, lookup_definitions, configuration_options))
    grammar.add_rule(*_make_array_field_rule(ns, lookup_definitions, configuration_options))
    grammar.add_rule(*_make_constant_rule(ns, lookup_definitions, configuration_options))
    grammar.add_rule(*_make_padding_rule())
    grammar.add_rule(*_make_service_response_marker_rule())
    grammar.add_rule(*_make_directive_rule())
    grammar.add_rule(*_make_empty_rule())

    for line_index, line_text in enumerate(definition.text.splitlines(keepends=False)):
        line_number = line_index + 1
        try:
            output = grammar.match(line_text)
            yield line_number, output
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
                            lookup_definitions: typing.List[DSDLDefinition],
                            configuration_options: ConfigurationOptions) -> _GrammarRule:
    def constructor(cast_mode: typing.Optional[str],
                    type_name: str,
                    field_name: str) -> Field:
        t = _construct_type(referer_namespace=referer_namespace,
                            cast_mode=cast_mode,
                            type_name=type_name,
                            lookup_definitions=lookup_definitions,
                            configuration_options=configuration_options)
        return Field(t, field_name)

    return _GrammarRule(r'\s*(?:(saturated|truncated)\s+)?'         # Cast mode
                        r'([a-zA-Z_][a-zA-Z0-9_\.]*)\s+'            # Type name
                        r'([a-zA-Z_][a-zA-Z0-9_]*)'                 # Field name
                        r'\s*(?:#.*)?$',                            # End of the line
                        constructor)


def _make_array_field_rule(referer_namespace:  str,
                           lookup_definitions: typing.List[DSDLDefinition],
                           configuration_options: ConfigurationOptions) -> _GrammarRule:
    def constructor(cast_mode: typing.Optional[str],
                    type_name: str,
                    mode_specifier: typing.Optional[str],
                    size_specifier: str,
                    field_name: str) -> Field:
        e = _construct_type(referer_namespace=referer_namespace,
                            cast_mode=cast_mode,
                            type_name=type_name,
                            lookup_definitions=lookup_definitions,
                            configuration_options=configuration_options)
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
                        lookup_definitions: typing.List[DSDLDefinition],
                        configuration_options: ConfigurationOptions) -> _GrammarRule:
    def constructor(cast_mode: typing.Optional[str],
                    type_name: str,
                    constant_name: str,
                    initialization_expression: str) -> Constant:
        t = _construct_type(referer_namespace=referer_namespace,
                            cast_mode=cast_mode,
                            type_name=type_name,
                            lookup_definitions=lookup_definitions,
                            configuration_options=configuration_options)
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


def _make_service_response_marker_rule() -> _GrammarRule:
    return _GrammarRule(r'\s*---\s*(?:#.*)?$',
                        lambda: _ServiceResponseMarkerPlaceholder())


def _make_directive_rule() -> _GrammarRule:
    # The fact that the DSDL grammar is so simple allows us to get by with ridiculously simple expressions here.
    # We just take everything between the directive itself and either the end of the line or the first comment
    # and treat it as the expression (to be handled later). Strings are not allowed inside the expression,
    # which simplifies handling greatly.
    return _GrammarRule(r'\s*@([a-zA-Z0-9_]+)\s*([^#]+?)?\s*(?:#.*)?$',
                        lambda d, e: _DirectivePlaceholder(d, e))


def _make_empty_rule() -> _GrammarRule:
    return _GrammarRule(r'\s*(?:#.*)?$', lambda: None)


def _construct_type(referer_namespace:  str,
                    cast_mode:          typing.Optional[str],
                    type_name:          str,
                    lookup_definitions: typing.List[DSDLDefinition],
                    configuration_options: ConfigurationOptions) -> DataType:
    assert referer_namespace == referer_namespace.strip().strip(CompoundType.NAME_COMPONENT_SEPARATOR).strip()

    def get_cast_mode() -> PrimitiveType.CastMode:
        return {
            'truncated': PrimitiveType.CastMode.TRUNCATED,
            'saturated': PrimitiveType.CastMode.SATURATED,
            None:        PrimitiveType.CastMode.SATURATED,
        }[cast_mode]

    def construct_compound(name: str, v_major: int, v_minor: int) -> CompoundType:
        if cast_mode is not None:
            raise SemanticError('Cast mode cannot be specified for compound data types')

        if CompoundType.NAME_COMPONENT_SEPARATOR not in name:
            # Namespace not specified, this means that we're using relative reference
            absolute_name = CompoundType.NAME_COMPONENT_SEPARATOR.join([referer_namespace, name])  # type: str
            _logger.debug('Relative reference: %r --> %r', name, absolute_name)
            name = absolute_name

        matching_name = list(filter(lambda x: x.full_name == name, lookup_definitions))
        if not matching_name:
            raise UndefinedDataTypeError('No type named ' + name)

        matching_major = list(filter(lambda x: x.version.major == v_major, matching_name))
        if not matching_major:
            raise UndefinedDataTypeError('No suitable major version of %r could be found. '
                                         'Requested version %d, found: %r' % (name, v_major, matching_name))

        matching_minor = list(filter(lambda x: x.version.minor == v_minor, matching_major))
        if not matching_minor:
            raise UndefinedDataTypeError('No suitable minor version of %r could be found. '
                                         'Requested minor version %d, found: %r' %
                                         (name, v_minor, matching_major))

        if len(matching_minor) != 1:    # pragma: no cover
            raise InternalError('Unexpected ambiguity: %r' % matching_minor)

        definition = matching_minor[0]

        # Remove all versions of the same type from lookup definitions to prevent circular dependencies
        lookup_definitions_without_circular_dependencies = [
            x for x in lookup_definitions if x.full_name != definition.full_name
        ]

        return parse_definition(definition,
                                lookup_definitions_without_circular_dependencies,
                                configuration_options)

    g = RegularGrammarMatcher()
    g.add_rule(r'bool$', lambda: BooleanType(get_cast_mode()))
    g.add_rule(r'void(\d\d?)$', lambda bw: VoidType(int(bw)))
    g.add_rule(r'float(\d\d?)$', lambda bw: FloatType(int(bw), get_cast_mode()))
    g.add_rule(r'int(\d\d?)$', lambda bw: SignedIntegerType(int(bw), get_cast_mode()))
    g.add_rule(r'uint(\d\d?)$', lambda bw: UnsignedIntegerType(int(bw), get_cast_mode()))
    g.add_rule(_COMPOUND_ATTRIBUTE_TYPE_REGEXP,
               lambda name, v_mj, v_mn: construct_compound(name.strip('.'), int(v_mj), int(v_mn)))
    try:
        t = g.match(type_name)
    except InvalidGrammarError:
        raise DSDLSyntaxError('Invalid type declaration: ' + type_name)
    else:
        assert isinstance(t, DataType)
        _logger.debug('Type constructed successfully: %r --> %r', type_name, t)
        return t


def _evaluate_expression(expression: str, **context: typing.Any) -> typing.Any:
    env = {
        'locals': None,
        'globals': None,
        '__builtins__': None,
        'true': True,
        'false': False,
    }
    env.update(context)
    return eval(expression, env)


class _OffsetValue:
    def __init__(self,
                 data_type: CompoundType,
                 next_attribute_index: int):
        self._data_type = data_type

        self._next_field_index = 0
        for i, a in enumerate(self._data_type.attributes[:next_attribute_index]):
            if isinstance(a, Field):
                self._next_field_index += 1

        assert next_attribute_index >= self._next_field_index
        _logger.debug('Index conversion: attribute #%d --> field #%d for %r',
                      next_attribute_index, self._next_field_index, data_type)

        self._set_cache = None      # type: typing.Optional[typing.Set[int]]

    @property
    def _set(self) -> typing.Set[int]:
        # We're using lazy evaluation because not every expression uses the offset value
        if self._set_cache is None:
            if self._next_field_index >= len(self._data_type.fields):
                self._set_cache = set(self._data_type.bit_length_values)
            else:
                if isinstance(self._data_type, StructureType):
                    self._set_cache = self._data_type.get_field_offset_values(field_index=self._next_field_index)
                elif isinstance(self._data_type, UnionType):
                    raise SemanticError('Inter-field min/max offset is not defined for unions')
                else:   # pragma: no cover
                    assert False, 'Ill-defined offset'

        assert len(self._set_cache) > 0, 'Empty BLV sets are forbidden'
        return self._set_cache

    @property
    def min(self) -> int:
        return min(self._set)   # Can be optimized for the case when next_field_index == len(fields)

    @property
    def max(self) -> int:
        return max(self._set)   # Can be optimized for the case when next_field_index == len(fields)

    def _do_elementwise(self,
                        element_operator: typing.Callable[[int, int], int],
                        right_hand_operand: int) -> typing.Set[int]:
        if isinstance(right_hand_operand, int):
            return set(map(lambda x: element_operator(x, right_hand_operand), self._set))
        else:
            raise SemanticError('Invalid operand %r' % right_hand_operand)

    def __eq__(self, other: typing.Any) -> bool:
        if isinstance(other, set):
            return other == self._set
        elif isinstance(other, _OffsetValue):
            return self._set == other._set
        else:
            raise SemanticError('Offset cannot be compared against %r' % other)

    def __mod__(self, other: int) -> typing.Set[int]:
        return self._do_elementwise(operator.mod, other)

    def __add__(self, other: int) -> typing.Set[int]:
        return self._do_elementwise(operator.add, other)

    def __sub__(self, other: int) -> typing.Set[int]:
        return self._do_elementwise(operator.sub, other)

    def __mul__(self, other: int) -> typing.Set[int]:
        return self._do_elementwise(operator.mul, other)

    def __truediv__(self, other: int) -> typing.Set[int]:
        """Floor division using the true division syntax"""
        return self._do_elementwise(operator.floordiv, other)

    __rmul__ = __mul__
    __radd__ = __add__

    # We can't rely on functools.total_order because we use unconventional elementwise operators
    def __lt__(self, other: int) -> bool:
        return all(self._do_elementwise(operator.lt, other))

    def __le__(self, other: int) -> bool:
        return all(self._do_elementwise(operator.le, other))

    def __gt__(self, other: int) -> bool:
        return all(self._do_elementwise(operator.gt, other))

    def __ge__(self, other: int) -> bool:
        return all(self._do_elementwise(operator.ge, other))

    def __str__(self) -> str:
        return str(self._set or '{}')

    __repr__ = __str__


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

    validate(_make_scalar_field_rule('', [], ConfigurationOptions()).regexp,
             'saturated uint8 value',
             ('saturated', 'uint8', 'value'))

    # This is not the intended behavior, but a side effect of the regular grammar we're using
    validate(_make_scalar_field_rule('', [], ConfigurationOptions()).regexp,
             'saturated uint8',
             (None, 'saturated', 'uint8'))

    validate(_make_scalar_field_rule('', [], ConfigurationOptions()).regexp,
             ' namespace.nested.TypeName.0.1  _0  # comment',
             (None, 'namespace.nested.TypeName.0.1', '_0'))

    validate(_make_array_field_rule('', [], ConfigurationOptions()).regexp,
             'namespace.nested.TypeName.0.1[123] _0',
             (None, 'namespace.nested.TypeName.0.1', None, '123', '_0'))

    validate(_make_array_field_rule('', [], ConfigurationOptions()).regexp,
             '  namespace.nested.TypeName.0.1  [   123  ]  _# comment',
             (None, 'namespace.nested.TypeName.0.1', None, '123', '_'))

    validate(_make_array_field_rule('', [], ConfigurationOptions()).regexp,
             'truncated type[<123] _0',
             ('truncated', 'type', '<', '123', '_0'))

    validate(_make_array_field_rule('', [], ConfigurationOptions()).regexp,
             'truncated type[<=123] _0',
             ('truncated', 'type', '<=', '123', '_0'))

    validate(_make_array_field_rule('', [], ConfigurationOptions()).regexp,
             ' truncated type  [ <= 123 ] _0',
             ('truncated', 'type', '<=', '123', '_0'))

    validate(_make_padding_rule().regexp, 'void1', ('1',))
    validate(_make_padding_rule().regexp, ' void64 ', ('64',))

    validate(_make_constant_rule('', [], ConfigurationOptions()).regexp,
             'uint8 NAME = 123',
             (None, 'uint8', 'NAME', '123'))

    validate(_make_constant_rule('', [], ConfigurationOptions()).regexp,
             'uint8 NAME = +123.456e+123',
             (None, 'uint8', 'NAME', '+123.456e+123'))

    validate(_make_constant_rule('', [], ConfigurationOptions()).regexp,
             'uint8 NAME = -0xabcdef',
             (None, 'uint8', 'NAME', '-0xabcdef'))

    validate(_make_constant_rule('', [], ConfigurationOptions()).regexp,
             'uint8 NAME = -0o123456',
             (None, 'uint8', 'NAME', '-0o123456'))

    validate(_make_constant_rule('', [], ConfigurationOptions()).regexp,
             ' uint8 NAME=123#comment',
             (None, 'uint8', 'NAME', '123'))

    validate(_make_constant_rule('', [], ConfigurationOptions()).regexp,
             " uint8 NAME='#'",
             (None, 'uint8', 'NAME', "'#'"))

    validate(_make_constant_rule('', [], ConfigurationOptions()).regexp,
             "\tuint8 NAME = '#'# comment",
             (None, 'uint8', 'NAME', "'#'"))

    validate(_make_directive_rule().regexp,
             "@directive",
             ('directive', None))

    validate(_make_directive_rule().regexp,
             " @directive # hello world",
             ('directive', None))

    validate(_make_directive_rule().regexp,
             " @directive a + b == c # hello world",
             ('directive', 'a + b == c'))

    validate(_make_directive_rule().regexp,
             " @directive a+b==c#hello world",
             ('directive', 'a+b==c'))

    validate(_make_directive_rule().regexp,
             " @directive a+b==c",
             ('directive', 'a+b==c'))

    validate(_make_service_response_marker_rule().regexp, "---", ())
    validate(_make_service_response_marker_rule().regexp, "\t---", ())
    validate(_make_service_response_marker_rule().regexp, "---  ", ())
    validate(_make_service_response_marker_rule().regexp, " ---  # whatever", ())
    validate(_make_service_response_marker_rule().regexp, "---#whatever", ())

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
             None)

    validate(_COMPOUND_ATTRIBUTE_TYPE_REGEXP,
             'uavcan.node.Heartbeat.1.',
             None)

    validate(_COMPOUND_ATTRIBUTE_TYPE_REGEXP,
             'Heartbeat.1.2',
             ('Heartbeat.', '1', '2'))

    validate(_COMPOUND_ATTRIBUTE_TYPE_REGEXP,
             'a1.123',
             None)

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
