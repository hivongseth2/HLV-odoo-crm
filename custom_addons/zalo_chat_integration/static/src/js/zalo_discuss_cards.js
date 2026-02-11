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

    // Handle escaped quotes inside attribute if double encoded
    json = json.replace(/\\"/g, '"').replace(/\"/g, '"');

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

    items.forEach((it) => {
        const card = document.createElement('div');
        card.className = 'zalo-assistant-card';

        card.style.cursor = 'pointer';
        card.title = 'Click để kiểm tra tồn kho';
        card.onclick = (e) => {
            e.stopPropagation();
            // Prefer name for query as it's more natural for the search method
            const query = it.name || it.code || '';
            const event = new CustomEvent('zalo-card-click', {
                bubbles: true,
                detail: { query: query }
            });
            card.dispatchEvent(event);
            console.log("Zalo Card clicked, dispatching event:", query);
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

            // Listen for custom event from cards
            root.addEventListener('zalo-card-click', async (ev) => {
                const productQuery = ev.detail ? ev.detail.query : null;
                if (!productQuery) return;

                console.log("Caught zalo-card-click event:", productQuery);

                // Get thread from message props
                const message = this.props.message;
                // Support both Odoo 17/18 structures where thread might be direct or originThread
                const thread = message.thread || message.originThread;

                if (!thread || (thread.model !== 'discuss.channel')) {
                    // Only work in discuss channels
                    return;
                }

                try {
                    notification.add("Đang kiểm tra tồn kho: " + productQuery, { type: "info" });
                    await orm.call("discuss.channel", "action_check_stock_item", [[thread.id], productQuery]);
                } catch (e) {
                    console.error("Stock check error invoked from specific card:", e);
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
