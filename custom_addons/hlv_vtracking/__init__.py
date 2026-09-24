from . import models
from . import controllers

from .models.res_company import INSTALL_DEFAULTS


def post_init_hook(env):
    """Điền cấu hình mặc định cho các công ty ĐÃ TỒN TẠI lúc cài module.

    ``default=`` trên field chỉ chạy khi tạo bản ghi mới. Công ty có sẵn từ trước khi cài
    sẽ nhận cột mới với giá trị NULL, nên màn cấu hình hiện ô rỗng và Timeout = 0 — mà
    timeout 0 nghĩa là request không bao giờ chờ được.

    Ghi bằng SQL với điều kiện ``IS NULL`` chứ không dùng ORM: với ô Boolean như "Kiểm
    tra chứng chỉ SSL", ORM không phân biệt được "chưa đặt" với "người dùng cố ý tắt",
    nên sẽ bật lại thứ người ta vừa tắt.
    """
    for field, value in INSTALL_DEFAULTS.items():
        env.cr.execute(
            'UPDATE res_company SET %s = %%s WHERE %s IS NULL' % (field, field),
            (value,),
        )
    env.invalidate_all()
