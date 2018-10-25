#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import re
import typing
from .error import DSDLSyntaxError, ParseError, InternalError


class Token:
    REGEXP = NotImplemented

    def __init__(self, text: str):
        self.text = text

    def __str__(self) -> str:   # pragma: no cover
        return self.text

    def __repr__(self) -> str:
        return self.__class__.__name__ + '(' + repr(self.text) + ')'

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Token):
            return bool((other.__class__ is self.__class__) and (other.text == self.text))
        else:   # pragma: no cover
            raise TypeError('Invalid other: %r' % other)

    def __add__(self, other: typing.Union[typing.Sequence['Token'], 'Token']) -> typing.List['Token']:
        if isinstance(other, list):
            return [self] + other
        elif isinstance(other, Token):
            return [self, other]
        else:   # pragma: no cover
            raise TypeError('Invalid other: %r' % other)

    def __radd__(self, other: typing.Sequence['Token']) -> typing.List['Token']:
        if isinstance(other, list):
            return other + [self]
        else:   # pragma: no cover
            raise TypeError('Invalid other: %r' % other)


class Keyword(Token):
    REGEXP = '(saturated|truncated)(?:\W|$)'


class Directive(Token):
    REGEXP = r'(@)\s*([a-zA-Z0-9._]+)'


class Identifier(Token):
    REGEXP = r'([a-zA-Z_][a-zA-Z0-9._]*)'


class ServiceResponseMarker(Token):
    REGEXP = r'(---)$'                    # Note: end of string required


class LeftBracket(Token):
    REGEXP = r'\['


class RightBracket(Token):
    REGEXP = r'\]'


class Operator(Token):
    pass


class Assignment(Operator):
    REGEXP = r'(=)[^=]'


class ArithmeticOperator(Operator):
    REGEXP = r'\+|-|\*|/|%|<=|>=|==|<|>'


class Literal(Token):
    pass


class StringLiteral(Literal):
    REGEXP = r"'.+'"


class NumericLiteral(Literal):
    pass        # Note that we don't match +/- because those are treated as arithmetic operators


class BinaryLiteral(NumericLiteral):
    REGEXP = r'(0b[01]+)(?:\W|$)'


class OctalLiteral(NumericLiteral):
    REGEXP = r'(0o[01234567]+)(?:\W|$)'


class DecimalLiteral(NumericLiteral):
    REGEXP = r'([1-9][0-9]*)(?:[^\w\.]|$)'


class HexadecimalLiteral(NumericLiteral):
    REGEXP = r'(0x[0-9A-Fa-f]+)(?:\W|$)'


class FloatingPointLiteral(NumericLiteral):
    REGEXP = r'([0-9]*\.?[0-9]*(?:[eE][-+]?[0-9]+)?)(?:\W|$)'


_TOKEN_TYPES_ORDERED_BY_PRECEDENCE = [
    Keyword,
    Directive,
    Identifier,
    StringLiteral,
    ServiceResponseMarker,      # Must precede ArithmeticOperator due to possible ambiguity
    LeftBracket,
    RightBracket,
    ArithmeticOperator,         # Also consumes +/- before literals
    Assignment,
    BinaryLiteral,
    OctalLiteral,
    DecimalLiteral,
    HexadecimalLiteral,
    FloatingPointLiteral,
]   # type: typing.List[typing.Type[Token]]


def _unittest_token_chaining() -> None:
    seq = Identifier('abc') + Assignment('=') + NumericLiteral('123') + [ArithmeticOperator('+'), StringLiteral('"0"')]
    assert str(seq) == \
        "[Identifier('abc'), Assignment('='), NumericLiteral('123'), ArithmeticOperator('+'), StringLiteral('\"0\"')]"


class Statement:
    def __init__(self, line_number: int, tokens: typing.Sequence[Token]):
        self.line_number = int(line_number)
        self.tokens = list(tokens)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Statement):
            return bool((other.__class__ is self.__class__) and
                        (other.tokens == self.tokens) and
                        (other.line_number == self.line_number))
        else:   # pragma: no cover
            raise TypeError('Invalid other: %r' % other)

    def __str__(self) -> str:   # pragma: no cover
        return '%s(%d:%r)' % (self.__class__.__name__, self.line_number, self.tokens)

    __repr__ = __str__


def tokenize_definition(text: str) -> typing.Iterator[Statement]:
    for line_index, line_text in enumerate(text.splitlines(keepends=False)):
        line_number = line_index + 1
        try:
            tokens = list(_tokenize_statement(line_text))
        except ParseError as ex:   # pragma: no cover
            ex.set_error_location_if_unknown(line=line_number)
            raise
        except Exception as ex:    # pragma: no cover
            raise InternalError(culprit=ex, line=line_number)

        if tokens:
            yield Statement(line_number, tokens)


