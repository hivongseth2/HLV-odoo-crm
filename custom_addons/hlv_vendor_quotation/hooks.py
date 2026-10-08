# -*- coding: utf-8 -*-
from .services.access_setup import grant_default_groups


def post_init_hook(env):
    """Cài mới: gán nhóm Hỏi giá NCC cho người đang có quyền vào trang (xem access_setup)."""
    grant_default_groups(env)
