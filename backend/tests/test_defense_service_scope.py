from __future__ import annotations

import pytest

from app.defense.service import DefenseService


class _Principal:
    def __init__(self, *, access_level: str, section_code: str | None):
        self.access_level = access_level
        self.section_code = section_code


def test_effective_section_uses_principal_section_for_section_users():
    principal = _Principal(access_level="section", section_code="telecom")
    out = DefenseService._effective_section(principal, requested_section="banking")
    assert out == "telecom"


def test_effective_section_requires_section_code_for_section_users():
    principal = _Principal(access_level="section", section_code=None)
    with pytest.raises(ValueError) as e:
        DefenseService._effective_section(principal, requested_section="telecom")
    assert str(e.value) == "principal_section_code_missing"


def test_effective_section_allows_central_to_select_section():
    principal = _Principal(access_level="central", section_code=None)
    out = DefenseService._effective_section(principal, requested_section="revenue")
    assert out == "revenue"
