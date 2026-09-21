/* Trang /giao-hang: bảng chuyến trong ngày, đơn của tôi, và nút nhờ AI.

   Gọi Odoo bằng JSON-RPC thường (/giao-hang/...), không dùng khung OWL: trang này nằm
   ngoài backend, người bán hàng mở nó như một trang web bình thường. */

(function () {
    const POSITION_REFRESH_MS = 30000;   // vị trí xe: đủ nhanh để thấy xe đang chạy
    const BOARD_REFRESH_MS = 120000;     // chuyến và yêu cầu: đổi chậm hơn nhiều

    // Mã sale nhớ trong trình duyệt: cả phòng dùng chung tài khoản Odoo, nên "tôi là ai"
    // là chuyện của cái máy đang ngồi, không phải của tài khoản.
    const SALER_KEY = "vt_saler_code";
    const state = { date: null, config: {}, pending: false, plans: [], saler: "", search: "" };

    function rpc(url, params) {
        return fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: params || {} }),
        })
            .then((response) => response.json())
            .then((body) => {
                if (body.error) {
                    throw new Error(body.error.data ? body.error.data.message : body.error.message);
                }
                return body.result;
            });
    }

    function el(id) {
        return document.getElementById(id);
    }

    function escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text == null ? "" : String(text);
        return div.innerHTML;
    }

    function todayString() {
        const now = new Date();
        return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    }

    function shiftDate(days) {
        const current = new Date(state.date + "T00:00:00");
        current.setDate(current.getDate() + days);
        setDate(current.toISOString().slice(0, 10));
    }

    function setDate(value) {
        state.date = value;
        el("vt-date").value = value;
        loadBoard();
    }

    // ---------------------------------------------------------------- vẽ

    const STATE_LABEL = { draft: "nháp", confirmed: "đã chốt", done: "xong" };

    /* Mỗi chuyến là một khối gập được: mở sẵn chuyến có đơn của mình, gập những chuyến
       còn lại. Năm xe mười điểm mở hết một lúc thì không ai đọc nổi. */
    function planCard(plan, index) {
        const stops = plan.stops.map(stopRow).join("");
        const mine = plan.has_mine ? '<span class="badge bg-primary">có đơn của tôi</span>' : "";
        const progress = plan.delivered_count
            ? `<span class="text-success small">đã giao ${plan.delivered_count}/${plan.stops.length}</span>`
            : "";
        const open = plan.has_mine || state.plans.length === 1;
        return `
            <div class="card mb-2 ${plan.has_mine ? "vt-mine" : ""}">
                <div class="card-header py-2 d-flex flex-wrap align-items-center gap-2 vt-plan-head"
                     data-vt-toggle="plan-${index}" role="button">
                    <i class="fa fa-chevron-${open ? "down" : "right"} text-muted vt-caret"></i>
                    <span class="fw-bold">${escapeHtml(plan.vehicle_plate)}</span>
                    <span class="text-muted">${escapeHtml(plan.session_label)}</span>
                    <span class="badge bg-light text-dark">${escapeHtml(STATE_LABEL[plan.state] || plan.state)}</span>
                    ${plan.zone_name ? `<span class="text-muted small">${escapeHtml(plan.zone_name)}</span>` : ""}
                    ${mine}${progress}
                    <span class="ms-auto small text-muted">
                        ${plan.stop_count} điểm · ${plan.line_count} phiếu ·
                        ~${plan.distance_km || 0} km · ${escapeHtml(plan.duration_display || "—")}
                    </span>
                </div>
                <div class="collapse ${open ? "show" : ""}" id="plan-${index}">
                    <div class="card-body p-0"><div class="vt-stops">${stops}</div></div>
                    <div class="card-footer py-1 d-flex align-items-center gap-2 flex-wrap">
                        <span class="small text-muted">
                            ${plan.driver_name ? "Tài xế " + escapeHtml(plan.driver_name) : "Chưa gán tài xế"}
                            ${plan.start_name ? " · xuất phát " + escapeHtml(plan.start_name) : ""}
                        </span>
                        <button type="button" class="btn btn-sm btn-outline-secondary ms-auto"
                                data-vt-route="${plan.id}">Xem lộ trình</button>
                        <button type="button" class="btn btn-sm btn-outline-primary"
                                data-vt-plan="${plan.id}">Nhờ AI xem chuyến này</button>
                    </div>
                </div>
            </div>`;
    }

    function stopRow(stop) {
        const flags = [];
        if (stop.returned) flags.push('<span class="badge bg-danger">chở về</span>');
        if (stop.waiting_picking) flags.push('<span class="badge bg-warning text-dark">chờ phiếu</span>');
        if (stop.procedure_blocked) flags.push('<span class="badge bg-danger">vướng thủ tục</span>');
        const eta = stop.arrive_offset_minutes != null
            ? `<span class="vt-eta text-muted">+${stop.arrive_offset_minutes}′</span>`
            : "";
        return `
            <div class="vt-stop ${stop.mine ? "vt-stop-mine" : ""} ${stop.delivered ? "vt-stop-done" : ""}">
                <span class="vt-seq">${stop.sequence}</span>
                <span class="vt-stop-main">
                    ${stop.delivered ? "✓ " : ""}${escapeHtml(stop.partner_name || "—")}
                    <span class="text-muted small d-block">${escapeHtml(stop.address || "")}</span>
                </span>
                ${eta}
                <span class="vt-flags">${flags.join(" ")}</span>
            </div>`;
    }

    function unplannedRow(order) {
        const due = order.commitment_date
            ? `hẹn ${escapeHtml(order.commitment_date.slice(0, 10))}`
            : "chưa có ngày hẹn";
        return `
            <div class="vt-row">
                <div class="flex-grow-1">
                    <div class="fw-semibold">${escapeHtml(order.name)}</div>
                    <div class="small text-muted">${escapeHtml(order.partner_name)} · ${due}</div>
                </div>
                <button type="button" class="btn btn-sm btn-primary" data-vt-order="${order.id}"
                        data-vt-order-name="${escapeHtml(order.name)}">Nhờ AI</button>
            </div>`;
    }

    function requestRow(item) {
        const tone = { feasible: "success", conditional: "warning", not_feasible: "danger" }[item.verdict] || "secondary";
        const verdict = item.verdict
            ? `<span class="badge bg-${tone}">${escapeHtml(item.verdict_label)}</span>`
            : `<span class="badge bg-light text-dark">${escapeHtml(item.state_label)}</span>`;
        return `
            <div class="vt-row flex-column align-items-start">
                <div class="d-flex w-100 align-items-center gap-2">
                    <span class="fw-semibold">${escapeHtml(item.order_name || item.type_label)}</span>
                    ${verdict}
                    <span class="ms-auto small text-muted">${escapeHtml((item.created_at || "").slice(0, 16))}</span>
                </div>
                <div class="small text-muted">${escapeHtml(item.message)}</div>
                ${item.answer ? `<div class="vt-answer small mt-1">${item.answer}</div>` : ""}
            </div>`;
    }

    function render(data) {
        state.config = { tile_url: data.tile_url, tile_attribution: data.tile_attribution };
        state.plans = data.plans;
        fillSalerOptions(data.saler_codes);
        el("vt-plans").innerHTML = data.plans.length
            ? data.plans.map(planCard).join("")
            : '<div class="text-muted">Ngày này chưa có chuyến nào.</div>';
        el("vt-unplanned").innerHTML = data.my_unplanned.length
            ? data.my_unplanned.map(unplannedRow).join("")
            : data.mine_configured
                ? '<div class="vt-row text-muted">Không có đơn nào chờ xếp.</div>'
                : `<div class="vt-row text-warning-emphasis">
                       Tài khoản chưa khai <b>mã sale MISA</b> nên không nhận ra đơn nào là
                       của bạn. Báo quản trị khai ở Cài đặt &gt; Người dùng.
                   </div>`;
        renderRequests(data.my_requests);
        const mine = data.plans.filter((plan) => plan.has_mine).length;
        el("vt-summary").textContent =
            `${data.plans.length} chuyến · ${mine} chuyến có đơn của tôi · ${data.my_unplanned.length} đơn chưa xếp`;
        window.VtSaleMap.update(data.vehicles, state.config);
        stamp();
    }

    function renderRequests(requests) {
        el("vt-requests").innerHTML = requests.length
            ? requests.map(requestRow).join("")
            : '<div class="vt-row text-muted">Chưa gửi yêu cầu nào.</div>';
        // Đếm số yêu cầu CÒN MỞ: đó là thứ người ta cần biết còn phải theo dõi mấy cái.
        el("vt-request-count").textContent = requests.filter((item) => item.open).length;
    }

    function fillSalerOptions(codes) {
        const select = el("vt-saler");
        if (select.dataset.filled === "1") {
            return;
        }
        for (const code of codes || []) {
            const option = document.createElement("option");
            option.value = code;
            option.textContent = code;
            select.appendChild(option);
        }
        select.value = state.saler;
        select.dataset.filled = "1";
    }

    function markRouteButtons() {
        const shown = window.VtSaleMap.shownRoute();
        for (const button of document.querySelectorAll("[data-vt-route]")) {
            const active = Number(button.dataset.vtRoute) === shown;
            button.classList.toggle("btn-secondary", active);
            button.classList.toggle("btn-outline-secondary", !active);
            button.textContent = active ? "Tắt lộ trình" : "Xem lộ trình";
        }
    }

    function stamp() {
        el("vt-updated").textContent = "Cập nhật " + new Date().toLocaleTimeString("vi-VN");
    }

    // ---------------------------------------------------------------- tải

    function loadBoard() {
        return rpc("/giao-hang/du-lieu",
                   { date: state.date, saler_code: state.saler, search: state.search })
            .then(render)
            .catch((error) => {
                el("vt-plans").innerHTML =
                    `<div class="alert alert-danger">Không tải được dữ liệu: ${escapeHtml(error.message)}</div>`;
            });
    }

    function loadPositions() {
        return rpc("/giao-hang/vi-tri", {})
            .then((data) => {
                window.VtSaleMap.update(data.vehicles, state.config);
                stamp();
            })
            .catch(() => {
                /* Mất mạng một nhịp không đáng báo động: nhịp sau tự cập nhật lại. */
            });
    }

    function loadUnplanned() {
        return rpc("/giao-hang/don-chua-xep", { saler_code: state.saler, search: state.search })
            .then((data) => {
                el("vt-unplanned").innerHTML = data.my_unplanned.length
                    ? data.my_unplanned.map(unplannedRow).join("")
                    : '<div class="vt-row text-muted">Không tìm thấy đơn nào.</div>';
            });
    }

    // ------------------------------------------------------------ yêu cầu

    let modal = null;
    const target = { sale_order_id: null, plan_id: null };

    function openRequest(options) {
        target.sale_order_id = options.orderId || null;
        target.plan_id = options.planId || null;
        el("vt-request-target").textContent = options.label;
        el("vt-request-message").value = "";
        el("vt-request-error").textContent = "";
        el("vt-request-type").value = options.planId ? "reschedule" : "earlier";
        el("vt-request-date").value = state.date;
        modal = modal || new bootstrap.Modal(el("vt-request-modal"));
        modal.show();
    }

    function sendRequest() {
        if (state.pending) {
            return;
        }
        state.pending = true;
        el("vt-request-send").disabled = true;
        rpc("/giao-hang/yeu-cau", {
            sale_order_id: target.sale_order_id,
            plan_id: target.plan_id,
            request_type: el("vt-request-type").value,
            desired_date: el("vt-request-date").value || null,
            desired_session: el("vt-request-session").value || null,
            message: el("vt-request-message").value,
        })
            .then((result) => {
                if (result.error) {
                    el("vt-request-error").textContent = result.error;
                    return;
                }
                el("vt-requests").innerHTML = result.my_requests.map(requestRow).join("");
                modal.hide();
            })
            .catch((error) => {
                el("vt-request-error").textContent = error.message;
            })
            .finally(() => {
                state.pending = false;
                el("vt-request-send").disabled = false;
            });
    }

    // ------------------------------------------------------------- khởi động

    document.addEventListener("click", (event) => {
        const orderButton = event.target.closest("[data-vt-order]");
        if (orderButton) {
            openRequest({
                orderId: Number(orderButton.dataset.vtOrder),
                label: "Đơn " + orderButton.dataset.vtOrderName,
            });
            return;
        }
        const planButton = event.target.closest("[data-vt-plan]");
        if (planButton) {
            openRequest({ planId: Number(planButton.dataset.vtPlan), label: "Chuyến đang xem" });
            return;
        }
        const dayButton = event.target.closest("[data-vt-day]");
        if (dayButton) {
            shiftDate(Number(dayButton.dataset.vtDay));
            return;
        }
        const routeButton = event.target.closest("[data-vt-route]");
        if (routeButton) {
            const plan = state.plans.find((item) => item.id === Number(routeButton.dataset.vtRoute));
            if (plan) {
                window.VtSaleMap.toggleRoute(plan);
                markRouteButtons();
            }
            return;
        }
        const head = event.target.closest("[data-vt-toggle]");
        if (head) {
            const body = document.getElementById(head.dataset.vtToggle);
            const caret = head.querySelector(".vt-caret");
            const shown = body.classList.toggle("show");
            caret.className = `fa fa-chevron-${shown ? "down" : "right"} text-muted vt-caret`;
        }
    });

    document.addEventListener("DOMContentLoaded", () => {
        state.date = todayString();
        state.saler = localStorage.getItem(SALER_KEY) || "";
        el("vt-date").value = state.date;
        el("vt-date").addEventListener("change", (event) => setDate(event.target.value));
        el("vt-today").addEventListener("click", () => setDate(todayString()));
        el("vt-request-send").addEventListener("click", sendRequest);
        el("vt-saler").addEventListener("change", (event) => {
            state.saler = event.target.value;
            localStorage.setItem(SALER_KEY, state.saler);
            window.VtSaleMap.clearRoute();
            loadBoard();
        });
        // Chờ người dùng gõ xong mới hỏi server: mỗi phím một request là vô ích.
        let typing = null;
        el("vt-search").addEventListener("input", (event) => {
            state.search = event.target.value;
            clearTimeout(typing);
            typing = setTimeout(loadUnplanned, 300);
        });
        el("vt-open-drawer").addEventListener("click", () => {
            bootstrap.Offcanvas.getOrCreateInstance(el("vt-drawer")).show();
        });
        loadBoard();
        setInterval(loadPositions, POSITION_REFRESH_MS);
        setInterval(loadBoard, BOARD_REFRESH_MS);
    });
})();
