import logging
from odoo import models

_logger = logging.getLogger(__name__)

class VTPSyncWizard(models.TransientModel):
    _name = "vtp.sync.wizard"
    _description = "Sync Viettel Post Address Master"

    def action_sync_geo(self):
        api = self.env["vtp.api"]
        provinces = (api.vtp_list_provinces() or {}).get("data") or []
        P = self.env["vtp.province"].sudo()
        D = self.env["vtp.district"].sudo()
        W = self.env["vtp.ward"].sudo()

        pid_map = {}
        for p in provinces:
            rec = P.search([("vtp_id", "=", p.get("PROVINCE_ID"))], limit=1)
            vals = {"name": p.get("PROVINCE_NAME"), "vtp_id": p.get("PROVINCE_ID")}
            if rec:
                rec.write(vals)
                pid_map[p.get("PROVINCE_ID")] = rec.id
            else:
                pid_map[p.get("PROVINCE_ID")] = P.create(vals).id

        for prov_vtp_id, prov_id in pid_map.items():
            districts = (api.vtp_list_districts(prov_vtp_id) or {}).get("data") or []
            for d in districts:
                d_rec = D.search([("vtp_id", "=", d.get("DISTRICT_ID"))], limit=1)
                d_vals = {"name": d.get("DISTRICT_NAME"), "vtp_id": d.get("DISTRICT_ID"), "province_id": prov_id}
                if d_rec:
                    d_rec.write(d_vals)
                    d_id = d_rec.id
                else:
                    d_id = D.create(d_vals).id

                wards = (api.vtp_list_wards(d.get("DISTRICT_ID")) or {}).get("data") or []
                for w in wards:
                    w_rec = W.search([("vtp_id", "=", w.get("WARDS_ID"))], limit=1)
                    w_vals = {"name": w.get("WARDS_NAME"), "vtp_id": w.get("WARDS_ID"), "district_id": d_id}
                    if w_rec:
                        w_rec.write(w_vals)
                    else:
                        W.create(w_vals)
        return {'type': 'ir.actions.client', 'tag': 'reload'}
