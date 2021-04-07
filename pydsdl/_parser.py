# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import os
import typing
import logging
import itertools
import functools
import fractions
import parsimonious
from parsimonious.nodes import Node as _Node
from . import _error
from . import _serializable
from . import _expression


class DSDLSyntaxError(_error.InvalidDefinitionError):
    pass


def parse(text: str, statement_stream_processor: "StatementStreamProcessor") -> None:
    """
    The entry point of the parser. As the text is being parsed, the parser invokes appropriate
    methods in the statement stream processor.
    """
    pr = _ParseTreeProcessor(statement_stream_processor)
    try:
        pr.visit(_get_grammar().parse(text))  # type: ignore
    except _error.FrontendError as ex:
        # Inject error location. If this exception is being propagated from a recursive instance, it already has
        # its error location populated, so nothing will happen here.
        ex.set_error_location_if_unknown(line=pr.current_line_number)
        raise ex
    except parsimonious.ParseError as ex:
        raise DSDLSyntaxError("Syntax error", line=int(ex.line())) from None  # type: ignore
    except parsimonious.VisitationError as ex:  # pragma: no cover
        # noinspection PyBroadException
        try:
            line = int(ex.original_class.line())
        except Exception:  # pylint: disable=broad-except
            line = pr.current_line_number
        # Treat as internal because all intentional errors are not wrapped into VisitationError.
        assert line > 0
        raise _error.InternalError(str(ex), line=line) from ex


class StatementStreamProcessor:
    """
    This interface must be implemented by the logic that sits on top of the transformer.
    The methods are invoked immediately as corresponding statements are encountered within the
    processed DSDL definition.
    This interface can be used to construct a more abstract intermediate representation of the processed text.
    """

    def on_header_comment(self, comment: str) -> None:
        raise NotImplementedError  # pragma: no cover

    def on_attribute_comment(self, comment: str) -> None:
        raise NotImplementedError  # pragma: no cover

    def on_constant(self, constant_type: _serializable.SerializableType, name: str, value: _expression.Any) -> None:
        raise NotImplementedError  # pragma: no cover

    def on_field(self, field_type: _serializable.SerializableType, name: str) -> None:
        raise NotImplementedError  # pragma: no cover

    def on_padding_field(self, padding_field_type: _serializable.VoidType) -> None:
        raise NotImplementedError  # pragma: no cover

    def on_directive(
        self, line_number: int, directive_name: str, associated_expression_value: typing.Optional[_expression.Any]
    ) -> None:
        raise NotImplementedError  # pragma: no cover

    def on_service_response_marker(self) -> None:
        """The correctness of the marker placement is not validated by the caller."""
        raise NotImplementedError  # pragma: no cover

    def resolve_top_level_identifier(self, name: str) -> _expression.Any:
        """Must throw an appropriate exception if the reference cannot be resolved."""
        raise NotImplementedError  # pragma: no cover

    def resolve_versioned_data_type(self, name: str, version: _serializable.Version) -> _serializable.CompositeType:
        """Must throw an appropriate exception if the data type is not found."""
        raise NotImplementedError  # pragma: no cover


@functools.lru_cache(None)
def _get_grammar() -> parsimonious.Grammar:
    with open(os.path.join(os.path.dirname(__file__), "grammar.parsimonious")) as _grammar_file:
        return parsimonious.Grammar(_grammar_file.read())  # type: ignore


_logger = logging.getLogger(__name__)


_Children = typing.Tuple[typing.Any, ...]
_VisitorHandler = typing.Callable[["_ParseTreeProcessor", _Node, _Children], typing.Any]
_PrimitiveTypeConstructor = typing.Callable[[_serializable.PrimitiveType.CastMode], _serializable.PrimitiveType]


