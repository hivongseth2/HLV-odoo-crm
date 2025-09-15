/** @odoo-module **/
import { registry } from "@web/core/registry";

function fmtCurrency(env, value) {
  try {
    const lang = (env.services.user?.lang || "vi_VN").replace("_", "-");
    return new Intl.NumberFormat(lang).format(value ?? 0);
  } catch {
    return String(value ?? "");
  }
}

registry.category("actions").add("hlv_show_panel_noqweb", async (env, action) => {
  const orm = env.services.orm;
  const notify = env.services.notification;

  const ctx = action.context || {};
  const resId =
    action.params?.res_id ??
    ctx.active_id ??
    (Array.isArray(ctx.active_ids) && ctx.active_ids.length ? ctx.active_ids[0] : undefined);

  if (!resId) {
    notify.add("Không xác định được Sale Order để xem nhanh.", { type: "warning" });
    return { destroy() {} };
  }

  document.querySelectorAll(".hlv-side-panel, .hlv-bottom-panel").forEach(n => n.remove());

  const target = document.createElement("div");
  target.className = "hlv-bottom-panel";
  target.innerHTML = `
    <div class="hlv-panel-header">
      <div class="hlv-title"></div>
      <button class="btn btn-sm btn-secondary hlv-close">Đóng</button>
    </div>
    <div class="hlv-panel-body">
      <div class="o_spinner o_spinner_large"></div>
    </div>
  `;
  document.body.appendChild(target);

  const destroy = () => { try { target.remove(); } catch {} };
  target.querySelector(".hlv-close").addEventListener("click", destroy);

  try {
    const [order] = await orm.read("sale.order", [resId], ["name","partner_id","state","amount_total"]);
    const lines = await orm.searchRead("sale.order.line",
      [["order_id","=",resId]],
      ["product_id","name","product_uom_qty","qty_delivered","price_unit","price_subtotal"]
    );

    target.querySelector(".hlv-title").textContent = order?.name || "Đơn bán";
    const body = target.querySelector(".hlv-panel-body");

    const rows = (lines || []).map(l => `
      <tr>
        <td>${(l.product_id && l.product_id[1]) || ""}</td>
        <td>${l.product_uom_qty ?? ""}</td>
        <td>${l.qty_delivered ?? ""}</td>
        <td>${fmtCurrency(env, l.price_unit)}</td>
        <td>${fmtCurrency(env, l.price_subtotal)}</td>
      </tr>`).join("");

    body.innerHTML = `
      <table class="table table-sm table-striped mb-0">
        <thead>
          <tr>
            <th>Sản phẩm</th>
            <th>Số lượng</th>
            <th>Đã giao</th>
            <th>Đơn giá</th>
            <th>Thành tiền</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  } catch (e) {
    console.error("[HLV] Quick panel error", e);
    notify.add("Không thể tải dữ liệu đơn hàng.", { type: "danger" });
    destroy();
  }

  return { destroy };
});
