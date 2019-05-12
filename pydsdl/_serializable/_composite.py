#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing
import itertools
from .. import _expression
from .. import _port_id_ranges
from .._bit_length_set import BitLengthSet
from ._root import SerializableType, TypeParameterError
from ._attribute import Attribute, Field, PaddingField, Constant
from ._name import check_name, InvalidNameError
from ._void import VoidType
from ._primitive import PrimitiveType, UnsignedIntegerType


Version = typing.NamedTuple('Version', [('major', int), ('minor', int)])


class InvalidVersionError(TypeParameterError):
    pass


class AttributeNameCollisionError(TypeParameterError):
    pass


class InvalidFixedPortIDError(TypeParameterError):
    pass


class MalformedUnionError(TypeParameterError):
    pass


class DeprecatedDependencyError(TypeParameterError):
    pass


class CompositeType(SerializableType):
    MAX_NAME_LENGTH = 50
    MAX_VERSION_NUMBER = 255
    NAME_COMPONENT_SEPARATOR = '.'

    def __init__(self,
                 name:             str,
                 version:          Version,
                 attributes:       typing.Iterable[Attribute],
                 deprecated:       bool,
                 fixed_port_id:    typing.Optional[int],
                 source_file_path: str,
                 parent_service:   typing.Optional['ServiceType'] = None):
        super(CompositeType, self).__init__()

        self._name = str(name).strip()
        self._version = version
        self._attributes = list(attributes)
        self._attributes_by_name = {a.name: a for a in self._attributes if not isinstance(a, PaddingField)}
        self._deprecated = bool(deprecated)
        self._fixed_port_id = None if fixed_port_id is None else int(fixed_port_id)
        self._source_file_path = str(source_file_path)
        self._parent_service = parent_service

        if self._parent_service is not None:
            assert self._name.endswith('.Request') or self._name.endswith('.Response')
            if not isinstance(self._parent_service, ServiceType):  # pragma: no cover
                raise ValueError('The parent service reference is invalid: %s' % type(parent_service).__name__)

        # Name check
        if not self._name:
            raise InvalidNameError('Composite type name cannot be empty')

        if self.NAME_COMPONENT_SEPARATOR not in self._name:
            raise InvalidNameError('Root namespace is not specified')

        if len(self._name) > self.MAX_NAME_LENGTH:
            raise InvalidNameError('Name is too long: %r is longer than %d characters' %
                                   (self._name, self.MAX_NAME_LENGTH))

        for component in self._name.split(self.NAME_COMPONENT_SEPARATOR):
            check_name(component)

        # Version check
        version_valid = (0 <= self._version.major <= self.MAX_VERSION_NUMBER) and\
                        (0 <= self._version.minor <= self.MAX_VERSION_NUMBER) and\
                        ((self._version.major + self._version.minor) > 0)

        if not version_valid:
            raise InvalidVersionError('Invalid version numbers: %s.%s' % (self._version.major, self._version.minor))

        # Attribute check
        used_names = set()      # type: typing.Set[str]
        for a in self._attributes:
            if a.name and a.name in used_names:
                raise AttributeNameCollisionError('Multiple attributes under the same name: %r' % a.name)
            else:
                used_names.add(a.name)

        # Port ID check
        port_id = self._fixed_port_id
        if port_id is not None:
            assert port_id is not None
            if isinstance(self, ServiceType):
                if not (0 <= port_id <= _port_id_ranges.MAX_SERVICE_ID):
                    raise InvalidFixedPortIDError('Fixed service ID %r is not valid' % port_id)
            else:
                if not (0 <= port_id <= _port_id_ranges.MAX_SUBJECT_ID):
                    raise InvalidFixedPortIDError('Fixed subject ID %r is not valid' % port_id)

        # Consistent deprecation check.
        # A non-deprecated type cannot be dependent on deprecated types.
        # A deprecated type can be dependent on anything.
        if not self.deprecated:
            for a in self._attributes:
                t = a.data_type
                if isinstance(t, CompositeType):
                    if t.deprecated:
                        raise DeprecatedDependencyError('A type cannot depend on deprecated types '
                                                        'unless it is also deprecated.')

    def is_mutually_bit_compatible_with(self, other: 'CompositeType') -> bool:
        """
        Checks for bit compatibility between two data types.
        The current implementation uses a relaxed simplified check that may yield a false-negative,
        but never a false-positive; i.e., it may fail to detect an incompatibility, but it is guaranteed
        to never report two data types as incompatible if they are compatible.
        The implementation may be updated in the future to use a strict check as defined in the specification
        while keeping the same API, so beware.
        """
        return self.bit_length_set == other.bit_length_set

    @property
    def full_name(self) -> str:
        """The full name, e.g., uavcan.node.Heartbeat"""
        return self._name

    @property
    def name_components(self) -> typing.List[str]:
        """Components of the full name as a list, e.g., ['uavcan', 'node', 'Heartbeat']"""
        return self._name.split(CompositeType.NAME_COMPONENT_SEPARATOR)

    @property
    def short_name(self) -> str:
        """The last component of the full name, e.g., Heartbeat of uavcan.node.Heartbeat"""
        return self.name_components[-1]

    @property
    def full_namespace(self) -> str:
        """The full name without the short name, e.g., uavcan.node for uavcan.node.Heartbeat"""
        return str(CompositeType.NAME_COMPONENT_SEPARATOR.join(self.name_components[:-1]))

    @property
    def root_namespace(self) -> str:
        """The first component of the full name, e.g., uavcan of uavcan.node.Heartbeat"""
        return self.name_components[0]

    @property
    def version(self) -> Version:
        return self._version

    @property
    def deprecated(self) -> bool:
        return self._deprecated

    @property
    def attributes(self) -> typing.List[Attribute]:
        return self._attributes[:]  # Return copy to prevent mutation

    @property
    def fields(self) -> typing.List[Field]:
        return [a for a in self.attributes if isinstance(a, Field)]

    @property
    def fields_except_padding(self) -> typing.List[Field]:
        return [a for a in self.attributes if isinstance(a, Field) and not isinstance(a, PaddingField)]

    @property
    def constants(self) -> typing.List[Constant]:
        return [a for a in self.attributes if isinstance(a, Constant)]

    @property
    def fixed_port_id(self) -> typing.Optional[int]:
        return self._fixed_port_id

    @property
    def has_fixed_port_id(self) -> bool:
        return self.fixed_port_id is not None

    @property
    def source_file_path(self) -> str:
        """Empty if this is a synthesized type, e.g. a service request or response section."""
        return self._source_file_path

    @property
    def parent_service(self) -> typing.Optional['ServiceType']:
        """
        Service types contain two implicit fields: request and response. Their types are instances of composite type,
        too; they can be distinguished from regular composites by the fact that their property "parent_service" points
        to the service type that contains them. For composites that are not parts of a service type this property will
        evaluate to None.
        """
        return self._parent_service

    def iterate_fields_with_offsets(self, base_offset: typing.Optional[BitLengthSet] = None) \
            -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        """
        This method is intended for code generators. It iterates over every field (not attribute, i.e.,
        constants are excluded) of the data type, yielding it together with its offset, where the offset is
        represented as BitLengthSet. The offset of each field is added to the base offset, which may be specified
        by the caller; if not specified, the base offset is assumed to be zero.

        The objective of this method is to allow code generators to easily implement fully unrolled serialization and
        deserialization routines, where "unrolled" means that upon encountering another (nested) composite type, the
        serialization routine would not delegate its serialization to the serialization routine of the encountered type,
        but instead would serialize it in-place, as if the field of that type was replaced with its own fields in-place.
        The lack of delegation has very important performance implications: when the serialization routine does
        not delegate serialization of the nested types, it can perform infinitely deep field alignment analysis,
        thus being able to reliably statically determine whether each field of the type, including nested types
        at arbitrarily deep levels of nesting, is aligned relative to the origin of the serialized representation
        of the outermost type. As a result, the code generator will be able to avoid unnecessary reliance on slow
        bit-level copy routines replacing them instead with much faster byte-level copy (like memcpy()) or even
        plain memory aliasing, since it will be able to determine and prove the alignment of each field statically.

        When invoked on a tagged union type, the method yields the same offset for every field (since that's how
        tagged unions are serialized), where the offset equals the bit length of the implicit union tag (plus the
        base offset, of course, if provided).

        Please refer to the usage examples to see how this feature can be used.

        :param base_offset: Assume the specified base offset; assume zero offset if the parameter is not provided.
                            This parameter should be used when serializing nested composite data types.

        :return: A generator of (Field, BitLengthSet). Each instance of BitLengthSet yielded by the generator is
                 a dedicated copy, meaning that the consumer can mutate the returned instances arbitrarily without
                 affecting future values. It is guaranteed that each yielded instance of BitLengthSet is non-empty.
        """
        raise NotImplementedError

    def _attribute(self, name: _expression.String) -> _expression.Any:
        """
        This is the handler for DSDL expressions like uavcan.node.Heartbeat.1.0.MODE_OPERATIONAL.
        """
        for c in self.constants:
            if c.name == name.native_value:
                assert isinstance(c.value, _expression.Any)
                return c.value

        return super(CompositeType, self)._attribute(name)  # Hand over up the inheritance chain, this is important

    def _compute_bit_length_set(self) -> BitLengthSet:
        raise NotImplementedError

    def __getitem__(self, attribute_name: str) -> Attribute:
        """
        Allows the caller to retrieve an attribute by name. Padding fields are not accessible via this interface.
        Raises KeyError if there is no such attribute.
        """
        return self._attributes_by_name[attribute_name]

    def __str__(self) -> str:
        return '%s.%d.%d' % (self.full_name, self.version.major, self.version.minor)

    def __repr__(self) -> str:
        return '%s(name=%r, version=%r, fields=%r, constants=%r, deprecated=%r, fixed_port_id=%r)' % \
            (self.__class__.__name__,
             self.full_name,
             self.version,
             self.fields,
             self.constants,
             self.deprecated,
             self.fixed_port_id)


