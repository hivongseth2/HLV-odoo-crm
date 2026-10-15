# -*- coding: utf-8 -*-
"""Cơ hội (Opportunity) trên MISA CRM: danh mục của form, tìm, xem hàng, tạo mới.

Tìm và xem hàng dùng lại misa_fetch_po_button (crm_search_opportunities, crm_opportunity_products).
"""
import logging

from odoo import models

from ..services.opportunity_payload import (
    FORM_LAYOUT_ID, line_amounts, opportunity_create_payload, opportunity_line, stage_history_payload,
)
from .misa_crm_client import CrmInputError, MisaCrmError

_logger = logging.getLogger(__name__)

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
        stage = self._pick(options["stages"], stage_id, "invalid_stage", "giai đoạn")
        source = self._pick(options["lead_sources"], lead_source_id, "invalid_lead_source", "nguồn gốc") \
            if lead_source_id not in (None, "") else None

        rows = [self._opportunity_row(index, line) for index, line in enumerate(lines, start=1)]
        payload = opportunity_create_payload(
            {"id": account["id"], "name": account["name"]},
            {"id": stage["id"], "text": stage["name"], "probability": stage["probability"]},
            closing_date, rows, name=name,
            lead_source={"id": source["id"], "text": source["name"]} if source else None,
            description=description,
        )
        opportunity_id = self._crm_data("POST", "Opportunity", payload=payload)
        if not opportunity_id:
            raise MisaCrmError("MISA báo tạo xong nhưng không trả ID cơ hội.")
        result = {"id": opportunity_id, "total": payload["CustomTables"][0]["Summary"]["TotalSummary"]}
        # Hai bước sau khi tạo đều phụ: lỗi thì vẫn trả ID (cơ hội ĐÃ có trên MISA, gọi lại là tạo trùng).
        try:
            self._crm("POST", "Opportunity/stageHistory", payload=stage_history_payload(
                opportunity_id, {"id": stage["id"], "text": stage["name"], "probability": stage["probability"]},
                closing_date))
        except Exception as error:  # noqa: BLE001
            _logger.warning("Cơ hội %s: không ghi được lịch sử giai đoạn: %s", opportunity_id, error)
            result["warning"] = "Đã tạo cơ hội nhưng không ghi được lịch sử giai đoạn: %s" % error
        result["code"] = self._opportunity_code(opportunity_id)
        return result

    # ------------------------------------------------------------------
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

    def _opportunity_row(self, index, line):
        product = self._product_by_code(line["code"])
        if product["is_combo"]:
            # Dòng combo trên form kéo theo các dòng con — chưa có request mẫu, không tự đoán.
            raise CrmInputError(400, "combo_not_supported",
                                "Mã %s là combo — API chưa hỗ trợ thêm combo vào cơ hội." % line["code"])
        amounts = line_amounts(line["qty"], product["tax_percent"],
                               price=line.get("price"), price_after_tax=line.get("price_after_tax"))
        return opportunity_line(index, product, line["qty"], amounts, line.get("description"))

    def _opportunity_code(self, opportunity_id):
        """Số cơ hội (CH…) MISA vừa cấp; không đọc được -> None (không làm hỏng kết quả tạo)."""
        try:
            data = self._crm_data(
                "POST", "Opportunity/FormDataNew/Opportunity/%d/4" % FORM_LAYOUT_ID,
                payload={"ID": str(opportunity_id), "MISAEntityState": 2,
                         "ActiveLayoutCode": None, "CustomDicData": None}) or {}
            return (data.get("CurrentData") or {}).get("OpportunityCode")
        except Exception as error:  # noqa: BLE001
            _logger.warning("Cơ hội %s: không đọc được số cơ hội: %s", opportunity_id, error)
            return None
