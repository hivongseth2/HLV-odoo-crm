# -*- coding: utf-8 -*-
"""Chạy tool MISA CRM mà Claude gọi tới, bằng hlv.misa.crm.connect.

Kiểm tham số và gọi model dùng lại ĐÚNG hàm của API /api/misa-crm/* (controllers.crm_api,
body_fields): tool tạo báo giá và route tạo báo giá không bao giờ lệch luật nhau. Bỏ qua công tắc
"cho phép tạo dữ liệu" của API — công tắc đó dành cho hệ thống bên ngoài cầm API key; ở đây người
gọi đã qua quyền Trợ lý quản trị và chốt đề xuất + OK.

Mọi kết quả có khoá 'status' để Claude phân biệt found / error / need_confirmation.
"""
import logging

from odoo import models
from odoo.exceptions import UserError

from odoo.addons.hlv_misa_crm_connect.controllers import body_fields as body
from odoo.addons.hlv_misa_crm_connect.controllers import crm_api
from odoo.addons.hlv_misa_crm_connect.controllers.api_common import int_field
from odoo.addons.hlv_misa_crm_connect.models.misa_crm_client import CrmInputError, MisaCrmError
from odoo.addons.hlv_product_agent.services import missing_from_proposal
from odoo.addons.misa_fetch_po_button.controllers.misa_product_api import ApiError

from ..services.crm_tools import CRM_WRITE_TOOL_NAMES, crm_event_text, write_tool_proposal_values

_logger = logging.getLogger(__name__)


# Mọi handler nhận (args, crm) — cùng thứ tự với các hàm route của controllers.crm_api dùng lại ở dưới.
def _search(method):
    """Tool tìm theo từ khoá + limit (cơ hội, báo giá, đơn hàng)."""
    return lambda args, crm: getattr(crm, method)(body.keyword(args, required=True), body.paging(args)[1])


def _by_id(method):
    return lambda args, crm: getattr(crm, method)(int_field(args, 'id'))


_HANDLERS = {
    'crm_tim_khach': lambda args, crm: crm.api_account_search(body.keyword(args, required=True), *body.paging(args)),
    'crm_xem_khach': lambda args, crm: {'account': crm.api_account_get(int_field(args, 'id'))},
    'crm_tim_hang': lambda args, crm: crm.api_product_search(
        body.keyword(args, required=True), *body.paging(args), in_stock_only=bool(args.get('chi_hang_con_ton'))),
    'crm_gia_cho_khach': crm_api._product_prices,
    'crm_danh_muc_co_hoi': lambda args, crm: crm.api_opportunity_options(),
    'crm_tim_co_hoi': _search('api_opportunity_search'),
    'crm_xem_hang_co_hoi': _by_id('api_opportunity_lines'),
    'crm_danh_muc_bao_gia': lambda args, crm: crm.api_quote_options(),
    'crm_tim_bao_gia': _search('api_quote_search'),
    'crm_xem_hang_bao_gia': _by_id('api_quote_lines'),
    'crm_tim_don_hang': _search('api_sale_order_search'),
    'crm_xem_hang_don_hang': _by_id('api_sale_order_lines'),
    'crm_tao_co_hoi': crm_api._create_opportunity,
    'crm_sua_co_hoi': crm_api._update_opportunity,
    'crm_tao_bao_gia': crm_api._create_quote,
    'crm_tao_bao_gia_tu_co_hoi': crm_api._create_quote_from_opportunity,
    'crm_sua_bao_gia': crm_api._update_quote,
}


class HlvAdminCrmTools(models.AbstractModel):
    _name = 'hlv.admin.crm.tools'
    _description = "Tool MISA CRM cho trợ lý quản trị"

    def run(self, session, name, args):
        """Chạy một tool CRM cho cuộc chat ``session``.

        Nhận: cuộc chat đang được xử lý, tên tool, dict tham số.
        Trả: dict kết quả, luôn có 'status'. Lệnh ghi chưa được đề xuất -> 'need_confirmation'.
        """
        handler = _HANDLERS.get(name)
        if not handler:
            return {'status': 'error', 'message': "Tool %s chưa được hỗ trợ." % name}
        if not isinstance(args, dict):
            return {'status': 'error', 'message': "Tham số phải là object JSON."}
        is_write = name in CRM_WRITE_TOOL_NAMES
        if is_write:
            unconfirmed = self._require_proposed(session, write_tool_proposal_values(name, args))
            if unconfirmed:
                return unconfirmed
        try:
            result = handler(args, self.env['hlv.misa.crm.connect'].sudo())
        except (ApiError, CrmInputError) as error:
            return {'status': 'error', 'message': error.message}
        except (MisaCrmError, UserError) as error:
            return {'status': 'error', 'message': "MISA báo lỗi: %s" % error}
        except Exception as error:  # noqa: BLE001 — lỗi mạng / MISA lạ: Claude phải nhận được kết quả lỗi
            _logger.exception("ADMIN_AGENT tool %s lỗi", name)
            return {'status': 'error', 'message': "Lỗi khi gọi MISA: %s" % error}
        if not is_write:
            return dict(result, status='found')

        # Ghi chú do Odoo chèn, không dựa vào lời Claude kể: người dùng thấy chính xác cái gì đã lên MISA.
        _logger.info("ADMIN_AGENT %s (cuộc %s) %s: %s", session.user_id.login, session.id, name, result)
        session.post_event(crm_event_text(name, result))
        return dict(result, status='success')

    @staticmethod
    def _require_proposed(session, values):
        """Chặn lệnh ghi khi ID / mã hàng chưa có nguyên văn trong câu trả lời trước của trợ lý.

        Chặn ở Odoo chứ không chỉ dặn trong prompt: Claude hiểu nhầm một câu hỏi thành lệnh là có
        báo giá sai trên MISA. Trả None nếu đủ; dict 'need_confirmation' nếu thiếu.
        """
        missing = missing_from_proposal(session.previous_reply(), values)
        if not missing:
            return None
        _logger.info("ADMIN_AGENT chặn lệnh ghi chưa đề xuất (cuộc %s): %s", session.id, missing)
        return {
            'status': 'need_confirmation',
            'message': "Chưa ghi gì lên MISA. Câu trả lời trước chưa có nguyên văn: %s. Gửi đề xuất "
                       "đầy đủ (khách kèm ID, từng dòng mã — tên — SL — đơn giá) rồi chờ người dùng xác "
                       "nhận ở tin sau." % ", ".join(missing),
        }