def _tokenize_statement(statement: str) -> typing.Sequence[Token]:
    statement = statement.strip()
    if not statement or statement[0] == '#':
        return []

    for k in _TOKEN_TYPES_ORDERED_BY_PRECEDENCE:
        match = re.match(k.REGEXP, statement)
        if match:
            groups = match.groups()
            if groups:
                text = ''.join([(g or '') for g in groups])
                end = match.end(match.lastindex)
            else:
                text = match.group(0)
                end = match.end(0)

            if end > 0:
                return k(text) + _tokenize_statement(statement[end:])

    raise DSDLSyntaxError('Unexpected sequence: %r' % statement)


def _unittest_statement_tokenizer() -> None:
    from pytest import raises

    assert len(_tokenize_statement('')) == 0

    assert _tokenize_statement('uint8 value # comment') == \
        Identifier('uint8') + Identifier('value')

    assert _tokenize_statement('truncated ns.nested.Type.0.1[<=+0x123] _value123 # comment') == \
        Keyword('truncated') + Identifier('ns.nested.Type.0.1') + \
        LeftBracket('[') + \
        ArithmeticOperator('<=') + ArithmeticOperator('+') + HexadecimalLiteral('0x123') +\
        RightBracket(']') + \
        Identifier('_value123')

    assert _tokenize_statement('---') == [ServiceResponseMarker('---')]

    assert _tokenize_statement('  0b011100# comment') == [BinaryLiteral('0b011100')]

    assert _tokenize_statement(' @directive') == [Directive('@directive')]

    assert _tokenize_statement('\ttruncated type name = initializer # comment') == \
        Keyword('truncated') + Identifier('type') + Identifier('name') + Assignment('=') + Identifier('initializer')

    assert _tokenize_statement(" type.name const_name='#'") == \
        Identifier('type.name') + Identifier('const_name') + Assignment('=') + StringLiteral("'#'")

    assert _tokenize_statement('@ assert min_offset % 8 == +16') == \
        Directive('@assert') + \
        Identifier('min_offset') + ArithmeticOperator('%') + DecimalLiteral('8') + ArithmeticOperator('==') + \
        ArithmeticOperator('+') + DecimalLiteral('16')

    assert _tokenize_statement('123.456')       == [FloatingPointLiteral('123.456')]
    assert _tokenize_statement('0e0')           == [FloatingPointLiteral('0e0')]
    assert _tokenize_statement('+123.456')      == ArithmeticOperator('+') + FloatingPointLiteral('123.456')
    assert _tokenize_statement('-123.456')      == ArithmeticOperator('-') + FloatingPointLiteral('123.456')
    assert _tokenize_statement('-123.456e123')  == ArithmeticOperator('-') + FloatingPointLiteral('123.456e123')
    assert _tokenize_statement('-123.456e+123') == ArithmeticOperator('-') + FloatingPointLiteral('123.456e+123')
    assert _tokenize_statement('-123.456e-123') == ArithmeticOperator('-') + FloatingPointLiteral('123.456e-123')
    assert _tokenize_statement('-123e-123')     == ArithmeticOperator('-') + FloatingPointLiteral('123e-123')
    assert _tokenize_statement('-123.e-123')    == ArithmeticOperator('-') + FloatingPointLiteral('123.e-123')
    assert _tokenize_statement('-.0e-123')      == ArithmeticOperator('-') + FloatingPointLiteral('.0e-123')
    assert _tokenize_statement('+0.e-123')      == ArithmeticOperator('+') + FloatingPointLiteral('0.e-123')
    assert _tokenize_statement('+0e+0')         == ArithmeticOperator('+') + FloatingPointLiteral('0e+0')

    with raises(DSDLSyntaxError):
        _tokenize_statement('0b123')

    with raises(DSDLSyntaxError):
        _tokenize_statement('@@directive')


def _unittest_tokenizer() -> None:
    from itertools import zip_longest

    def tk(text: str, reference: typing.List[Statement]) -> None:
        my = zip_longest
        arms = tokenize_definition(text)
        again = reference
        # I want to be
        for given, i_want_to_hold_you in my(arms, again):
            assert given == i_want_to_hold_you

    tk(
        """#comment
        uint8 whatever
        truncated namespace.nested.Type.0.1[0x123] whatever#comment
        saturated Type.0.1[<=+123]whatever

        # another comment

        @ directive

        float64 CONSTANT = '/'  # comment
        """,
        [
            Statement(
                2,
                Identifier('uint8') + Identifier('whatever')
            ),
            Statement(
                3,
                Keyword('truncated') + Identifier('namespace.nested.Type.0.1') + LeftBracket('[') +
                HexadecimalLiteral('0x123') + RightBracket(']') + Identifier('whatever')
            ),
            Statement(
                4,
                Keyword('saturated') + Identifier('Type.0.1') + LeftBracket('[') + ArithmeticOperator('<=') +
                ArithmeticOperator('+') + DecimalLiteral('123') + RightBracket(']') + Identifier('whatever')
            ),
            Statement(
                8,
                [Directive('@directive')]
            ),
            Statement(
                10,
                Identifier('float64') + Identifier('CONSTANT') + Assignment('=') + StringLiteral("'/'")
            ),
        ]
    )
