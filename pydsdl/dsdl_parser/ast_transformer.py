#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os
import typing
import logging
import functools

from fractions import Fraction
from parsimonious import NodeVisitor, VisitationError, Grammar
from parsimonious import ParseError as ParsimoniousParseError       # Oops? This sort of conflict is kinda bad.
from parsimonious.nodes import Node

from ..parse_error import ParseError, InternalError, InvalidDefinitionError
from ..data_type import BooleanType, SignedIntegerType, UnsignedIntegerType, FloatType, VoidType, DataType
from ..data_type import ArrayType, StaticArrayType, DynamicArrayType, CompoundType, UnionType, StructureType
from ..data_type import ServiceType, Attribute, Field, PaddingField, Constant, PrimitiveType, Version
from ..data_type import TypeParameterError, InvalidFixedPortIDError
from ..port_id_ranges import is_valid_regulated_subject_id, is_valid_regulated_service_id

from . import expression
from .exceptions import DSDLSyntaxError, SemanticError, InvalidOperandError, ExpressionError, UndefinedDataTypeError
from .exceptions import AssertionCheckFailureError


_GRAMMAR_DEFINITION_FILE_PATH = os.path.join(os.path.dirname(__file__), 'grammar.parsimonious')

_FULL_BIT_WIDTH_SET = list(range(1, 65))


_logger = logging.getLogger(__name__)


#
# Decorators for use with the transformer.
#
_VisitorHandler = typing.Callable[['ASTTransformer', Node, typing.Any], typing.Any]


def _logged_transformation(fun: _VisitorHandler) -> _VisitorHandler:
    """
    Simply logs the resulting transformation upon its completion.
    """
    @functools.wraps(fun)
    def wrapper(self: 'ASTTransformer', node: Node, children: typing.Any) -> typing.Any:
        result = '<TRANSFORMATION FAILED>'  # type: typing.Any
        try:
            result = fun(self, node, children)
            return result
        finally:
            _logger.debug('Transformation: %s(%s) --> %r', node.expr_name, _print_node(children), result)

    return wrapper


# Directive handler is invoked when the parser encounters a directive.
# The arguments are:
#   - Line number, one-based.
#   - Name of the directive.
#   - The result of its expression, if provided; otherwise, None.
OnDirectiveCallback = typing.Callable[[int, str, typing.Optional[expression.Any]], None]


