# -*- coding: utf-8 -*-
"""Cấu hình trợ lý quản trị: một bản ghi duy nhất — prompt lõi, model, mức suy nghĩ.

API key dùng chung với trợ lý tạo mã hàng (Cài đặt > Tồn kho > Trợ lý tạo mã hàng): một chỗ khai
key, một chỗ thanh toán.
"""
from odoo import api, fields, models
from odoo.tools import file_open

from odoo.addons.hlv_product_agent.services import prompt_version
from odoo.addons.hlv_product_agent.services.claude_api_payload import EFFORT_CHOICES, MODEL_CHOICES

from ..services.admin_payload import admin_system_text

DEFAULT_PROMPT_FILE = 'hlv_admin_agent/data/prompt_defaults/admin_core.md'
# Vân tay (prompt_version) các bản prompt lõi mặc định đã phát hành. Prompt trong DB còn đúng một bản
# này = chưa ai sửa, nâng cấp module thì thay bằng bản mặc định hiện tại; đã sửa tay thì giữ nguyên.
OLD_DEFAULT_VERSIONS = {
    '4f5c506fe741c064',  # 18.0.1.0.0 - 18.0.1.1.0: chưa có ghi nhớ, cuộc chat cũ, nút dừng
    'd1b651b1c510cc1b',  # 18.0.1.2.0: còn ghi combo chưa thêm được vào báo giá / cơ hội
}
# Quản trị hỏi ít nhưng việc khó hơn sale (ghép báo giá nhiều dòng, đối chiếu giá khách): mặc định
# model kỹ hơn trợ lý tạo mã.
DEFAULT_MODEL = 'claude-sonnet-5-5'
DEFAULT_EFFORT = 'medium'


class HlvAdminAgentConfig(models.Model):
    _name = 'hlv.admin.agent.config'
    _description = "Cấu hình trợ lý quản trị"

    name = fields.Char(default="Trợ lý quản trị", required=True)
    model = fields.Selection(MODEL_CHOICES, string="Model", default=DEFAULT_MODEL, required=True)
    effort = fields.Selection(EFFORT_CHOICES, string="Mức suy nghĩ", default=DEFAULT_EFFORT, required=True,
                              help="Cao: kỹ hơn nhưng chậm và tốn token hơn.")
    prompt_core = fields.Text(
        "Prompt lõi", required=True,
        help="Luật riêng của trợ lý quản trị. Prompt của trợ lý tạo mã hàng được nối sau làm phụ lục "
             "(sửa ở Tồn kho > Cấu hình > Trợ lý tạo mã hàng > Prompt trợ lý).",
    )

    @api.model
    def current(self):
        """Bản ghi cấu hình (tạo từ mặc định nếu chưa có)."""
        config = self.sudo().search([], limit=1)
        return config or self.sudo().create({'prompt_core': self._default_prompt()})

    @api.model
    def _ensure_default(self):
        """Gọi từ data XML mỗi lần cài / nâng cấp: tạo bản cấu hình nếu chưa có; prompt lõi còn nguyên bản
        mặc định cũ thì lên bản mới."""
        config = self.current()
        if prompt_version((config.prompt_core or '').strip() + "\n") in OLD_DEFAULT_VERSIONS:
            config.prompt_core = self._default_prompt()

    @api.model
    def action_open_current(self):
        """Menu "Cấu hình" mở thẳng bản ghi duy nhất."""
        return {
            'type': 'ir.actions.act_window',
            'name': "Cấu hình trợ lý quản trị",
            'res_model': self._name,
            'res_id': self.current().id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def _default_prompt(self):
        # file_open không nhận encoding: đọc byte rồi tự giải mã UTF-8 (prompt toàn tiếng Việt có dấu).
        with file_open(DEFAULT_PROMPT_FILE, 'rb') as handle:
            return handle.read().decode('utf-8').strip() + "\n"

    def action_reset_prompt(self):
        """Đưa prompt lõi về bản mặc định đi kèm module."""
        for config in self:
            config.prompt_core = self._default_prompt()

    def run_config(self):
        """Cấu hình cho một lượt chạy: dict ``{'api_key', 'model', 'effort', 'worker_model'}``.

        api_key và model phụ tra cứu lấy của trợ lý tạo mã (model phụ chạy bằng code của module đó).
        """
        self.ensure_one()
        product = self.env['hlv.product.agent.api.runner'].sudo().config()
        return {'api_key': product['api_key'], 'model': self.model, 'effort': self.effort,
                'worker_model': product['worker_model']}

    def system_text(self):
        """System prompt hoàn chỉnh: prompt lõi + prompt trợ lý tạo mã (phụ lục)."""
        self.ensure_one()
        product_prompt, _version = self.env['hlv.product.agent.prompt'].sudo().build_prompt()
        return admin_system_text(self.prompt_core, product_prompt)
