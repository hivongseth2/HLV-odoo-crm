# -*- coding: utf-8 -*-
"""Báo giá (Quote) trên MISA CRM: tìm, xem hàng, danh mục tình trạng, tạo, tạo từ cơ hội, sửa.

Tìm và xem hàng dùng lại misa_fetch_po_button (crm_search_quotes, crm_quote_products).
"""
import logging
from datetime import datetime, timezone

from odoo import models

from ..services import opportunity_payload as opportunity_form
from ..services.misa_form import VN_UTC_OFFSET, edit_rows, payload_total, renew_set_master_ids, subform_request
from ..services.quote_payload import (
    DEFAULT_STAGE, FORM_LAYOUT_ID, SUBFORM_AGGREGATES, SUBFORM_COLUMNS, TABLE, quote_line,
    quote_line_from_opportunity, quote_payload, saved_quote_row,
)
from .misa_crm_client import MODE_VIEW, CrmInputError, MisaCrmError

_logger = logging.getLogger(__name__)

MODULE = "Quote"
LAYOUT = "quote"
_DICTIONARY_PARAMS = {
    "page": "null", "searchText": "", "isLocationConcat": "false", "isContainFormLayoutName": "true",
    "isProductCustomField": "false", "isView": "true",
}


class MisaCrmQuote(models.AbstractModel):
    _inherit = "hlv.misa.crm.connect"

    def api_quote_search(self, keyword, limit=10):
        """Báo giá khớp ``keyword`` (số BG…, tên khách…). Xem misa.api.utils.crm_search_quotes."""
        return {"items": self._misa().crm_search_quotes(keyword, limit)}

    def api_quote_lines(self, quote_id):
        """Hàng của một báo giá. Xem misa.api.utils.crm_quote_products."""
        return {"items": self._misa().crm_quote_products(quote_id)}

    def api_quote_options(self):
        """Danh mục tình trạng báo giá. Trả {"stages": [{"id", "name"}]}."""
        stages = self._crm_data("GET", "Dictionary/Details/Quote/StageID/false/%d/1/null" % FORM_LAYOUT_ID,
                                LAYOUT, params=_DICTIONARY_PARAMS) or []
        return {"stages": [{"id": item.get("id"), "name": item.get("text")}
                           for item in stages if item.get("IsShow", True)]}

    def api_quote_create(self, account_id, lines, header, opportunity_id=None, stage_id=None):
        """Tạo báo giá như bấm Lưu ở trang "Thêm Báo giá".

        ``header``: quote_date, expired_date, description, prepaid, shipping_cost, commission_percent,
        validity_days, payment_terms, delivery_days (đã kiểm ở controller; shipping_cost,
        commission_percent bắt buộc như form MISA). ``opportunity_id``: gắn báo giá vào cơ hội (tuỳ chọn).
        Mọi tham chiếu được tra TRƯỚC khi tạo. Trả {"id", "code", "total"}.
        """
        account = self._quote_account(account_id)
        opportunity = self._quote_opportunity(opportunity_id) if opportunity_id else None
        stage = self._pick_quote_stage(stage_id)
        rows = self._new_lines(lines, _quote_row)
        return self._create_quote(account, opportunity, stage, header, rows)

    def api_quote_create_from_opportunity(self, opportunity_id, header, stage_id=None):
        """Tạo báo giá từ cơ hội: khách và hàng (SL, giá, thuế, chiết khấu) chép từ cơ hội, báo giá
        gắn vào cơ hội đó. Bỏ dòng ghi chú; combo chép cả dòng cha lẫn dòng con. Trả {"id", "code", "total"}."""
        current = self._current_record("Opportunity", opportunity_form.FORM_LAYOUT_ID, opportunity_id, "cơ hội")
        saved = self._saved_lines("Opportunity", opportunity_id, subform_request(
            opportunity_form.TABLE, opportunity_form.SUBFORM_COLUMNS, opportunity_form.SUBFORM_AGGREGATES))
        products = [row for row in sorted(saved, key=lambda r: r.get("SortOrder") or 0) if not row.get("IsNoteRow")]
        if not products:
            raise CrmInputError(400, "no_lines", "Cơ hội chưa có hàng — báo giá phải có ít nhất một dòng hàng.")
        account = self._quote_account(current["AccountID"])
        opportunity = {"id": current["ID"], "name": current.get("OpportunityName")}
        stage = self._pick_quote_stage(stage_id)
        # Combo chép nguyên dòng cha + dòng con, nhưng mã nhóm combo phải mới: mã cũ đang nối các dòng
        # của cơ hội, dùng lại là hai chứng từ chung một nhóm.
        rows = renew_set_master_ids(
            [quote_line_from_opportunity(index, row) for index, row in enumerate(products, start=1)])
        return self._create_quote(account, opportunity, stage, header, rows)

    def api_quote_update(self, quote_id, header, lines=None, stage_id=None):
        """Sửa báo giá như mở form, sửa, bấm Lưu. Khoá nào không có trong ``header`` = giữ nguyên.

        ``lines`` None = giữ hàng như cũ; có ``lines`` = THAY toàn bộ hàng (dòng cũ bị xoá).
        Ba trường công thức (còn phải thu, hoa hồng, lãi lỗ) luôn tính lại theo số mới.
        Trả {"id", "code", "total"}. Người khác vừa sửa cùng báo giá -> MISA từ chối (502).
        """
        current = self._current_record(MODULE, FORM_LAYOUT_ID, quote_id, "báo giá")
        values = {
            "quote_date": current.get("QuoteDate"), "expired_date": current.get("ExpiredDate"),
            "description": current.get("Description"), "prepaid": current.get("CustomField8"),
            "shipping_cost": current.get("CustomField18"), "commission_percent": current.get("CustomField19"),
            "validity_days": current.get("CustomField13"), "payment_terms": current.get("CustomField14"),
            "delivery_days": current.get("CustomField17"),
        }
        values.update(header)
        values.update({
            "account": {"id": current.get("AccountID"), "name": current.get("AccountIDText"),
                        "address": current.get("Address"), "tax_code": current.get("TaxCode")},
            "opportunity": {"id": current["OpportunityID"], "name": current.get("OpportunityIDText")}
            if current.get("OpportunityID") else None,
            "stage": self._pick_quote_stage(stage_id) if stage_id is not None else {
                "id": current.get("StageID"), "text": current.get("StageIDText")},
        })
        old_rows = [saved_quote_row(row) for row in self._saved_lines(
            MODULE, quote_id, subform_request(TABLE, SUBFORM_COLUMNS, SUBFORM_AGGREGATES))]
        new_rows = None if lines is None else self._new_lines(lines, _quote_row)
        payload = quote_payload(values, edit_rows(old_rows, new_rows), old_rows, {
            "id": current["ID"], "code": current.get("QuoteCode"),
            "modified_date": current.get("ModifiedDate"), "version": current.get("Version"),
        })
        saved_id = self._save_quote(payload)
        return {"id": saved_id, "code": current.get("QuoteCode"), "total": payload_total(payload)}

    # ------------------------------------------------------------------
    def _create_quote(self, account, opportunity, stage, header, rows):
        values = dict(header, account=account, opportunity=opportunity, stage=stage)
        values["quote_date"] = values.get("quote_date") or _today_vn()
        payload = quote_payload(values, rows)
        quote_id = self._save_quote(payload)
        return {"id": quote_id, "code": self._quote_code(quote_id), "total": payload_total(payload)}

    def _save_quote(self, payload):
        record_id = self._crm_data("POST", MODULE, LAYOUT, payload=payload)
        if not record_id:
            raise MisaCrmError("MISA báo lưu xong nhưng không trả ID báo giá.")
        return record_id

    def _quote_account(self, account_id):
        """Khách cho đầu báo giá — form tự điền địa chỉ và MST theo khách."""
        account = self.api_account_get(account_id)
        return {"id": account["id"], "name": account["name"], "address": account["billing_address"],
                "tax_code": account["tax_code"]}

    def _quote_opportunity(self, opportunity_id):
        current = self._current_record("Opportunity", opportunity_form.FORM_LAYOUT_ID, opportunity_id, "cơ hội",
                                       mode=MODE_VIEW)
        return {"id": current["ID"], "name": current.get("OpportunityName")}

    def _pick_quote_stage(self, stage_id):
        """Tình trạng đã chọn; None -> "Bản thảo" (mặc định của form, không cần tra danh mục)."""
        if stage_id is None:
            return DEFAULT_STAGE
        stages = self.api_quote_options()["stages"]
        found = next((stage for stage in stages if stage["id"] == stage_id), None)
        if not found:
            choices = ", ".join("%s=%s" % (stage["id"], stage["name"]) for stage in stages)
            raise CrmInputError(400, "invalid_stage", "Không có tình trạng ID %s. Chọn: %s." % (stage_id, choices))
        return {"id": found["id"], "text": found["name"]}

    def _quote_code(self, quote_id):
        """Số báo giá MISA vừa cấp; không đọc được -> None (không làm hỏng kết quả tạo)."""
        try:
            return self._current_record(MODULE, FORM_LAYOUT_ID, quote_id, "báo giá", mode=MODE_VIEW).get("QuoteCode")
        except Exception as error:  # noqa: BLE001
            _logger.warning("Báo giá %s: không đọc được số báo giá: %s", quote_id, error)
            return None


def _quote_row(index, product, qty, amounts, line):
    return quote_line(index, product, qty, amounts, line.get("description"), line.get("customer_item"))


def _today_vn():
    return (datetime.now(timezone.utc) + VN_UTC_OFFSET).date().isoformat()
