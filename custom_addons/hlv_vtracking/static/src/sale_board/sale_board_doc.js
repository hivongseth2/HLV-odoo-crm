/* Hộp thoại xem một chứng từ trên trang /giao-hang: phiếu xuất kho, hoặc đơn bán.

   Tách khỏi sale_board.js vì đây là một màn hình riêng, dựng từ một khối dữ liệu riêng
   (/giao-hang/chung-tu) — file kia lo bảng điều khiển.

   Phiếu xuất kho được dựng kỹ hơn đơn bán, vì đó là thứ người bán hàng mở ra khi khách gọi
   hỏi "đợt này tôi nhận được bao nhiêu": bốn mốc của phiếu, chuyến đang chở, và bảng ba cột
   đơn đặt / phiếu này chở / còn lại. */

window.VtSaleDoc = (function () {
    let openRequestHandler = null;

    function esc(text) {
        const div = document.createElement("div");
        div.textContent = text == null ? "" : String(text);
        return div.innerHTML;
    }

    function money(value) {
        return (value || 0).toLocaleString("vi-VN") + " đ";
    }

    /* "2026-09-22 08:12:00" -> "22/09 08:12". Giờ Odoo trả là UTC, trình duyệt của người
       dùng ở +7 — đổi qua giờ địa phương rồi mới cắt chuỗi. */
    function stamp(value, withTime) {
        if (!value) {
            return "";
        }
        const date = new Date(value.replace(" ", "T") + "Z");
        if (Number.isNaN(date.getTime())) {
            return value;
        }
        const day = String(date.getDate()).padStart(2, "0");
        const month = String(date.getMonth() + 1).padStart(2, "0");
        if (!withTime) {
            return `${day}/${month}/${date.getFullYear()}`;
        }
        const hour = String(date.getHours()).padStart(2, "0");
        const minute = String(date.getMinutes()).padStart(2, "0");
        return `${day}/${month} ${hour}:${minute}`;
    }

    function number(value) {
        return (value || 0).toLocaleString("vi-VN");
    }

    // ------------------------------------------------------------ phiếu kho

    function milestones(doc) {
        const items = doc.milestones.map((item, index) => {
            const last = index === doc.milestones.length - 1;
            const label = item.label === "Lên xe" && doc.plan
                ? `Lên xe ${doc.plan.vehicle_plate}`
                : item.label;
            return `
                <span class="vt-mile ${item.done ? "is-done" : ""} ${last ? "is-last" : ""}">
                    <span class="vt-mile-track">
                        <span class="vt-mile-dot">${item.done ? "✓" : ""}</span>
                        ${last ? "" : '<span class="vt-mile-line"></span>'}
                    </span>
                    <span class="vt-mile-label">${esc(label)}</span>
                    <span class="vt-mile-at">${item.at ? esc(stamp(item.at, true)) : (item.done ? "" : "chưa")}</span>
                </span>`;
        }).join("");
        return `<div class="vt-miles">${items}</div>`;
    }

    function planBar(plan) {
        if (!plan) {
            return `<div class="vt-plan-line vt-muted">Phiếu này chưa được xếp vào chuyến nào.</div>`;
        }
        return `
            <div class="vt-plan-line">
                <span>
                    Chuyến <b>${esc(plan.vehicle_plate)}</b> · điểm
                    <b>${plan.stop_index}/${plan.stop_count}</b>
                    ${plan.started_at ? " · xuất phát " + esc(stamp(plan.started_at, true)) : ""}
                    ${plan.duration_display ? " · dự kiến chạy " + esc(plan.duration_display) : ""}
                </span>
                <span class="vt-plan-bar" title="Đã giao ${plan.delivered_count}/${plan.stop_count} điểm">
                    <span style="width:${plan.percent}%"></span>
                </span>
            </div>`;
    }

    function pickingTable(doc) {
        if (!doc.lines.length) {
            return '<div class="vt-empty">Phiếu chưa có dòng hàng nào.</div>';
        }
        const rows = doc.lines.map((line) => `
            <tr>
                <td>
                    ${line.code ? `<span class="vt-num vt-muted">[${esc(line.code)}]</span> ` : ""}
                    ${esc(line.product)}
                </td>
                <td class="vt-muted">${esc(line.uom)}</td>
                <td class="vt-right vt-num">${number(line.qty_ordered)}</td>
                <td class="vt-right vt-num vt-cell-this">${number(line.qty_this)}</td>
                <td class="vt-right vt-num ${line.qty_remaining ? "vt-cell-left" : "vt-muted"}">
                    ${number(line.qty_remaining)}
                </td>
            </tr>`).join("");
        return `
            <table class="vt-doc-table">
                <thead>
                    <tr>
                        <th>Hàng hoá</th>
                        <th>ĐVT</th>
                        <th class="vt-right">Đơn đặt<small>cả đơn</small></th>
                        <th class="vt-right vt-cell-this">Phiếu này chở<small>đi chuyến này</small></th>
                        <th class="vt-right">Còn lại<small>chờ phiếu sau</small></th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>`;
    }

    function otherPickings(doc) {
        if (!doc.other_pickings || !doc.other_pickings.length) {
            return "";
        }
        const chips = doc.other_pickings.map((item) => `
            <button type="button" class="vt-btn vt-btn-mini" data-vt-doc="picking" data-vt-doc-id="${item.id}">
                <span class="vt-status ${item.state === "done" ? "vt-status-run" : "vt-status-park"}"></span>
                <span class="vt-num">${esc(item.name)}</span>
                <span class="vt-muted">
                    ${item.date_done ? "đã giao " + esc(stamp(item.date_done)) : esc(item.state_label)}
                    ${item.vehicle_plate ? " · chuyến " + esc(item.vehicle_plate) : ""}
                </span>
            </button>`).join("");
        return `<div class="vt-doc-others"><span class="vt-muted">Phiếu khác của đơn này:</span>${chips}</div>`;
    }

    function pickingHtml(doc) {
        return `
            <div class="vt-doc-head">
                <span class="vt-doc-mark">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <path d="M6 3h9l4 4v14H6z"></path><path d="M15 3v4h4"></path>
                        <path d="M9 13h6M9 17h4"></path>
                    </svg>
                </span>
                <span class="vt-doc-title">
                    <span class="vt-doc-name">
                        <span class="vt-num">${esc(doc.title)}</span>
                        <span class="vt-chip">${esc(doc.state_label)}</span>
                    </span>
                    <span class="vt-muted">
                        ${doc.sale_order_name ? `Đơn <button type="button" class="vt-doc"
                            data-vt-doc="order" data-vt-doc-id="${doc.sale_order_id}">
                            ${esc(doc.sale_order_name)}</button> · ` : ""}
                        ${esc(doc.partner_name)}${doc.address ? " · giao " + esc(doc.address) : ""}
                        ${doc.commitment_date ? " · hẹn " + esc(stamp(doc.commitment_date)) : ""}
                    </span>
                </span>
            </div>
            <div class="vt-doc-progress">
                ${milestones(doc)}
                ${planBar(doc.plan)}
            </div>
            ${pickingTable(doc)}
            <div class="vt-doc-sum">
                <span class="vt-muted">
                    ${doc.amount_total ? "Đơn " + money(doc.amount_total) : ""}
                    ${doc.delivery_status ? " · " + esc(doc.delivery_status) : ""}
                </span>
            </div>
            ${otherPickings(doc)}`;
    }

    // ------------------------------------------------------------- đơn bán

    function orderHtml(doc) {
        const facts = [
            ["Khách", esc(doc.partner_name)],
            ["Trạng thái", esc(doc.state_label)],
            ["Giao hàng", esc(doc.delivery_status)],
            ["Ngày hẹn giao", esc(stamp(doc.commitment_date))],
            ["Mã sale", esc(doc.saler_code)],
            ["Tiền hàng", money(doc.amount_total)],
            ["Địa chỉ giao", esc(doc.address)],
        ]
            .filter(([, value]) => value)
            .map(([label, value]) => `<div class="vt-fact"><span>${label}</span><b>${value}</b></div>`)
            .join("");
        const rows = doc.lines.map((line) => `
            <tr>
                <td>${esc(line.product)}</td>
                <td class="vt-muted">${esc(line.uom || "")}</td>
                <td class="vt-right vt-num">${number(line.qty_ordered)}</td>
                <td class="vt-right vt-num">${number(line.qty_delivered)}</td>
                <td class="vt-right vt-num ${line.qty_remaining ? "vt-cell-left" : "vt-muted"}">
                    ${number(line.qty_remaining)}
                </td>
            </tr>`).join("");
        const pickings = doc.pickings.length
            ? doc.pickings.map((item) => `
                <button type="button" class="vt-btn vt-btn-mini" data-vt-doc="picking" data-vt-doc-id="${item.id}">
                    <span class="vt-num">${esc(item.name)}</span>
                    <span class="vt-muted">${esc(item.state_label)}
                        ${item.vehicle_plate ? " · " + esc(item.vehicle_plate) : ""}</span>
                </button>`).join("")
            : '<span class="vt-muted">Chưa có phiếu kho nào.</span>';
        return `
            <div class="vt-doc-head">
                <span class="vt-doc-title">
                    <span class="vt-doc-name"><span class="vt-num">${esc(doc.title)}</span></span>
                    <span class="vt-muted">${esc(doc.partner_name)}</span>
                </span>
            </div>
            <div class="vt-facts">${facts}</div>
            <table class="vt-doc-table">
                <thead>
                    <tr>
                        <th>Hàng hoá</th><th>ĐVT</th>
                        <th class="vt-right">Đặt</th>
                        <th class="vt-right">Đã giao</th>
                        <th class="vt-right">Còn lại</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
            <div class="vt-doc-others"><span class="vt-muted">Phiếu kho:</span>${pickings}</div>`;
    }

    // -------------------------------------------------------------- khung

    function render(doc) {
        const body = document.getElementById("vt-doc-body");
        const footer = document.getElementById("vt-doc-foot");
        if (doc.error) {
            body.innerHTML = `<div class="vt-alert">${esc(doc.error)}</div>`;
            footer.innerHTML = "";
            return;
        }
        document.getElementById("vt-doc-title").textContent = doc.title;
        body.innerHTML = doc.kind === "picking" ? pickingHtml(doc) : orderHtml(doc);
        const orderId = doc.kind === "picking" ? doc.sale_order_id : doc.id;
        const orderName = doc.kind === "picking" ? doc.sale_order_name : doc.title;
        footer.innerHTML = `
            ${orderId ? `<button type="button" class="vt-btn vt-btn-primary"
                data-vt-order="${orderId}" data-vt-order-name="${esc(orderName)}">
                Xin đổi lịch cho đơn này</button>` : ""}
            <span class="vt-muted vt-push">Giờ có dấu ~ là ước tính, không phải giờ đã hẹn với khách.</span>`;
        void openRequestHandler;
    }

    return { render, stamp, money, number, esc };
})();
