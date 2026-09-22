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
        date: null, config: {}, plans: [], vehicles: [], places: [],
        saler: "", search: "", mineOnly: false, pending: false,
        // Chuyến đang xem ở cột phải. null = chưa chọn -> chưa dựng bản đồ.
        selectedPlanId: null,
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

    /* Thẻ chuyến ở danh sách: CHỈ phần đọc một nhịp là hiểu — xe, buổi, cụm, ba con số,
       và dải điểm ghé. Toàn bộ chi tiết (địa chỉ, chứng từ, nút xin đổi lịch) nằm ở cột
       phải khi chọn chuyến.

       Trước đây mỗi thẻ tự mở sẵn cả danh sách điểm kèm nút, nên ba chuyến là đã phải cuộn
       và không còn nhìn ra chuyến nào là chuyến nào — đó chính là chỗ rối. */
    function planCard(plan) {
        const selected = plan.id === state.selectedPlanId;
        const total = plan.stops.length;
        const percent = total ? Math.round((plan.delivered_count / total) * 100) : 0;
        const vehicle = state.vehicles.find((item) => item.name === plan.vehicle_plate);
        const dot = vehicle
            ? `<span class="vt-status vt-status-${vehicle.status}"
                     title="${escapeHtml(vehicle.status_label)}"></span>`
            : "";
        return `
            <section class="vt-plan ${plan.has_mine ? "is-mine" : ""} ${selected ? "is-selected" : ""}"
                     data-vt-select="${plan.id}" role="button" tabindex="0">
                <header class="vt-plan-head">
                    ${dot}
                    <span class="vt-plate">${escapeHtml(plan.vehicle_plate)}</span>
                    <span class="vt-session vt-session-${plan.session || "other"}">
                        ${escapeHtml(plan.session_label)}
                    </span>
                    ${plan.zone_name ? `<span class="vt-zone">${escapeHtml(plan.zone_name)}</span>` : ""}
                    <span class="vt-chip vt-chip-soft">${escapeHtml(STATE_LABEL[plan.state] || plan.state)}</span>
                    ${plan.has_mine ? '<span class="vt-chip vt-chip-mine">có đơn của tôi</span>' : ""}
                    <span class="vt-plan-open">Xem chi tiết ›</span>
                </header>
                <div class="vt-plan-meta">${planMetaText(plan)}</div>
                <div class="vt-progress" title="Đã giao ${plan.delivered_count}/${total} điểm">
                    <span style="width:${percent}%"></span>
                </div>
                <ol class="vt-strip">${plan.stops.map((stop) => stripItem(stop, plan)).join("")}</ol>
            </section>`;
    }

    /* Ba con số của chuyến. Hiện km ĐƯỜNG THẬT khi đã lấy được (ghi rõ "đường bộ"), không
       thì km chim bay kèm dấu ~ — hai con số khác nguồn, đọc phải biết đang xem cái nào. */
    function planMetaText(plan) {
        const km = plan.road_distance_km
            ? `${plan.road_distance_km} km đường bộ`
            : `~${plan.distance_km || 0} km`;
        return `${plan.stop_count} điểm · ${km} · ${escapeHtml(plan.duration_display || "—")}`;
    }

    /* Một điểm trong dải điểm của thẻ: số thứ tự, tên khách rút gọn, giờ tới ước tính. */
    function stripItem(stop, plan) {
        const eta = etaLabel(stop.arrive_offset_minutes, plan.session_label);
        return `
            <li class="vt-strip-item ${stop.mine ? "is-mine" : ""} ${stop.delivered ? "is-done" : ""}"
                title="${escapeHtml(stop.partner_name || "")}">
                <span class="vt-seq">${stop.sequence}</span>
                <span class="vt-strip-name">${escapeHtml(stop.partner_name || "—")}</span>
                <span class="vt-strip-eta">${eta}</span>
            </li>`;
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
                    <span class="vt-docs">
                        ${stop.sale_order_name ? `<button type="button" class="vt-doc"
                            data-vt-doc="order" data-vt-doc-id="${stop.sale_order_id}">
                            ${escapeHtml(stop.sale_order_name)}</button>` : ""}
                        ${stop.picking_name ? `<button type="button" class="vt-doc"
                            data-vt-doc="picking" data-vt-doc-id="${stop.picking_id}">
                            ${escapeHtml(stop.picking_name)}</button>` : ""}
                    </span>
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

    /* Cột phải khi đã chọn một chuyến: đầy đủ từng điểm, kèm nút của người bán hàng. Đây
       là nơi DUY NHẤT còn dùng stopRow — thẻ chuyến bên trái chỉ hiện dải điểm rút gọn. */
    function planDetail(plan) {
        return `
            <div class="vt-panel-head">
                <span class="vt-plate">${escapeHtml(plan.vehicle_plate)}</span>
                <span class="vt-session vt-session-${plan.session || "other"}">
                    ${escapeHtml(plan.session_label)}
                </span>
                ${plan.zone_name ? `<span class="vt-zone">${escapeHtml(plan.zone_name)}</span>` : ""}
                <button type="button" class="vt-btn vt-btn-mini vt-btn-ghost ms-auto"
                        data-vt-unselect="1" title="Đóng, ẩn bản đồ">✕</button>
            </div>
            <div class="vt-detail-meta">
                ${planMetaText(plan)}
                <span class="vt-muted">
                    · ${plan.driver_name ? "tài xế " + escapeHtml(plan.driver_name) : "chưa gán tài xế"}
                    ${plan.start_name ? " · xuất phát " + escapeHtml(plan.start_name) : ""}
                </span>
            </div>
            <ol class="vt-stops">${plan.stops.map((stop) => stopRow(stop, plan)).join("")}</ol>
            <footer class="vt-plan-foot">
                <button type="button" class="vt-btn vt-btn-ghost" data-vt-route="${plan.id}">
                    Xem toàn bộ hành trình
                </button>
            </footer>`;
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
        // Câu trả lời của AI dài 15–20 dòng. Mở sẵn hết thì phải cuộn mãi mới thấy yêu cầu
        // thứ hai, nên gập lại và để người đọc tự mở cái mình cần.
        const answer = item.answer
            ? `<details class="vt-answer-box">
                   <summary>Xem AI trả lời</summary>
                   <div class="vt-answer">${item.answer}</div>
               </details>`
            : "";
        return `
            <article class="vt-request">
                <header>
                    <span class="vt-row-title">${escapeHtml(item.order_name || item.type_label)}</span>
                    ${badge}
                    <span class="vt-muted vt-push">${escapeHtml((item.created_at || "").slice(0, 16))}</span>
                </header>
                <p class="vt-muted">${escapeHtml(item.message)}</p>
                ${answer}
            </article>`;
    }

    function render(data) {
        state.config = { tile_url: data.tile_url, tile_attribution: data.tile_attribution };
        state.plans = data.plans;
        state.vehicles = data.vehicles;
        state.places = data.places || [];
        fillSalerOptions(data.saler_codes);
        renderPlans();
        renderUnplanned(data.my_unplanned, data.mine_configured);
        renderRequests(data.my_requests);
        // Vẽ lên bản đồ chỉ khi nó ĐÃ được mở (người dùng đã chọn một chuyến). Chưa mở thì
        // dữ liệu vẫn nằm trong state, lúc mở sẽ vẽ một lượt — xem showDetail().
        if (window.VtSaleMap.isOpen()) {
            window.VtSaleMap.update(state.vehicles);
            window.VtSaleMap.showPlaces(state.places);
        }
        stamp();
    }

    function renderPlans() {
        const plans = state.mineOnly ? state.plans.filter((plan) => plan.has_mine) : state.plans;
        el("vt-plans").innerHTML = plans.length
            ? plans.map(planCard).join("")
            : `<div class="vt-empty">${state.mineOnly
                ? "Ngày này không có chuyến nào chở đơn của bạn."
                : "Ngày này chưa có chuyến nào."}</div>`;
        el("vt-kpi-plans").textContent = plans.length;
        el("vt-kpi-stops").textContent = plans.reduce(
            (total, plan) => total + (plan.stop_count || 0), 0);
        // Chuyến đang chọn có thể biến mất sau khi đổi ngày / bật lọc "chỉ đơn của tôi" —
        // bỏ chọn luôn thay vì để cột phải hiện một chuyến không còn trong danh sách.
        if (state.selectedPlanId && !plans.some((plan) => plan.id === state.selectedPlanId)) {
            hideDetail();
            return;
        }
        renderDetail();
    }

    /* Vẽ lại cột phải theo chuyến đang chọn. Gọi cả sau mỗi lượt làm tươi 120 giây, nên
       chuyến đang mở tự cập nhật (điểm vừa giao xong, giờ tới đổi) mà không phải chọn lại.

       ``fit``: chỉ lúc người dùng vừa CHỌN chuyến mới căn khung nhìn về toàn tuyến. Lượt làm
       tươi định kỳ thì không — xem showRoute() trong sale_board_map.js. */
    function renderDetail(fit) {
        const plan = state.plans.find((item) => item.id === state.selectedPlanId);
        if (!plan) {
            return;
        }
        el("vt-detail-panel").innerHTML = planDetail(plan);
        if (window.VtSaleMap.isOpen()) {
            window.VtSaleMap.showRoute(plan, fit === true);
        }
    }

    function showDetail(planId) {
        state.selectedPlanId = planId;
        const plan = state.plans.find((item) => item.id === planId);
        if (!plan) {
            return;
        }
        // Bỏ lớp ẩn TRƯỚC khi dựng bản đồ: Leaflet đo kích thước khung lúc khởi tạo, dựng
        // trên khung còn ẩn thì bản đồ ra méo.
        el("vt-detail-empty").classList.add("is-hidden");
        el("vt-detail").classList.remove("is-hidden");
        window.VtSaleMap.open(state.config);
        window.VtSaleMap.update(state.vehicles);
        window.VtSaleMap.showPlaces(state.places);
        renderDetail(true);
        markSelectedCard();
    }

    function hideDetail() {
        state.selectedPlanId = null;
        window.VtSaleMap.clearRoute();
        el("vt-detail").classList.add("is-hidden");
        el("vt-detail-empty").classList.remove("is-hidden");
        el("vt-detail-panel").innerHTML = "";
        markSelectedCard();
    }

    /* Đổi viền thẻ đang chọn mà KHÔNG vẽ lại cả danh sách: vẽ lại làm mất vị trí cuộn của
       người đang xem chuyến thứ năm. */
    function markSelectedCard() {
        for (const card of document.querySelectorAll("[data-vt-select]")) {
            card.classList.toggle("is-selected",
                                  Number(card.dataset.vtSelect) === state.selectedPlanId);
        }
    }

    function renderUnplanned(orders, mineConfigured) {
        el("vt-unplanned-count").textContent = orders.length;
        el("vt-kpi-unplanned").textContent = orders.length;
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
                renderFleet(data.vehicles);
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

    // -------------------------------------------------------- xem chứng từ

    function openDocument(kind, recordId) {
        const body = el("vt-doc-body");
        body.innerHTML = '<div class="vt-empty">Đang tải…</div>';
        bootstrap.Modal.getOrCreateInstance(el("vt-doc-modal")).show();
        rpc("/giao-hang/chung-tu", { kind: kind, id: recordId })
            .then((doc) => {
                if (doc.error) {
                    body.innerHTML = `<div class="vt-alert">${escapeHtml(doc.error)}</div>`;
                    return;
                }
                el("vt-doc-title").textContent = doc.title;
                body.innerHTML = doc.kind === "order" ? orderHtml(doc) : pickingHtml(doc);
            })
            .catch((error) => {
                body.innerHTML = `<div class="vt-alert">${escapeHtml(error.message)}</div>`;
            });
    }

    function factRow(label, value) {
        return value ? `<div class="vt-fact"><span>${label}</span><b>${escapeHtml(value)}</b></div>` : "";
    }

    function money(value) {
        return (value || 0).toLocaleString("vi-VN") + " đ";
    }

    function linesTable(lines, columns) {
        if (!lines.length) {
            return '<div class="vt-empty">Không có dòng hàng.</div>';
        }
        const rows = lines.map((line) => `
            <tr>
                <td>${escapeHtml(line.product)}</td>
                <td class="text-end">${line.qty_ordered}</td>
                <td class="text-end">${line.qty_delivered}</td>
                <td>${escapeHtml(line.uom || "")}</td>
            </tr>`).join("");
        return `<table class="vt-table">
                    <thead><tr><th>Hàng</th><th class="text-end">${columns[0]}</th>
                    <th class="text-end">${columns[1]}</th><th>ĐVT</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>`;
    }

    function orderHtml(doc) {
        const pickings = doc.pickings.length
            ? doc.pickings.map((picking) => `
                <button type="button" class="vt-doc" data-vt-doc="picking" data-vt-doc-id="${picking.id}">
                    ${escapeHtml(picking.name)} · ${escapeHtml(picking.state_label)}
                </button>`).join("")
            : '<span class="vt-muted">Chưa có phiếu kho nào.</span>';
        return `
            <div class="vt-facts">
                ${factRow("Khách", doc.partner_name)}
                ${factRow("Trạng thái", doc.state_label)}
                ${factRow("Ngày hẹn giao", (doc.commitment_date || "").slice(0, 10))}
                ${factRow("Mã sale", doc.saler_code)}
                ${factRow("Tiền hàng", money(doc.amount_total))}
                ${factRow("Địa chỉ giao", doc.address)}
            </div>
            ${linesTable(doc.lines, ["Đặt", "Đã giao"])}
            <div class="vt-doc-links"><span class="vt-muted">Phiếu kho:</span> ${pickings}</div>`;
    }

    function pickingHtml(doc) {
        const order = doc.sale_order_id
            ? `<button type="button" class="vt-doc" data-vt-doc="order" data-vt-doc-id="${doc.sale_order_id}">
                   ${escapeHtml(doc.sale_order_name)}</button>`
            : '<span class="vt-muted">Không rõ đơn</span>';
        return `
            <div class="vt-facts">
                ${factRow("Khách", doc.partner_name)}
                ${factRow("Trạng thái", doc.state_label)}
                ${factRow("Dự kiến", (doc.scheduled_date || "").slice(0, 16))}
                ${factRow("Hoàn tất lúc", (doc.date_done || "").slice(0, 16))}
                ${factRow("Nguồn", doc.origin)}
                ${factRow("Địa chỉ giao", doc.address)}
            </div>
            ${linesTable(doc.lines, ["Yêu cầu", "Đã lấy"])}
            <div class="vt-doc-links"><span class="vt-muted">Đơn bán:</span> ${order}</div>`;
    }

    // ------------------------------------------------------------- sự kiện

    document.addEventListener("click", (event) => {
        const orderButton = event.target.closest("[data-vt-order]");
        if (orderButton) {
            openRequest(Number(orderButton.dataset.vtOrder), orderButton.dataset.vtOrderName);
            return;
        }
        const doc = event.target.closest("[data-vt-doc]");
        if (doc) {
            openDocument(doc.dataset.vtDoc, Number(doc.dataset.vtDocId));
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
            // Vẽ lại chứ không bật/tắt: nút này để CĂN LẠI khung nhìn về toàn tuyến sau khi
            // người dùng đã phóng to xem một điểm.
            const plan = state.plans.find((item) => item.id === Number(routeButton.dataset.vtRoute));
            if (plan) {
                window.VtSaleMap.showRoute(plan);
            }
            return;
        }
        if (event.target.closest("[data-vt-unselect]")) {
            hideDetail();
            return;
        }
        const dayButton = event.target.closest("[data-vt-day]");
        if (dayButton) {
            shiftDate(Number(dayButton.dataset.vtDay));
            return;
        }
        const card = event.target.closest("[data-vt-select]");
        if (card) {
            const planId = Number(card.dataset.vtSelect);
            // Bấm lại chuyến đang xem thì đóng: đó là cách tắt bản đồ nhanh nhất, khỏi phải
            // với tay lên nút ✕.
            if (planId === state.selectedPlanId) {
                hideDetail();
            } else {
                showDetail(planId);
            }
        }
    });

    /* Bàn phím: thẻ chuyến là role="button" nên Enter/Space phải chọn được như chuột. */
    document.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") {
            return;
        }
        const card = event.target.closest && event.target.closest("[data-vt-select]");
        if (card) {
            event.preventDefault();
            showDetail(Number(card.dataset.vtSelect));
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
            hideDetail();
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
