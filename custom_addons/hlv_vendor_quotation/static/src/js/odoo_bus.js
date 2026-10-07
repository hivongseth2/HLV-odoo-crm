/**
 * Nghe bus (websocket) của Odoo từ trang tự dựng — không cần bộ JS backend của Odoo.
 *
 * Giao thức Odoo 18 (bus/websocket.py): mở ws://<host>/websocket?version=<bản worker>, gửi
 * {"event_name": "subscribe", "data": {"channels": [...], "last": <id>}}; server đẩy về mảng
 * [{id, message: {type, payload}}]. Gửi "subscribe" lần nữa là THAY danh sách kênh.
 * Mất kết nối thì nối lại, chờ tăng dần tới 30 giây.
 *
 * Dùng: var bus = HlvBus.listen({version, channels, onMessage(type, payload)});
 *       bus.setChannels([...]);
 */
(function () {
    "use strict";

    var MAX_DELAY = 30000;

    function listen(options) {
        var channels = options.channels || [];
        var last = 0;
        var delay = 1000;
        var socket = null;

        function subscribe() {
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ event_name: "subscribe", data: { channels: channels, last: last } }));
            }
        }

        function connect() {
            var scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
            socket = new WebSocket(scheme + "//" + window.location.host + "/websocket?version=" +
                encodeURIComponent(options.version || ""));
            socket.onopen = function () {
                delay = 1000;
                subscribe();
            };
            socket.onmessage = function (event) {
                var notifications;
                try {
                    notifications = JSON.parse(event.data);
                } catch (e) {
                    return;
                }
                (Array.isArray(notifications) ? notifications : []).forEach(function (notification) {
                    if (notification.id > last) {
                        last = notification.id;
                    }
                    var message = notification.message || {};
                    if (message.type) {
                        options.onMessage(message.type, message.payload || {});
                    }
                });
            };
            socket.onclose = function () {
                setTimeout(connect, delay);
                delay = Math.min(delay * 2, MAX_DELAY);
            };
        }

        if (window.WebSocket && options.version) {
            connect();
        }
        return {
            setChannels: function (newChannels) {
                channels = newChannels || [];
                subscribe();
            },
        };
    }

    window.HlvBus = { listen: listen };
})();
