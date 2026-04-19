/**
 * HLV Mobile Barcode App - Multi-Screen State Machine
 * Main application controller for screen transitions and logic
 */

(function () {
    "use strict";

    // ===== APP STATE =====
    const app = {
        currentScreen: "login",
        currentWorkflow: null,
        auth: { db: "", username: "", password: "" },
        authToken: null,
        currentSlip: { id: null, type: null, details: null },
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

    // ===== SCREEN TRANSITIONS =====
    function toLogin() {
        show("login-screen");
        app.currentScreen = "login";
        byId("hlv_password").focus();
    }

    function toWorkflow() {
        show("workflow-screen");
        app.currentScreen = "workflow";
    }

    function toSlipScan() {
        show("slip-scan-screen");
        app.currentScreen = "slip";
        byId("hlv_slip_scan_input").focus();
        updateSlipTitle();
        clearSlipPreview();
    }

    function toDetailScan() {
        show("detail-scan-screen");
        app.currentScreen = "detail";
        byId("hlv_detail_scan_input").focus();
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

    // ===== LOGIN LOGIC =====
    byId("hlv_btn_login").addEventListener("click", async function () {
        const db = byId("hlv_db").value.trim();
        const username = byId("hlv_login").value.trim();
        const password = byId("hlv_password").value;

        if (!db || !username || !password) {
            showLoginError("Vui lòng nhập đầy đủ thông tin");
            return;
        }

        try {
            // Call JSON-RPC authenticate
            const response = await callRPC("common", "authenticate", [db, username, password, {}]);
            
            if (!response) {
                showLoginError("Đăng nhập thất bại");
                return;
            }

            app.auth = { db, username, password };
            app.authToken = response.user_id;
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

    // ===== WORKFLOW SELECTION =====
    document.querySelectorAll(".hlv-workflow-card").forEach(card => {
        card.addEventListener("click", function () {
            const workflow = this.dataset.workflow;
            app.currentWorkflow = workflow;
            beep(true);
            toSlipScan();
        });
    });

    // ===== SLIP SCAN LOGIC =====
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
            // Call API to get slip details
            const slip = await callRPC("hlv_mobile_barcode_lite", "get_slip_details", [
                app.auth.db,
                app.currentWorkflow,
                slipId
            ]);

            if (!slip) {
                beep(false);
                showSlipError("Không tìm thấy phiếu: " + slipId);
                return;
            }

            app.currentSlip = {
                id: slip.id || slipId,
                type: app.currentWorkflow,
                details: slip
            };
            app.slipLineItems = slip.line_items || [];

            displaySlipPreview(slip);
            beep(true);
        } catch (error) {
            beep(false);
            showSlipError("Lỗi: " + error.message);
        }
    });

    function displaySlipPreview(slip) {
        byId("hlv_slip_id_display").textContent = slip.id || app.currentSlip.id;
        byId("hlv_slip_status_display").textContent = slip.state || "pending";
        byId("hlv_slip_item_count").textContent = (slip.line_items || []).length;
        byId("hlv_slip_preview").style.display = "block";
    }

    function showSlipError(msg) {
        // Could show a toast or alert - for now, just log
        alert(msg);
    }

    byId("hlv_btn_continue_detail").addEventListener("click", function () {
        app.stageState = {};
        toDetailScan();
    });

    byId("hlv_btn_back_slip").addEventListener("click", toWorkflow);

    // ===== DETAIL SCAN LOGIC =====
    function updateDetailHeader() {
        byId("hlv_detail_title").textContent = `Quét Chi Tiết - ${app.currentSlip.id}`;
        byId("hlv_detail_required").textContent = app.slipLineItems.length;
        updateDetailProgress();
    }

    function updateDetailProgress() {
        byId("hlv_detail_scanned").textContent = Object.keys(app.stageState).length;
    }

    byId("hlv_btn_detail_scan").addEventListener("click", async function () {
        const barcode = byId("hlv_detail_scan_input").value.trim();
        if (!barcode) {
            beep(false);
            return;
        }

        try {
            // Look up product by barcode
            const product = await callRPC("hlv_mobile_barcode_lite", "get_product_by_scan", [
                app.auth.db,
                barcode
            ]);

            if (!product) {
                beep(false);
                return;
            }

            // Add/increment to staging
            upsertStageProduct(product);
            byId("hlv_detail_scan_input").value = "";
            byId("hlv_detail_scan_input").focus();
            updateDetailProgress();
            renderDetailCards();
            beep(true);
        } catch (error) {
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

    // ===== CONFIRM LOGIC =====
    function renderConfirmScreen() {
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
        const items = Object.values(app.stageState).map(item => ({
            product_id: item.product_id,
            qty_done: item.qty_done
        }));
        return { slip_id: app.currentSlip.id, items };
    }

    byId("hlv_btn_submit_confirm").addEventListener("click", async function () {
        try {
            const payload = buildPayload();
            const result = await callRPC("hlv_mobile_barcode_lite", "submit_operation", [
                app.auth.db,
                app.currentWorkflow,
                payload
            ]);

            if (result.success) {
                toResult(true, "✓ Thành Công!");
            } else {
                showConfirmError("Lỗi: " + (result.message || "Thao tác thất bại"));
            }
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

    // ===== RESULT LOGIC =====
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

    // ===== JSON-RPC CALLS =====
    async function callRPC(model, method, params) {
        const payload = {
            jsonrpc: "2.0",
            method: "call",
            params: {
                service: "object",
                method: "execute",
                args: [app.auth.db, app.authToken, model, method, ...params]
            },
            id: Math.random()
        };

        const response = await fetch("/jsonrpc", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const data = await response.json();
        if (data.error) {
            throw new Error(data.error.data.message || "RPC Error");
        }
        return data.result;
    }

    // ===== INIT =====
    document.addEventListener("DOMContentLoaded", function () {
        toLogin();
    });

})();
