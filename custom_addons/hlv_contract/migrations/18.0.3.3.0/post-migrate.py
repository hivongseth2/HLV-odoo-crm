# -*- coding: utf-8 -*-
"""Bản 3.3: khuôn số hợp đồng theo mẫu + sửa đè biến tự điền.

- Mẫu đã có nhận khuôn số mặc định theo loại (mua bán: ngày soạn + HLV-mã khách).
- Hợp đồng đã có: ghi danh sách biến tự điền đọc từ bản chụp; số cũ giữ nguyên, không tự cấp lại.
"""

from odoo import SUPERUSER_ID, api

from odoo.addons.hlv_contract.models.contract_template import DEFAULT_NUMBER_PATTERNS
from odoo.addons.hlv_contract.utils import contract_vars, docx_merge


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for template in env['hlv.contract.template'].with_context(active_test=False).search([]):
        template.number_pattern = DEFAULT_NUMBER_PATTERNS.get(template.contract_type)
    for contract in env['hlv.contract'].search([]):
        names = docx_merge.list_merge_fields(contract._doc_bytes())
        contract.write({
            'doc_system_fields': ','.join(n for n in names if contract_vars.is_system_variable(n)),
            'number_auto': False,
        })
