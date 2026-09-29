# -*- coding: utf-8 -*-
import json
import logging
from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from ..services import build_tools_schema, extract_output, strip_file_citations

_logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
except ImportError:
    _logger.warning("Thư viện 'openai' chưa được cài đặt. Hãy chạy: pip install openai")
    OpenAI = None

# Số vòng gọi API tối đa cho một lượt (mỗi vòng = 1 lần gọi model + 1 lượt chạy tool).
# Lộ trình 4 bước search + tra nhóm + tạo + vòng chốt lời vừa đúng 8. Mỗi vòng thừa là
# một lần tính tiền lại TOÀN BỘ chuỗi, nên đừng nới nếu không có bằng chứng bị cắt ngang.
MAX_TOOL_STEPS = 8
# Số tin cũ gửi kèm khi phải dựng lại ngữ cảnh từ DB.
COLD_START_HISTORY_LIMIT = 10

# Cắt chuỗi previous_response_id khi người dùng im lâu hoặc chuỗi đã dài.
#
# Mỗi lần gọi, OpenAI tính tiền TOÀN BỘ chuỗi như input: mọi tin nhắn, mọi kết quả tool
# MISA, mọi đoạn trích file_search của các lượt trước. Session Zalo tìm theo zalo_user_id
# nên dùng lại vĩnh viễn — không cắt thì tin sau luôn đắt hơn tin trước, chi phí một
# session tăng theo bình phương số lượt.
#
# Cắt xong, lượt kế tiếp dựng lại ngữ cảnh từ DB: chỉ COLD_START_HISTORY_LIMIT tin chữ,
# không mang theo kết quả tool cũ.
CHAIN_IDLE_HOURS = 3
CHAIN_MAX_TURNS = 20


def _is_successful_create(tool_call, output_item):
    """Lượt gọi tool này có vừa tạo thành công một sản phẩm MISA không.

    Nhận: dict tool_call của OpenAI và dict kết quả do executor dựng.
    Trả: True/False.
    Biên: output không phải JSON hợp lệ -> False (không dám coi là đã tạo).
    """
    if tool_call.get('name') != 'create_product_misa':
        return False
    try:
        return json.loads(output_item.get('output') or '{}').get('status') == 'success'
    except (TypeError, ValueError):
        return False


