// /** @odoo-module */

// /**
//  * HLV Browser Back Button
//  * 
//  * Thay đổi hành vi của nút ứng dụng (app button) trong Odoo:
//  * - Khi click vào nút tên ứng dụng (Bán hàng, Mua hàng, etc.), 
//  *   sử dụng history.back() thay vì về menu chính
//  * - Giúp người dùng quay lại trang trước đó với các bộ lọc được giữ nguyên
//  * 
//  * Target: .o_menu_toggle (nút với icon 9 ô vuông + tên ứng dụng)
//  */

// // Hàm thay đổi behavior của nút ứng dụng
// function modifyAppButton(appButton) {
//     if (!appButton || appButton.dataset.hlvModified) return;

//     // Đánh dấu đã xử lý
//     appButton.dataset.hlvModified = 'true';

//     // Clone link để remove TẤT CẢ event listeners (bao gồm OWL bindings)
//     const newButton = appButton.cloneNode(true);

//     // Thêm event listener mới
//     newButton.addEventListener('click', function (ev) {
//         ev.preventDefault();
//         ev.stopPropagation();
//         ev.stopImmediatePropagation();

//         console.log('[HLV] App button clicked - using history.back()');
//         window.history.back();

//         return false;
//     }, true); // capture phase

//     // Thêm mousedown listener để chặn sớm hơn
//     newButton.addEventListener('mousedown', function (ev) {
//         ev.stopPropagation();
//     }, true);

//     // Replace button cũ bằng button mới
//     appButton.parentNode.replaceChild(newButton, appButton);

//     console.log('[HLV] Replaced app button:', newButton);
// }

// // Scan và modify nút ứng dụng
// function scanAndModifyAppButtons() {
//     // Target: .o_menu_toggle (nút ứng dụng với logo và tên app)
//     const appButtons = document.querySelectorAll('.o_menu_toggle');
//     appButtons.forEach(modifyAppButton);
// }

// // Khởi tạo MutationObserver để theo dõi DOM changes
// function initObserver() {
//     const observer = new MutationObserver((mutations) => {
//         let shouldScan = false;

//         for (const mutation of mutations) {
//             if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
//                 for (const node of mutation.addedNodes) {
//                     if (node.nodeType === Node.ELEMENT_NODE) {
//                         // Check if it's an app button or contains one
//                         if (node.classList?.contains('o_menu_toggle') ||
//                             node.querySelector?.('.o_menu_toggle')) {
//                             shouldScan = true;
//                             break;
//                         }
//                         // Also check for navbar
//                         if (node.classList?.contains('o_main_navbar') ||
//                             node.querySelector?.('.o_main_navbar')) {
//                             shouldScan = true;
//                             break;
//                         }
//                     }
//                 }
//             }
//             if (shouldScan) break;
//         }

//         if (shouldScan) {
//             // Delay một chút để OWL render xong
//             setTimeout(scanAndModifyAppButtons, 100);
//         }
//     });

//     // Observe toàn bộ document
//     observer.observe(document.body, {
//         childList: true,
//         subtree: true
//     });

//     console.log('[HLV] MutationObserver initialized');
// }

// // Khởi tạo module
// function init() {
//     // Scan ngay lập tức
//     scanAndModifyAppButtons();

//     // Thiết lập observer cho dynamic content
//     initObserver();

//     // Scan lại sau mỗi 2 giây (backup)
//     setInterval(scanAndModifyAppButtons, 2000);

//     console.log('[HLV] Browser Back Button module initialized');
// }

// // Khởi tạo khi document ready
// if (document.readyState === 'loading') {
//     document.addEventListener('DOMContentLoaded', init);
// } else {
//     init();
// }

// console.log('[HLV] Browser Back Button module loaded');