def _make_typesafe_child_lifter(expected_type: typing.Type[object]) -> _VisitorHandler:
    def visitor_handler(_self: "_ParseTreeProcessor", _n: _Node, children: _Children) -> typing.Any:
        (sole_child,) = children
        assert isinstance(sole_child, expected_type), "The child should have been of type %r, not %r: %r" % (
            expected_type,
            type(sole_child),
            sole_child,
        )
        return sole_child

    return visitor_handler


def _make_binary_operator_handler(operator: _expression.BinaryOperator[_expression.OperatorOutput]) -> _VisitorHandler:
    return lambda _self, _node, _children: operator


# noinspection PyMethodMayBeStatic
class _ParseTreeProcessor(parsimonious.NodeVisitor):
    """
    This class processes the parse tree, evaluates the expressions and emits a high-level representation
    of the processed description. Essentially it does most of the ground work related to supporting the DSDL
    language, which is bad because it makes the class unnecessarily complex and hard to maintain. Shall it be
    needed to extend the language, please consider refactoring the logic by adding an intermediate abstract
    syntax tree in order to separate the semantic analysis from the grammar-related logic. If that is done,
    expression evaluation will be performed at the AST level rather than at the parse tree level, as it is
    done currently.
    """

    # Intentional exceptions that shall not be treated as parse errors.
    # Beware that those might be propagated from recursive parser instances!
    unwrapped_exceptions = (_error.FrontendError, SystemError, MemoryError, SystemExit)  # type: ignore

    def __init__(self, statement_stream_processor: StatementStreamProcessor):
        assert isinstance(statement_stream_processor, StatementStreamProcessor)
        self._statement_stream_processor = statement_stream_processor  # type: StatementStreamProcessor
        self._current_line_number = 1  # Lines are numbered from one
        self._comment = ""
        self._comment_is_header = True
        super().__init__()

    @property
    def current_line_number(self) -> int:
        assert self._current_line_number > 0
        return self._current_line_number

    # Misc. helpers
    def _flush_comment(self) -> None:
        if self._comment_is_header:
            self._statement_stream_processor.on_header_comment(self._comment)
        else:
            self._statement_stream_processor.on_attribute_comment(self._comment)
        self._comment_is_header = False
        self._comment = ""

    def generic_visit(self, node: _Node, children: typing.Sequence[typing.Any]) -> typing.Any:
        """If the node has children, replace the node with them."""
        return tuple(children) or node

    def visit_line(self, node: _Node, children: _Children) -> None:
        if len(node.text) == 0:
            # Line is empty, flush comment
            self._flush_comment()

    def visit_end_of_line(self, _n: _Node, _c: _Children) -> None:
        self._current_line_number += 1

    # ================================================== Statements ==================================================

    visit_statement = _make_typesafe_child_lifter(type(None))  # Make sure all sub-nodes have been handled,
    visit_statement_attribute = _make_typesafe_child_lifter(type(None))  # because processing terminates here; these
    visit_statement_directive = _make_typesafe_child_lifter(type(None))  # nodes are above the top level.

    def visit_comment(self, node: _Node, children: _Children) -> None:
        assert isinstance(node.text, str)
        self._comment += "\n" if self._comment != "" else ""
        self._comment += node.text[2:] if node.text.startswith("# ") else node.text[1:]

    def visit_statement_constant(self, _n: _Node, children: _Children) -> None:
        constant_type, _sp0, name, _sp1, _eq, _sp2, exp = children
        assert isinstance(constant_type, _serializable.SerializableType) and isinstance(name, str) and name
        assert isinstance(exp, _expression.Any)
        self._flush_comment()
        self._statement_stream_processor.on_constant(constant_type, name, exp)

    def visit_statement_field(self, _n: _Node, children: _Children) -> None:
        field_type, _space, name = children
        assert isinstance(field_type, _serializable.SerializableType) and isinstance(name, str) and name
        self._flush_comment()
        self._statement_stream_processor.on_field(field_type, name)

    def visit_statement_padding_field(self, _n: _Node, children: _Children) -> None:
        void_type = children[0]
        assert isinstance(void_type, _serializable.VoidType)
        self._flush_comment()
        self._statement_stream_processor.on_padding_field(void_type)

    def visit_statement_service_response_marker(self, _n: _Node, _c: _Children) -> None:
        self._flush_comment()
        self._comment_is_header = True  # Allow response header comment
        self._statement_stream_processor.on_service_response_marker()

    def visit_statement_directive_with_expression(self, _n: _Node, children: _Children) -> None:
        _at, name, _space, exp = children
        assert isinstance(name, str) and name and isinstance(exp, _expression.Any)
        self._flush_comment()
        self._statement_stream_processor.on_directive(
            line_number=self.current_line_number, directive_name=name, associated_expression_value=exp
        )

    def visit_statement_directive_without_expression(self, _n: _Node, children: _Children) -> None:
        _at, name = children
        assert isinstance(name, str) and name
        self._flush_comment()
        self._statement_stream_processor.on_directive(
            line_number=self.current_line_number, directive_name=name, associated_expression_value=None
        )

    def visit_identifier(self, node: _Node, _c: _Children) -> str:
        assert isinstance(node.text, str) and node.text
        self._flush_comment()
        return node.text

    # ================================================== Data types ==================================================

    visit_type = _make_typesafe_child_lifter(_serializable.SerializableType)
    visit_type_array = _make_typesafe_child_lifter(_serializable.ArrayType)
    visit_type_scalar = _make_typesafe_child_lifter(_serializable.SerializableType)
    visit_type_primitive = _make_typesafe_child_lifter(_serializable.PrimitiveType)

    visit_type_primitive_name = parsimonious.NodeVisitor.lift_child

    def visit_type_array_variable_inclusive(
        self, _n: _Node, children: _Children
    ) -> _serializable.VariableLengthArrayType:
        element_type, _s0, _bl, _s1, _op, _s2, length, _s3, _br = children
        return _serializable.VariableLengthArrayType(element_type, _unwrap_array_capacity(length))

    def visit_type_array_variable_exclusive(
        self, _n: _Node, children: _Children
    ) -> _serializable.VariableLengthArrayType:
        element_type, _s0, _bl, _s1, _op, _s2, length, _s3, _br = children
        return _serializable.VariableLengthArrayType(element_type, _unwrap_array_capacity(length) - 1)

    def visit_type_array_fixed(self, _n: _Node, children: _Children) -> _serializable.FixedLengthArrayType:
        element_type, _s0, _bl, _s1, length, _s2, _br = children
        return _serializable.FixedLengthArrayType(element_type, _unwrap_array_capacity(length))

    def visit_type_versioned(self, _n: _Node, children: _Children) -> _serializable.CompositeType:
        name, name_tail, _, version = children
        assert isinstance(name, str) and name and isinstance(version, _serializable.Version)
        for _, component in name_tail:
            assert isinstance(component, str)
            name += _serializable.CompositeType.NAME_COMPONENT_SEPARATOR + component

        return self._statement_stream_processor.resolve_versioned_data_type(name, version)

    def visit_type_version_specifier(self, _n: _Node, children: _Children) -> _serializable.Version:
        major, _, minor = children
        assert isinstance(major, _expression.Rational) and isinstance(minor, _expression.Rational)
        return _serializable.Version(major=major.as_native_integer(), minor=minor.as_native_integer())

    def visit_type_primitive_truncated(self, _n: _Node, children: _Children) -> _serializable.PrimitiveType:
        _kw, _sp, cons = children  # type: _Node, _Node, _PrimitiveTypeConstructor
        return cons(_serializable.PrimitiveType.CastMode.TRUNCATED)

    def visit_type_primitive_saturated(self, _n: _Node, children: _Children) -> _serializable.PrimitiveType:
        _, cons = children  # type: _Node, _PrimitiveTypeConstructor
        return cons(_serializable.PrimitiveType.CastMode.SATURATED)

    def visit_type_primitive_name_boolean(self, _n: _Node, _c: _Children) -> _PrimitiveTypeConstructor:
        return typing.cast(_PrimitiveTypeConstructor, _serializable.BooleanType)

    def visit_type_primitive_name_unsigned_integer(self, _n: _Node, children: _Children) -> _PrimitiveTypeConstructor:
        return lambda cm: _serializable.UnsignedIntegerType(children[-1], cm)

    def visit_type_primitive_name_signed_integer(self, _n: _Node, children: _Children) -> _PrimitiveTypeConstructor:
        return lambda cm: _serializable.SignedIntegerType(children[-1], cm)

    def visit_type_primitive_name_floating_point(self, _n: _Node, children: _Children) -> _PrimitiveTypeConstructor:
        return lambda cm: _serializable.FloatType(children[-1], cm)

    def visit_type_void(self, _n: _Node, children: _Children) -> _serializable.VoidType:
        _, width = children
        assert isinstance(width, int)
        return _serializable.VoidType(width)

    def visit_type_bit_length_suffix(self, node: _Node, _c: _Children) -> int:
        return int(node.text)

    # ================================================== Expressions ==================================================

    visit_expression = parsimonious.NodeVisitor.lift_child

    visit_op2_log = parsimonious.NodeVisitor.lift_child
    visit_op2_cmp = parsimonious.NodeVisitor.lift_child
    visit_op2_bit = parsimonious.NodeVisitor.lift_child
    visit_op2_add = parsimonious.NodeVisitor.lift_child
    visit_op2_mul = parsimonious.NodeVisitor.lift_child
    visit_op2_exp = parsimonious.NodeVisitor.lift_child

    def visit_expression_list(self, _n: _Node, children: _Children) -> typing.Tuple[_expression.Any, ...]:
        out = []  # type: typing.List[_expression.Any]
        if children:
            children = children[0]
            assert len(children) == 2
            out = [children[0]]
            for _, _, _, exp in children[1]:
                out.append(exp)

        assert all(map(lambda x: isinstance(x, _expression.Any), out))
        return tuple(out)

    def visit_expression_parenthesized(self, _n: _Node, children: _Children) -> _expression.Any:
        _, _, exp, _, _ = children
        assert isinstance(exp, _expression.Any)
        return exp

    def visit_expression_atom(self, _n: _Node, children: _Children) -> _expression.Any:
        (atom,) = children
        if isinstance(atom, str):  # Identifier resolution
            new_atom = self._statement_stream_processor.resolve_top_level_identifier(atom)
            if not isinstance(new_atom, _expression.Any):
                raise _error.InternalError(
                    "Identifier %r resolved as %r, expected expression" % (atom, type(new_atom))
                )  # pragma: no cover
            atom = new_atom
            del new_atom

        assert isinstance(atom, _expression.Any)
        return atom

    def _visit_binary_operator_chain(self, _n: _Node, children: _Children) -> _expression.Any:
        left = children[0]
        assert isinstance(left, _expression.Any)
        for _, operator, _, right in children[1]:
            assert callable(operator)
            left = operator(left, right)
            assert isinstance(left, _expression.Any)
        return left

    # Operators are handled through different grammar rules for precedence management purposes.
    # At the time of evaluation there is no point keeping them separate.
    visit_ex_attribute = _visit_binary_operator_chain
    visit_ex_exponential = _visit_binary_operator_chain
    visit_ex_multiplicative = _visit_binary_operator_chain
    visit_ex_additive = _visit_binary_operator_chain
    visit_ex_bitwise = _visit_binary_operator_chain
    visit_ex_comparison = _visit_binary_operator_chain
    visit_ex_logical = _visit_binary_operator_chain

    # These are implemented via unary forms, no handling required.
    visit_ex_logical_not = parsimonious.NodeVisitor.lift_child
    visit_ex_inversion = parsimonious.NodeVisitor.lift_child

    def visit_op1_form_log_not(self, _n: _Node, children: _Children) -> _expression.Any:
        _op, _, exp = children
        assert isinstance(_op, _Node) and isinstance(exp, _expression.Any)
        return _expression.logical_not(exp)

    def visit_op1_form_inv_pos(self, _n: _Node, children: _Children) -> _expression.Any:
        _op, _, exp = children
        assert isinstance(_op, _Node) and isinstance(exp, _expression.Any)
        return _expression.positive(exp)

    def visit_op1_form_inv_neg(self, _n: _Node, children: _Children) -> _expression.Any:
        _op, _, exp = children
        assert isinstance(_op, _Node) and isinstance(exp, _expression.Any)
        return _expression.negative(exp)

    visit_op2_log_or = _make_binary_operator_handler(_expression.logical_or)
    visit_op2_log_and = _make_binary_operator_handler(_expression.logical_and)
    visit_op2_cmp_equ = _make_binary_operator_handler(_expression.equal)
    visit_op2_cmp_neq = _make_binary_operator_handler(_expression.not_equal)
    visit_op2_cmp_leq = _make_binary_operator_handler(_expression.less_or_equal)
    visit_op2_cmp_geq = _make_binary_operator_handler(_expression.greater_or_equal)
    visit_op2_cmp_lss = _make_binary_operator_handler(_expression.less)
    visit_op2_cmp_grt = _make_binary_operator_handler(_expression.greater)
    visit_op2_bit_or = _make_binary_operator_handler(_expression.bitwise_or)
    visit_op2_bit_xor = _make_binary_operator_handler(_expression.bitwise_xor)
    visit_op2_bit_and = _make_binary_operator_handler(_expression.bitwise_and)
    visit_op2_add_add = _make_binary_operator_handler(_expression.add)
    visit_op2_add_sub = _make_binary_operator_handler(_expression.subtract)
    visit_op2_mul_mul = _make_binary_operator_handler(_expression.multiply)
    visit_op2_mul_div = _make_binary_operator_handler(_expression.divide)
    visit_op2_mul_mod = _make_binary_operator_handler(_expression.modulo)
    visit_op2_exp_pow = _make_binary_operator_handler(_expression.power)

    def visit_op2_attrib(self, _n: _Node, _c: _Children) -> _expression.AttributeOperator[_expression.Any]:
        return _expression.attribute

    # ================================================== Literals ==================================================

    visit_literal = _make_typesafe_child_lifter(_expression.Any)
    visit_literal_boolean = _make_typesafe_child_lifter(_expression.Boolean)
    visit_literal_string = _make_typesafe_child_lifter(_expression.String)

    def visit_literal_set(self, _n: _Node, children: _Children) -> _expression.Set:
        _, _, exp_list, _, _ = children
        assert all(map(lambda x: isinstance(x, _expression.Any), exp_list))
        return _expression.Set(exp_list)

    def visit_literal_real(self, node: _Node, _c: _Children) -> _expression.Rational:
        return _expression.Rational(fractions.Fraction(node.text.replace("_", "")))

    def visit_literal_integer(self, node: _Node, _c: _Children) -> _expression.Rational:
        return _expression.Rational(int(node.text.replace("_", ""), base=0))

    def visit_literal_integer_decimal(self, node: _Node, _c: _Children) -> _expression.Rational:
        return _expression.Rational(int(node.text.replace("_", "")))

    def visit_literal_boolean_true(self, _n: _Node, _c: _Children) -> _expression.Boolean:
        return _expression.Boolean(True)

    def visit_literal_boolean_false(self, _n: _Node, _c: _Children) -> _expression.Boolean:
        return _expression.Boolean(False)

    def visit_literal_string_single_quoted(self, node: _Node, _c: _Children) -> _expression.String:
        return _parse_string_literal(node.text)

    def visit_literal_string_double_quoted(self, node: _Node, _c: _Children) -> _expression.String:
        return _parse_string_literal(node.text)


