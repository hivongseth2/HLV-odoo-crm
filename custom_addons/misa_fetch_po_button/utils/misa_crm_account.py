# -*- coding: utf-8 -*-
"""Tìm khách hàng (Account) trên MISA CRM theo MST / tên / mã khách — cho hộp thoại "Tạo khách từ
MISA CRM" (wizard/misa_crm_partner_create.py). Chỉ đọc.

Gọi bằng token chung (_crm_read_call: hết hạn thì đăng nhập lại một lần, lỗi → UserError đọc được).
"""
import base64
import uuid

from odoo import models

GRID_URL = "https://amisapp.misa.vn/crm/g1/api/business/Account/Grid"
# Đủ cột cho misa.crm.contact.sync.run._values_from_crm_account (ánh xạ Account → res.partner) và để
# người dùng phân biệt các khách trùng tên.
_GRID_COLUMNS = (
    "ID,AccountNumber,AccountName,TaxCode,OfficeTel,OfficeEmail,BillingAddress,BillingProvinceIDText,"
    "OwnerIDText,Inactive"
)
ACCOUNT_LIMIT = 20


class MisaCrmAccount(models.AbstractModel):
    _inherit = 'misa.api.utils'

    def crm_search_accounts(self, keyword, limit=ACCOUNT_LIMIT):
        """Khách hàng CRM khớp ``keyword`` theo ô tìm của trang danh sách khách trên CRM, mới sửa trước.

        Trả nguyên dòng CRM (dict có các cột _GRID_COLUMNS); keyword rỗng → []. UserError khi không
        gọi được CRM.
        """
        keyword = (keyword or "").strip()
        if not keyword:
            return []
        rows = self._crm_read_call(self._post_account_grid, keyword, limit)
        return [row for row in rows if row.get("ID")]

    def _post_account_grid(self, headers, keyword, limit):
        return self._post_crm_read(headers, GRID_URL, {
            "Columns": base64.b64encode(_GRID_COLUMNS.encode("utf-8")).decode("ascii"),
            "Sorts": [{"SortBy": "ModifiedDate", "Type": 0, "SortDirection": 1}],
            "Start": 0, "Page": 1, "PageSize": limit,
            "Filters": [], "Formula": "",
            "LayoutCode": "Account", "LayoutCodeCheckPermission": "Account",
            "DefaultTotal": True, "IsMappingData": False, "MappingValueObject": {},
            "IsApproved": False, "CustomPagingData": {}, "IsUsedELTS": True,
            "ListGmailPage": [], "ListFacebookPage": {}, "IsListPaging": True, "IsGetCache": True,
            "IsCheckInactive": False, "IsConverted": False, "SessionID": str(uuid.uuid4()),
            "AISearchKeyword": keyword, "SkipNormalSearch": False,
        }, "account")
