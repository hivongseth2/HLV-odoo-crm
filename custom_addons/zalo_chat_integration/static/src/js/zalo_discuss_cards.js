/** @odoo-module */

import { onMounted } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { Message } from "@mail/core/common/message";
import { useService } from "@web/core/utils/hooks";

function decodeHtml(str) {
    const txt = document.createElement('textarea');
    txt.innerHTML = str;
    return txt.value;
}

function renderCard(el) {
    const dataEl = el.querySelector('.zalo-assistant-data');
    if (!dataEl) return;

    // Get text content (which should be the escaped JSON string)
    let json = dataEl.textContent || '';

    // Decode HTML entities if needed (e.g. &quot; -> ")
    json = decodeHtml(json);

    // If it's wrapped in quotes, remove them
    if (json.startsWith('"') && json.endsWith('"')) {
        json = json.substring(1, json.length - 1);
    }

    let data;
    try {
        data = JSON.parse(json);
    } catch (e) {
        console.error("Zalo Card JSON Parse Error", e, json);
        return;
    }
    const items = data.items || [];
    const phase = data.phase || '';

    const container = document.createElement('div');
    container.className = 'zalo-assistant-card-container';

    if (phase) {
        const p = document.createElement('div');
        p.className = 'zalo-assistant-phase';
        p.innerText = `⏱ Giai đoạn: ${phase}`;
        container.appendChild(p);
    }

    // STATE: Track selected items
    const selectedQueries = new Set();
    const actionArea = document.createElement('div');
    actionArea.className = 'zalo-assistant-actions';
    actionArea.style.display = 'none';

    const btnCheck = document.createElement('button');
    btnCheck.className = 'zalo-btn-check-stock';
    btnCheck.innerHTML = '<i class="fa fa-cubes"></i> Kiểm tra tồn';
    btnCheck.onclick = (e) => {
        e.stopPropagation();
        if (selectedQueries.size === 0) return;

        const queries = Array.from(selectedQueries);
        const event = new CustomEvent('zalo-card-check-batch', {
            bubbles: true,
            detail: { queries: queries }
        });
        container.dispatchEvent(event);
        console.log("Zalo Batch Check clicked:", queries);
    };
    actionArea.appendChild(btnCheck);

    const updateUI = () => {
        if (selectedQueries.size > 0) {
            actionArea.style.display = 'block';
            btnCheck.innerHTML = `<i class="fa fa-cubes"></i> Kiểm tra tồn (${selectedQueries.size})`;
        } else {
            actionArea.style.display = 'none';
        }
    };

    items.forEach((it) => {
        const card = document.createElement('div');
        card.className = 'zalo-assistant-card';
        card.style.cursor = 'pointer';
        card.title = 'Click để chọn kiểm tra tồn kho';

        const query = it.name || it.code || '';

        card.onclick = (e) => {
            e.stopPropagation();

            // Toggle selection
            if (selectedQueries.has(query)) {
                selectedQueries.delete(query);
                card.classList.remove('selected');
            } else {
                selectedQueries.add(query);
                card.classList.add('selected');
            }

            updateUI();
        };

        const title = document.createElement('div');
        title.className = 'title';
        title.innerText = it.name || '';
        const meta = document.createElement('div');
        meta.className = 'meta';
        meta.innerText = `${it.code || ''} | Giá: ${it.price || '-'} | ĐVT: ${it.unit || ''}`;
        const stock = document.createElement('div');
        stock.className = 'stock';
        stock.innerHTML = it.stock || ''; // Allow HTML for stock (e.g. <b> or span)

        card.appendChild(title);
        card.appendChild(meta);
        card.appendChild(stock);
        container.appendChild(card);
    });

    container.appendChild(actionArea);
    el.replaceWith(container);
}

function unwrapRawHtml(root) {
    // If message body is escaped and shown as raw text, convert it back to HTML
    // Selectors for message body in Odoo 17/18
    const candidates = root.querySelectorAll('.o-mail-Message-body, .o-mail-Message-content, .o_mail_message_body');
    candidates.forEach((el) => {
        const text = el.textContent || '';
        // Check if it looks like our card HTML was escaped
        if (text.includes("zalo-assistant-card") && (text.includes("<div") || text.includes("&lt;div"))) {
            // Check if it really is escaped (contains tag-like text)
            // If text content has '<', render it as HTML
            if (text.indexOf('<') !== -1) {
                el.innerHTML = text;
            }
        }
    });
}

function processCards(root) {
    // First try to unwrap any escaped HTML
    unwrapRawHtml(root);
    // Then find any cards (now rendered as HTML nodes)
    const nodes = root.querySelectorAll('.zalo-assistant-card');
    nodes.forEach((el) => renderCard(el));
}

patch(Message.prototype, {
    setup() {
        super.setup();
        const orm = useService("orm");
        const notification = useService("notification");

        onMounted(() => {
            const root = this.el;
            if (!root) return;

            // Listen for card click (Legacy single click - deprecated or kept for compat?)
            // We replaced click with selection toggle, so only listen for batch event now.

            // Listen for BATCH check event
            root.addEventListener('zalo-card-check-batch', async (ev) => {
                const queries = ev.detail ? ev.detail.queries : [];
                if (!queries || queries.length === 0) return;

                console.log("Caught zalo-card-check-batch event:", queries);

                // Get thread from message props
                const message = this.props.message;
                const thread = message.thread || message.originThread;

                if (!thread || (thread.model !== 'discuss.channel')) {
                    return;
                }

                try {
                    notification.add(`Đang kiểm tra tồn kho ${queries.length} sản phẩm...`, { type: "info" });
                    await orm.call("discuss.channel", "action_check_stock_items", [[thread.id], queries]);
                } catch (e) {
                    console.error("Batch stock check error:", e);
                    notification.add("Lỗi kiểm tra tồn: " + e.message, { type: "danger" });
                }
            });

            processCards(root);
        });
    },
});

// Fallback: observe for dynamically inserted messages
const observer = new MutationObserver((mutations) => {
    mutations.forEach((m) => {
        m.addedNodes.forEach((node) => {
            if (node.nodeType === 1) {
                processCards(node);
            }
        });
    });
});

// Ensure observer runs on document body
window.addEventListener('load', () => {
    // Use a slight delay or just observe body
    observer.observe(document.body, { childList: true, subtree: true });
});
