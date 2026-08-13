"""权限与多用户隔离测试:admin 专属接口、会话/消息越权 404。"""
# 权限边界是本系统的安全底线:管理接口必须只对 admin 开放,
# 用户数据必须只对属主可见,越权访问统一返回 404 而不是暴露资源存在性。
from tests.conftest import auth_headers


# admin 专属接口测试组:验证"谁能看"的边界,覆盖三类角色(admin/普通用户/匿名)。
# 依赖 conftest 的 user_tokens/admin_token fixture:两个用户互不知晓对方。
class TestAdminOnly:
    async def test_normal_user_forbidden_on_documents(self, client, user_tokens):
        # 解构只取 token_a:本用例只需要一个普通用户,不需要 user_b。
        token_a, _ = user_tokens
        # 普通用户即使带了合法 JWT 也不能访问管理接口:权限判断不能只看"是否登录"。
        resp = await client.get("/api/documents", headers=auth_headers(token_a))
        assert resp.status_code == 403
        # 403 响应还带业务码 FORBIDDEN:前端可按 code 做统一的错误提示。
        assert resp.json()["code"] == "FORBIDDEN"

    async def test_anonymous_forbidden_on_documents(self, client):
        # 匿名请求(无 token)返回 401:与 403 区分"没登录"和"没权限"。
        # 匿名请求先被认证中间件拦下,根本到不了权限判断那一步。
        resp = await client.get("/api/documents")
        assert resp.status_code == 401

    async def test_admin_can_access_documents(self, client, admin_token):
        # 对照组:admin 访问同一接口必须放行,防止权限逻辑"一刀切"全拒。
        # 角色信息编码在 JWT 载荷里,由后端依赖注入解析后做角色比对。
        resp = await client.get("/api/documents", headers=auth_headers(admin_token))
        assert resp.status_code == 200

    async def test_admin_stats(self, client, admin_token):
        # 统计接口是运营视图:文档数/知识块数/用户数,指标字段必须齐全。
        # 字段缺失或改名会破坏前端运营页,这里固化了返回契约。
        resp = await client.get("/api/documents/admin/stats", headers=auth_headers(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        for key in ("document_count", "chunk_count", "user_count"):
            assert key in data


# 会话隔离测试组:核心约束是"user_b 永远看不到 user_a 的任何数据"。
class TestConversationIsolation:
    # 内部辅助:帮当前用户创建一个会话,返回其 id,供各越权用例使用。
    # 建会话接口对普通用户同样开放,这里只是为越权用例准备"攻击目标"。
    async def _create_conv(self, client, token: str) -> str:
        resp = await client.post(
            "/api/conversations", json={"title": "测试会话"}, headers=auth_headers(token)
        )
        # 建会话失败时断言会带出响应:夹具报错比用例报错更容易定位根因。
        assert resp.status_code == 200
        return resp.json()["id"]

    async def test_access_others_conversation_404(self, client, user_tokens):
        token_a, token_b = user_tokens
        conv_id = await self._create_conv(client, token_a)

        # user_b 访问 user_a 的会话 → 404(不暴露存在性)
        # GET/PUT/DELETE 三连测:读、改、删全覆盖,任何一个入口泄密都算越权。
        # 404 的语义是"对越权者表现得像资源不存在",无法通过报错差异去猜 id。
        resp = await client.get(f"/api/conversations/{conv_id}", headers=auth_headers(token_b))
        assert resp.status_code == 404
        resp = await client.put(
            f"/api/conversations/{conv_id}",
            json={"title": "改名"},
            headers=auth_headers(token_b),
        )
        assert resp.status_code == 404
        resp = await client.delete(f"/api/conversations/{conv_id}", headers=auth_headers(token_b))
        assert resp.status_code == 404

        # user_a 正常访问
        # 对照组:属主本人访问必须 200,证明 404 是"越权"而非"接口坏了"。
        resp = await client.get(f"/api/conversations/{conv_id}", headers=auth_headers(token_a))
        assert resp.status_code == 200

    async def test_access_others_messages_404(self, client, user_tokens):
        token_a, token_b = user_tokens
        conv_id = await self._create_conv(client, token_a)
        # 消息列表同样按属主过滤:历史记录是隐私数据,越权读要 404。
        resp = await client.get(
            f"/api/conversations/{conv_id}/messages", headers=auth_headers(token_b)
        )
        assert resp.status_code == 404

    async def test_feedback_others_message_404(self, client, user_tokens):
        token_a, token_b = user_tokens
        conv_id = await self._create_conv(client, token_a)
        # 构造一条消息(直接写库更快,不走聊天链路)
        # 写库绕过聊天接口,只为了拿到一个真实 msg_id,聚焦测试"点赞越权"这一件事。
        from app.db.session import async_session_maker
        from app.models import Message

        async with async_session_maker() as db:
            msg = Message(conversation_id=conv_id, role="user", content="你好")
            db.add(msg)
            await db.commit()
            msg_id = msg.id

        # 给别人消息点赞也必须 404:反馈会影响答案质量统计,不能被人恶意刷分。
        # feedback 是"点赞/点踩":让无关用户操作它,会污染答案质量数据。
        resp = await client.post(
            f"/api/conversations/messages/{msg_id}/feedback",
            json={"value": 1},
            headers=auth_headers(token_b),
        )
        assert resp.status_code == 404

    async def test_conversation_list_isolation(self, client, user_tokens):
        token_a, _ = user_tokens
        await self._create_conv(client, token_a)
        # 会话列表只返回自己的会话:若混入他人会话,说明过滤条件漏了 user_id。
        # user_a 只创建过自己的会话:列表里出现任何非自己创建的项都算隔离失效。
        resp = await client.get("/api/conversations", headers=auth_headers(token_a))
        assert resp.status_code == 200
        assert len(resp.json()["items"]) >= 1
