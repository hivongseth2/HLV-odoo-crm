# -*- coding: utf-8 -*-
"""Đọc cơ hội (Opportunity) trên MISA CRM: tìm cơ hội, lấy danh sách hàng của một cơ hội — để
trang hỏi giá NCC (/hoi-gia-ncc) lấy hàng của cơ hội bỏ vào phiếu hỏi giá. Chỉ đọc.

Dùng token CRM đã lưu (_with_crm_reauth): token hết hiệu lực thì đăng nhập lại đúng một lần.
"""
import base64
import logging
import uuid

from odoo import models
from odoo.exceptions import UserError

from .misa_api_utils import MisaAuthExpired

_logger = logging.getLogger(__name__)

GRID_URL = "https://amisapp.misa.vn/crm/g1/api/business/Opportunity/Grid"
LINES_URL = "https://amisapp.misa.vn/crm/g1/api/business/Opportunity/DataSubPaging"
# CRM nhận danh sách cột dạng base64 của "Cột1,Cột2,…".
_GRID_COLUMNS = (
    "ID,OpportunityCode,OpportunityName,AccountIDText,OwnerIDText,StageIDText,ClosingDate,ListProduct"
)
_LINE_COLUMNS = (
    "ID,SortOrder,ProductID,ProductIDText,Description,UnitID,UnitIDText,Amount,Price,TaxPercentIDText,"
    "PriceAfterTax,IsNoteRow,IsSetProduct,IsChildProduct"
)
OPPORTUNITY_LIMIT = 10
LINE_LIMIT = 200


def _columns(names):
    return base64.b64encode(names.encode("utf-8")).decode("ascii")


class MisaOpportunity(models.AbstractModel):
    _inherit = 'misa.api.utils'

    def crm_search_opportunities(self, keyword, limit=OPPORTUNITY_LIMIT):
        """Cơ hội khớp ``keyword`` (số cơ hội, tên cơ hội, khách hàng…) theo ô tìm của CRM.

        Trả [{"id", "code", "name", "account", "owner", "stage", "closing_date", "products"}];
        products = chuỗi mã hàng CRM ghi sẵn ("48-22-7412X;48-22-2913"). keyword rỗng → [].
        UserError khi không gọi được CRM.
        """
        keyword = (keyword or "").strip()
        if not keyword:
            return []
        rows = self._crm_opportunity_call(self._post_opportunity_grid, keyword, limit)
        return [
            {
                "id": row.get("ID"),
                "code": row.get("OpportunityCode") or "",
                "name": row.get("OpportunityName") or "",
                "account": row.get("AccountIDText") or "",
                "owner": row.get("OwnerIDText") or "",
                "stage": row.get("StageIDText") or "",
                "closing_date": (row.get("ClosingDate") or "")[:10],
                "products": row.get("ListProduct") or "",
            }
            for row in rows if row.get("ID")
        ]

    def crm_opportunity_products(self, opportunity_id):
        """Hàng của một cơ hội: [{"code", "description", "unit", "qty", "price", "price_after_tax",
        "tax", "is_combo"}] theo thứ tự trên CRM. Bỏ dòng ghi chú và dòng con của combo (combo đã có
        một dòng riêng). UserError khi không gọi được CRM."""
        rows = self._crm_opportunity_call(self._post_opportunity_lines, int(opportunity_id))
        return [
            {
                "code": (row.get("ProductIDText") or "").strip(),
                "description": row.get("Description") or "",
                "unit": row.get("UnitIDText") or "",
                "qty": float(row.get("Amount") or 0),
                "price": float(row.get("Price") or 0),
                "price_after_tax": float(row.get("PriceAfterTax") or 0),
                "tax": row.get("TaxPercentIDText") or "",
                "is_combo": bool(row.get("IsSetProduct")),
            }
            for row in sorted(rows, key=lambda r: r.get("SortOrder") or 0)
            if not row.get("IsNoteRow") and not row.get("IsChildProduct") and row.get("ProductIDText")
        ]

    # ------------------------------------------------------------------
    def _crm_opportunity_call(self, post, *args):
        """Gọi CRM bằng token đã lưu (đăng nhập lại một lần nếu hết hạn); lỗi → UserError đọc được."""
        try:
            return self._with_crm_reauth(post, *args)
        except UserError:
            raise
        except Exception as exc:  # noqa: BLE001 — lỗi mạng / token / CRM trả lỗi đều báo cho người dùng
            _logger.warning("Gọi MISA CRM (cơ hội) lỗi: %s", exc)
            raise UserError(f"Không gọi được MISA CRM: {exc}") from exc

    def _post_opportunity(self, headers, url, payload):
        headers = dict(headers, LayoutCode="opportunity")
        res = self._get_retry_session().post(url, headers=headers, json=payload, timeout=30)
        if res.status_code in (401, 403):
            raise MisaAuthExpired(f"CRM từ chối phiên đăng nhập (HTTP {res.status_code})")
        data = res.json()
        if not data.get("Success"):
            raise Exception(data.get("UserMessage") or f"CRM trả lỗi: {res.text[:200]}")
        return data.get("Data") or []

    def _post_opportunity_grid(self, headers, keyword, limit):
        return self._post_opportunity(headers, GRID_URL, {
            "Columns": _columns(_GRID_COLUMNS),
            "Sorts": [{"SortBy": "ModifiedDate", "Type": 0, "SortDirection": 1}],
            "Start": 0, "Page": 1, "PageSize": limit,
            "Filters": [], "Formula": "",
            "LayoutCode": "Opportunity", "LayoutCodeCheckPermission": "Opportunity",
            "DefaultTotal": True, "IsMappingData": False, "MappingValueObject": {},
            "IsApproved": False, "CustomPagingData": {}, "IsUsedELTS": True,
            "ListGmailPage": [], "ListFacebookPage": {}, "IsListPaging": True, "IsGetCache": True,
            "IsCheckInactive": False, "IsConverted": False, "SessionID": str(uuid.uuid4()),
            # Ô tìm của trang danh sách cơ hội trên CRM (gõ số cơ hội / tên / khách hàng).
            "AISearchKeyword": keyword, "SkipNormalSearch": False,
        })

    def _post_opportunity_lines(self, headers, opportunity_id):
        return self._post_opportunity(headers, LINES_URL, {
            "Columns": _columns(_LINE_COLUMNS),
            "Sorts": [], "Start": 0, "Page": 1, "PageSize": LINE_LIMIT,
            "Filters": [], "DefaultTotal": False, "IsMappingData": False,
            "MappingValueObject": {
                "MasterID": str(opportunity_id), "TableName": "opportunity_product",
                "MasterKey": "CustomID", "SumColumn": "",
            },
            "IsApproved": False,
            # Không cần dòng tổng — để trống phần cột tổng hợp của bảng con.
            "CustomPagingData": {"SubFormConfig": {
                "ColumnFieldSubForm": "", "ColumnAggregateSubForm": "", "TableName": "opportunity_product",
                "IsSystem": True, "ParentIDKey": "CustomID", "IsBringSerialType": False, "AggregateField": [],
            }},
            "IsUsedELTS": True, "ListGmailPage": [], "ListFacebookPage": {}, "IsListPaging": True,
            "IsGetCache": True, "IsCheckInactive": False, "IsConverted": False,
            "SessionID": str(uuid.uuid4()), "AISearchKeyword": "", "SkipNormalSearch": False,
        })
