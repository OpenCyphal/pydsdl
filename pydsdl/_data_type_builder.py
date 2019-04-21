#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing
import logging
from . import _serializable
from . import _expression
from . import _error
from . import _dsdl_definition
from . import _parser
from . import _data_schema_builder
from . import _port_id_ranges


class AssertionCheckFailureError(_error.InvalidDefinitionError):
    pass


class UndefinedDataTypeError(_error.InvalidDefinitionError):
    pass


class UndefinedIdentifierError(_error.InvalidDefinitionError):
    pass


class InvalidDirectiveError(_error.InvalidDefinitionError):
    pass


_logger = logging.getLogger(__name__)


class DataTypeBuilder(_parser.StatementStreamProcessor):
    def __init__(self,
                 definition:                      _dsdl_definition.DSDLDefinition,
                 lookup_definitions:              typing.Iterable[_dsdl_definition.DSDLDefinition],
                 print_output_handler:            typing.Callable[[int, str], None],
                 allow_unregulated_fixed_port_id: bool):
        self._definition = definition
        self._lookup_definitions = list(lookup_definitions)
        self._print_output_handler = print_output_handler
        self._allow_unregulated_fixed_port_id = allow_unregulated_fixed_port_id

        assert isinstance(self._definition, _dsdl_definition.DSDLDefinition)
        assert all(map(lambda x: isinstance(x, _dsdl_definition.DSDLDefinition), lookup_definitions))
        assert callable(self._print_output_handler)
        assert isinstance(self._allow_unregulated_fixed_port_id, bool)

        self._structs = [_data_schema_builder.DataSchemaBuilder()]
        self._is_deprecated = False

    def finalize(self) -> _serializable.CompositeType:
        if len(self._structs) == 1:     # Message type
            struct, = self._structs     # type: _data_schema_builder.DataSchemaBuilder,
            if struct.union:
                out = _serializable.UnionType(
                    name=self._definition.full_name,
                    version=self._definition.version,
                    attributes=struct.attributes,
                    deprecated=self._is_deprecated,
                    fixed_port_id=self._definition.fixed_port_id,
                    source_file_path=self._definition.file_path)  # type: _serializable.CompositeType
            else:
                out = _serializable.StructureType(
                    name=self._definition.full_name,
                    version=self._definition.version,
                    attributes=struct.attributes,
                    deprecated=self._is_deprecated,
                    fixed_port_id=self._definition.fixed_port_id,
                    source_file_path=self._definition.file_path)
        else:  # Service type
            request, response = self._structs
            # noinspection SpellCheckingInspection
            out = _serializable.ServiceType(
                name=self._definition.full_name,            # pozabito vse na svete
                version=self._definition.version,           # serdce zamerlo v grudi
                request_attributes=request.attributes,      # tolko nebo tolko veter
                response_attributes=response.attributes,    # tolko radost vperedi
                request_is_union=request.union,             # tolko nebo tolko veter
                response_is_union=response.union,           # tolko radost vperedi
                deprecated=self._is_deprecated,
                fixed_port_id=self._definition.fixed_port_id,
                source_file_path=self._definition.file_path)

        if not self._allow_unregulated_fixed_port_id:
            port_id = out.fixed_port_id
            if port_id is not None:
                is_service_type = isinstance(out, _serializable.ServiceType)
                f = _port_id_ranges.is_valid_regulated_service_id if is_service_type else \
                    _port_id_ranges.is_valid_regulated_subject_id
                if not f(port_id, out.root_namespace):
                    raise _serializable.InvalidFixedPortIDError(
                        'Regulated port ID %r for %s type %r is not valid. '
                        'Consider using allow_unregulated_fixed_port_id.' %
                        (port_id, 'service' if is_service_type else 'message', out.full_name))

        assert isinstance(out, _serializable.CompositeType)
        return out

    def on_constant(self,
                    constant_type: _serializable.SerializableType,
                    name: str,
                    value: _expression.Any) -> None:
        self._structs[-1].add_constant(_serializable.Constant(constant_type, name, value))

    def on_field(self, field_type: _serializable.SerializableType, name: str) -> None:
        self._structs[-1].add_field(_serializable.Field(field_type, name))

    def on_padding_field(self, padding_field_type: _serializable.VoidType) -> None:
        self._structs[-1].add_field(_serializable.PaddingField(padding_field_type))

    def on_directive(self,
                     line_number: int,
                     directive_name: str,
                     associated_expression_value: typing.Optional[_expression.Any]) -> None:
        try:
            handler = {
                'print':      self._on_print_directive,
                'assert':     self._on_assert_directive,
                'union':      self._on_union_directive,
                'deprecated': self._on_deprecated_directive,
            }[directive_name]
        except KeyError:
            raise InvalidDirectiveError('Unknown directive %r' % directive_name)
        else:
            assert callable(handler)
            return handler(line_number, associated_expression_value)

    def on_service_response_marker(self) -> None:
        if len(self._structs) > 1:
            raise _error.InvalidDefinitionError('Duplicated service response marker')

        self._structs.append(_data_schema_builder.DataSchemaBuilder())
        assert len(self._structs) == 2

    def resolve_top_level_identifier(self, name: str) -> _expression.Any:
        # Look only in the current data structure. The lookup cannot cross the service request/response boundary.
        for c in self._structs[-1].constants:
            if c.name == name:
                return c.value

        if name == '_offset_':
            bls = self._structs[-1].bit_length_set
            assert len(bls) > 0 and all(map(lambda x: isinstance(x, int), bls))
            return _expression.Set(map(_expression.Rational, bls))
        else:
            raise UndefinedIdentifierError('Undefined identifier: %r' % name)

    def resolve_versioned_data_type(self, name: str, version: _serializable.Version) -> _serializable.CompositeType:
        if _serializable.CompositeType.NAME_COMPONENT_SEPARATOR in name:
            full_name = name
        else:
            full_name = _serializable.CompositeType.NAME_COMPONENT_SEPARATOR.join([self._definition.full_namespace,
                                                                                   name])
            _logger.debug('The full name of a relatively referred type %r reconstructed as %r', name, full_name)

        del name
        found = list(filter(lambda d: d.full_name == full_name and d.version == version, self._lookup_definitions))
        if not found:
            raise UndefinedDataTypeError('Data type %r version %d.%d could not be found' %
                                         (full_name, version.major, version.minor))
        if len(found) > 1:  # pragma: no cover
            raise _error.InternalError('Conflicting definitions: %r' % found)

        target_definition = found[0]
        assert isinstance(target_definition, _dsdl_definition.DSDLDefinition)
        assert target_definition.full_name == full_name
        assert target_definition.version == version
        # Recursion is cool.
        return target_definition.read(lookup_definitions=self._lookup_definitions,
                                      print_output_handler=self._print_output_handler,
                                      allow_unregulated_fixed_port_id=self._allow_unregulated_fixed_port_id)

    def _on_print_directive(self, line_number: int, value: typing.Optional[_expression.Any]) -> None:
        _logger.info('Print directive at %s:%d%s', self._definition.file_path, line_number,
                     (': %s' % value) if value is not None else ' (no value to print)')
        self._print_output_handler(line_number, str(value if value is not None else ''))

    def _on_assert_directive(self, line_number: int, value: typing.Optional[_expression.Any]) -> None:
        if isinstance(value, _expression.Boolean):
            if not value.native_value:
                raise AssertionCheckFailureError('Assertion check has failed',
                                                 path=self._definition.file_path,
                                                 line=line_number)
            else:
                _logger.debug('Assertion check successful at %s:%d', self._definition.file_path, line_number)
        elif value is None:
            raise InvalidDirectiveError('Assert directive requires an expression')
        else:
            raise InvalidDirectiveError('The assertion check expression must yield a boolean, not %s' %
                                        value.TYPE_NAME)

    def _on_union_directive(self, _ln: int, value: typing.Optional[_expression.Any]) -> None:
        if value is not None:
            raise InvalidDirectiveError('The union directive does not expect an expression')

        if self._structs[-1].union:
            raise InvalidDirectiveError('Duplicated union directive')

        if not self._structs[-1].empty:
            raise InvalidDirectiveError('The union directive must be placed before the first '
                                        'attribute definition')

        self._structs[-1].make_union()

    def _on_deprecated_directive(self, _ln: int, value: typing.Optional[_expression.Any]) -> None:
        if value is not None:
            raise InvalidDirectiveError('The deprecated directive does not expect an expression')

        if self._is_deprecated:
            raise InvalidDirectiveError('Duplicated deprecated directive')

        if len(self._structs) > 1:
            raise InvalidDirectiveError('The deprecated directive cannot be placed in the response section')

        if not self._structs[-1].empty:
            raise InvalidDirectiveError('The deprecated directive must be placed before the first '
                                        'attribute definition')

        self._is_deprecated = True
