/** @odoo-module **/

import { registry } from "@web/core/registry";

function isPickingReport(action) {
    const model = action.model || action.context?.active_model;
    if (model !== "stock.picking") return false;
    const reportName = (action.report_name || "").toLowerCase();
    const actionName = (action.name || action.display_name || "").toLowerCase();
    return reportName.startsWith("stock.report_picking") || actionName.includes("lấy hàng") || actionName.includes("hoạt động lấy hàng");
}

function optionHtml(packer) {
    const label = packer.packer_name || packer.name || "";
    return `<option value="${packer.id}">${label}</option>`;
}

function rowHtml(picking) {
    const assigned = picking.packer_user ? ` · đang assign: ${picking.packer_user[1]}` : "";
    return `<tr><td>${picking.name || ""}</td><td>${picking.origin || ""}</td><td>${assigned}</td></tr>`;
}

function askPacker(data) {
    return new Promise((resolve) => {
        const wrapper = document.createElement("div");
        wrapper.style.cssText = "position:fixed;inset:0;z-index:3000;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;font-family:Segoe UI,Arial,sans-serif;";
        wrapper.innerHTML = `
            <div style="width:min(560px,calc(100vw - 32px));background:#fff;border-radius:6px;box-shadow:0 12px 32px rgba(0,0,0,.28);overflow:hidden;">
                <div style="padding:12px 16px;border-bottom:1px solid #e5e7eb;font-weight:700;display:flex;align-items:center;gap:8px;">
                    <i class="fa fa-user-plus"></i><span>Chọn người đóng gói</span>
                </div>
                <div style="padding:16px;">
                    <label style="display:block;font-size:12px;font-weight:700;color:#6b7280;text-transform:uppercase;margin-bottom:6px;">Người đóng</label>
                    <select class="o_hlv_packer_select" style="width:100%;height:34px;border:1px solid #cbd5e1;border-radius:4px;padding:4px 8px;">
                        ${(data.packers || []).map(optionHtml).join("")}
                    </select>
                    <div style="margin-top:12px;max-height:220px;overflow:auto;border:1px solid #e5e7eb;border-radius:4px;">
                        <table style="width:100%;border-collapse:collapse;font-size:12px;">
                            <thead style="background:#f8fafc;color:#64748b;"><tr><th style="text-align:left;padding:7px 8px;">Phiếu PICK</th><th style="text-align:left;padding:7px 8px;">Chứng từ</th><th style="text-align:left;padding:7px 8px;">Ghi chú</th></tr></thead>
                            <tbody>${(data.pickings || []).map(rowHtml).join("")}</tbody>
                        </table>
                    </div>
                </div>
                <div style="padding:10px 16px;border-top:1px solid #e5e7eb;display:flex;justify-content:flex-end;gap:8px;">
                    <button class="o_hlv_cancel btn btn-sm btn-outline-secondary" type="button">Hủy</button>
                    <button class="o_hlv_confirm btn btn-sm btn-primary" type="button">Assign và in</button>
                </div>
            </div>`;
        document.body.appendChild(wrapper);
        const cleanup = (value) => {
            wrapper.remove();
            resolve(value);
        };
        wrapper.querySelector(".o_hlv_cancel").addEventListener("click", () => cleanup(false));
        wrapper.addEventListener("click", (ev) => {
            if (ev.target === wrapper) cleanup(false);
        });
        wrapper.querySelector(".o_hlv_confirm").addEventListener("click", () => {
            const select = wrapper.querySelector(".o_hlv_packer_select");
            cleanup(parseInt(select.value || "0"));
        });
    });
}

registry.category("ir.actions.report handlers").add(
    "hlv_assign_packer_before_picking_print",
    async (action, options, env) => {
        if (action.type !== "ir.actions.report" || action.report_type !== "qweb-pdf") return false;
        if (action.context?.hlv_skip_packer_assignment_dialog) return false;
        if (!isPickingReport(action)) return false;

        const activeIds = action.context?.active_ids || (action.context?.active_id ? [action.context.active_id] : []);
        if (!activeIds.length) return false;

        const orm = env.services.orm;
        const notification = env.services.notification;
        const data = await orm.call("stock.picking", "prepare_picking_print_assignment_data", [], { picking_ids: activeIds });
        if (!data.required) return false;
        if (!data.packers || !data.packers.length) {
            notification.add("Không có người dùng nội bộ để assign đóng gói", { type: "warning" });
            return true;
        }
        const packerUserId = await askPacker(data);
        if (!packerUserId) return true;

        const result = await orm.call("stock.picking", "assign_picking_print_packer", [], {
            picking_ids: data.picking_ids,
            packer_user_id: packerUserId,
        });
        if (!result.success) {
            notification.add(result.message || "Không assign được người đóng", { type: "danger" });
            return true;
        }

        action.context = {
            ...(action.context || {}),
            hlv_skip_packer_assignment_dialog: true,
        };
        return false;
    },
    { sequence: 1 }
);
