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


# Basic atomic value types used by the expression evaluation logic.
_Primitive = typing.Union[
    bool,               # Boolean expressions
    Fraction,           # Integer and real-typed expressions
    str,
]

# All possible expression types; this includes container types.
Expression = typing.Union[
    _Primitive,
    # We have to use Any with containers because MyPy does not yet support recursive types.
    typing.FrozenSet[typing.Any],
]

# For some weird reason the typing constructs can't be used with isinstance(), so we have to do this:
_EXPRESSION_TYPES = bool, Fraction, str, frozenset


_TypeList = typing.Union[type, typing.Tuple[type, ...]]

# Directive handler is invoked when the parser encounters a directive.
# The arguments are:
#   - Line number, one-based.
#   - Name of the directive.
#   - The result of its expression, if provided; otherwise, None.
DirectiveHandler = typing.Callable[[int, str, typing.Optional[Expression]], None]


# noinspection PyMethodMayBeStatic
class ASTTransformer(NodeVisitor):
    # Populating the default grammar (see the NodeVisitor API).
    grammar = Grammar(open(_GRAMMAR_DEFINITION_FILE_PATH).read())

    # Intentional exceptions that shall not be treated as parse errors.
    # Beware that those might be propagated from recursive parser instances!
    unwrapped_exceptions = ParseError,

    def __init__(self,
                 on_directive: DirectiveHandler):
        self._on_directive = on_directive

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
        assert isinstance(children[0], Fraction) and isinstance(children[2], Fraction)
        major, _, minor = children
        return Version(major=int(major), minor=int(minor))

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
            assert isinstance(exp, _EXPRESSION_TYPES)

        self._on_directive(_get_line_number(node), name, exp)

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
                  children: typing.Tuple[Node, Node, typing.Tuple[Expression, ...], Node, Node]) \
            -> typing.FrozenSet[Expression]:
        _, _, exp_list, _, _ = children
        if len(set(map(type, exp_list))) > 1:
            raise InvalidOperandError('Heterogeneous sets are not allowed')
        return frozenset(exp_list)

    @_logged_transformation
    def visit_parenthetical(self,
                            _node: Node,
                            children: typing.Tuple[Node, Node, Expression, Node, Node]) -> Expression:
        _, _, exp, _, _ = children
        assert isinstance(exp, _EXPRESSION_TYPES)
        return exp

    @_logged_transformation
    def visit_expression_list(self,
                              _node: Node,
                              children: typing.Tuple[Expression, typing.Tuple[Node, ...]]) -> \
            typing.Tuple[Expression, ...]:
        assert len(children) == 2
        out = [children[0]]
        assert isinstance(out[0], _EXPRESSION_TYPES)
        for _, _, _, exp in children[1]:
            assert isinstance(exp, _EXPRESSION_TYPES)
            out.append(exp)
        return tuple(out)

    def _visit_binary_operator_chain(self, _node: Node, children: typing.Tuple[Expression, Node]) -> Expression:
        left = children[0]
        for _, op, _, right in children[1]:
            assert isinstance(op, str)
            left = _apply_binary_operator(op, left, right)
        return left

    # Operators are handled through different grammar rules for precedence management purposes.
    # At the time of evaluation there is no point keeping them separate.
    visit_ex_multiplicative = _visit_binary_operator_chain
    visit_ex_additive       = _visit_binary_operator_chain
    visit_ex_bitwise        = _visit_binary_operator_chain
    visit_ex_comparison     = _visit_binary_operator_chain
    visit_ex_logical        = _visit_binary_operator_chain

    # These are implemented via unary forms, no handling required.
    visit_ex_logical_not = NodeVisitor.lift_child
    visit_ex_inversion   = NodeVisitor.lift_child

    def visit_op1_form_log_not(self, _node: Node, children: typing.Tuple[Node, Node, Expression]) -> Expression:
        _op, _, exp = children
        assert isinstance(_op, Node) and isinstance(exp, _EXPRESSION_TYPES)
        if isinstance(exp, bool):
            return not exp
        else:
            raise InvalidOperandError('Unsupported operand type for logical not: %r' % type(exp))

    def visit_op1_form_inv_pos(self, _node: Node, children: typing.Tuple[Node, Node, Expression]) -> Expression:
        _op, _, exp = children
        assert isinstance(_op, Node) and isinstance(exp, _EXPRESSION_TYPES)
        return _apply_binary_operator('*', Fraction(+1), exp)

    def visit_op1_form_inv_neg(self, _node: Node, children: typing.Tuple[Node, Node, Expression]) -> Expression:
        _op, _, exp = children
        assert isinstance(_op, Node) and isinstance(exp, _EXPRESSION_TYPES)
        return _apply_binary_operator('*', Fraction(-1), exp)

    def visit_ex_exponential(self, _node: Node, children: typing.Tuple[Expression, Node]) -> Expression:
        if list(children[1]):
            base, exponent = children[0], children[1][0][-1]
            return _apply_binary_operator('**', base, exponent)
        else:
            return children[0]  # Pass through

    def visit_op2_log_or(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return "||"

    def visit_op2_log_and(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return "&&"

    def visit_op2_cmp_equ(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return "=="

    def visit_op2_cmp_neq(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return "!="

    def visit_op2_cmp_leq(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return "<="

    def visit_op2_cmp_geq(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return ">="

    def visit_op2_cmp_lss(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return "<"

    def visit_op2_cmp_grt(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return ">"

    def visit_op2_bit_or(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return "|"

    def visit_op2_bit_xor(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return "^"

    def visit_op2_bit_and(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return "&"

    def visit_op2_add_add(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return "+"

    def visit_op2_add_sub(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return "-"

    def visit_op2_mul_mul(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return "*"

    def visit_op2_mul_fdv(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return "//"

    def visit_op2_mul_tdv(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return "/"

    def visit_op2_mul_mod(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return "%"

    def visit_op2_exp_pow(self, _node: Node, _children: typing.Sequence[Node]) -> str:
        return "**"

    #
    # Literals. All arithmetic values are represented internally as rationals.
    #
    visit_literal = NodeVisitor.lift_child
    visit_boolean = NodeVisitor.lift_child

    def visit_real(self, node: Node, _children: typing.Sequence[Node]) -> Fraction:
        return Fraction(node.text)

    def visit_integer(self, node: Node, _children: typing.Sequence[Node]) -> Fraction:
        return Fraction(int(node.text, base=0))

    def visit_decimal_integer(self, node: Node, _children: typing.Sequence[Node]) -> Fraction:
        return Fraction(int(node.text))

    def visit_boolean_true(self, _node: Node, _children: typing.Sequence[Node]) -> bool:
        return True

    def visit_boolean_false(self, _node: Node, _children: typing.Sequence[Node]) -> bool:
        return False

    @_logged_transformation
    def visit_string(self, node: Node, _children: typing.Sequence[Node]) -> str:
        # TODO: manual handling of strings, incl. escape sequences and hex char notation
        out = eval(node.text)
        assert isinstance(out, str)
        return out


def _apply_binary_operator(operator_symbol: str, left: Expression, right: Expression) -> Expression:
    """
    This function implements all binary operators defined for constant expressions.
    Operators of other arity metrics are handled differently.
    """
    # If either of the below assertions fail, we're processing the tree improperly. Useful for development.
    assert isinstance(left, _EXPRESSION_TYPES)
    assert isinstance(right, _EXPRESSION_TYPES)
    try:
        if isinstance(left, frozenset) and isinstance(right, frozenset):  # (set, set) -> (set|bool)
            result = {
                # Set algebra; yields set
                '|': lambda a, b: frozenset(a | b),  # Union
                '&': lambda a, b: frozenset(a & b),  # Intersection
                '^': lambda a, b: frozenset(a ^ b),  # Unique
                # Set algebra; yields bool
                '<': lambda a, b: a < b,    # A is a proper subset of B
                '>': lambda a, b: a > b,    # A is a proper superset of B
                '<=': lambda a, b: a <= b,  # A is a subset of B
                '>=': lambda a, b: a >= b,  # A is a superset of B
                # Comparison; yields bool
                '==': lambda a, b: a == b,
                '!=': lambda a, b: a != b,
            }[operator_symbol](left, right)
            assert isinstance(result, (bool, frozenset))
            return result

        if isinstance(left, bool) and isinstance(right, bool):  # (bool, bool) -> bool
            result = {
                '||': lambda a, b: a or b,
                '&&': lambda a, b: a and b,
                '==': lambda a, b: a == b,
                '!=': lambda a, b: a != b,
            }[operator_symbol](left, right)
            assert isinstance(result, bool)
            return result

        if isinstance(left, Fraction) and isinstance(right, Fraction):  # (rational, rational) -> (rational|bool)
            result = {
                # Comparison operators yield bool
                '==': lambda a, b: a == b,
                '>=': lambda a, b: a >= b,
                '<=': lambda a, b: a <= b,
                '!=': lambda a, b: a != b,
                '<': lambda a, b: a < b,
                '>': lambda a, b: a > b,
                # Bitwise operators yield an integral fraction; fail if any of the operands is not an integer
                '|': lambda a, b: Fraction(_as_integer(a) | _as_integer(b)),
                '^': lambda a, b: Fraction(_as_integer(a) ^ _as_integer(b)),
                '&': lambda a, b: Fraction(_as_integer(a) & _as_integer(b)),
                # Arithmetic operators accept any fractions
                '+': lambda a, b: Fraction(a + b),
                '-': lambda a, b: Fraction(a - b),
                '%': lambda a, b: Fraction(a % b),
                '*': lambda a, b: Fraction(a * b),
                '/': lambda a, b: Fraction(a / b),
                '//': lambda a, b: Fraction(a // b),
                '**': lambda a, b: Fraction(a ** b),
            }[operator_symbol](left, right)
            assert isinstance(result, (bool, Fraction))
            return result

        if isinstance(left, str) and isinstance(right, str):  # (str, str) -> (str|bool)
            result = {
                # Creational, yields str
                '+': lambda a, b: a + b,
                # Comparison, yields bool
                '==': lambda a, b: a == b,
                '!=': lambda a, b: a != b,
            }[operator_symbol](left, right)
            assert isinstance(result, (bool, str))
            return result

        # Left/right side elementwise expansion; support for other containers may be added later.
        if isinstance(left, frozenset):  # (set, any) -> set
            return frozenset({_apply_binary_operator(operator_symbol, x, right) for x in left})
        if isinstance(right, frozenset):  # (set, any) -> set
            return frozenset({_apply_binary_operator(operator_symbol, left, x) for x in right})

        raise KeyError
    except KeyError:
        raise InvalidOperandError('Binary operator %r is not defined for: %s, %s' %
                                  (operator_symbol, left, right))
    except ZeroDivisionError:
        raise InvalidOperandError('Division by zero')


def _as_integer(value: Expression) -> int:
    if isinstance(value, Fraction) and value.denominator == 1:
        return value.numerator
    else:
        raise InvalidOperandError('Expected an integer, found this: %s' % value)


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