class HlvChatgptSession(models.Model):
    _name = 'hlv.chatgpt.session'
    _description = 'Phiên Chat AI (OpenAI Responses API)'
    _rec_name = 'name'
    _order = 'last_activity desc'

    name = fields.Char(string='Chủ đề', default='Hội thoại mới', required=True)
    state = fields.Selection([('new', 'Mới'), ('active', 'Đang hoạt động')], default='new')
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user, index=True)
    last_activity = fields.Datetime(default=fields.Datetime.now)
    zalo_user_id = fields.Char(string="Zalo User ID", index=True)

    last_response_id = fields.Char(
        string="OpenAI Response ID",
        readonly=True,
        copy=False,
        help="ID phản hồi cuối cùng của OpenAI. Nhờ nó mà lượt sau chỉ cần gửi tin mới, "
             "còn toàn bộ ngữ cảnh (kể cả tool call và ảnh) do OpenAI giữ.",
    )

    chain_turns = fields.Integer(
        string="Số lượt trong chuỗi OpenAI",
        readonly=True,
        copy=False,
        help="Số lượt đã nối vào last_response_id hiện tại. Chạm CHAIN_MAX_TURNS thì cắt chuỗi.",
    )

    message_ids = fields.One2many('hlv.chatgpt.message', 'session_id')
    input_text = fields.Text()

    # =========================================================================
    # 1. VÒNG ĐỜI MỘT LƯỢT TRẢ LỜI
    # =========================================================================
    def answer_pending(self):
        """Sinh câu trả lời cho các tin người dùng đang chờ trong session.

        Trả về text để hiển thị / gửi lại cho người dùng. Lỗi cấu hình và lỗi gọi API
        được trả về dưới dạng text chứ không raise, để webhook Zalo luôn có gì đó để trả lời.
        """
        self.ensure_one()
        if OpenAI is None:
            return _("Lỗi Server: Chưa cài đặt thư viện OpenAI (pip install openai).")

        config = self.env['hlv.chatgpt.config'].sudo().get_config()
        if not config:
            return _("Lỗi: Chưa có cấu hình ChatGPT nào đang hoạt động.")
        if not config.api_key or not config.prompt_id:
            return _("Lỗi: Cấu hình ChatGPT còn thiếu API Key hoặc Prompt ID.")

        client = OpenAI(api_key=config.api_key)
        self._restart_chain_if_stale()
        try:
            return self._run_prompt_workflow(client, config)
        except Exception:
            # Người dùng Zalo không bao giờ được nhận im lặng: webhook chạy trong luồng
            # nền với except trần, lỗi lọt tới đó là mất cả câu trả lời lẫn tin đã gửi.
            _logger.exception("Chat workflow lỗi ngoài dự kiến, session %s", self.id)
            return _("Em đang gặp lỗi hệ thống nên chưa xử lý được. "
                     "Anh/chị thử lại sau ít phút giúp em.")

    def _restart_chain_if_stale(self):
        """Bỏ last_response_id khi chuỗi đã cũ hoặc đã dài, để lượt này dựng ngữ cảnh mới.

        Phải gọi TRƯỚC khi lượt này ghi last_activity: căn cứ "im bao lâu" là lần hoạt
        động của lượt trước, không phải lượt hiện tại.
        """
        self.ensure_one()
        if not self.last_response_id:
            return

        idle_since = fields.Datetime.now() - timedelta(hours=CHAIN_IDLE_HOURS)
        is_idle = bool(self.last_activity) and self.last_activity < idle_since
        if not (is_idle or self.chain_turns >= CHAIN_MAX_TURNS):
            return

        _logger.info(
            "Cắt chuỗi OpenAI của session %s (%s)", self.id,
            "im quá %sh" % CHAIN_IDLE_HOURS if is_idle else "đã %s lượt" % self.chain_turns,
        )
        self.sudo().write({'last_response_id': False, 'chain_turns': 0})

    def _run_prompt_workflow(self, client, config):
        """Gọi Responses API và chạy vòng lặp tool cho tới khi model trả lời xong."""
        self.ensure_one()
        pending = self._pending_messages()
        if not pending:
            return ""

        tools = build_tools_schema(
            vector_store_ids=config.get_vector_store_ids(),
            enable_web_search=config.enable_web_search,
        )
        executor = self.env['hlv.chatgpt.tool.executor']
        tool_cache = {}

        is_admin = self._is_admin_sender()
        previous_response_id = self.last_response_id or False
        next_input = (
            [msg.to_openai_input(is_admin=is_admin) for msg in pending]
            if previous_response_id
            else self._cold_start_input(pending, is_admin)
        )

        # Giữ lại id của lần gọi thành công gần nhất: nếu bước sau lỗi, ngữ cảnh đã gửi
        # vẫn nằm bên OpenAI, không được gửi lại lần nữa kẻo trùng.
        last_ok_response_id = False
        can_rebuild_context = bool(previous_response_id)
        interim_text = ""
        final_text = ""
        error_text = None
        # Tạo xong sản phẩm là hết việc của cuộc hội thoại đó: cắt chuỗi ngay tại ranh
        # giới nghiệp vụ, thay vì đợi chạm ngưỡng cứng rồi cắt ngang giữa một luồng.
        product_created = False

        for _step in range(MAX_TOOL_STEPS):
            params = {
                'prompt': {'id': config.prompt_id},
                'input': next_input,
                'tools': tools,
            }
            if previous_response_id:
                params['previous_response_id'] = previous_response_id

            try:
                response = client.responses.create(**params)
            except Exception as error:
                # OpenAI chỉ giữ response 30 ngày; chuỗi hết hạn thì dựng lại ngữ cảnh
                # từ DB một lần, thay vì để session hỏng vĩnh viễn.
                if can_rebuild_context:
                    _logger.warning(
                        "Không nối được chuỗi response %s (%s), dựng lại ngữ cảnh từ DB",
                        previous_response_id, error,
                    )
                    can_rebuild_context = False
                    previous_response_id = False
                    next_input = self._cold_start_input(pending, is_admin)
                    continue
                _logger.exception("OpenAI Responses API error")
                error_text = _("Lỗi gọi OpenAI: %s") % error
                break

            last_ok_response_id = getattr(response, 'id', None) or last_ok_response_id
            previous_response_id = last_ok_response_id
            # Đã gọi được ít nhất một lần: ngữ cảnh nằm bên OpenAI rồi, lỗi ở các bước
            # sau không được dựng lại từ DB nữa kẻo gửi trùng tin của người dùng.
            can_rebuild_context = False

            parsed = extract_output(response)
            if not parsed['tool_calls']:
                final_text = parsed['text'] or interim_text
                break

            # Model vừa nói vừa gọi tool: giữ lại câu nói để dùng nếu bước cuối im lặng.
            if parsed['text']:
                interim_text = parsed['text']
            next_input = []
            for tool_call in parsed['tool_calls']:
                output_item = executor.run_tool_call(tool_call, tool_cache)
                if _is_successful_create(tool_call, output_item):
                    product_created = True
                next_input.append(output_item)
        else:
            final_text = interim_text or _(
                "Yêu cầu cần quá nhiều bước xử lý. Bạn mô tả cụ thể hơn giúp mình nhé."
            )

        if last_ok_response_id:
            self._close_turn(last_ok_response_id, pending, reset_chain=product_created)
        if error_text:
            return error_text
        return strip_file_citations(final_text) or "..."

    def _close_turn(self, response_id, sent_messages, reset_chain=False):
        """Chốt một lượt: nhớ response id và tắt cờ chờ gửi của các tin đã vào ngữ cảnh.

        reset_chain=True thì quên luôn chuỗi: lượt sau dựng ngữ cảnh mới từ DB.
        """
        self.ensure_one()
        vals = {
            'last_activity': fields.Datetime.now(),
            'last_response_id': False if reset_chain else response_id,
            'chain_turns': 0 if reset_chain else self.chain_turns + 1,
        }
        if self.state == 'new':
            vals['state'] = 'active'
        self.sudo().write(vals)
        if sent_messages:
            sent_messages.sudo().write({'to_send': False})

    def _is_admin_sender(self):
        """Người gửi của session này có quyền quản trị không.

        Zalo: chỉ dựa vào whitelist hlv.chatgpt.admin. Lời tự xưng trong tin nhắn
        không có giá trị vì ai cũng gõ được.
        Giao diện Odoo: dựa vào group Quản lý Chat AI của chính người đang bấm nút.
        """
        self.ensure_one()
        if self.zalo_user_id:
            return self.env['hlv.chatgpt.admin'].is_admin_zalo_user(self.zalo_user_id)
        return self.env.user.has_group('hlv_chatgpt.group_hlv_chatgpt_manager')

    # =========================================================================
    # 2. DỰNG NGỮ CẢNH ĐẦU VÀO
    # =========================================================================
    def _pending_messages(self):
        """Các tin của người dùng chưa được đưa vào ngữ cảnh OpenAI, theo thứ tự thời gian."""
        self.ensure_one()
        return self.env['hlv.chatgpt.message'].sudo().search([
            ('session_id', '=', self.id),
            ('role', '=', 'user'),
            ('to_send', '=', True),
        ], order='id asc')

    def _cold_start_input(self, pending, is_admin=False):
        """Dựng ngữ cảnh khi session chưa có last_response_id.

        Chỉ xảy ra với session tạo trước khi nâng cấp, hoặc session vừa được tạo mới.
        Ảnh của các tin cũ không tải lại (tốn thời gian và link Zalo thường đã hết hạn),
        chỉ ghi chú là có ảnh; từ lượt sau OpenAI tự giữ ảnh qua previous_response_id.
        """
        self.ensure_one()
        history = self.env['hlv.chatgpt.message'].sudo().search([
            ('session_id', '=', self.id),
            ('id', 'not in', pending.ids),
            ('role', 'in', ['user', 'assistant']),
        ], order='id desc', limit=COLD_START_HISTORY_LIMIT)

        payload = [
            msg.to_openai_input(with_image=False, is_admin=is_admin)
            for msg in history.sorted('id')
        ]
        payload += [msg.to_openai_input(is_admin=is_admin) for msg in pending]
        return payload

    # =========================================================================
    # 3. ĐẦU VÀO TỪ ZALO
    # =========================================================================
    @api.model
    def process_zalo_message(self, zalo_user_id, message_content, zalo_msg_id=False, image_url=False):
        """Điểm vào của webhook Zalo.

        Trả về text để gửi lại cho người dùng, hoặc False khi bỏ qua (tin trùng) để
        webhook biết là không cần gửi gì.
        """
        Message = self.env['hlv.chatgpt.message'].sudo()
        if zalo_msg_id and Message.search_count([('zalo_msg_id', '=', zalo_msg_id)]):
            _logger.info("Bỏ qua tin Zalo trùng: %s", zalo_msg_id)
            return False

        session = self._get_or_create_zalo_session(zalo_user_id)

        try:
            with self.env.cr.savepoint():
                Message.create({
                    'session_id': session.id,
                    'role': 'user',
                    'content': message_content or False,
                    'image_url': image_url or False,
                    'zalo_msg_id': zalo_msg_id or False,
                    'to_send': True,
                })
                # Ép ghi xuống DB ngay để unique index bắt được ca hai webhook chạy song song.
                self.env.flush_all()
        except IntegrityError:
            _logger.info("Webhook Zalo trùng chạy song song, bỏ qua: %s", zalo_msg_id)
            self.env.invalidate_all()
            return False

        if not session._try_lock_for_processing():
            session.sudo().write({'last_activity': fields.Datetime.now()})
            return session._busy_reply()

        reply = session.answer_pending()
        Message.create({'session_id': session.id, 'role': 'assistant', 'content': reply})
        session.sudo().write({'last_activity': fields.Datetime.now()})
        return reply

    def _get_or_create_zalo_session(self, zalo_user_id):
        session = self.sudo().search(
            [('zalo_user_id', '=', zalo_user_id)], limit=1, order='last_activity desc',
        )
        if session:
            return session
        return self.sudo().create({
            'name': 'Zalo Chat - %s' % zalo_user_id,
            'zalo_user_id': zalo_user_id,
            'state': 'active',
        })

    def _try_lock_for_processing(self):
        """False nếu một webhook khác đang xử lý session này."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    "SELECT id FROM hlv_chatgpt_session WHERE id = %s FOR UPDATE NOWAIT",
                    [self.id],
                )
            return True
        except Exception:
            _logger.info("Session %s đang được xử lý bởi luồng khác", self.id)
            return False

    @staticmethod
    def _busy_reply():
        # Tin nhắn vừa nhận đã được lưu với to_send=True nên sẽ đi kèm ở lượt kế tiếp;
        # xin người dùng gửi lại là cách đơn giản nhất để kích hoạt lượt đó.
        return _("Mình đang xử lý yêu cầu trước đó. Bạn gửi lại tin này sau ít giây giúp mình nhé.")

    # =========================================================================
    # 4. ĐẦU VÀO TỪ GIAO DIỆN ODOO
    # =========================================================================
    def action_send_message(self):
        """Nút gửi tin nhắn trên form chat."""
        self.ensure_one()
        content = (self.input_text or '').strip()
        if not content:
            raise UserError(_("Chưa nhập nội dung."))

        Message = self.env['hlv.chatgpt.message']
        Message.create({
            'session_id': self.id,
            'role': 'user',
            'content': content,
            'to_send': True,
        })
        self.input_text = False

        reply = self.answer_pending()
        Message.create({'session_id': self.id, 'role': 'assistant', 'content': reply})
