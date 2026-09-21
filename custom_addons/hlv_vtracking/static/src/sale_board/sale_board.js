/* Trang /giao-hang cho người bán hàng: chuyến trong ngày, xe đang ở đâu, và xin điều
   chỉnh lịch cho ĐƠN CỦA MÌNH.

   Nguyên tắc dựng màn này: người bán hàng không điều phối. Họ không xếp chuyến, không đổi
   thứ tự ghé — họ chỉ cần biết hàng của khách mình đi lúc nào, và xin đổi khi khách hỏi.
   Nên mọi nút bấm đều gắn vào MỘT ĐƠN cụ thể, không có nút nào tác động lên cả chuyến.

   Gọi Odoo bằng JSON-RPC thường; trang này nằm ngoài backend nên không dùng khung OWL. */

(function () {
    const POSITION_REFRESH_MS = 30000;   // vị trí xe: đủ nhanh để thấy xe đang chạy
    const BOARD_REFRESH_MS = 120000;     // chuyến và yêu cầu: đổi chậm hơn nhiều
    // Cả phòng dùng chung một tài khoản Odoo, nên "tôi là ai" là chuyện của cái máy đang
    // ngồi, không phải của tài khoản.
    const SALER_KEY = "vt_saler_code";
    const STATE_LABEL = { draft: "nháp", confirmed: "đã chốt", done: "xong" };

    const state = {
        date: null, config: {}, plans: [], vehicles: [],
        saler: "", search: "", mineOnly: false, pending: false,
    };

    // ------------------------------------------------------------ tiện ích

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

    /* Giờ tới ước tính: cộng số phút vào giờ bắt đầu buổi. Giờ đồng hồ dễ hình dung hơn
       "+93 phút", nhưng luôn kèm dấu ~ để không ai đọc thành giờ đã hẹn với khách. */
    function etaLabel(minutes, sessionLabel) {
        if (minutes == null) {
            return "";
        }
        const base = (sessionLabel || "").indexOf("Chiều") === 0 ? 13 * 60 : 8 * 60;
        const total = base + minutes;
        const hour = String(Math.floor(total / 60) % 24).padStart(2, "0");
        const minute = String(total % 60).padStart(2, "0");
        return `~${hour}:${minute}`;
    }

    // ---------------------------------------------------------------- vẽ

    function planCard(plan) {
        const open = plan.has_mine || state.plans.length === 1;
        const total = plan.stops.length;
        const percent = total ? Math.round((plan.delivered_count / total) * 100) : 0;
        const vehicle = state.vehicles.find((item) => item.name === plan.vehicle_plate);
        const dot = vehicle
            ? `<span class="vt-status vt-status-${vehicle.status}"
                     title="${escapeHtml(vehicle.status_label)}"></span>`
            : "";
        return `
            <section class="vt-plan ${plan.has_mine ? "is-mine" : ""} ${open ? "is-open" : ""}">
                <header class="vt-plan-head" data-vt-toggle="${plan.id}" role="button" tabindex="0">
                    <span class="vt-caret">${open ? "▾" : "▸"}</span>
                    ${dot}
                    <span class="vt-plate">${escapeHtml(plan.vehicle_plate)}</span>
                    <span class="vt-chip">${escapeHtml(plan.session_label)}</span>
                    <span class="vt-chip vt-chip-soft">${escapeHtml(STATE_LABEL[plan.state] || plan.state)}</span>
                    ${plan.zone_name ? `<span class="vt-muted">${escapeHtml(plan.zone_name)}</span>` : ""}
                    ${plan.has_mine ? '<span class="vt-chip vt-chip-mine">có đơn của tôi</span>' : ""}
                    <span class="vt-plan-meta">
                        ${plan.stop_count} điểm · ~${plan.distance_km || 0} km ·
                        ${escapeHtml(plan.duration_display || "—")}
                    </span>
                </header>
                <div class="vt-progress" title="Đã giao ${plan.delivered_count}/${total} điểm">
                    <span style="width:${percent}%"></span>
                </div>
                <div class="vt-plan-body">
                    <ol class="vt-stops">${plan.stops.map((stop) => stopRow(stop, plan)).join("")}</ol>
                    <footer class="vt-plan-foot">
                        <span class="vt-muted">
                            ${plan.driver_name ? "Tài xế " + escapeHtml(plan.driver_name) : "Chưa gán tài xế"}
                            ${plan.start_name ? " · xuất phát " + escapeHtml(plan.start_name) : ""}
                        </span>
                        <button type="button" class="vt-btn vt-btn-ghost" data-vt-route="${plan.id}">
                            Xem lộ trình trên bản đồ
                        </button>
                    </footer>
                </div>
            </section>`;
    }

    function stopRow(stop, plan) {
        const flags = [];
        if (stop.returned) flags.push('<span class="vt-tag vt-tag-danger">chở về</span>');
        if (stop.procedure_blocked) flags.push('<span class="vt-tag vt-tag-danger">vướng thủ tục</span>');
        if (stop.waiting_picking) flags.push('<span class="vt-tag vt-tag-warn">chờ phiếu</span>');
        // Nút chỉ hiện ở ĐIỂM CỦA MÌNH: xin đổi lịch cho đơn người khác không phải việc của
        // người bán hàng này.
        const ask = stop.mine && stop.sale_order_id
            ? `<button type="button" class="vt-btn vt-btn-mini" data-vt-order="${stop.sale_order_id}"
                       data-vt-order-name="${escapeHtml(stop.reference)}">Xin đổi lịch</button>`
            : "";
        const locate = stop.latitude
            ? `<button type="button" class="vt-btn vt-btn-mini vt-btn-ghost"
                       data-vt-locate="${stop.latitude},${stop.longitude}"
                       data-vt-label="${escapeHtml(stop.partner_name || "")}">Xem trên bản đồ</button>`
            : "";
        return `
            <li class="vt-stop ${stop.mine ? "is-mine" : ""} ${stop.delivered ? "is-done" : ""}">
                <span class="vt-seq">${stop.sequence}</span>
                <span class="vt-stop-main">
                    <span class="vt-stop-name">
                        ${stop.delivered ? '<span class="vt-check">✓</span>' : ""}
                        ${escapeHtml(stop.partner_name || "—")}
                        ${stop.mine ? '<span class="vt-tag vt-tag-mine">đơn của tôi</span>' : ""}
                    </span>
                    <span class="vt-stop-address">${escapeHtml(stop.address || "")}</span>
                    <span class="vt-stop-actions">${ask}${locate}</span>
                </span>
                <span class="vt-stop-side">
                    <span class="vt-eta" title="Giờ tới ước tính, không phải giờ đã hẹn">
                        ${etaLabel(stop.arrive_offset_minutes, plan.session_label)}
                    </span>
                    ${flags.join("")}
                </span>
            </li>`;
    }

    function unplannedRow(order) {
        const due = order.commitment_date
            ? `hẹn ${escapeHtml(order.commitment_date.slice(0, 10))}`
            : "chưa có ngày hẹn";
        return `
            <div class="vt-row">
                <div class="vt-row-main">
                    <div class="vt-row-title">${escapeHtml(order.name)}</div>
                    <div class="vt-muted">${escapeHtml(order.partner_name)} · ${due}</div>
                </div>
                <button type="button" class="vt-btn vt-btn-primary" data-vt-order="${order.id}"
                        data-vt-order-name="${escapeHtml(order.name)}">Nhờ AI xếp</button>
            </div>`;
    }

    function requestRow(item) {
        const tone = { feasible: "ok", conditional: "warn", not_feasible: "danger" }[item.verdict] || "soft";
        const badge = item.verdict
            ? `<span class="vt-tag vt-tag-${tone}">${escapeHtml(item.verdict_label)}</span>`
            : `<span class="vt-tag vt-tag-soft">${escapeHtml(item.state_label)}</span>`;
        return `
            <article class="vt-request">
                <header>
                    <span class="vt-row-title">${escapeHtml(item.order_name || item.type_label)}</span>
                    ${badge}
                    <span class="vt-muted vt-push">${escapeHtml((item.created_at || "").slice(0, 16))}</span>
                </header>
                <p class="vt-muted">${escapeHtml(item.message)}</p>
                ${item.answer ? `<div class="vt-answer">${item.answer}</div>` : ""}
            </article>`;
    }

    function render(data) {
        state.config = { tile_url: data.tile_url, tile_attribution: data.tile_attribution };
        state.plans = data.plans;
        state.vehicles = data.vehicles;
        fillSalerOptions(data.saler_codes);
        renderPlans();
        renderUnplanned(data.my_unplanned, data.mine_configured);
        renderRequests(data.my_requests);
        window.VtSaleMap.update(data.vehicles, state.config);
        stamp();
    }

    function renderPlans() {
        const plans = state.mineOnly ? state.plans.filter((plan) => plan.has_mine) : state.plans;
        el("vt-plans").innerHTML = plans.length
            ? plans.map(planCard).join("")
            : `<div class="vt-empty">${state.mineOnly
                ? "Ngày này không có chuyến nào chở đơn của bạn."
                : "Ngày này chưa có chuyến nào."}</div>`;
        const mine = state.plans.filter((plan) => plan.has_mine).length;
        el("vt-summary").innerHTML = `<b>${state.plans.length}</b> chuyến · <b>${mine}</b> có đơn của tôi`;
        markRouteButtons();
    }

    function renderUnplanned(orders, mineConfigured) {
        el("vt-unplanned-count").textContent = orders.length;
        if (orders.length) {
            el("vt-unplanned").innerHTML = orders.map(unplannedRow).join("");
            return;
        }
        el("vt-unplanned").innerHTML = mineConfigured || state.saler
            ? '<div class="vt-empty">Không có đơn nào chờ xếp.</div>'
            : '<div class="vt-empty">Chọn <b>mã sale</b> của bạn ở thanh trên để thấy đơn của mình.</div>';
    }

    function renderRequests(requests) {
        el("vt-requests").innerHTML = requests.length
            ? requests.map(requestRow).join("")
            : '<div class="vt-empty">Chưa gửi yêu cầu nào.</div>';
        // Đếm yêu cầu CÒN MỞ: đó là thứ người ta cần biết còn phải theo dõi mấy cái.
        const waiting = requests.filter((item) => item.open).length;
        el("vt-request-count").textContent = waiting;
        el("vt-request-count").classList.toggle("is-zero", !waiting);
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
            button.classList.toggle("is-active", active);
            button.textContent = active ? "Tắt lộ trình" : "Xem lộ trình trên bản đồ";
        }
    }

    function stamp() {
        el("vt-updated").textContent = "Cập nhật " + new Date().toLocaleTimeString("vi-VN");
    }

    // ---------------------------------------------------------------- tải

    function loadBoard() {
        el("vt-plans").classList.add("is-loading");
        return rpc("/giao-hang/du-lieu",
                   { date: state.date, saler_code: state.saler, search: state.search })
            .then(render)
            .catch((error) => {
                el("vt-plans").innerHTML =
                    `<div class="vt-alert">Không tải được dữ liệu: ${escapeHtml(error.message)}</div>`;
            })
            .finally(() => el("vt-plans").classList.remove("is-loading"));
    }

    function loadUnplanned() {
        return rpc("/giao-hang/don-chua-xep", { saler_code: state.saler, search: state.search })
            .then((data) => renderUnplanned(data.my_unplanned, true));
    }

    function loadPositions() {
        return rpc("/giao-hang/vi-tri", {})
            .then((data) => {
                state.vehicles = data.vehicles;
                window.VtSaleMap.update(data.vehicles, state.config);
                stamp();
            })
            .catch(() => {
                /* Mất mạng một nhịp không đáng báo động: nhịp sau tự cập nhật lại. */
            });
    }

    function setDate(value) {
        state.date = value;
        el("vt-date").value = value;
        window.VtSaleMap.clearRoute();
        loadBoard();
    }

    function shiftDate(days) {
        const current = new Date(state.date + "T00:00:00");
        current.setDate(current.getDate() + days);
        setDate(current.toISOString().slice(0, 10));
    }

    // ------------------------------------------------------------ yêu cầu

    const target = { sale_order_id: null };

    function openRequest(orderId, label) {
        target.sale_order_id = orderId;
        el("vt-request-target").textContent = label || "";
        el("vt-request-message").value = "";
        el("vt-request-error").textContent = "";
        el("vt-request-date").value = state.date;
        bootstrap.Modal.getOrCreateInstance(el("vt-request-modal")).show();
    }

    function sendRequest() {
        if (state.pending) {
            return;
        }
        state.pending = true;
        el("vt-request-send").disabled = true;
        rpc("/giao-hang/yeu-cau", {
            sale_order_id: target.sale_order_id,
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
                renderRequests(result.my_requests);
                bootstrap.Modal.getOrCreateInstance(el("vt-request-modal")).hide();
                bootstrap.Offcanvas.getOrCreateInstance(el("vt-drawer")).show();
            })
            .catch((error) => {
                el("vt-request-error").textContent = error.message;
            })
            .finally(() => {
                state.pending = false;
                el("vt-request-send").disabled = false;
            });
    }

    // ------------------------------------------------------------- sự kiện

    document.addEventListener("click", (event) => {
        const orderButton = event.target.closest("[data-vt-order]");
        if (orderButton) {
            openRequest(Number(orderButton.dataset.vtOrder), orderButton.dataset.vtOrderName);
            return;
        }
        const locate = event.target.closest("[data-vt-locate]");
        if (locate) {
            const [lat, lng] = locate.dataset.vtLocate.split(",").map(Number);
            window.VtSaleMap.focus(lat, lng, locate.dataset.vtLabel);
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
        const dayButton = event.target.closest("[data-vt-day]");
        if (dayButton) {
            shiftDate(Number(dayButton.dataset.vtDay));
            return;
        }
        const head = event.target.closest("[data-vt-toggle]");
        if (head) {
            const card = head.closest(".vt-plan");
            const open = card.classList.toggle("is-open");
            head.querySelector(".vt-caret").textContent = open ? "▾" : "▸";
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
        el("vt-mine-only").addEventListener("change", (event) => {
            state.mineOnly = event.target.checked;
            renderPlans();
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
