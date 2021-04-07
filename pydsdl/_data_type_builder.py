# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import os
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


class UnregulatedFixedPortIDError(_error.InvalidDefinitionError):
    pass


class MissingSerializationModeError(_error.InvalidDefinitionError):
    pass


_logger = logging.getLogger(__name__)


class DataTypeBuilder(_parser.StatementStreamProcessor):
    def __init__(
        self,
        definition: _dsdl_definition.DSDLDefinition,
        lookup_definitions: typing.Iterable[_dsdl_definition.DSDLDefinition],
        print_output_handler: typing.Callable[[int, str], None],
        allow_unregulated_fixed_port_id: bool,
    ):
        self._definition = definition
        self._lookup_definitions = list(lookup_definitions)
        self._print_output_handler = print_output_handler
        self._allow_unregulated_fixed_port_id = allow_unregulated_fixed_port_id
        self._element_callback = None  # type: typing.Optional[typing.Callable[[str], None]]

        assert isinstance(self._definition, _dsdl_definition.DSDLDefinition)
        assert all(map(lambda x: isinstance(x, _dsdl_definition.DSDLDefinition), lookup_definitions))
        assert callable(self._print_output_handler)
        assert isinstance(self._allow_unregulated_fixed_port_id, bool)

        self._structs = [_data_schema_builder.DataSchemaBuilder()]
        self._is_deprecated = False

    def finalize(self) -> _serializable.CompositeType:
        if len(self._structs) == 1:  # Structure type
            (builder,) = self._structs  # type: _data_schema_builder.DataSchemaBuilder,
            out = self._make_composite(
                builder=builder,
                name=self._definition.full_name,
                version=self._definition.version,
                deprecated=self._is_deprecated,
                fixed_port_id=self._definition.fixed_port_id,
                source_file_path=self._definition.file_path,
                has_parent_service=False,
            )
        else:  # Service type
            request_builder, response_builder = self._structs
            assert isinstance(request_builder, _data_schema_builder.DataSchemaBuilder)
            assert isinstance(response_builder, _data_schema_builder.DataSchemaBuilder)
            sep = _serializable.CompositeType.NAME_COMPONENT_SEPARATOR
            request = self._make_composite(
                builder=request_builder,
                name=sep.join([self._definition.full_name, "Request"]),
                version=self._definition.version,
                deprecated=self._is_deprecated,
                fixed_port_id=None,
                source_file_path=self._definition.file_path,
                has_parent_service=True,
            )
            response = self._make_composite(
                builder=response_builder,
                name=sep.join([self._definition.full_name, "Response"]),
                version=self._definition.version,
                deprecated=self._is_deprecated,
                fixed_port_id=None,
                source_file_path=self._definition.file_path,
                has_parent_service=True,
            )
            # noinspection SpellCheckingInspection
            out = _serializable.ServiceType(  # pozabito vse na svete
                request=request,  # serdce zamerlo v grudi
                response=response,  # tolko nebo tolko veter
                fixed_port_id=self._definition.fixed_port_id,  # tolko radost vperedi
            )

        assert isinstance(out, _serializable.CompositeType)
        if not self._allow_unregulated_fixed_port_id:
            port_id = out.fixed_port_id
            if port_id is not None:
                is_service_type = isinstance(out, _serializable.ServiceType)
                f = (
                    _port_id_ranges.is_valid_regulated_service_id
                    if is_service_type
                    else _port_id_ranges.is_valid_regulated_subject_id
                )
                if not f(port_id, out.root_namespace):
                    raise UnregulatedFixedPortIDError(
                        "Regulated port ID %r for %s type %r is not valid. "
                        "Consider using allow_unregulated_fixed_port_id."
                        % (port_id, "service" if is_service_type else "message", out.full_name)
                    )
        return out

    def on_attribute_comment(self, comment: str) -> None:
        # Flush queued attribute with doc comment
        self._flush_attribute(comment)

    def on_header_comment(self, comment: str) -> None:
        # Attach doc to composite type
        self._structs[-1].set_comment(comment)

    def on_constant(self, constant_type: _serializable.SerializableType, name: str, value: _expression.Any) -> None:
        self._on_attribute()
        self._queue_attribute(
            lambda doc: self._structs[-1].add_constant(_serializable.Constant(constant_type, name, value, doc))
        )

    def on_field(self, field_type: _serializable.SerializableType, name: str) -> None:
        self._on_attribute()
        self._queue_attribute(lambda doc: self._structs[-1].add_field(_serializable.Field(field_type, name, doc)))

    def on_padding_field(self, padding_field_type: _serializable.VoidType) -> None:
        self._on_attribute()
        self._queue_attribute(
            lambda doc: self._structs[-1].add_field(_serializable.PaddingField(padding_field_type, doc))
        )

    def on_directive(
        self, line_number: int, directive_name: str, associated_expression_value: typing.Optional[_expression.Any]
    ) -> None:
        try:
            handler = {
                "print": self._on_print_directive,
                "assert": self._on_assert_directive,
                "extent": self._on_extent_directive,
                "sealed": self._on_sealed_directive,
                "union": self._on_union_directive,
                "deprecated": self._on_deprecated_directive,
            }[directive_name]
        except KeyError:
            raise InvalidDirectiveError("Unknown directive %r" % directive_name) from None
        else:
            assert callable(handler)
            return handler(line_number, associated_expression_value)

    def on_service_response_marker(self) -> None:
        if len(self._structs) > 1:
            raise _error.InvalidDefinitionError("Duplicated service response marker")

        self._structs.append(_data_schema_builder.DataSchemaBuilder())
        assert len(self._structs) == 2

    def resolve_top_level_identifier(self, name: str) -> _expression.Any:
        # Look only in the current data structure. The lookup cannot cross the service request/response boundary.
        for c in self._structs[-1].constants:
            if c.name == name:
                return c.value

        if name == "_offset_":
            bls = self._structs[-1].offset
            assert len(bls) > 0 and all(map(lambda x: isinstance(x, int), bls))
            # FIXME: THIS OPERATION TRIGGERS NUMERICAL EXPANSION OF THE BIT LENGTH SET.
            # TODO: INTEGRATE THE SET EXPRESSION WITH THE BIT LENGTH SET SOLVER TO IMPROVE PERFORMANCE.
            return _expression.Set(map(_expression.Rational, bls))
        raise UndefinedIdentifierError("Undefined identifier: %r" % name)

    def resolve_versioned_data_type(self, name: str, version: _serializable.Version) -> _serializable.CompositeType:
        if _serializable.CompositeType.NAME_COMPONENT_SEPARATOR in name:
            full_name = name
        else:
            full_name = _serializable.CompositeType.NAME_COMPONENT_SEPARATOR.join(
                [self._definition.full_namespace, name]
            )
            _logger.debug("The full name of a relatively referred type %r reconstructed as %r", name, full_name)

        del name
        found = list(filter(lambda d: d.full_name == full_name and d.version == version, self._lookup_definitions))
        if not found:
            # Play Sherlock to help the user with mistakes like https://forum.uavcan.org/t/dsdl-compilation-error/904/2
            requested_ns = full_name.split(_serializable.CompositeType.NAME_COMPONENT_SEPARATOR)[0]
            lookup_nss = set(x.root_namespace for x in self._lookup_definitions)
            subroot_ns = self._definition.name_components[1] if len(self._definition.name_components) > 2 else None
            error_description = "Data type %s.%d.%d could not be found in the following root namespaces: %s. " % (
                full_name,
                version.major,
                version.minor,
                lookup_nss or "(empty set)",
            )
            if requested_ns not in lookup_nss and requested_ns == subroot_ns:
                error_description += " Did you mean to use the directory %r instead of %r?" % (
                    os.path.join(self._definition.root_namespace_path, subroot_ns),
                    self._definition.root_namespace_path,
                )
            else:
                error_description += " Please make sure that you specified the directories correctly."
            raise UndefinedDataTypeError(error_description)

        if len(found) > 1:  # pragma: no cover
            raise _error.InternalError("Conflicting definitions: %r" % found)

        target_definition = found[0]
        assert isinstance(target_definition, _dsdl_definition.DSDLDefinition)
        assert target_definition.full_name == full_name
        assert target_definition.version == version
        # Recursion is cool.
        return target_definition.read(
            lookup_definitions=self._lookup_definitions,
            print_output_handler=self._print_output_handler,
            allow_unregulated_fixed_port_id=self._allow_unregulated_fixed_port_id,
        )

    def _queue_attribute(self, element_callback: typing.Callable[[str], None]) -> None:
        self._flush_attribute("")
        self._element_callback = element_callback

    def _flush_attribute(self, comment: str) -> None:
        if self._element_callback is not None:
            self._element_callback(comment)
        self._element_callback = None

    def _on_attribute(self) -> None:
        if isinstance(self._structs[-1].serialization_mode, _data_schema_builder.DelimitedSerializationMode):
            raise InvalidDirectiveError(
                "The extent directive can only be placed after the last attribute definition in the schema. "
                "This is to prevent errors if the extent is dependent on the bit length set of the data schema."
            )

    def _on_print_directive(self, line_number: int, value: typing.Optional[_expression.Any]) -> None:
        _logger.info(
            "Print directive at %s:%d%s",
            self._definition.file_path,
            line_number,
            (": %s" % value) if value is not None else " (no value to print)",
        )
        self._print_output_handler(line_number, str(value if value is not None else ""))

    def _on_assert_directive(self, line_number: int, value: typing.Optional[_expression.Any]) -> None:
        if isinstance(value, _expression.Boolean):
            if not value.native_value:
                raise AssertionCheckFailureError(
                    "Assertion check has failed", path=self._definition.file_path, line=line_number
                )
            _logger.debug("Assertion check successful at %s:%d", self._definition.file_path, line_number)
        elif value is None:
            raise InvalidDirectiveError("Assert directive requires an expression")
        else:
            raise InvalidDirectiveError("The assertion check expression must yield a boolean, not %s" % value.TYPE_NAME)

    def _on_extent_directive(self, line_number: int, value: typing.Optional[_expression.Any]) -> None:
        if self._structs[-1].serialization_mode is not None:
            raise InvalidDirectiveError(
                "Misplaced extent directive. The serialization mode is already set to %s"
                % self._structs[-1].serialization_mode
            )
        if value is None:
            raise InvalidDirectiveError("The extent directive requires an expression")
        if isinstance(value, _expression.Rational):
            struct = self._structs[-1]
            bits = value.as_native_integer()
            struct.set_serialization_mode(_data_schema_builder.DelimitedSerializationMode(bits))
            _logger.debug("The extent is set to %d bits at %s:%d", bits, self._definition.file_path, line_number)
        else:
            raise InvalidDirectiveError("The extent directive expects a rational, not %s" % value.TYPE_NAME)

    def _on_sealed_directive(self, _ln: int, value: typing.Optional[_expression.Any]) -> None:
        if self._structs[-1].serialization_mode is not None:
            raise InvalidDirectiveError(
                "Misplaced sealing directive. The serialization mode is already set to %s"
                % self._structs[-1].serialization_mode
            )
        if value is not None:
            raise InvalidDirectiveError("The sealed directive does not expect an expression")
        self._structs[-1].set_serialization_mode(_data_schema_builder.SealedSerializationMode())

    def _on_union_directive(self, _ln: int, value: typing.Optional[_expression.Any]) -> None:
        if value is not None:
            raise InvalidDirectiveError("The union directive does not expect an expression")
        if self._structs[-1].union:
            raise InvalidDirectiveError("Duplicated union directive")
        if self._structs[-1].attributes:
            raise InvalidDirectiveError("The union directive must be placed before the first " "attribute definition")
        self._structs[-1].make_union()

    def _on_deprecated_directive(self, _ln: int, value: typing.Optional[_expression.Any]) -> None:
        if value is not None:
            raise InvalidDirectiveError("The deprecated directive does not expect an expression")
        if self._is_deprecated:
            raise InvalidDirectiveError("Duplicated deprecated directive")
        if len(self._structs) > 1:
            raise InvalidDirectiveError("The deprecated directive cannot be placed in the response section")
        if self._structs[-1].attributes:
            raise InvalidDirectiveError(
                "The deprecated directive must be placed before the first " "attribute definition"
            )
        self._is_deprecated = True

    @staticmethod
    def _make_composite(  # pylint: disable=too-many-arguments
        builder: _data_schema_builder.DataSchemaBuilder,
        name: str,
        version: _serializable.Version,
        deprecated: bool,
        fixed_port_id: typing.Optional[int],
        source_file_path: str,
        has_parent_service: bool,
    ) -> _serializable.CompositeType:
        ty = _serializable.UnionType if builder.union else _serializable.StructureType
        inner = ty(
            name=name,
            version=version,
            attributes=builder.attributes,
            deprecated=deprecated,
            fixed_port_id=fixed_port_id,
            source_file_path=source_file_path,
            has_parent_service=has_parent_service,
            doc=builder.doc,
        )  # type: _serializable.CompositeType
        sm = builder.serialization_mode
        if isinstance(sm, _data_schema_builder.DelimitedSerializationMode):
            out = _serializable.DelimitedType(inner, extent=sm.extent)  # type: _serializable.CompositeType
            _logger.debug("%r wrapped into %r", inner, out)
        elif isinstance(sm, _data_schema_builder.SealedSerializationMode):
            out = inner
        else:
            assert sm is None, "I wish Python had a strong static type system"
            raise MissingSerializationModeError(
                "%s: Either `@sealed` or `@extent ...` are required. "
                "The smallest valid extent for this type (i.e., its max bit length) is %d bits (%d bytes). "
                "If you are not sure what this means, add the following line near the end of this definition: "
                "`@extent %d * 8`"
                % (inner.short_name, inner.extent, inner.extent // 8, DataTypeBuilder._suggest_extent_in_bytes(inner))
            )

        return out

    @staticmethod
    def _suggest_extent_in_bytes(model: _serializable.CompositeType) -> int:
        """
        An implementation-specific heuristic intended to lower the entry barrier.
        The numbers are subject to change between minor revisions.
        """
        return max(64, model.extent * 2 // 8)