class UnionType(CompositeType):
    MIN_NUMBER_OF_VARIANTS = 2

    def __init__(self,
                 name:             str,
                 version:          Version,
                 attributes:       typing.Iterable[Attribute],
                 deprecated:       bool,
                 fixed_port_id:    typing.Optional[int],
                 source_file_path: str,
                 parent_service:   typing.Optional['ServiceType'] = None):
        # Proxy all parameters directly to the base type - I wish we could do that
        # with kwargs while preserving the type information
        super(UnionType, self).__init__(name=name,
                                        version=version,
                                        attributes=attributes,
                                        deprecated=deprecated,
                                        fixed_port_id=fixed_port_id,
                                        source_file_path=source_file_path,
                                        parent_service=parent_service)

        if self.number_of_variants < self.MIN_NUMBER_OF_VARIANTS:
            raise MalformedUnionError('A tagged union cannot contain fewer than %d variants' %
                                      self.MIN_NUMBER_OF_VARIANTS)

        for a in attributes:
            if isinstance(a, PaddingField) or not a.name or isinstance(a.data_type, VoidType):
                raise MalformedUnionError('Padding fields not allowed in unions')

        # Construct once to allow reference equality checks
        assert (self.number_of_variants - 1) > 0
        tag_bit_length = (self.number_of_variants - 1).bit_length()
        self._tag_field_type = UnsignedIntegerType(tag_bit_length, PrimitiveType.CastMode.TRUNCATED)

    @property
    def number_of_variants(self) -> int:
        return len(self.fields)

    @property
    def tag_field_type(self) -> UnsignedIntegerType:
        """
        Returns the best-matching unsigned integer type of the implicit union tag field.
        This is convenient for code generation.
        WARNING: the set of valid tag values is a subset of that of the returned type.
        """
        return self._tag_field_type

    def iterate_fields_with_offsets(self, base_offset: typing.Optional[BitLengthSet] = None) \
            -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        base_offset = BitLengthSet(base_offset or {0})
        base_offset.increment(self.tag_field_type.bit_length)
        for f in self.fields:  # Same offset for every field, because it's a tagged union, not a struct
            yield f, BitLengthSet(base_offset)      # We yield a copy of the offset to prevent mutation

    def _compute_bit_length_set(self) -> BitLengthSet:
        return BitLengthSet.for_tagged_union(map(lambda f: f.data_type.bit_length_set, self.fields))


