from odoo import models, fields, _
from odoo.exceptions import UserError
import requests
import json
import logging

_logger = logging.getLogger(__name__)

class MisaPOFetch(models.Model):
    _name = "misa.po.fetch"
    _description = "Fetch PO from MISA"

    name = fields.Char(string="Tên hành động", default="Lấy PO từ MISA")

    def action_fetch_po(self):
        url = "https://actapp.misa.vn/g1/api/pu/v1/pu_list/paging_filter_v2"
        access_token = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOiJkZjBjYjMzYi1iMTM5LTQ5ZjUtYWMyNC1mOWY4NjBiNGU5ODciLCJ1bmEiOiJOR1VZRU5USEFOSExVQU4iLCJhdXQiOiIwIiwidWVtIjoibmd1eWVubHVhbjEzMDMwMUBnbWFpbC5jb20iLCJuYmYiOjE3NTA0MDcwNjIsImV4cCI6MTc1MDQ5MzQ5MCwiaWF0IjoxNzUwNDA3MDYyLCJpc3MiOiJNSVNBSlNDIn0.dISLn9Vd2j5rRDWHi0wFDyfdDlk4-PeDIDHpp-5Dh4Q"

        headers = {
            "Authorization": access_token,
            "Content-Type": "application/json",
            "x-device": "04aadfced5b04995ecfacb0a7da5c50c",
            "x-misa-context": '{"TenantId":"47ab503b-99d5-4eb8-aa11-24927abb3585","TenantCode":"3R2PY2F4","DatabaseId":"f4b18d63-6c99-4a53-b974-f6208e84fced","BranchId":"53a073a0-5381-4493-820f-51ea32ebe990","WorkingBook":0,"Language":"vi","IncludeDependentBranch":"false","SessionId":"ssdf0cb33bb13949f5ac24f9f860b4e987.04aadfced5b04995ecfacb0a7da5c50c.f4b18d636c994a53b974f6208e84fced.638860290625845472","DBType":1,"AuthType":0,"AmisSessionId":"NAA3AGEAYgA1ADAAMwBiADkAOQBkADUANABlAGIAOABhAGEAMQAxADIANAA5ADIANwBhAGIAYgAzADUAOAA1ADAAYgBlADEAMgAyAGIAMAA3AGIANAAyADQAZAAzAGMAOQA1AGQAYQBjAGEANAAxADYAZQAxADIAMwBhADAAYQA=","HasAgent":false,"UserType":1,"art":0,"UserId":"df0cb33b-b139-49f5-ac24-f9f860b4e987","isc":false}'
        }

        payload = {
            "filter": [{
                "property": 3654,
                "value": "2025-05-31T17:00:00.00Z",
                "operator": 10,
                "operand": 1,
                "data_type": 3
            }],
            "loadMode": 2,
            "pageIndex": 1,
            "pageSize": 20,
            "sort": "[{\"property\":3654,\"desc\":true,\"data_type\":3,\"operand\":1}]",
            "summaryColumns": [5080, 5730, 5128, 5059],
            "useSp": False,
            "view": 40
        }

        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            _logger.info("Kết quả gọi API MISA:%s", json.dumps(response.json(), ensure_ascii=False, indent=2))
        else:
            raise UserError(_("Gọi API thất bại: %s") % response.text)