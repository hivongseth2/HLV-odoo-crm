/** @odoo-module */

import { onMounted } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { Message } from "@mail/core/common/message";

function renderCard(el) {
    const b64 = el.getAttribute('data-json-b64');
    if (!b64) return;
    let data;
    try {
        const json = atob(b64);
        data = JSON.parse(json);
    } catch (e) {
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
        const title = document.createElement('div');
        title.className = 'title';
        title.innerText = it.name || '';
        const meta = document.createElement('div');
        meta.className = 'meta';
        meta.innerText = `${it.code || ''} | Giá: ${it.price || '-'} | ĐVT: ${it.unit || ''}`;
        const stock = document.createElement('div');
        stock.className = 'stock';
        stock.innerText = it.stock || '';
        card.appendChild(title);
        card.appendChild(meta);
        card.appendChild(stock);
        container.appendChild(card);
    });

    el.replaceWith(container);
}

function unwrapRawHtml(root) {
    // If message body is escaped and shown as raw text, convert it back to HTML
    const candidates = root.querySelectorAll('.o-mail-Message-body, .o_mail_thread_message_content, .o_mail_message_content, .o-mail-Message-bodyText');
    candidates.forEach((el) => {
        const text = el.textContent || '';
        if (text.includes("zalo-assistant-card") && text.includes("data-json-b64")) {
            el.innerHTML = text;
        }
    });
}

function processCards(root) {
    unwrapRawHtml(root);
    const nodes = root.querySelectorAll('.zalo-assistant-card[data-json-b64]');
    nodes.forEach((el) => renderCard(el));
}

patch(Message.prototype, {
    setup() {
        super.setup();
        onMounted(() => {
            const root = this.el;
            if (!root) return;
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

window.addEventListener('DOMContentLoaded', () => {
    observer.observe(document.body, { childList: true, subtree: true });
});
