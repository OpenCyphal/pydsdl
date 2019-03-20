#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os
import enum
import typing
import logging
import functools

from fractions import Fraction
from parsimonious import NodeVisitor, Grammar
from parsimonious.nodes import Node

from .frontend_error import FrontendError
from . import data_type
from . import expression


_GRAMMAR_DEFINITION_FILE_PATH = os.path.join(os.path.dirname(__file__), 'grammar.parsimonious')

_FULL_BIT_WIDTH_SET = list(range(1, 65))


_logger = logging.getLogger(__name__)


class StatementStreamProcessor:
    """
    This interface must be implemented by the logic that sits on top of the transformer.
    The methods are invoked immediately as corresponding statements are encountered within the
    processed DSDL definition.
    This interface can be used to construct a more abstract intermediate representation of the processed text.
    """
    def on_directive(self,
                     line_number: int,
                     directive_name: str,
                     associated_expression_value: typing.Optional[expression.Any]) -> None:
        raise NotImplementedError

    def on_service_response_marker(self) -> None:
        """The correctness of the marker placement is not validated by the caller."""
        raise NotImplementedError

    def resolve_top_level_identifier(self, name: str) -> expression.Any:
        """Must throw an appropriate exception if the reference cannot be resolved."""
        raise NotImplementedError

    def resolve_versioned_data_type(self, name: str, version: data_type.Version) -> data_type.CompoundType:
        """Must throw an appropriate exception if the data type is not found."""
        raise NotImplementedError


#
# Decorators for use with the transformer.
#
_VisitorHandler = typing.Callable[['ParseTreeTransformer', Node, typing.Any], typing.Any]


def _logged_transformation(fun: _VisitorHandler) -> _VisitorHandler:
    """
    Simply logs the resulting transformation upon its completion.
    """
    @functools.wraps(fun)
    def wrapper(self: 'ParseTreeTransformer', node: Node, children: typing.Any) -> typing.Any:
        result = '<TRANSFORMATION FAILED>'  # type: typing.Any
        try:
            result = fun(self, node, children)
            return result
        finally:
            _logger.debug('Transformation: %s(%s) --> %r', node.expr_name, _print_node(children), result)

    return wrapper


# noinspection PyMethodMayBeStatic
class ParseTreeTransformer(NodeVisitor):
    # Populating the default grammar (see the NodeVisitor API).
    grammar = Grammar(open(_GRAMMAR_DEFINITION_FILE_PATH).read())

    # Intentional exceptions that shall not be treated as parse errors.
    # Beware that those might be propagated from recursive parser instances!
    unwrapped_exceptions = FrontendError,

    def __init__(self, statement_stream_processor: StatementStreamProcessor):
        assert isinstance(statement_stream_processor, StatementStreamProcessor)
        self._statement_stream_processor = statement_stream_processor   # type: StatementStreamProcessor

    def generic_visit(self, node: Node, children: typing.Sequence[typing.Any]) -> typing.Any:
        """If the node has children, replace the node with them."""
        return tuple(children) or node

    # ================================================= Core elements ================================================

    def visit_identifier(self, node: Node, _children: typing.Tuple) -> str:
        assert isinstance(node.text, str) and node.text
        return node.text

    def visit_statement_service_response_marker(self, _node: Node, _children: typing.Tuple) -> None:
        self._statement_stream_processor.on_service_response_marker()

    # ================================================== Data types ==================================================

    def visit_type_version_specifier(self, _node: Node, children: typing.Sequence[int]) -> data_type.Version:
        major, _, minor = children
        assert isinstance(major, expression.Rational) and isinstance(minor, expression.Rational)
        return data_type.Version(major=major.as_native_integer(),
                                 minor=minor.as_native_integer())

    # ================================================== Expressions ==================================================

    visit_expression = NodeVisitor.lift_child

    visit_op2_log = NodeVisitor.lift_child
    visit_op2_cmp = NodeVisitor.lift_child
    visit_op2_bit = NodeVisitor.lift_child
    visit_op2_add = NodeVisitor.lift_child
    visit_op2_mul = NodeVisitor.lift_child
    visit_op2_exp = NodeVisitor.lift_child

    def visit_expression_list(self, _node: Node, children: tuple) -> typing.Tuple[expression.Any, ...]:
        out = []    # type: typing.List[expression.Any]
        if children:
            children = children[0]
            assert len(children) == 2
            out = [children[0]]
            for _, _, _, exp in children[1]:
                out.append(exp)

        assert all(map(lambda x: isinstance(x, expression.Any), out))
        return tuple(out)

    @_logged_transformation
    def visit_expression_parenthesized(self, _node: Node, children: tuple) -> expression.Any:
        _, _, exp, _, _ = children
        assert isinstance(exp, expression.Any)
        return exp

    def visit_expression_atom(self, _node: Node, children: tuple) -> expression.Any:
        atom, = children
        if isinstance(atom, str):   # Identifier resolution
            atom = self._statement_stream_processor.resolve_top_level_identifier(atom)

        assert isinstance(atom, expression.Any)
        return atom

    def _visit_binary_operator_chain(self, _node: Node, children: tuple) -> expression.Any:
        left = children[0]
        for _, operator, _, right in children[1]:
            assert callable(operator)
            left = operator(left, right)
        return left

    # Operators are handled through different grammar rules for precedence management purposes.
    # At the time of evaluation there is no point keeping them separate.
    visit_ex_attribute      = _visit_binary_operator_chain
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
    def visit_op2_mul_div(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.divide
    def visit_op2_mul_mod(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.modulo
    def visit_op2_exp_pow(self, _n: Node, _c: list) -> expression.BinaryOperator: return expression.power
    def visit_op2_attrib(self, _n: Node, _c: list)  -> expression.BinaryOperator: return expression.attribute

    # ================================================== Literals ==================================================

    visit_literal         = NodeVisitor.lift_child
    visit_literal_boolean = NodeVisitor.lift_child
    visit_literal_string  = NodeVisitor.lift_child

    @_logged_transformation
    def visit_literal_set(self, _node: Node, children: tuple) -> expression.Set:
        _, _, exp_list, _, _ = children
        assert all(map(lambda x: isinstance(x, expression.Any), exp_list))
        return expression.Set(exp_list)

    def visit_literal_real(self, node: Node, _children: typing.Sequence[Node]) -> expression.Rational:
        return expression.Rational(Fraction(node.text))

    def visit_literal_integer(self, node: Node, _children: typing.Sequence[Node]) -> expression.Rational:
        return expression.Rational(int(node.text, base=0))

    def visit_literal_integer_decimal(self, node: Node, _children: typing.Sequence[Node]) -> expression.Rational:
        return expression.Rational(int(node.text))

    def visit_literal_boolean_true(self, _node: Node, _children: typing.Sequence[Node]) -> expression.Boolean:
        return expression.Boolean(True)

    def visit_literal_boolean_false(self, _node: Node, _children: typing.Sequence[Node]) -> expression.Boolean:
        return expression.Boolean(False)

    @_logged_transformation
    def visit_literal_string_single_quoted(self, node: Node, _children: typing.Sequence[Node]) -> expression.String:
        # TODO: manual handling of strings, incl. escape sequences and hex char notation
        return expression.String(eval(node.text))

    @_logged_transformation
    def visit_literal_string_double_quoted(self, node: Node, _children: typing.Sequence[Node]) -> expression.String:
        # TODO: manual handling of strings, incl. escape sequences and hex char notation
        return expression.String(eval(node.text))


#
# Internal helper functions.
#
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