class StructureType(CompositeType):
    def iterate_fields_with_offsets(self, base_offset: typing.Optional[BitLengthSet] = None) \
            -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        base_offset = BitLengthSet(base_offset or 0)

        # The following variables do not serve the business logic, they are needed only for runtime cross-checking
        _self_test_original_offset = BitLengthSet(0)
        _self_test_field_bls_collection = []  # type: typing.List[BitLengthSet]

        for f in self.fields:
            yield f, BitLengthSet(base_offset)      # We yield a copy of the offset to prevent mutation
            base_offset.increment(f.data_type.bit_length_set)

            # This is only for ensuring that the logic is functioning as intended.
            # Combinatorial transformations are easy to mess up, so we have to employ defensive programming.
            _self_test_original_offset.increment(f.data_type.bit_length_set)
            _self_test_field_bls_collection.append(f.data_type.bit_length_set)
            assert BitLengthSet.for_struct(_self_test_field_bls_collection) == _self_test_original_offset

    def _compute_bit_length_set(self) -> BitLengthSet:
        return BitLengthSet.for_struct(map(lambda f: f.data_type.bit_length_set, self.fields))


class ServiceType(CompositeType):
    def __init__(self,
                 name:                str,
                 version:             Version,
                 request_attributes:  typing.Iterable[Attribute],
                 response_attributes: typing.Iterable[Attribute],
                 request_is_union:    bool,
                 response_is_union:   bool,
                 deprecated:          bool,
                 fixed_port_id:       typing.Optional[int],
                 source_file_path:    str):
        request_meta_type = UnionType if request_is_union else StructureType  # type: type
        self._request_type = request_meta_type(name=name + '.Request',
                                               version=version,
                                               attributes=request_attributes,
                                               deprecated=deprecated,
                                               fixed_port_id=None,
                                               source_file_path='',
                                               parent_service=self)  # type: CompositeType

        response_meta_type = UnionType if response_is_union else StructureType  # type: type
        self._response_type = response_meta_type(name=name + '.Response',
                                                 version=version,
                                                 attributes=response_attributes,
                                                 deprecated=deprecated,
                                                 fixed_port_id=None,
                                                 source_file_path='',
                                                 parent_service=self)  # type: CompositeType

        container_attributes = [
            Field(data_type=self._request_type,  name='request'),
            Field(data_type=self._response_type, name='response'),
        ]

        super(ServiceType, self).__init__(name=name,
                                          version=version,
                                          attributes=container_attributes,
                                          deprecated=deprecated,
                                          fixed_port_id=fixed_port_id,
                                          source_file_path=source_file_path)
        assert self.request_type.parent_service is self
        assert self.response_type.parent_service is self

    @property
    def request_type(self) -> CompositeType:
        return self._request_type

    @property
    def response_type(self) -> CompositeType:
        return self._response_type

    def iterate_fields_with_offsets(self, base_offset: typing.Optional[BitLengthSet] = None) \
            -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        raise TypeError('Service types do not have serializable fields. Use either request or response.')

    def _compute_bit_length_set(self) -> BitLengthSet:     # pragma: no cover
        raise TypeError('Service types are not directly serializable. Use either request or response.')


