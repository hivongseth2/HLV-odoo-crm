/**
 * HLV Mobile Barcode App - Multi-Screen State Machine
 * Main application controller for screen transitions and logic
 */

 (function () {
    "use strict";

    const app = {
        currentScreen: "login",
        currentWorkflow: null,
        auth: { db: "", login: "", password: "", mode: "prod" },
        currentSlip: { id: "", type: "", details: null },
        stageState: {},
        slipLineItems: [],
        apiResponse: null,
    };

    // ===== ELEMENT SHORTCUTS =====
    function byId(id) {
        return document.getElementById(id);
    }

    function show(screenId) {
        document.querySelectorAll(".hlv-screen").forEach(s => s.classList.remove("hlv-screen-active"));
        const screen = byId(screenId);
        if (screen) {
            screen.classList.add("hlv-screen-active");
        }
    }

    function toLogin() {
        show("login-screen");
        app.currentScreen = "login";
        const passwordInput = byId("hlv_password");
        if (passwordInput) {
            passwordInput.focus();
        }
    }

    function toWorkflow() {
        show("workflow-screen");
        app.currentScreen = "workflow";
    }

    function toSlipScan() {
        show("slip-scan-screen");
        app.currentScreen = "slip";
        const slipInput = byId("hlv_slip_scan_input");
        if (slipInput) {
            slipInput.focus();
        }
        updateSlipTitle();
        clearSlipPreview();
    }

    function toDetailScan() {
        show("detail-scan-screen");
        app.currentScreen = "detail";
        const detailInput = byId("hlv_detail_scan_input");
        if (detailInput) {
            detailInput.focus();
        }
        updateDetailHeader();
        renderDetailCards();
    }

    function toConfirm() {
        show("confirm-screen");
        app.currentScreen = "confirm";
        renderConfirmScreen();
    }

    function toResult(success = true, message = "Thành Công!") {
        show("result-screen");
        app.currentScreen = "result";
        byId("hlv_result_icon").textContent = success ? "✓" : "✗";
        byId("hlv_result_icon").style.color = success ? "#10b981" : "#ef4444";
        byId("hlv_result_title").textContent = message;
    }

    byId("hlv_btn_login").addEventListener("click", async function () {
        const db = byId("hlv_db").value.trim();
        const login = byId("hlv_login").value.trim();
        const password = byId("hlv_password").value;

        if (!db || !login || !password) {
            showLoginError("Vui lòng nhập đầy đủ thông tin");
            return;
        }

        try {
            app.auth = { db, login, password, mode: "prod" };
            // Probe endpoint to validate credentials using middleware auth.
            await callEndpoint("/api/v1/list-sale-orders", { limit: 1, page: 1 });
            clearLoginError();
            toWorkflow();
        } catch (error) {
            showLoginError("Lỗi: " + error.message);
        }
    });

    function showLoginError(msg) {
        const errorDiv = byId("hlv_login_error");
        errorDiv.textContent = msg;
        errorDiv.style.display = "block";
    }

    function clearLoginError() {
        byId("hlv_login_error").style.display = "none";
    }

    byId("hlv_btn_back_workflow").addEventListener("click", toLogin);

    document.querySelectorAll(".hlv-workflow-card").forEach(card => {
        card.addEventListener("click", function () {
            const workflow = this.dataset.workflow;
            app.currentWorkflow = workflow;
            app.currentSlip = { id: "", type: workflow, details: null };
            app.slipLineItems = [];
            app.stageState = {};
            beep(true);
            toSlipScan();
        });
    });

    function updateSlipTitle() {
        const titles = {
            picking: "Quét Phiếu Xuất",
            receiving: "Quét Phiếu Nhập",
            transfer: "Quét Lệnh Chuyển",
            product_locator: "Quét Sản Phẩm",
            shipment: "Quét Kiện",
        };
        byId("hlv_slip_title").textContent = titles[app.currentWorkflow] || "Quét Phiếu";
    }

    function clearSlipPreview() {
        byId("hlv_slip_preview").style.display = "none";
        byId("hlv_slip_scan_input").value = "";
    }

    byId("hlv_btn_slip_scan").addEventListener("click", async function () {
        const slipId = byId("hlv_slip_scan_input").value.trim();
        if (!slipId) {
            beep(false);
            return;
        }

        try {
            let data;
            if (app.currentWorkflow === "picking") {
                const soId = parsePositiveInt(slipId, "SO ID phải là số nguyên dương");
                data = await callEndpoint("/api/v1/list-line-items-by-sale-order", { so_id: soId });
            } else if (app.currentWorkflow === "receiving") {
                const poId = parsePositiveInt(slipId, "PO ID phải là số nguyên dương");
                data = await callEndpoint("/api/v1/list-line-items-by-purchase-order", { po_id: poId });
            } else if (app.currentWorkflow === "shipment") {
                const soId = parsePositiveInt(slipId, "SO ID phải là số nguyên dương");
                data = await callEndpoint("/api/v1/list-sales-order-shipments", {
                    so_id: soId,
                    shipment_name: "",
                    limit: 20,
                    page: 1,
                });
            } else {
                // transfer and product locator do not require fetching line-items by slip.
                data = [];
            }

            app.currentSlip = {
                id: slipId,
                type: app.currentWorkflow,
                details: data,
            };
            app.slipLineItems = Array.isArray(data) ? data : [];
            displaySlipPreview({
                id: slipId,
                state: "ready",
                line_items: app.slipLineItems,
            });
            beep(true);
        } catch (error) {
            beep(false);
            showSlipError(error.message || String(error));
        }
    });

    function displaySlipPreview(slip) {
        byId("hlv_slip_id_display").textContent = slip.id || app.currentSlip.id;
        byId("hlv_slip_status_display").textContent = slip.state || "pending";
        byId("hlv_slip_item_count").textContent = (slip.line_items || []).length;
        byId("hlv_slip_preview").style.display = "block";
    }

    function showSlipError(msg) {
        alert("Lỗi: " + msg);
    }

    byId("hlv_btn_continue_detail").addEventListener("click", function () {
        app.stageState = {};
        toDetailScan();
    });

    byId("hlv_btn_back_slip").addEventListener("click", toWorkflow);

    function updateDetailHeader() {
        byId("hlv_detail_title").textContent = `Quét Chi Tiết - ${app.currentSlip.id}`;
        byId("hlv_detail_required").textContent = app.slipLineItems.length;
        updateDetailProgress();
    }

    function updateDetailProgress() {
        const total = Object.values(app.stageState).reduce((sum, item) => sum + (item.qty_done || 0), 0);
        byId("hlv_detail_scanned").textContent = total;
    }

    byId("hlv_btn_detail_scan").addEventListener("click", async function () {
        const barcode = byId("hlv_detail_scan_input").value.trim();
        if (!barcode) {
            beep(false);
            return;
        }

        try {
            if (app.currentWorkflow === "transfer") {
                upsertTransferItem(barcode);
            } else if (app.currentWorkflow === "shipment") {
                upsertShipmentItem(barcode);
            } else {
                const products = await callEndpoint("/api/v1/get-product-by-scan", { product_codes: [barcode] });
                if (!Array.isArray(products) || products.length === 0) {
                    throw new Error("Không tìm thấy sản phẩm theo barcode vừa quét.");
                }
                upsertStageProduct(products[0]);
            }

            byId("hlv_detail_scan_input").value = "";
            byId("hlv_detail_scan_input").focus();
            updateDetailProgress();
            renderDetailCards();
            beep(true);
        } catch (error) {
            showConfirmError("Lỗi: " + (error.message || String(error)));
            beep(false);
        }
    });

    function upsertStageProduct(product) {
        const key = String(product.id);
        if (!app.stageState[key]) {
            app.stageState[key] = {
                product_id: product.id,
                product_code: product.barcode,
                product_name: product.name,
                qty_done: 0
            };
        }
        app.stageState[key].qty_done += 1;
    }

    function upsertTransferItem(barcode) {
        const key = `transfer:${barcode}`;
        if (!app.stageState[key]) {
            app.stageState[key] = {
                product_id: 0,
                product_code: barcode,
                product_name: `Transfer ${barcode}`,
                qty_done: 0,
            };
        }
        app.stageState[key].qty_done += 1;
    }

    function upsertShipmentItem(shipmentCode) {
        const key = `shipment:${shipmentCode}`;
        if (!app.stageState[key]) {
            app.stageState[key] = {
                product_id: 0,
                product_code: shipmentCode,
                product_name: `Shipment ${shipmentCode}`,
                qty_done: 0,
            };
        }
        app.stageState[key].qty_done += 1;
    }

    function renderDetailCards() {
        const container = byId("hlv_detail_cards");
        const cards = Object.values(app.stageState).map(item => {
            return `
                <div class="hlv-detail-card">
                    <div class="hlv-detail-card-info">
                        <div class="hlv-detail-card-name">${escapeHtml(item.product_name)}</div>
                        <div class="hlv-detail-card-sku">SKU: ${escapeHtml(item.product_code)}</div>
                    </div>
                    <div class="hlv-detail-card-qty">${item.qty_done}</div>
                    <button class="hlv-detail-card-delete" onclick="deleteStageItem('${item.product_id}')">Xoá</button>
                </div>
            `;
        });
        container.innerHTML = cards.join("");
    }

    window.deleteStageItem = function (productId) {
        delete app.stageState[productId];
        updateDetailProgress();
        renderDetailCards();
    };

    byId("hlv_btn_clear_staging").addEventListener("click", function () {
        app.stageState = {};
        updateDetailProgress();
        renderDetailCards();
    });

    byId("hlv_btn_confirm_detail").addEventListener("click", toConfirm);
    byId("hlv_btn_back_detail").addEventListener("click", toSlipScan);

    function renderConfirmScreen() {
        byId("hlv_confirm_error").style.display = "none";
        byId("hlv_confirm_slip_id").textContent = app.currentSlip.id;
        byId("hlv_confirm_workflow").textContent = getWorkflowName(app.currentWorkflow);
        byId("hlv_confirm_item_count").textContent = Object.keys(app.stageState).length;

        // Render scanned items
        const itemsContainer = byId("hlv_confirm_items");
        const items = Object.values(app.stageState).map(item => {
            return `
                <div class="hlv-confirm-item">
                    <span class="hlv-confirm-item-name">${escapeHtml(item.product_name)}</span>
                    <span class="hlv-confirm-item-qty">${item.qty_done}</span>
                </div>
            `;
        });
        itemsContainer.innerHTML = items.join("");

        // Build payload
        const payload = buildPayload();
        byId("hlv_confirm_payload").textContent = JSON.stringify(payload, null, 2);
    }

    function getWorkflowName(workflow) {
        const names = {
            picking: "Lấy Hàng",
            receiving: "Nhận Hàng",
            transfer: "Chuyển Kho",
            product_locator: "Vị Trí Sản Phẩm",
            shipment: "Quét Kiện"
        };
        return names[workflow] || workflow;
    }

    function buildPayload() {
        const values = Object.values(app.stageState);
        if (app.currentWorkflow === "picking") {
            return {
                so_id: parseInt(app.currentSlip.id, 10),
                line_items: [{
                    normal: values.map((item) => ({
                        product_id: item.product_id,
                        qty_done: item.qty_done,
                        expiry_date: "",
                    })),
                }],
            };
        }

        if (app.currentWorkflow === "receiving") {
            return {
                po_id: parseInt(app.currentSlip.id, 10),
                line_items: [{
                    normal: values.map((item) => ({
                        product_id: item.product_id,
                        qty_done: item.qty_done,
                        expiry_date: "",
                    })),
                }],
            };
        }

        if (app.currentWorkflow === "shipment") {
            return {
                so_id: parseInt(app.currentSlip.id, 10),
                shipment_name: values[0] ? values[0].product_code : "",
                limit: 20,
                page: 1,
            };
        }

        if (app.currentWorkflow === "transfer") {
            return {
                source: 0,
                destination: 0,
                line_items: values.map((item) => ({
                    product_code: item.product_code,
                    lot_or_serial: "none",
                    lot_serial: "",
                    quantity: item.qty_done,
                    note: "",
                })),
            };
        }

        return {
            product_codes: values.map((item) => item.product_code),
        };
    }

    byId("hlv_btn_submit_confirm").addEventListener("click", async function () {
        try {
            const payload = buildPayload();
            let result;
            if (app.currentWorkflow === "picking") {
                result = await callEndpoint("/api/v1/picking-by-sale-order", payload);
            } else if (app.currentWorkflow === "receiving") {
                result = await callEndpoint("/api/v1/receiving-by-purchase-order", payload);
            } else if (app.currentWorkflow === "shipment") {
                result = await callEndpoint("/api/v1/list-sales-order-shipments", payload);
            } else if (app.currentWorkflow === "product_locator") {
                result = await callEndpoint("/api/v1/get-product-by-scan", payload);
            } else {
                throw new Error("Màn hình chuyển kho cần thêm source/destination trước khi xác nhận.");
            }

            app.apiResponse = result;
            byId("hlv_result_msg").textContent = `Đã xử lý ${Object.keys(app.stageState).length} dòng quét.`;
            byId("hlv_result_details").textContent = JSON.stringify(result, null, 2);
            toResult(true, "Thành công");
        } catch (error) {
            showConfirmError("Lỗi: " + error.message);
        }
    });

    function showConfirmError(msg) {
        byId("hlv_confirm_error").textContent = msg;
        byId("hlv_confirm_error").style.display = "block";
    }

    byId("hlv_btn_cancel_confirm").addEventListener("click", toDetailScan);
    byId("hlv_btn_back_confirm").addEventListener("click", toDetailScan);

    byId("hlv_btn_scan_again").addEventListener("click", toWorkflow);
    byId("hlv_btn_logout").addEventListener("click", toLogin);

    // ===== UTILITIES =====
    function escapeHtml(text) {
        const map = {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#039;"
        };
        return String(text).replace(/[&<>"']/g, m => map[m]);
    }

    function beep(success) {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.type = "sine";
            osc.frequency.value = success ? 980 : 220;
            gain.gain.value = 0.06;
            osc.start();
            osc.stop(ctx.currentTime + 0.1);
        } catch (err) {
            // Fallback - some browsers may block AudioContext
        }
    }

    async function callEndpoint(path, inputs) {
        if (!app.auth.db || !app.auth.login || !app.auth.password) {
            throw new Error("Thiếu DB/Login/Password.");
        }

        const payload = {
            jsonrpc: "2.0",
            method: "call",
            params: {
                db: app.auth.db,
                login: app.auth.login,
                password: app.auth.password,
                mode: app.auth.mode,
                inputs: inputs || {},
            },
            id: Date.now(),
        };

        const response = await fetch(path, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        const data = await response.json();
        if (data.error) {
            throw new Error(data.error.data.message || "RPC Error");
        }

        const result = data.result || {};
        if (result.status === "error") {
            throw new Error(result.message || "Request failed");
        }
        return result.data;
    }

    function parsePositiveInt(raw, errorMessage) {
        const value = Number(raw);
        if (!Number.isInteger(value) || value <= 0) {
            throw new Error(errorMessage);
        }
        return value;
    }

    document.addEventListener("DOMContentLoaded", function () {
        toLogin();
    });

})();
