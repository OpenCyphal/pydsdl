#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os
import typing
import logging
import operator
import functools
import collections
from decimal import Decimal
from parsimonious import NodeVisitor, VisitationError, Grammar
from parsimonious import ParseError as ParsimoniousParseError       # Oops? This sort of conflict is kinda bad.
from parsimonious.nodes import Node
from .parse_error import ParseError, InternalError, InvalidDefinitionError
from .dsdl_definition import DSDLDefinition
from .data_type import BooleanType, SignedIntegerType, UnsignedIntegerType, FloatType, VoidType, DataType
from .data_type import ArrayType, StaticArrayType, DynamicArrayType, CompoundType, UnionType, StructureType
from .data_type import ServiceType, Attribute, Field, PaddingField, Constant, PrimitiveType, Version
from .data_type import TypeParameterError, InvalidFixedPortIDError
from .port_id_ranges import is_valid_regulated_subject_id, is_valid_regulated_service_id


_GRAMMAR_DEFINITION_FILE_PATH = os.path.join(os.path.dirname(__file__), 'grammar.parsimonious')

_FULL_BIT_WIDTH_SET = list(range(1, 65))


class DSDLSyntaxError(InvalidDefinitionError):
    pass


class SemanticError(InvalidDefinitionError):
    pass


class AssertionCheckFailureError(SemanticError):
    pass


class UndefinedDataTypeError(SemanticError):
    pass


class ExpressionError(SemanticError):
    pass


class InvalidOperandError(ExpressionError):
    pass


# Arguments: emitting definition, line number, value to print
# The lines are numbered starting from one
PrintDirectiveOutputHandler = typing.Callable[[DSDLDefinition, int, typing.Any], None]


class ConfigurationOptions:
    def __init__(self) -> None:
        self.print_handler = None                       # type: typing.Optional[PrintDirectiveOutputHandler]
        self.allow_unregulated_fixed_port_id = False
        self.skip_assertion_checks = False


_logger = logging.getLogger(__name__)


def parse_definition(definition:            DSDLDefinition,
                     lookup_definitions:    typing.Sequence[DSDLDefinition],
                     configuration_options: ConfigurationOptions) -> CompoundType:
    _logger.info('Parsing definition %r', definition)

    try:
        transformer = _ASTTransformer(lookup_definitions,
                                      configuration_options)
        with open(definition.file_path) as f:
            print(transformer.parse(f.read()))

        raise KeyboardInterrupt
    except ParsimoniousParseError as ex:
        raise DSDLSyntaxError('Syntax error', path=definition.file_path, line=ex.line())
    except VisitationError as ex:
        raise DSDLSyntaxError(str(ex), path=definition.file_path)
    except TypeParameterError as ex:
        raise SemanticError(str(ex), path=definition.file_path)
    except ParseError as ex:  # pragma: no cover
        ex.set_error_location_if_unknown(path=definition.file_path)
        raise
    except Exception as ex:  # pragma: no cover
        raise InternalError(culprit=ex, path=definition.file_path)


VisitorHandler = typing.Callable[['_ASTTransformer', Node, typing.Sequence[typing.Any]], typing.Any]


def _ignores_untransformed_children(fun: VisitorHandler) -> VisitorHandler:
    """
    This decorator removes Node instances from the list of children.
    It is useful for visitor handlers that operate only on transformed entries,
    ignoring auxiliary elements of the grammar, such as comma separators or whitespaces.
    """
    @functools.wraps(fun)
    def wrapper(self: '_ASTTransformer', node: Node, children: typing.Sequence[typing.Any]) -> typing.Any:
        children = list(filter(lambda n: not isinstance(n, Node), children))
        return fun(self, node, children)

    return wrapper


def _polyadic_operator(fun: VisitorHandler) -> VisitorHandler:
    """
    Eliminates unvisited children and then invokes the inferior only if there are at least two children;
    otherwise, returns the sole child as-is.
    """
    @functools.wraps(fun)
    def wrapper(self: '_ASTTransformer', node: Node, children: typing.Sequence[typing.Any]) -> typing.Any:
        children = list(filter(lambda n: not isinstance(n, Node), children))
        if len(children) > 1:
            return _logged_transformation(fun)(self, node, children)
        else:
            return children[0]

    return wrapper


def _logged_transformation(fun: VisitorHandler) -> VisitorHandler:
    """
    Simply logs the resulting transformation upon its completion.
    """
    def print_node(n: Node) -> str:
        return '%s=%r' % (n.expr.name or '<anonymous>', n.text)

    @functools.wraps(fun)
    def wrapper(self: '_ASTTransformer', node: Node, children: typing.Sequence[typing.Any]) -> typing.Any:
        result = fun(self, node, children)
        _logger.debug('Transformation: %s [%s] --> %r',
                      print_node(node),
                      ', '.join([print_node(s) if isinstance(s, Node) else repr(s) for s in children])
                      or '<no children>',
                      result)
        return result

    return wrapper


TypeList = typing.Union[type, typing.Tuple[type, ...]]

# Note that we don't use floats internally; we use Decimals!
PrimitiveExpressionValue = typing.Union[bool, int, Decimal, str]

ExpressionValue = typing.Union[
    PrimitiveExpressionValue,
    typing.Set[typing.Any],  # There should be ExpressionValue instead of Any; MyPy does not support recursive types
]


