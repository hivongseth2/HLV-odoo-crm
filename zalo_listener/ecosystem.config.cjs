// pm2: chạy nền đúng MỘT bản (Zalo chỉ cho một kết nối web mỗi tài khoản — hai bản sẽ đá nhau, mã 3000).
// restart_delay 60s: chương trình có lỗi khởi động thì pm2 không bật lại tức thì thành vòng đăng nhập dồn dập
// (sự cố cũ: 11 lần đăng nhập trong 2,5 phút).
module.exports = {
    apps: [
        {
            name: "hlv-zalo-listener",
            script: "src/main.js",
            cwd: __dirname,
            instances: 1,
            exec_mode: "fork",
            autorestart: true,
            restart_delay: 60000,
            min_uptime: 60000,
            max_restarts: 30,
        },
    ],
};