# noinspection PyMethodMayBeStatic
class ASTTransformer(NodeVisitor):
    # Populating the default grammar (see the NodeVisitor API).
    grammar = Grammar(open(_GRAMMAR_DEFINITION_FILE_PATH).read())

    # Intentional exceptions that shall not be treated as parse errors.
    # Beware that those might be propagated from recursive parser instances!
    unwrapped_exceptions = ParseError,

    def __init__(self,
                 on_directive_callback: OnDirectiveCallback):
        self._on_directive_callback = on_directive_callback

    def generic_visit(self, node: Node, children: typing.Sequence[typing.Any]) -> typing.Any:
        """If the node has children, replace the node with them."""
        return tuple(children) or node

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
    visit_cast_mode = NodeVisitor.lift_child

    def visit_cast_mode_saturated(self, _node: Node, _children: typing.Sequence[Node]) -> PrimitiveType.CastMode:
        return PrimitiveType.CastMode.SATURATED

    def visit_cast_mode_truncated(self, _node: Node, _children: typing.Sequence[Node]) -> PrimitiveType.CastMode:
        return PrimitiveType.CastMode.TRUNCATED

    def visit_type_version(self, _node: Node, children: typing.Sequence[int]) -> Version:
        major, _, minor = children
        assert isinstance(major, expression.Rational) and isinstance(minor, expression.Rational)
        return Version(major=major.as_native_integer(),
                       minor=minor.as_native_integer())

    #
    # Names
    #
    def visit_name_component(self, node: Node, _children: typing.List) -> str:
        out = node.text
        assert isinstance(out, str) and out
        return out

    #
    # Directives
    #
    def visit_directive(self,
                        node: Node,
                        children: typing.Tuple[Node, str, typing.Union[Node, tuple]]) -> None:
        _at, name, exp = children
        assert _at.text == '@'
        assert isinstance(name, str)
        if isinstance(exp, Node):
            assert not exp.children
            exp = None
        else:
            assert isinstance(exp, tuple) and len(exp) == 1
            assert isinstance(exp[0], tuple) and len(exp[0]) == 2
            _, exp = exp[0]
            assert isinstance(exp, expression.Any)

        self._on_directive_callback(_get_line_number(node), name, exp)

    #
    # Expressions
    #
    visit_expression = NodeVisitor.lift_child
    visit_atom       = NodeVisitor.lift_child

    visit_op2_log = NodeVisitor.lift_child
    visit_op2_cmp = NodeVisitor.lift_child
    visit_op2_bit = NodeVisitor.lift_child
    visit_op2_add = NodeVisitor.lift_child
    visit_op2_mul = NodeVisitor.lift_child
    visit_op2_exp = NodeVisitor.lift_child

    @_logged_transformation
    def visit_set(self,
                  _node: Node,
                  children: typing.Tuple[Node, Node, typing.Tuple[expression.Any, ...], Node, Node]) \
            -> expression.Set:
        _, _, exp_list, _, _ = children
        assert all(map(lambda x: isinstance(x, expression.Any), exp_list))
        return expression.Set(exp_list)

    @_logged_transformation
    def visit_parenthetical(self,
                            _node: Node,
                            children: typing.Tuple[Node, Node, expression.Any, Node, Node]) -> expression.Any:
        _, _, exp, _, _ = children
        assert isinstance(exp, expression.Any)
        return exp

    @_logged_transformation
    def visit_expression_list(self,
                              _node: Node,
                              children: typing.Tuple[expression.Any,  # I feel so type safe right now
                                                     typing.Tuple[typing.Tuple[Node, Node, Node, expression.Any]]]) \
            -> typing.Tuple[expression.Any, ...]:
        assert len(children) == 2
        out = [children[0]]
        for _, _, _, exp in children[1]:
            out.append(exp)
        assert all(map(lambda x: isinstance(x, expression.Any), out))
        return tuple(out)

    def _visit_binary_operator_chain(self,
                                     _node: Node,
                                     children: typing.Tuple[expression.Any,  # I miss static typing so much right now
                                                            typing.Iterable[typing.Tuple[Node,
                                                                                         expression.BinaryOperator,
                                                                                         Node,
                                                                                         expression.Any]]]) \
            -> expression.Any:
        left = children[0]
        for _, operator, _, right in children[1]:
            assert callable(operator)
            left = operator(left, right)
        return left

    # Operators are handled through different grammar rules for precedence management purposes.
    # At the time of evaluation there is no point keeping them separate.
    visit_ex_exponential    = _visit_binary_operator_chain
    visit_ex_multiplicative = _visit_binary_operator_chain
    visit_ex_additive       = _visit_binary_operator_chain
    visit_ex_bitwise        = _visit_binary_operator_chain
    visit_ex_comparison     = _visit_binary_operator_chain
    visit_ex_logical        = _visit_binary_operator_chain

    # These are implemented via unary forms, no handling required.
    visit_ex_logical_not = NodeVisitor.lift_child
    visit_ex_inversion   = NodeVisitor.lift_child

    def visit_op1_form_log_not(self, _node: Node, children: typing.Tuple[Node, Node, expression.Any]) -> expression.Any:
        _op, _, exp = children
        assert isinstance(_op, Node) and isinstance(exp, expression.Any)
        return expression.logical_not(exp)

    def visit_op1_form_inv_pos(self, _node: Node, children: typing.Tuple[Node, Node, expression.Any]) -> expression.Any:
        _op, _, exp = children
        assert isinstance(_op, Node) and isinstance(exp, expression.Any)
        return expression.positive(exp)

    def visit_op1_form_inv_neg(self, _node: Node, children: typing.Tuple[Node, Node, expression.Any]) -> expression.Any:
        _op, _, exp = children
        assert isinstance(_op, Node) and isinstance(exp, expression.Any)
        return expression.negative(exp)

    def visit_op2_log_or(self, _n: Node, _c: list)  -> expression.BinaryOperator: return expression.logical_or
    def visit_op2_log_and(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.logical_and
    def visit_op2_cmp_equ(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.equal
    def visit_op2_cmp_neq(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.not_equal
    def visit_op2_cmp_leq(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.less_or_equal
    def visit_op2_cmp_geq(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.greater_or_equal
    def visit_op2_cmp_lss(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.less
    def visit_op2_cmp_grt(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.greater
    def visit_op2_bit_or(self, _n: Node, _c: list)  -> expression.BinaryOperator: return expression.bitwise_or
    def visit_op2_bit_xor(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.bitwise_xor
    def visit_op2_bit_and(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.bitwise_and
    def visit_op2_add_add(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.add
    def visit_op2_add_sub(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.subtract
    def visit_op2_mul_mul(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.multiply
    def visit_op2_mul_fdv(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.floor_divide
    def visit_op2_mul_div(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.divide
    def visit_op2_mul_mod(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.modulo
    def visit_op2_exp_pow(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.power

    #
    # Literals.
    #
    visit_literal = NodeVisitor.lift_child
    visit_boolean = NodeVisitor.lift_child

    def visit_real(self, node: Node, _children: typing.Sequence[Node]) -> expression.Rational:
        return expression.Rational(Fraction(node.text))

    def visit_integer(self, node: Node, _children: typing.Sequence[Node]) -> expression.Rational:
        return expression.Rational(int(node.text, base=0))

    def visit_decimal_integer(self, node: Node, _children: typing.Sequence[Node]) -> expression.Rational:
        return expression.Rational(int(node.text))

    def visit_boolean_true(self, _node: Node, _children: typing.Sequence[Node]) -> expression.Boolean:
        return expression.Boolean(True)

    def visit_boolean_false(self, _node: Node, _children: typing.Sequence[Node]) -> expression.Boolean:
        return expression.Boolean(False)

    @_logged_transformation
    def visit_string(self, node: Node, _children: typing.Sequence[Node]) -> expression.String:
        # TODO: manual handling of strings, incl. escape sequences and hex char notation
        out = eval(node.text)
        assert isinstance(out, str)
        return expression.String(out)


def _print_node(n: typing.Any) -> str:
    """Simple printing helper; the default printing method from Parsimonious is no good."""
    if isinstance(n, Node):
        return '%s=%r%s' % (
            n.expr.name or '<anonymous>',
            n.text,
            _print_node(n.children) if n.children else ''
        )
    elif isinstance(n, (list, tuple)):
        return '[%s]' % ', '.join(map(_print_node, n))
    else:
        return repr(n)


def _get_line_number(node: Node) -> int:
    """Returns the one-based line number where the specified node is located."""
    return int(node.full_text.count('\n', 0, node.start) + 1)
