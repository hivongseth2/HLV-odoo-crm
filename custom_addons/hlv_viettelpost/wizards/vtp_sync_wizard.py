import logging
from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class VTPSyncWizard(models.TransientModel):
    _name = "vtp.sync.wizard"
    _description = "Sync Viettel Post Address Master"

    def action_sync_geo(self):
        api = self.env["vtp.api"]
        token = self.env["ir.config_parameter"].sudo().get_param("vtp.token")
        if not token:
            raise UserError(_("Chưa có token VTP. Vào Settings → Viettel Post → bấm 'Login & Get Token' trước."))

        provinces = (api.vtp_list_provinces() or {}).get("data") or []
        P = self.env["vtp.province"].sudo()
        D = self.env["vtp.district"].sudo()
        W = self.env["vtp.ward"].sudo()

        c_p_new = c_p_upd = c_d_new = c_d_upd = c_w_new = c_w_upd = 0
        pid_map = {}

        for p in provinces:
            vtp_pid = p.get("PROVINCE_ID")
            vals = {"name": p.get("PROVINCE_NAME"), "vtp_id": vtp_pid}
            rec = P.search([("vtp_id", "=", vtp_pid)], limit=1)
            if rec:
                rec.write(vals); c_p_upd += 1; pid_map[vtp_pid] = rec.id
            else:
                pid_map[vtp_pid] = P.create(vals).id; c_p_new += 1

        for prov_vtp_id, prov_id in pid_map.items():
            districts = (api.vtp_list_districts(prov_vtp_id) or {}).get("data") or []
            for d in districts:
                vtp_did = d.get("DISTRICT_ID")
                d_vals = {"name": d.get("DISTRICT_NAME"), "vtp_id": vtp_did, "province_id": prov_id}
                d_rec = D.search([("vtp_id", "=", vtp_did)], limit=1)
                if d_rec:
                    d_rec.write(d_vals); d_id = d_rec.id; c_d_upd += 1
                else:
                    d_id = D.create(d_vals).id; c_d_new += 1

                wards = (api.vtp_list_wards(vtp_did) or {}).get("data") or []
                for w in wards:
                    vtp_wid = w.get("WARDS_ID")
                    w_vals = {"name": w.get("WARDS_NAME"), "vtp_id": vtp_wid, "district_id": d_id}
                    w_rec = W.search([("vtp_id", "=", vtp_wid)], limit=1)
                    if w_rec:
                        w_rec.write(w_vals); c_w_upd += 1
                    else:
                        W.create(w_vals); c_w_new += 1

        return {
            "type": "ir.actions.act_window",
            "name": "Viettel Post - Phường/Xã",
            "res_model": "vtp.ward",
            "view_mode": "list,form",
            "target": "current",
        }
