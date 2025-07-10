from odoo import models
import json

class MisaConfig(models.AbstractModel):
    _name = 'misa.config'
    _description = 'MISA Configuration'

    def get_misa_context(self):
        """Trả về context cấu hình cho MISA API."""
        return  {"TenantId":"47ab503b-99d5-4eb8-aa11-24927abb3585","TenantCode":"3R2PY2F4","DatabaseId":"f4b18d63-6c99-4a53-b974-f6208e84fced","BranchId":"53a073a0-5381-4493-820f-51ea32ebe990","WorkingBook":0,"Language":"vi","IncludeDependentBranch":"false","SessionId":"ss1547cc69a995421e91347736dabe6cb9.693017cdc24074e96e4756afbf2b6ab6.f4b18d636c994a53b974f6208e84fced.638877626393411146","DBType":1,"AuthType":0,"AmisSessionId":"NAA3AGEAYgA1ADAAMwBiADkAOQBkADUANABlAGIAOABhAGEAMQAxADIANAA5ADIANwBhAGIAYgAzADUAOAA1ADkAMgBiADgANABhADYAZgBiADYAZQBiADQANwBhADgAYQA0AGUAMgBhAGUAYgAzAGEAZQA2ADMAYgA0ADYAYwA=","HasAgent":false,"UserType":1,"art":1,"UserId":"1547cc69-a995-421e-9134-7736dabe6cb9","isc":false}
    def get_default_headers(self, access_token):
        """Trả về headers mặc định cho MISA API."""
        context = self.get_misa_context()
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-MISA-Context": json.dumps(self.get_misa_context()),  # Chuyển sang string nếu cần
            "X-MISA-BranchID": context['BranchId'],
            "X-MISA-Language": "vi",
            "X-MISA-WorkingBook": "0",
            "X-Device": "04aadfced5b04995ecfacb0a7da5c50c",
            "Host":"actapp.misa.vn",
            "Content-Length":"574",
            "Connection":"keep-alive"
            
        }