#
# Internal helper functions.
#
def _unwrap_array_capacity(ex: _expression.Any) -> int:
    assert isinstance(ex, _expression.Any)
    if isinstance(ex, _expression.Rational):
        out = ex.as_native_integer()
        assert isinstance(out, int)  # Oh mypy, why are you so weird
        return out
    raise _error.InvalidDefinitionError("Array capacity expression must yield a rational, not %s" % ex.TYPE_NAME)


def _parse_string_literal(literal: str) -> _expression.String:
    assert literal[0] == literal[-1]
    assert literal[0] in "'\""
    assert len(literal) >= 2

    quote_symbol = literal[0]
    iterator = iter(literal[1:-1])

    def _next_symbol() -> str:
        try:
            s = next(iterator)  # type: str
        except StopIteration:
            return ""

        if s != "\\":
            assert s != quote_symbol, "Unescaped quotes cannot appear inside string literals. Bad grammar?"
            return s

        s = next(iterator)
        if s in "uU":
            h = ""
            for _ in range(4 if s.islower() else 8):
                s = next(iterator).lower()
                if s not in "0123456789abcdef":
                    raise DSDLSyntaxError("Invalid hex character: %r" % s)
                h += s
            return chr(int(h, 16))

        try:
            return {
                "r": "\r",
                "n": "\n",
                "t": "\t",
                '"': '"',
                "'": "'",
                "\\": "\\",
            }[s.lower()]
        except KeyError:
            raise DSDLSyntaxError("Invalid escape sequence") from None

    out = ""
    for index in itertools.count():  # pragma: no branch
        try:
            symbol = _next_symbol()
        except DSDLSyntaxError as ex:
            raise DSDLSyntaxError("The string literal is malformed after index %d: %s" % (index, ex.text)) from None
        except StopIteration:
            raise DSDLSyntaxError("Unexpected end of string literal after index %d" % index) from None
        else:
            if len(symbol) == 0:
                break
            assert len(symbol) == 1
            out += symbol

    return _expression.String(out)


