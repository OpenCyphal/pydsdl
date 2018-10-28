#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import re
import typing
import logging


GrammarConstructHandler = typing.Union[
    typing.Callable[[], typing.Any],
    typing.Callable[[str], typing.Any],
    typing.Callable[[str, str], typing.Any],
    typing.Callable[[str, str, str], typing.Any],
    typing.Callable[[str, str, str, str], typing.Any],
    typing.Callable[[str, str, str, str, str], typing.Any],
    typing.Callable[[str, str, str, str, str, str], typing.Any],
]


_logger = logging.getLogger(__name__)


class InvalidGrammarError(ValueError):
    pass


class RegularGrammarMatcher:
    """
    Holds a collection of regular expression that together define a simple regular grammar.
    Can process text, matching the defined grammar rules against it; invokes a specified handler on first match
    and returns its output. If no match is found, raises InvalidGrammarError. The arguments of the handler are
    the captured strings, if any are specified; nothing otherwise.
    """

    def __init__(self) -> None:
        # static type not specified because mypy is malfunctioning on re.Pattern
        # noinspection Mypy
        self._rules = []        # type: ignore

    def add_rule(self,
                 regular_expression: str,
                 handler: GrammarConstructHandler) -> None:
        self._rules.append((re.compile(regular_expression), handler))

    def match(self, text: str) -> typing.Any:
        for regexp, handler in self._rules:
            match = re.match(regexp, text)
            if match:
                captured = match.groups()
                _logger.debug('Text %r produced %r matching this: %s', text, captured, regexp.pattern)
                return handler(*captured)

        raise InvalidGrammarError('Invalid grammar: %s' % text)


def _unittest_regular_grammar_matcher() -> None:
    from pytest import raises

    m = RegularGrammarMatcher()
    m.add_rule(r'float(\d\d?)$', lambda bits: 'F%d' % int(bits))
    m.add_rule(r'int(\d\d?)$', lambda bits: 'I%d' % int(bits))
    m.add_rule(r'uint(\d\d?)$', lambda bits: 'U%d' % int(bits))
    m.add_rule(r'void(\d\d?)$', lambda bits: 'V%d' % int(bits))
    m.add_rule(r'float(\d\d?)$', lambda _: None)  # Will never be invoked - consumed by previously defined
    m.add_rule(r'([a-zA-Z0-9_\.]+?)\.(\d+)(?:.(\d+))?$', lambda n, j, m: (n, int(j), None if m is None else int(m)))

    assert m.match('float64') == 'F64'
    assert m.match('int13') == 'I13'
    assert m.match('void52') == 'V52'

    with raises(InvalidGrammarError):
        m.match('no match')

    assert m.match('namespace.nested.Type.123.456') == ('namespace.nested.Type', 123, 456)
    assert m.match('namespace.nested.Type.123') == ('namespace.nested.Type', 123, None)
    with raises(InvalidGrammarError):
        m.match('namespace.nested.Type.')

    with raises(InvalidGrammarError):
        m.match('namespace.nested.Type.123.')
