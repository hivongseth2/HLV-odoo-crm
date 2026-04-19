(function () {
    "use strict";

    const stageState = {
        picking: {},
        receiving: {},
    };

    let lastScanValue = "";

    function byId(id) {
        return document.getElementById(id);
    }

    function getCredentials() {
        return {
            db: (byId("hlv_db").value || "").trim(),
            login: (byId("hlv_login").value || "").trim(),
            password: byId("hlv_password").value || "",
            mode: (byId("hlv_mode").value || "").trim(),
        };
    }

    function parseJsonInput(elementId, fallback) {
        const raw = (byId(elementId).value || "").trim();
        if (!raw) {
            return fallback;
        }
        return JSON.parse(raw);
    }

    function printOutput(payload) {
        byId("hlv_output").textContent = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
    }

    function printStage() {
        const active = getActiveTab();
        const data = active === "receiving" ? stageState.receiving : stageState.picking;
        byId("hlv_stage_preview").textContent = JSON.stringify(data, null, 2);
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
            osc.stop(ctx.currentTime + 0.08);
        } catch (err) {
            err.toString();
        }
    }

    async function callEndpoint(path, inputs) {
        const creds = getCredentials();
        if (!creds.db || !creds.login || !creds.password) {
            throw new Error("Vui long nhap du DB, Login, Password.");
        }

        const params = {
            db: creds.db,
            login: creds.login,
            password: creds.password,
            inputs: inputs || {},
        };

        if (creds.mode) {
            params.mode = creds.mode;
        }

        const response = await fetch(path, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                jsonrpc: "2.0",
                method: "call",
                params: params,
                id: Date.now(),
            }),
        });

        const body = await response.json();
        if (body.error) {
            throw new Error(body.error.message || "JSON-RPC failed");
        }
        return body.result;
    }

    function initTabs() {
        const tabWrap = byId("hlv_tabs");
        const tabButtons = tabWrap.querySelectorAll("button");
        const panels = document.querySelectorAll(".hlv-panel");

        tabButtons.forEach((button) => {
            button.addEventListener("click", () => {
                const tab = button.dataset.tab;
                tabButtons.forEach((btn) => btn.classList.remove("active"));
                button.classList.add("active");
                panels.forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === tab));
                updateScanHint();
                printStage();
                byId("hlv_scan_input").focus();
            });
        });
    }

    function getActiveTab() {
        const active = document.querySelector("#hlv_tabs button.active");
        return active ? active.dataset.tab : "picking";
    }

    function updateScanHint() {
        const tab = getActiveTab();
        let hint = "";
        if (tab === "picking") {
            hint = "Che do Lay hang: quet SO ID truoc, tiep theo quet barcode san pham de tang qty.";
        } else if (tab === "receiving") {
            hint = "Che do Nhan hang: quet PO ID truoc, tiep theo quet barcode san pham de tang qty.";
        } else if (tab === "transfer") {
            hint = "Che do Chuyen kho: quet location id cho source/destination, roi quet barcode vao line_items.";
        } else if (tab === "product_locator") {
            hint = "Che do Vi tri SP: quet barcode san pham hoac ma vi tri de tra cuu nhanh.";
        } else {
            hint = "Che do Quet kien: quet SO ID roi quet ma shipment de xem noi dung.";
        }
        byId("hlv_scan_hint").textContent = hint;
    }

    function updateLastScan(code) {
        lastScanValue = code;
        byId("hlv_scan_last").textContent = "Last scan: " + code;
    }

    function upsertStageLine(type, product) {
        const key = String(product.id);
        if (!stageState[type][key]) {
            stageState[type][key] = {
                product_id: product.id,
                product_code: product.barcode || "",
                product_name: product.name || "",
                qty_done: 0,
            };
        }
        stageState[type][key].qty_done += 1;
    }

    function rebuildPayloadFromStage(type) {
        const lines = Object.values(stageState[type]);
        const payload = [{ normal: lines.map((x) => ({ product_id: x.product_id, qty_done: x.qty_done, expiry_date: "" })) }];
        if (type === "picking") {
            byId("hlv_picking_lines").value = JSON.stringify(payload);
        } else {
            byId("hlv_receiving_lines").value = JSON.stringify(payload);
        }
        printStage();
    }

    function appendTransferLineFromScan(barcode) {
        const lines = parseJsonInput("hlv_transfer_lines", []);
        lines.push({
            product_code: barcode,
            lot_or_serial: "none",
            lot_serial: "",
            quantity: 1,
            note: "",
        });
        byId("hlv_transfer_lines").value = JSON.stringify(lines);
        byId("hlv_stage_preview").textContent = JSON.stringify(lines, null, 2);
    }

    async function onScan(code) {
        const normalized = (code || "").trim();
        if (!normalized) {
            return;
        }
        updateLastScan(normalized);

        const tab = getActiveTab();
        try {
            if (tab === "picking") {
                if (!byId("hlv_so_id").value && /^\d+$/.test(normalized)) {
                    byId("hlv_so_id").value = normalized;
                    const data = await callEndpoint("/api/v1/list-line-items-by-sale-order", { so_id: Number(normalized) });
                    printOutput(data);
                } else {
                    const products = await callEndpoint("/api/v1/get-product-by-scan", { product_codes: [normalized] });
                    if (!Array.isArray(products) || products.length === 0) {
                        throw new Error("Khong tim thay san pham theo barcode vua quet.");
                    }
                    upsertStageLine("picking", products[0]);
                    rebuildPayloadFromStage("picking");
                }
            } else if (tab === "receiving") {
                if (!byId("hlv_po_id").value && /^\d+$/.test(normalized)) {
                    byId("hlv_po_id").value = normalized;
                    const data = await callEndpoint("/api/v1/list-line-items-by-purchase-order", { po_id: Number(normalized) });
                    printOutput(data);
                } else {
                    const products = await callEndpoint("/api/v1/get-product-by-scan", { product_codes: [normalized] });
                    if (!Array.isArray(products) || products.length === 0) {
                        throw new Error("Khong tim thay san pham theo barcode vua quet.");
                    }
                    upsertStageLine("receiving", products[0]);
                    rebuildPayloadFromStage("receiving");
                }
            } else if (tab === "transfer") {
                appendTransferLineFromScan(normalized);
            } else if (tab === "product_locator") {
                const data = await callEndpoint("/api/v1/get-product-by-scan", { product_codes: [normalized] });
                printOutput(data);
                byId("hlv_inventory_product_code").value = normalized;
            } else if (tab === "shipment_scan") {
                if (!byId("hlv_shipment_so_id").value && /^\d+$/.test(normalized)) {
                    byId("hlv_shipment_so_id").value = normalized;
                } else {
                    byId("hlv_shipment_name").value = normalized;
                    const soId = Number(byId("hlv_shipment_so_id").value || 0);
                    if (soId > 0) {
                        const data = await callEndpoint("/api/v1/list-sales-order-shipments", {
                            so_id: soId,
                            shipment_name: normalized,
                            limit: 20,
                            page: 1,
                        });
                        printOutput(data);
                    }
                }
            }
            beep(true);
        } catch (error) {
            printOutput({ status: "error", message: error.message || String(error) });
            beep(false);
        } finally {
            byId("hlv_scan_input").value = "";
            byId("hlv_scan_input").focus();
        }
    }

    function bindActions() {
        document.querySelectorAll("[data-action]").forEach((button) => {
            button.addEventListener("click", async () => {
                const action = button.dataset.action;
                printOutput("Loading...");
                try {
                    let result;
                    if (action === "listSaleOrders") {
                        result = await callEndpoint("/api/v1/list-sale-orders", { limit: 20, page: 1 });
                    } else if (action === "listSaleLines") {
                        result = await callEndpoint("/api/v1/list-line-items-by-sale-order", {
                            so_id: Number(byId("hlv_so_id").value || 0),
                        });
                    } else if (action === "doPicking") {
                        result = await callEndpoint("/api/v1/picking-by-sale-order", {
                            so_id: Number(byId("hlv_so_id").value || 0),
                            line_items: parseJsonInput("hlv_picking_lines", []),
                        });
                    } else if (action === "listPurchaseOrders") {
                        result = await callEndpoint("/api/v1/list-purchase-orders", { limit: 20, page: 1 });
                    } else if (action === "listPurchaseLines") {
                        result = await callEndpoint("/api/v1/list-line-items-by-purchase-order", {
                            po_id: Number(byId("hlv_po_id").value || 0),
                        });
                    } else if (action === "doReceiving") {
                        result = await callEndpoint("/api/v1/receiving-by-purchase-order", {
                            po_id: Number(byId("hlv_po_id").value || 0),
                            line_items: parseJsonInput("hlv_receiving_lines", []),
                        });
                    } else if (action === "doTransfer") {
                        result = await callEndpoint("/api/v1/internal-transfer", {
                            src_wh_name: (byId("hlv_src_wh_name").value || "").trim(),
                            dst_wh_name: (byId("hlv_dst_wh_name").value || "").trim(),
                            source: Number(byId("hlv_transfer_source").value || 0),
                            destination: Number(byId("hlv_transfer_destination").value || 0),
                            line_items: parseJsonInput("hlv_transfer_lines", []),
                        });
                    } else if (action === "scanProducts") {
                        const productCodes = (byId("hlv_product_codes").value || "")
                            .split(",")
                            .map((x) => x.trim())
                            .filter(Boolean);
                        result = await callEndpoint("/api/v1/get-product-by-scan", { product_codes: productCodes });
                    } else if (action === "inventoryByLocation") {
                        result = await callEndpoint("/api/v1/item-inventory-by-locations", {
                            product_code: (byId("hlv_inventory_product_code").value || "").trim(),
                            location_name: (byId("hlv_inventory_location_name").value || "").trim(),
                            limit: 50,
                            offset: 0,
                        });
                    } else if (action === "scanLocation") {
                        result = await callEndpoint("/api/v1/get-location-by-scan", {
                            location_barcode: (byId("hlv_location_barcode").value || "").trim(),
                            wh_name: (byId("hlv_location_wh_name").value || "").trim(),
                        });
                    } else if (action === "listShipments") {
                        result = await callEndpoint("/api/v1/list-sales-order-shipments", {
                            so_id: Number(byId("hlv_shipment_so_id").value || 0),
                            shipment_name: (byId("hlv_shipment_name").value || "").trim(),
                            limit: 20,
                            page: 1,
                        });
                    } else if (action === "finderSearch") {
                        result = await callEndpoint("/api/v1/finder-search", parseJsonInput("hlv_finder_payload", {}));
                    } else if (action === "resetPickingStage") {
                        stageState.picking = {};
                        byId("hlv_picking_lines").value = "[]";
                        result = { message: "Picking staging reset." };
                    } else if (action === "resetReceivingStage") {
                        stageState.receiving = {};
                        byId("hlv_receiving_lines").value = "[]";
                        result = { message: "Receiving staging reset." };
                    } else if (action === "setSourceFromScan") {
                        byId("hlv_transfer_source").value = lastScanValue;
                        result = { message: "Source set from last scan." };
                    } else if (action === "setDestinationFromScan") {
                        byId("hlv_transfer_destination").value = lastScanValue;
                        result = { message: "Destination set from last scan." };
                    } else {
                        throw new Error("Unsupported action: " + action);
                    }
                    printOutput(result);
                    printStage();
                } catch (error) {
                    printOutput({ status: "error", message: error.message || String(error) });
                }
            });
        });

        byId("hlv_clear_output").addEventListener("click", () => {
            printOutput("Ready.");
        });

        byId("hlv_clear_stage").addEventListener("click", () => {
            stageState.picking = {};
            stageState.receiving = {};
            byId("hlv_stage_preview").textContent = "{}";
            byId("hlv_picking_lines").value = "[]";
            byId("hlv_receiving_lines").value = "[]";
        });

        byId("hlv_scan_btn").addEventListener("click", () => onScan(byId("hlv_scan_input").value));
        byId("hlv_scan_input").addEventListener("keypress", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                onScan(byId("hlv_scan_input").value);
            }
        });

        document.addEventListener("click", (event) => {
            const target = event.target;
            if (target && target.id !== "hlv_scan_input") {
                setTimeout(() => byId("hlv_scan_input").focus(), 40);
            }
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        initTabs();
        bindActions();
        updateScanHint();
        printStage();
        byId("hlv_scan_input").focus();
    });
})();
