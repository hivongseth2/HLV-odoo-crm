# -*- coding: utf-8 -*-
"""Khách hàng (Account) trên MISA CRM: tìm, xem một khách."""
from odoo import models

from ..services.crm_payloads import account_row, account_search_payload
from .misa_crm_client import CrmInputError

_ACCOUNT_GET_COLUMNS = "ID;AccountName;AccountNumber;TaxCode;OfficeTel;OfficeEmail;BillingAddress;ShippingAddress;OwnerID"


class MisaCrmAccount(models.AbstractModel):
    _inherit = "hlv.misa.crm.connect"

    def api_account_search(self, keyword, page=1, limit=10):
        """Khách khớp ``keyword`` ở tên / MST / mã KH / SĐT / địa chỉ (kiểu "chứa").

        Trả {"items": [account_row...], "page"}. Từ khoá rỗng -> khách sửa gần nhất.
        """
        payload = account_search_payload(keyword, page, limit)
        rows = self._crm_data("POST", "Account/grid", payload=payload) or []
        return {"items": [account_row(row) for row in rows], "page": payload["page"]}

    def api_account_get(self, account_id):
        """Một khách theo ID MISA. Không có -> CrmInputError 404."""
        data = self._crm_data("GET", "Account/%d/" % int(account_id),
                              params={"columns": _ACCOUNT_GET_COLUMNS})
        if not isinstance(data, dict) or not data.get("ID"):
            raise CrmInputError(404, "not_found", "Không có khách ID %s trên MISA." % account_id)
        return account_row(data)
