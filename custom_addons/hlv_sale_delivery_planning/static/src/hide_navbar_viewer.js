/** @odoo-module **/
/**
 * Viewer mode: when opened from /sale_plan, hide the top navbar
 * so external users only see the delivery planner dashboard.
 * Triggered by ?viewer=1 in the URL query string.
 */
(function () {
    if (new URLSearchParams(window.location.search).get('viewer') !== '1') {
        return;
    }
    var css =
        'nav.o_main_navbar { display: none !important; }' +
        '.o_web_client { padding-top: 0 !important; }' +
        '.o_action_manager { top: 0 !important; height: 100vh !important; }';

    function injectStyle() {
        if (document.getElementById('_hlv_viewer_css')) return;
        var s = document.createElement('style');
        s.id = '_hlv_viewer_css';
        s.textContent = css;
        (document.head || document.documentElement).appendChild(s);
    }

    // Inject immediately and also after DOM ready (Odoo may replace head)
    injectStyle();
    document.addEventListener('DOMContentLoaded', injectStyle);

    // Re-apply after each OWL re-render cycle (navbar may be re-mounted)
    var observer = new MutationObserver(injectStyle);
    document.addEventListener('DOMContentLoaded', function () {
        observer.observe(document.body, { childList: true, subtree: true });
    });
})();