def _unittest_parse_string_literal() -> None:
    from pytest import raises

    def once(literal: str, value: str) -> None:
        assert _parse_string_literal(literal).native_value == value

    def auto_repr(text: str) -> None:
        r = repr(text)
        for x in range(256):
            r = r.replace(r"\x%02x" % x, r"\u00%02x" % x)
        once(r, text)

    auto_repr("")
    auto_repr("123")
    auto_repr('"')
    auto_repr('"')
    auto_repr("\n")
    auto_repr("\u0000\u0001\U000000ff")

    for a in range(256):
        as_hex = "%02x" % a
        auto_repr("\\u" + as_hex * 2)
        auto_repr("\"'\\u" + as_hex * 2)
        auto_repr("\\U" + as_hex * 4)

        if chr(a).lower() not in "0123456789abcdef":
            with raises(DSDLSyntaxError, match=".*hex character.*"):
                _parse_string_literal('"\\U0000000%s"' % chr(a))

            with raises(DSDLSyntaxError, match=".*hex character.*"):
                _parse_string_literal("'\\u00%s0'" % chr(a))
        else:
            with raises(DSDLSyntaxError, match=".*expected.*"):
                _parse_string_literal("'\\u%s'" % chr(a))

    with raises(DSDLSyntaxError, match=".*expected.*"):
        _parse_string_literal("'\\u'")

    with raises(DSDLSyntaxError, match=".*expected.*"):
        _parse_string_literal("'\\'")

    with raises(DSDLSyntaxError, match=".*escape.*"):
        _parse_string_literal("'\\z'")

    once('"evening"', "evening")  # okay we support English, cool
    once('"вечер"', "вечер")  # and Russian too
    once('"õhtust"', "õhtust")  # heck, even Estonian