# noinspection PyMethodMayBeStatic
class _ASTTransformer(NodeVisitor):
    # Populating the default grammar (see the NodeVisitor API).
    grammar = Grammar(open(_GRAMMAR_DEFINITION_FILE_PATH).read())

    # Intentional exceptions that shall not be treated as parse errors.
    # Beware that those might be propagated from recursive parser instances!
    unwrapped_exceptions = ParseError,

    def __init__(self,
                 lookup_definitions: typing.Sequence[DSDLDefinition],
                 configuration_options: ConfigurationOptions):
        self._lookup_definitions    = lookup_definitions
        self._configuration_options = configuration_options

    def generic_visit(self, node: Node, children: typing.Sequence[typing.Any]) -> typing.Any:
        # If the node has only one child and it has been transformed,
        # float the child up the parse tree by replacing the parent node with it.
        transformed = list(filter(lambda n: not isinstance(n, Node), children))
        if len(transformed) == 1:
            return transformed[0]

        return node

    #
    # Fields
    #
    @_logged_transformation
    def visit_padding_field(self, node: Node, _children: typing.Sequence[Node]) -> PaddingField:
        # Using reverse matching to weed out improper integer representations, e.g. with leading zeros
        try:
            data_type = {
                'void%d' % i: VoidType(i) for i in _FULL_BIT_WIDTH_SET
            }[node.text]
        except KeyError:
            raise UndefinedDataTypeError(node.text) from None
        else:
            return PaddingField(data_type)

    #
    # Type references
    #
    def visit_cast_mode(self, node: Node, _children: typing.Sequence[Node]) -> PrimitiveType.CastMode:
        return {
            'saturated': PrimitiveType.CastMode.SATURATED,
            'truncated': PrimitiveType.CastMode.TRUNCATED,
        }[node.text]

    @_logged_transformation
    @_ignores_untransformed_children
    def visit_type_version(self, _node: Node, children: typing.Sequence[int]) -> Version:
        assert all(isinstance(x, int) for x in children)
        major, minor = children
        return Version(major=major, minor=minor)

    #
    # Expressions
    #
    @_polyadic_operator
    def visit_power_ex(self, _node: Node, children: typing.Sequence[ExpressionValue]) -> ExpressionValue:
        return _elementwise_recursive_fold_left(children, operator.pow, (int, Decimal))

    #
    # Literals
    #
    def visit_real(self, node: Node, _children: typing.Sequence[Node]) -> Decimal:
        return Decimal(node.text)

    def visit_integer(self, node: Node, _children: typing.Sequence[Node]) -> int:
        return int(node.text, base=0)

    def visit_decimal_integer(self, node: Node, _children: typing.Sequence[Node]) -> int:
        return int(node.text)

    def visit_string(self, node: Node, _children: typing.Sequence[Node]) -> str:
        # TODO: manual handling of strings, incl. escape sequences and hex char notation
        out = eval(node.text)
        assert isinstance(out, str)
        return out

    def visit_boolean(self, node: Node, _children: typing.Sequence[Node]) -> bool:
        return {
            'true':  True,
            'false': False
        }[node.text]


def _elementwise_recursive_fold_left(operands: typing.Sequence[ExpressionValue],
                                     elementwise_operator: typing.Callable[[PrimitiveExpressionValue,
                                                                            PrimitiveExpressionValue],
                                                                           PrimitiveExpressionValue],
                                     left_operand_types: TypeList,
                                     right_operand_types: typing.Optional[TypeList] = None) -> ExpressionValue:
    """
    Elementwise application of the scalar operator with recursive traversal of nested containers.
    """
    def is_container(x: ExpressionValue) -> bool:
        return isinstance(x, collections.abc.Collection) and not isinstance(x, str)

    def enforce_type(value: typing.Any, expected_types: TypeList) -> None:
        # TODO: bool shall not be considered a subclass of int!
        if not isinstance(value, expected_types):
            raise InvalidOperandError('Invalid operand type: expected types %r, found %s' %
                                      (expected_types, type(value).__name__))

    def op(left: ExpressionValue, right: ExpressionValue) -> ExpressionValue:
        if not is_container(left) and not is_container(right):
            enforce_type(left, left_operand_types)
            enforce_type(right, right_operand_types or left_operand_types)
            return elementwise_operator(left, right)    # type: ignore

        elif is_container(left) and not is_container(right):
            return type(left)(_elementwise_recursive_fold_left([s, right],  # type: ignore
                                                               elementwise_operator,
                                                               left_operand_types,
                                                               right_operand_types)
                              for s in left)  # type: ignore

        elif not is_container(left) and is_container(right):
            return type(right)(_elementwise_recursive_fold_left([left, s],  # type: ignore
                                                                elementwise_operator,
                                                                left_operand_types,
                                                                right_operand_types)
                               for s in right)  # type: ignore

        else:
            # This could be a dot product or a matrix multiplication; it must be handled by the caller.
            raise InvalidOperandError("Don't know how to fold (%r) and (%r)" % (left, right))

    out = functools.reduce(op, operands)
    _logger.debug('Recursive left folding over %r: %r --> %r', elementwise_operator, operands, out)
    return out


def _unittest_elementwise_recursive_fold_left() -> None:
    from pytest import raises

    assert _elementwise_recursive_fold_left([1, 2], operator.add, int) == 3
    assert _elementwise_recursive_fold_left([
        {1, 2, frozenset({3, 4, frozenset({3, 4})})},
        5
    ], operator.add, int) == {6, 7, frozenset({8, 9, frozenset({8, 9})})}

    with raises(InvalidOperandError, match='.*fold.*'):
        _elementwise_recursive_fold_left([{1}, {2}], operator.add, int)

    with raises(InvalidOperandError, match='.*operand type.*'):
        _elementwise_recursive_fold_left([1, 2], operator.mul, str)
