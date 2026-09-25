# -*- coding: utf-8 -*-

from .confirmation import missing_from_proposal
from .enroll_code import ENROLL_CODE_LENGTH, normalize_enroll_code, random_enroll_code
from .permission_marker import apply_permission_marker, strip_permission_markers
from .sale_identity import parse_sale_identities, resolve_sale_identity
from .system_prompt import build_system_prompt, prompt_version, render_special_rules
from .turn_prompt import attachment_filename, build_turn_prompt

__all__ = [
    "missing_from_proposal",
    "ENROLL_CODE_LENGTH",
    "normalize_enroll_code",
    "random_enroll_code",
    "apply_permission_marker",
    "strip_permission_markers",
    "parse_sale_identities",
    "resolve_sale_identity",
    "build_system_prompt",
    "prompt_version",
    "render_special_rules",
    "attachment_filename",
    "build_turn_prompt",
]