def _unittest_composite_types() -> None:
    from pytest import raises
    from ._primitive import SignedIntegerType, FloatType
    from ._array import FixedLengthArrayType, VariableLengthArrayType

    def try_name(name: str) -> CompositeType:
        return CompositeType(name=name,
                             version=Version(0, 1),
                             attributes=[],
                             deprecated=False,
                             fixed_port_id=None,
                             source_file_path='')

    with raises(InvalidNameError, match='(?i).*empty.*'):
        try_name('')

    with raises(InvalidNameError, match='(?i).*root namespace.*'):
        try_name('T')

    with raises(InvalidNameError, match='(?i).*long.*'):
        try_name('namespace.another.deeper.' * 10 + 'LongTypeName')

    with raises(InvalidNameError, match='(?i).*component.*empty.*'):
        try_name('namespace.ns..T')

    with raises(InvalidNameError, match='(?i).*component.*empty.*'):
        try_name('.namespace.ns.T')

    with raises(InvalidNameError, match='(?i).*cannot start with.*'):
        try_name('namespace.0ns.T')

    with raises(InvalidNameError, match='(?i).*cannot start with.*'):
        try_name('namespace.ns.0T')

    with raises(InvalidNameError, match='(?i).*cannot contain.*'):
        try_name('namespace.n-s.T')

    assert try_name('root.nested.T').full_name == 'root.nested.T'
    assert try_name('root.nested.T').full_namespace == 'root.nested'
    assert try_name('root.nested.T').root_namespace == 'root'
    assert try_name('root.nested.T').short_name == 'T'

    with raises(MalformedUnionError, match='.*variants.*'):
        UnionType(name='a.A',
                  version=Version(0, 1),
                  attributes=[],
                  deprecated=False,
                  fixed_port_id=None,
                  source_file_path='')

    with raises(MalformedUnionError, match='(?i).*padding.*'):
        UnionType(name='a.A',
                  version=Version(0, 1),
                  attributes=[
                      Field(UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED), 'a'),
                      Field(SignedIntegerType(16, PrimitiveType.CastMode.SATURATED), 'b'),
                      PaddingField(VoidType(16)),
                  ],
                  deprecated=False,
                  fixed_port_id=None,
                  source_file_path='')

    u = UnionType(name='a.A',
                  version=Version(0, 1),
                  attributes=[
                      Field(UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED), 'a'),
                      Field(SignedIntegerType(16, PrimitiveType.CastMode.SATURATED), 'b'),
                      Constant(FloatType(32, PrimitiveType.CastMode.SATURATED), 'A', _expression.Rational(123)),
                  ],
                  deprecated=False,
                  fixed_port_id=None,
                  source_file_path='')
    assert u['a'].name == 'a'
    assert u['b'].name == 'b'
    assert u['A'].name == 'A'
    assert u.fields == u.fields_except_padding
    with raises(KeyError):
        assert u['c']
    del u

    s = StructureType(name='a.A',
                      version=Version(0, 1),
                      attributes=[
                          PaddingField(VoidType(8)),
                          Field(UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED), 'a'),
                          PaddingField(VoidType(64)),
                          Field(SignedIntegerType(16, PrimitiveType.CastMode.SATURATED), 'b'),
                          PaddingField(VoidType(2)),
                          Constant(FloatType(32, PrimitiveType.CastMode.SATURATED), 'A', _expression.Rational(123)),
                      ],
                      deprecated=False,
                      fixed_port_id=None,
                      source_file_path='')
    assert s['a'].name == 'a'
    assert s['b'].name == 'b'
    assert s['A'].name == 'A'
    assert len(s.constants) == 1
    assert len(s.fields) == 5
    assert len(s.fields_except_padding) == 2
    with raises(KeyError):
        assert s['c']
    with raises(KeyError):
        assert s['']        # Padding fields are not accessible
    del s

    def try_union_fields(field_types: typing.List[SerializableType]) -> UnionType:
        atr = []
        for i, t in enumerate(field_types):
            atr.append(Field(t, '_%d' % i))

        return UnionType(name='a.A',
                         version=Version(0, 1),
                         attributes=atr,
                         deprecated=False,
                         fixed_port_id=None,
                         source_file_path='')

    assert try_union_fields([
        UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
        SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
    ]).bit_length_set == {17}

    # The reference values for the following test are explained in the array tests above
    tu8 = UnsignedIntegerType(8, cast_mode=PrimitiveType.CastMode.TRUNCATED)
    small = VariableLengthArrayType(tu8, 2)
    outer = FixedLengthArrayType(small, 2)   # bit length values: {4, 12, 20, 28, 36}

    # Above plus one bit to each, plus 16-bit for the unsigned integer field
    assert try_union_fields([
        outer,
        SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
    ]).bit_length_set == {5, 13, 17, 21, 29, 37}

    def try_struct_fields(field_types: typing.List[SerializableType]) -> StructureType:
        atr = []
        for i, t in enumerate(field_types):
            atr.append(Field(t, '_%d' % i))

        return StructureType(name='a.A',
                             version=Version(0, 1),
                             attributes=atr,
                             deprecated=False,
                             fixed_port_id=None,
                             source_file_path='')

    assert try_struct_fields([
        UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
        SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
    ]).bit_length_set == {32}

    assert try_struct_fields([]).bit_length_set == {0}   # Empty sets forbidden

    assert try_struct_fields([
        outer,
        SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
    ]).bit_length_set == {4 + 16, 12 + 16, 20 + 16, 28 + 16, 36 + 16}

    assert try_struct_fields([outer]).bit_length_set == {4, 12, 20, 28, 36}


