# -*- coding: utf-8 -*-
from odoo import _, fields, models

from ..services.claude_api_payload import (
    DEFAULT_EFFORT, DEFAULT_MODEL, DEFAULT_WORKER_MODEL, EFFORT_CHOICES, MODEL_CHOICES,
)
from .product_agent_api_runner import (
    CRON_XMLID, DEFAULT_PARALLEL, MAX_PARALLEL, MODE_API, MODE_LOCAL, PARAM_API_KEY,
    PARAM_EFFORT, PARAM_MODE, PARAM_MODEL, PARAM_PARALLEL, PARAM_WORKER_MODEL, TurnFailed,
)
from .product_name_alias import DEFAULT_ALIAS_MODEL, PARAM_ALIAS_MODEL, STUDY_BATCH


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    hlv_product_agent_mode = fields.Selection(
        [(MODE_LOCAL, "Máy chạy Claude (agent trên máy văn phòng)"),
         (MODE_API, "Claude API (API key, Odoo tự gọi)")],
        string="Trợ lý tạo mã chạy bằng", default=MODE_LOCAL, config_parameter=PARAM_MODE,
        help="Máy chạy Claude: agent cài trên máy văn phòng poll về Odoo (Claude Code, gói "
             "Claude). Claude API: Odoo tự gọi Claude bằng API key, không cần máy nào bật, "
             "tính tiền theo token. Đổi qua lại lúc nào cũng được; hai bên dùng chung hàng chờ.",
    )
    # Chỉ admin hệ thống mở được trang cài đặt, và giá trị nằm trong ir.config_parameter
    # (chỉ group_system đọc được) — cùng mức bảo vệ với token agent.
    hlv_product_agent_api_key = fields.Char(
        "Anthropic API key", config_parameter=PARAM_API_KEY,
        help="Tạo ở console.anthropic.com > API keys. Dạng sk-ant-...",
    )
    hlv_product_agent_api_model = fields.Selection(
        MODEL_CHOICES, string="Model", default=DEFAULT_MODEL, config_parameter=PARAM_MODEL,
    )
    hlv_product_agent_api_worker_model = fields.Selection(
        MODEL_CHOICES, string="Model phụ đi tra cứu", default=DEFAULT_WORKER_MODEL,
        config_parameter=PARAM_WORKER_MODEL,
        help="Model chính giao việc tra cứu dài (lịch sử xuất nhập, lịch sử giá bán, ai đang giữ...) "
             "cho model này đọc rồi tóm tắt. Haiku: rẻ, đủ cho việc đọc số liệu.",
    )
    hlv_product_agent_api_effort = fields.Selection(
        EFFORT_CHOICES, string="Mức suy nghĩ", default=DEFAULT_EFFORT, config_parameter=PARAM_EFFORT,
        help="Cao: kỹ hơn nhưng chậm và tốn token hơn. Vừa là đủ cho tạo mã hàng.",
    )
    hlv_product_agent_api_parallel = fields.Integer(
        "Số cuộc chạy song song", default=DEFAULT_PARALLEL, config_parameter=PARAM_PARALLEL,
        help="Số sale được Claude trả lời cùng lúc (1 tới %d). Ai tới sau thì xếp hàng." % MAX_PARALLEL,
    )

    hlv_product_agent_alias_model = fields.Selection(
        MODEL_CHOICES, string="Model đọc danh mục", default=DEFAULT_ALIAS_MODEL,
        config_parameter=PARAM_ALIAS_MODEL,
        help="Mỗi giờ Claude đọc các tên loại hàng mới trong kho, liệt kê cách sale hay gọi (\"tê\" cho "
             "\"Chữ T PVC\", \"băng tan\" cho \"Cao su non\") để trợ lý tìm không sót. Chỉ tốn token với loại "
             "mới. Opus biết nhiều cách gọi hơn nhưng đắt gấp đôi Sonnet.",
    )

    def set_values(self):
        super().set_values()
        # Chế độ máy văn phòng thì tắt cron: khỏi chạy không mỗi phút, khỏi rác log.
        cron = self.env.ref(CRON_XMLID, raise_if_not_found=False)
        if cron:
            cron.sudo().active = self.hlv_product_agent_mode == MODE_API

    def action_hlv_product_agent_study_catalog(self):
        """Cho Claude đọc ngay một đợt tên loại chưa đọc (không chờ cron)."""
        self.ensure_one()
        # Một lô (~1 phút) cho kịp trả lời trình duyệt; phần còn lại cron đọc mỗi giờ.
        added = self.env['hlv.product.name.type']._cron_study_catalog(limit=STUDY_BATCH)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'type': 'info', 'title': _("Tên gọi khác"),
                       'message': _("Đã thêm %s cách gọi khác. Các loại còn lại cron đọc tiếp mỗi giờ.") % added},
        }

    def action_hlv_product_agent_check_api(self):
        """Thử API key + model đang nhập. Không tốn token."""
        self.ensure_one()
        try:
            message = self.env['hlv.product.agent.api.runner'].check_connection(
                (self.hlv_product_agent_api_key or '').strip(),
                self.hlv_product_agent_api_model or DEFAULT_MODEL,
            )
            kind = 'success'
        except TurnFailed as failure:
            message, kind = str(failure), 'danger'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'type': kind, 'title': _("Claude API"), 'message': message},
        }
