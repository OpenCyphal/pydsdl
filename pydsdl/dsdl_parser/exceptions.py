#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

from ..parse_error import InvalidDefinitionError


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
