# -*- coding: utf-8 -*-
"""Lớp gọi MISA CRM (g1) dùng chung cho mọi nhóm API của module.

Đăng nhập KHÔNG viết lại: dùng token CRM đã lưu của misa_fetch_po_button
(``misa.api.utils._with_crm_reauth``) — token hết hạn thì đăng nhập lại đúng một lần.
"""
import logging

from odoo import models
from odoo.addons.misa_fetch_po_button.utils.misa_api_utils import MisaAuthExpired

from ..services.crm_payloads import misa_error_message

_logger = logging.getLogger(__name__)

BASE_URL = "https://amisapp.misa.vn/crm/g1/api/business/"
# Trang "Thêm Cơ hội" gửi layoutcode=opportunity cho mọi lệnh (kể cả tìm khách / tìm hàng).
OPPORTUNITY_LAYOUT = "opportunity"
# Chế độ mở form trong URL của MISA: 2 = sửa, 4 = xem.
MODE_EDIT, MODE_VIEW = 2, 4


class CrmInputError(Exception):
    """Dữ liệu bên gọi gửi sai / tham chiếu không có trên MISA — trả thẳng cho bên gọi."""

    def __init__(self, status, error, message):
        super().__init__(message)
        self.status = status
        self.error = error
        self.message = message


class MisaCrmError(Exception):
    """MISA từ chối hoặc trả lỗi."""


class MisaCrmConnect(models.AbstractModel):
    _name = "hlv.misa.crm.connect"
    _description = "Kết nối MISA CRM (API cho bên ngoài)"

    def _misa(self):
        return self.env["misa.api.utils"].sudo()

    def _crm(self, method, path, layout=OPPORTUNITY_LAYOUT, payload=None, params=None):
        """Gọi ``BASE_URL + path``; trả cả response JSON (dict) khi ``Success``.

        MisaCrmError khi MISA trả lỗi / không phải JSON. Lỗi mạng ném nguyên (requests).
        """
        return self._misa()._with_crm_reauth(self._crm_send, method, path, layout, payload, params)

    def _crm_send(self, headers, method, path, layout, payload, params):
        # Header CRM dùng chung có "content-length" cứng: với GET (không body) MISA sẽ chờ
        # đủ số byte đó rồi treo tới timeout — phải bỏ. LayoutCode đặt lại theo từng màn.
        headers = {key: value for key, value in headers.items()
                   if key.lower() not in ("content-length", "layoutcode")}
        headers["LayoutCode"] = layout
        if method == "GET":
            headers = {key: value for key, value in headers.items() if key.lower() != "content-type"}
        response = self._misa()._get_retry_session().request(
            method, BASE_URL + path, headers=headers, params=params,
            json=payload if method != "GET" else None, timeout=30,
        )
        if response.status_code in (401, 403):
            raise MisaAuthExpired("CRM từ chối phiên đăng nhập (HTTP %s)" % response.status_code)
        try:
            data = response.json()
        except ValueError:
            raise MisaCrmError("MISA trả về không phải JSON (HTTP %s): %s"
                               % (response.status_code, response.text[:200]))
        if not isinstance(data, dict) or not data.get("Success"):
            message = misa_error_message(data) or response.text[:300]
            _logger.warning("MISA CRM %s %s lỗi: %s", method, path, message)
            raise MisaCrmError(message)
        return data

    def _crm_data(self, method, path, layout=OPPORTUNITY_LAYOUT, payload=None, params=None):
        """Như ``_crm`` nhưng chỉ trả phần ``Data``."""
        return self._crm(method, path, layout, payload, params).get("Data")

    # ── Mở form như người dùng bấm Sửa / Xem ─────────────────────────────
    def _current_record(self, module, form_layout_id, record_id, label, mode=MODE_EDIT):
        """Dữ liệu đang lưu của một bản ghi (FormDataNew) — gồm ModifiedDate / Version để sửa.

        ``module``: "Opportunity" / "Quote". Không có bản ghi -> CrmInputError 404.
        """
        data = self._crm_data(
            "POST", "%s/FormDataNew/%s/%d/%d" % (module, module, form_layout_id, mode), module.lower(),
            payload={"ID": str(record_id), "MISAEntityState": 2, "ActiveLayoutCode": None, "CustomDicData": None},
        ) or {}
        current = data.get("CurrentData") or {}
        if not current.get("ID"):
            raise CrmInputError(404, "not_found", "Không có %s ID %s trên MISA." % (label, record_id))
        return current

    def _saved_lines(self, module, record_id, subform_body):
        """Dòng hàng đang lưu của một bản ghi (GetDataSubFormByID, như khi mở form sửa)."""
        data = self._crm_data("POST", "%s/GetDataSubFormByID/%d/%d/null" % (module, int(record_id), MODE_EDIT),
                              module.lower(), payload=subform_body) or []
        return (data[0].get("DataFieldSubForm") if data else None) or []
