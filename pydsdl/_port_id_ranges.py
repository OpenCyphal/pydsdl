# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

MAX_SUBJECT_ID = 8191
MAX_SERVICE_ID = 511


_STANDARD_ROOT_NAMESPACE = "uavcan"

_STANDARD_MESSAGES = 7168, 8191
_STANDARD_SERVICES = 384, 511

# The upper end of the ranges may be consumed by the standard types shall that become necessary,
# so new fixed port-ID allocations should be granted at the bottom of the ranges only.
_VENDOR_MESSAGES = 6144, 7167
_VENDOR_SERVICES = 256, 383


def is_valid_regulated_subject_id(regulated_id: int, root_namespace: str) -> bool:
    is_standard = root_namespace.strip() == _STANDARD_ROOT_NAMESPACE
    lo, hi = _STANDARD_MESSAGES if is_standard else _VENDOR_MESSAGES
    return lo <= int(regulated_id) <= hi


def is_valid_regulated_service_id(regulated_id: int, root_namespace: str) -> bool:
    is_standard = root_namespace.strip() == _STANDARD_ROOT_NAMESPACE
    lo, hi = _STANDARD_SERVICES if is_standard else _VENDOR_SERVICES
    return lo <= int(regulated_id) <= hi


def _unittest_pid_ranges() -> None:
    assert is_valid_regulated_subject_id(regulated_id=7000, root_namespace="sirius_cybernetics_corp")
    assert not is_valid_regulated_subject_id(regulated_id=7000, root_namespace="uavcan")
    assert is_valid_regulated_subject_id(regulated_id=8000, root_namespace="uavcan")
    assert not is_valid_regulated_subject_id(regulated_id=8000, root_namespace="sirius_cybernetics_corp")
    assert not is_valid_regulated_subject_id(regulated_id=6000, root_namespace="uavcan")
    assert not is_valid_regulated_subject_id(regulated_id=6000, root_namespace="sirius_cybernetics_corp")

    assert is_valid_regulated_service_id(regulated_id=260, root_namespace="sirius_cybernetics_corp")
    assert not is_valid_regulated_service_id(regulated_id=260, root_namespace="uavcan")
    assert is_valid_regulated_service_id(regulated_id=400, root_namespace="uavcan")
    assert not is_valid_regulated_service_id(regulated_id=400, root_namespace="sirius_cybernetics_corp")
    assert not is_valid_regulated_service_id(regulated_id=600, root_namespace="uavcan")
    assert not is_valid_regulated_service_id(regulated_id=600, root_namespace="sirius_cybernetics_corp")
