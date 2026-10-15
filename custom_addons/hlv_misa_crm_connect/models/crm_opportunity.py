# -*- coding: utf-8 -*-
"""Cơ hội (Opportunity) trên MISA CRM: danh mục của form, tìm, xem hàng, tạo, sửa.

Tìm và xem hàng dùng lại misa_fetch_po_button (crm_search_opportunities, crm_opportunity_products).
"""
import logging

from odoo import models

from ..services.misa_form import edit_rows, payload_total, saved_row, subform_request
from ..services.opportunity_payload import (
    FORM_LAYOUT_ID, SUBFORM_AGGREGATES, SUBFORM_COLUMNS, TABLE, opportunity_line, opportunity_payload,
    stage_history_payload,
)
from .misa_crm_client import MODE_VIEW, CrmInputError, MisaCrmError

_logger = logging.getLogger(__name__)

MODULE = "Opportunity"
_DICTIONARY_PARAMS = {
    "page": "null", "searchText": "", "isLocationConcat": "false", "isContainFormLayoutName": "true",
    "isProductCustomField": "false", "isView": "true",
}


class MisaCrmOpportunity(models.AbstractModel):
    _inherit = "hlv.misa.crm.connect"

    def api_opportunity_options(self):
        """Danh mục cho form Cơ hội: giai đoạn (kèm % thành công) và nguồn gốc.

        Trả {"stages": [{"id", "name", "probability"}], "lead_sources": [{"id", "name"}]}.
        """
        stages = self._crm_data(
            "GET", "Dictionary/Details/Opportunity/StageID/false/%d/1/null" % FORM_LAYOUT_ID,
            params=_DICTIONARY_PARAMS) or []
        probability = self._crm_data(
            "GET", "StageProbability/GetStageProbability/Opportunity/StageID/false/%d" % FORM_LAYOUT_ID) or {}
        by_stage = {item.get("Value"): item.get("Probability")
                    for item in probability.get("ListStageProbability") or []}
        sources = self._crm_data(
            "GET", "Dictionary/Details/Opportunity/LeadSourceID/false/%d/null/null" % FORM_LAYOUT_ID,
            params=_DICTIONARY_PARAMS) or []
        return {
            "stages": [{"id": item.get("id"), "name": item.get("text"), "probability": by_stage.get(item.get("id"))}
                       for item in stages if item.get("IsShow", True)],
            "lead_sources": [{"id": item.get("id"), "name": item.get("text")}
                             for item in sources if item.get("IsShow", True)],
        }

    def api_opportunity_search(self, keyword, limit=10):
        """Cơ hội khớp ``keyword`` (số cơ hội, tên, khách…). Xem misa.api.utils.crm_search_opportunities."""
        return {"items": self._misa().crm_search_opportunities(keyword, limit)}

    def api_opportunity_lines(self, opportunity_id):
        """Hàng của một cơ hội. Xem misa.api.utils.crm_opportunity_products."""
        return {"items": self._misa().crm_opportunity_products(opportunity_id)}

    def api_opportunity_create(self, account_id, closing_date, lines, stage_id=1, lead_source_id=None,
                               name=None, description=None):
        """Tạo cơ hội như bấm Lưu ở trang "Thêm Cơ hội".

        ``lines``: [{"code", "qty", "price_after_tax" | "price", "description"?}] — đã kiểm kiểu ở
        controller. Mọi tham chiếu (khách, giai đoạn, nguồn, mã hàng) được tra trên MISA TRƯỚC khi
        tạo: sai một cái là không tạo gì (CrmInputError).
        Trả {"id", "code", "total", "warning"?}. Người phụ trách = tài khoản MISA mà Odoo đăng nhập.
        """
        account = self.api_account_get(account_id)
        options = self.api_opportunity_options()
        stage = self._pick_stage(options, stage_id)
        source = self._pick_source(options, lead_source_id)
        rows = self._new_lines(lines, _opportunity_row)
        payload = opportunity_payload({
            "account": {"id": account["id"], "name": account["name"]}, "stage": stage,
            "closing_date": closing_date, "name": name, "lead_source": source, "description": description,
        }, rows)
        opportunity_id = self._save_opportunity(payload)
        result = {"id": opportunity_id, "total": payload_total(payload)}
        # Hai bước sau khi tạo đều phụ: lỗi thì vẫn trả ID (cơ hội ĐÃ có trên MISA, gọi lại là tạo trùng).
        result.update(self._after_stage_change(opportunity_id, stage, closing_date))
        result["code"] = self._opportunity_code(opportunity_id)
        return result

    def api_opportunity_update(self, opportunity_id, name=None, stage_id=None, closing_date=None,
                               lead_source_id=None, description=None, lines=None):
        """Sửa cơ hội như mở form, sửa, bấm Lưu. Trường None = giữ nguyên.

        ``lines`` None = giữ hàng như cũ; có ``lines`` = THAY toàn bộ hàng (dòng cũ bị xoá).
        Trả {"id", "code", "total", "warning"?}. Người khác vừa sửa cùng cơ hội -> MISA từ chối (502).
        """
        current = self._current_record(MODULE, FORM_LAYOUT_ID, opportunity_id, "cơ hội")
        options = self.api_opportunity_options() if stage_id is not None or lead_source_id is not None else None
        stage = self._pick_stage(options, stage_id) if stage_id is not None else {
            "id": current.get("StageID"), "text": current.get("StageIDText"),
            "probability": current.get("Probability")}
        if lead_source_id is not None:
            source = self._pick_source(options, lead_source_id)
        else:
            source = {"id": current["LeadSourceID"], "text": current.get("LeadSourceIDText")} \
                if current.get("LeadSourceID") else None
        closing = closing_date or current.get("ClosingDate")
        old_rows = [saved_row(row, TABLE) for row in self._saved_lines(
            MODULE, opportunity_id, subform_request(TABLE, SUBFORM_COLUMNS, SUBFORM_AGGREGATES))]
        new_rows = None if lines is None else self._new_lines(lines, _opportunity_row)
        payload = opportunity_payload({
            "account": {"id": current.get("AccountID"), "name": current.get("AccountIDText")},
            "stage": stage, "closing_date": closing,
            "name": name or current.get("OpportunityName"), "lead_source": source,
            "description": current.get("Description") if description is None else description,
            "custom_field13": current.get("CustomField13"),
        }, edit_rows(old_rows, new_rows), old_rows, {
            "id": current["ID"], "code": current.get("OpportunityCode"),
            "modified_date": current.get("ModifiedDate"), "version": current.get("Version"),
        })
        saved_id = self._save_opportunity(payload)
        result = {"id": saved_id, "code": current.get("OpportunityCode"), "total": payload_total(payload)}
        if stage["id"] != current.get("StageID"):
            result.update(self._after_stage_change(saved_id, stage, closing))
        return result

    # ------------------------------------------------------------------
    def _save_opportunity(self, payload):
        record_id = self._crm_data("POST", MODULE, payload=payload)
        if not record_id:
            raise MisaCrmError("MISA báo lưu xong nhưng không trả ID cơ hội.")
        return record_id

    def _after_stage_change(self, opportunity_id, stage, closing_date):
        """Ghi lịch sử giai đoạn như form làm sau khi lưu. Lỗi -> {"warning"} (cơ hội đã lưu rồi)."""
        try:
            self._crm("POST", "Opportunity/stageHistory",
                      payload=stage_history_payload(opportunity_id, stage, closing_date))
            return {}
        except Exception as error:  # noqa: BLE001
            _logger.warning("Cơ hội %s: không ghi được lịch sử giai đoạn: %s", opportunity_id, error)
            return {"warning": "Đã lưu cơ hội nhưng không ghi được lịch sử giai đoạn: %s" % error}

    @staticmethod
    def _pick(items, wanted, error, label):
        try:
            wanted = int(wanted)
        except (TypeError, ValueError):
            raise CrmInputError(400, error, "ID %s không hợp lệ: %r." % (label, wanted))
        found = next((item for item in items if item["id"] == wanted), None)
        if not found:
            choices = ", ".join("%s=%s" % (item["id"], item["name"]) for item in items)
            raise CrmInputError(400, error, "Không có %s ID %s. Chọn: %s." % (label, wanted, choices))
        return found

    def _pick_stage(self, options, stage_id):
        stage = self._pick(options["stages"], stage_id, "invalid_stage", "giai đoạn")
        return {"id": stage["id"], "text": stage["name"], "probability": stage["probability"]}

    def _pick_source(self, options, lead_source_id):
        """Nguồn gốc đã chọn; None / "" -> None (không gắn nguồn)."""
        if lead_source_id in (None, ""):
            return None
        source = self._pick(options["lead_sources"], lead_source_id, "invalid_lead_source", "nguồn gốc")
        return {"id": source["id"], "text": source["name"]}

    def _opportunity_code(self, opportunity_id):
        """Số cơ hội (CH…) MISA vừa cấp; không đọc được -> None (không làm hỏng kết quả tạo)."""
        try:
            return self._current_record(MODULE, FORM_LAYOUT_ID, opportunity_id, "cơ hội",
                                        mode=MODE_VIEW).get("OpportunityCode")
        except Exception as error:  # noqa: BLE001
            _logger.warning("Cơ hội %s: không đọc được số cơ hội: %s", opportunity_id, error)
            return None


def _opportunity_row(index, product, qty, amounts, line):
    return opportunity_line(index, product, qty, amounts, line.get("description"))