def _unittest_field_iterators() -> None:
    from pytest import raises
    from ._primitive import BooleanType, FloatType
    from ._array import FixedLengthArrayType, VariableLengthArrayType

    saturated = PrimitiveType.CastMode.SATURATED
    _seq_no = 0

    def make_type(meta: typing.Type[CompositeType], attributes: typing.Iterable[Attribute]) -> CompositeType:
        nonlocal _seq_no
        _seq_no += 1
        return meta('ns.Type' + str(_seq_no),
                    version=Version(1, 0),
                    attributes=attributes,
                    deprecated=False,
                    fixed_port_id=None,
                    source_file_path='')

    def validate_iterator(t: CompositeType,
                          reference: typing.Iterable[typing.Tuple[str, typing.Set[int]]],
                          base_offset: typing.Optional[BitLengthSet] = None) -> None:
        for (name, ref_set), (field, real_set) in itertools.zip_longest(reference,
                                                                        t.iterate_fields_with_offsets(base_offset)):
            assert field.name == name
            assert real_set == ref_set, field.name + ': ' + str(real_set)

    a = make_type(StructureType, [
        Field(UnsignedIntegerType(10, saturated), 'a'),
        Field(BooleanType(saturated), 'b'),
        Field(VariableLengthArrayType(FloatType(32, saturated), 2), 'c'),
        Field(FixedLengthArrayType(FloatType(32, saturated), 7), 'd'),
        PaddingField(VoidType(3)),
    ])

    validate_iterator(a, [
        ('a', {0}),
        ('b', {10}),
        ('c', {11}),
        ('d', {
            11 + 2 + 32 * 0,
            11 + 2 + 32 * 1,
            11 + 2 + 32 * 2,
        }),
        ('', {
            11 + 2 + 32 * 0 + 32 * 7,
            11 + 2 + 32 * 1 + 32 * 7,
            11 + 2 + 32 * 2 + 32 * 7,
        }),
    ])

    a_bls_options = [
        11 + 2 + 32 * 0 + 32 * 7 + 3,
        11 + 2 + 32 * 1 + 32 * 7 + 3,
        11 + 2 + 32 * 2 + 32 * 7 + 3,
    ]
    assert a.bit_length_set == BitLengthSet(a_bls_options)

    # Testing "a" again, this time with non-zero base offset
    validate_iterator(a, [
        ('a', {1, 16}),
        ('b', {1 + 10, 16 + 10}),
        ('c', {1 + 11, 16 + 11}),
        ('d', {
            1 + 11 + 2 + 32 * 0,
            1 + 11 + 2 + 32 * 1,
            1 + 11 + 2 + 32 * 2,
            16 + 11 + 2 + 32 * 0,
            16 + 11 + 2 + 32 * 1,
            16 + 11 + 2 + 32 * 2,
        }),
        ('', {
            1 + 11 + 2 + 32 * 0 + 32 * 7,
            1 + 11 + 2 + 32 * 1 + 32 * 7,
            1 + 11 + 2 + 32 * 2 + 32 * 7,
            16 + 11 + 2 + 32 * 0 + 32 * 7,
            16 + 11 + 2 + 32 * 1 + 32 * 7,
            16 + 11 + 2 + 32 * 2 + 32 * 7,
        }),
    ], BitLengthSet({1, 16}))

    b = make_type(StructureType, [
        Field(a, 'z'),
        Field(VariableLengthArrayType(a, 2), 'y'),
        Field(UnsignedIntegerType(6, saturated), 'x'),
    ])

    validate_iterator(b, [
        ('z', {0}),
        ('y', {
            a_bls_options[0],
            a_bls_options[1],
            a_bls_options[2],
        }),
        ('x', {  # The lone "+2" is for the variable-length array's implicit length field
            # First length option of z
            a_bls_options[0] + 2 + a_bls_options[0] * 0,  # suka
            a_bls_options[0] + 2 + a_bls_options[1] * 0,
            a_bls_options[0] + 2 + a_bls_options[2] * 0,
            a_bls_options[0] + 2 + a_bls_options[0] * 1,
            a_bls_options[0] + 2 + a_bls_options[1] * 1,
            a_bls_options[0] + 2 + a_bls_options[2] * 1,
            a_bls_options[0] + 2 + a_bls_options[0] * 2,
            a_bls_options[0] + 2 + a_bls_options[1] * 2,
            a_bls_options[0] + 2 + a_bls_options[2] * 2,
            # Second length option of z
            a_bls_options[1] + 2 + a_bls_options[0] * 0,
            a_bls_options[1] + 2 + a_bls_options[1] * 0,
            a_bls_options[1] + 2 + a_bls_options[2] * 0,
            a_bls_options[1] + 2 + a_bls_options[0] * 1,
            a_bls_options[1] + 2 + a_bls_options[1] * 1,
            a_bls_options[1] + 2 + a_bls_options[2] * 1,
            a_bls_options[1] + 2 + a_bls_options[0] * 2,
            a_bls_options[1] + 2 + a_bls_options[1] * 2,
            a_bls_options[1] + 2 + a_bls_options[2] * 2,
            # Third length option of z
            a_bls_options[2] + 2 + a_bls_options[0] * 0,
            a_bls_options[2] + 2 + a_bls_options[1] * 0,
            a_bls_options[2] + 2 + a_bls_options[2] * 0,
            a_bls_options[2] + 2 + a_bls_options[0] * 1,
            a_bls_options[2] + 2 + a_bls_options[1] * 1,
            a_bls_options[2] + 2 + a_bls_options[2] * 1,
            a_bls_options[2] + 2 + a_bls_options[0] * 2,
            a_bls_options[2] + 2 + a_bls_options[1] * 2,
            a_bls_options[2] + 2 + a_bls_options[2] * 2,
        }),
    ])

    # Ensuring the equivalency between bit length and bit offset
    b_offset = BitLengthSet()
    for f in b.fields:
        b_offset.increment(f.data_type.bit_length_set)
    print('b_offset:', b_offset)
    assert b_offset == b.bit_length_set
    assert b_offset.is_aligned_at_byte()
    assert not b_offset.is_aligned_at(32)

    c = make_type(UnionType, [
        Field(a, 'foo'),
        Field(b, 'bar'),
    ])

    validate_iterator(c, [
        ('foo', {1}),       # The offset is the same because it's a union
        ('bar', {1}),
    ])

    validate_iterator(c, [
        ('foo', {8 + 1}),
        ('bar', {8 + 1}),
    ], BitLengthSet(8))

    validate_iterator(c, [
        ('foo', {0 + 1, 4 + 1, 8 + 1}),
        ('bar', {0 + 1, 4 + 1, 8 + 1}),
    ], BitLengthSet({0, 4, 8}))

    with raises(TypeError, match='.*request or response.*'):
        ServiceType(name='ns.S',
                    version=Version(1, 0),
                    request_attributes=[],
                    response_attributes=[],
                    request_is_union=False,
                    response_is_union=False,
                    deprecated=False,
                    fixed_port_id=None,
                    source_file_path='').iterate_fields_with_offsets()
