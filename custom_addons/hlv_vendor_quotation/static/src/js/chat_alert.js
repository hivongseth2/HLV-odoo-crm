/**
 * Báo tin nhắn mới kiểu Zalo / Facebook cho hai trang tự dựng (NCC và sale):
 * - tiếng "ting" ngắn (WebAudio tự tạo — không cần tệp âm thanh);
 * - số trên tab "(N) Tiêu đề", và khi tab đang ẩn thì tiêu đề nháy chữ báo ai vừa nhắn,
 *   quay lại tab là thôi nháy.
 *
 * Trình duyệt chỉ cho phát tiếng sau khi người dùng đã bấm / gõ trên trang, nên AudioContext
 * được "mở khoá" ở thao tác đầu tiên; chưa thao tác gì thì chỉ đổi tiêu đề, không kêu.
 *
 * Dùng: HlvChatAlert.notify("Nhi vừa nhắn") — có tin của bên kia;
 *       HlvChatAlert.setUnread(n) — số chưa xem lấy từ server (trang NCC: số trên chuông).
 */
(function () {
    "use strict";

    var BLINK_MS = 1200;
    var baseTitle = document.title;
    var unread = 0;      // chưa xem theo server
    var missed = 0;      // tin đến lúc tab đang ẩn
    var blinkText = "";
    var blinkTimer = null;
    var audio = null;

    function render(showBlink) {
        var count = unread + missed;
        document.title = showBlink && blinkText ? blinkText : (count ? "(" + count + ") " : "") + baseTitle;
    }

    function startBlink() {
        if (blinkTimer) {
            return;
        }
        var on = false;
        blinkTimer = setInterval(function () {
            on = !on;
            render(on);
        }, BLINK_MS);
    }

    function stopBlink() {
        clearInterval(blinkTimer);
        blinkTimer = null;
        blinkText = "";
        missed = 0;
        render(false);
    }

    function unlockAudio() {
        var Context = window.AudioContext || window.webkitAudioContext;
        if (!Context) {
            return;
        }
        audio = audio || new Context();
        if (audio.state === "suspended") {
            audio.resume();
        }
    }

    /** Hai nốt ngắn đi lên, nhỏ tiếng. */
    function ping() {
        if (!audio || audio.state !== "running") {
            return;
        }
        var start = audio.currentTime;
        [880, 1320].forEach(function (freq, index) {
            var osc = audio.createOscillator();
            var gain = audio.createGain();
            var at = start + index * 0.12;
            osc.type = "sine";
            osc.frequency.value = freq;
            gain.gain.setValueAtTime(0.0001, at);
            gain.gain.exponentialRampToValueAtTime(0.18, at + 0.02);
            gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.25);
            osc.connect(gain).connect(audio.destination);
            osc.start(at);
            osc.stop(at + 0.26);
        });
    }

    function notify(text) {
        ping();
        if (document.hidden) {
            missed += 1;
            blinkText = text || "Có tin nhắn mới";
            startBlink();
            render(true);
        }
    }

    function setUnread(count) {
        unread = Math.max(0, count | 0);
        render(false);
    }

    ["pointerdown", "keydown"].forEach(function (type) {
        document.addEventListener(type, unlockAudio, { capture: true });
    });
    document.addEventListener("visibilitychange", function () {
        if (!document.hidden) {
            stopBlink();
        }
    });

    window.HlvChatAlert = { notify: notify, setUnread: setUnread };
})();
