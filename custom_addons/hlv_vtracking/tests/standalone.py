"""Nạp các module ``tools/`` thuần để test chạy được KHÔNG cần Odoo.

Trong Odoo: import bình thường qua ``odoo.addons``. Ngoài Odoo: dựng khung package
``odoo.addons.hlv_vtracking.tools`` / ``odoo.addons.hlv_geo_utils.tools`` trỏ thẳng vào thư
mục thật, KHÔNG chạy ``__init__.py`` của addon (cái đó kéo models vào -> cần Odoo). Nhờ vậy
import tương đối giữa các file trong ``tools/`` vẫn chạy đúng như trong Odoo.
"""

import importlib
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ADDONS = os.path.abspath(os.path.join(HERE, '..', '..'))


def _stub_package(name, path=None):
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    if path is not None:
        module.__path__ = [path]
    return module


def load_tool(name):
    """``load_tool('vtracking_route')`` -> module ``hlv_vtracking/tools/vtracking_route.py``."""
    try:
        return importlib.import_module('odoo.addons.hlv_vtracking.tools.%s' % name)
    except ImportError:
        pass
    _stub_package('odoo')
    _stub_package('odoo.addons')
    _stub_package('odoo.addons.hlv_geo_utils', os.path.join(ADDONS, 'hlv_geo_utils'))
    _stub_package('odoo.addons.hlv_geo_utils.tools',
                  os.path.join(ADDONS, 'hlv_geo_utils', 'tools'))
    _stub_package('odoo.addons.hlv_vtracking', os.path.join(ADDONS, 'hlv_vtracking'))
    _stub_package('odoo.addons.hlv_vtracking.tools',
                  os.path.join(ADDONS, 'hlv_vtracking', 'tools'))
    return importlib.import_module('odoo.addons.hlv_vtracking.tools.%s' % name)
