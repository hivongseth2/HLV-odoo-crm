(function () {
    "use strict";

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
            });
        });
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
                    } else {
                        throw new Error("Unsupported action: " + action);
                    }
                    printOutput(result);
                } catch (error) {
                    printOutput({ status: "error", message: error.message || String(error) });
                }
            });
        });

        byId("hlv_clear_output").addEventListener("click", () => {
            printOutput("Ready.");
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        initTabs();
        bindActions();
    });
})();
