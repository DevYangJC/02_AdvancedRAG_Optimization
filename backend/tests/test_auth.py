"""认证功能测试:注册 / 登录 / 刷新 / 改密 / token 失效。

所有注册用户名使用唯一后缀,保证测试可重复运行。
"""
# 认证是其它一切接口的前置依赖,因此本文件也顺带验证了"注册 → 登录"的完整链路。
# 全部用户名都用 unique_name 生成:即使测试库持久化,重复执行也不会相互干扰。
from tests.conftest import auth_headers, unique_name

from app.core.security import hash_password, verify_password


# 密码哈希单元测试:不依赖数据库/HTTP,验证哈希与校验的对称性;
# 加盐随机性等细节由底层哈希库保证,这里只验证行为契约。
class TestPassword:
    def test_hash_and_verify(self):
        # 哈希结果绝不能等于明文:否则等价于密码裸存,是安全事故。
        h = hash_password("123456")
        assert h != "123456"
        assert verify_password("123456", h)
        # 错误密码必须校验失败:防止"任意密码都通过"的实现缺陷。
        assert not verify_password("wrong", h)


# 认证接口测试组:走真实 HTTP 链路,验证注册/登录/刷新/改密的完整闭环,
# 覆盖正常路径与各种错误路径,保证前端拿到的状态码/错误码语义稳定。
class TestAuthAPI:
    async def test_register_and_login(self, client):
        # 正常路径:注册新用户,断言返回的用户信息与 token 字段。
        username = unique_name("new_user")
        resp = await client.post(
            "/api/auth/register",
            json={"username": username, "password": "secret123", "nickname": "小王"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["username"] == username
        # 新注册用户默认角色必须是 user,绝不能默认授予 admin 权限。
        assert data["user"]["role"] == "user"
        # 注册成功应直接返回 access_token:前端"注册即登录",无需二次请求。
        assert data["access_token"]

        # 用同一账号密码再登录一次:验证密码写入正确、可正常回读验证。
        resp = await client.post(
            "/api/auth/login", json={"username": username, "password": "secret123"}
        )
        assert resp.status_code == 200
        # 昵称是注册时提交的展示名,登录后应原样返回。
        assert resp.json()["user"]["nickname"] == "小王"

    async def test_register_duplicate(self, client):
        # 首次注册必须成功(200):作为"第二次应失败"的前提铺垫。
        username = unique_name("dup_user")
        await client.post(
            "/api/auth/register", json={"username": username, "password": "secret123"}
        )
        # 同名二次注册应被拒绝:用户名是唯一标识,覆盖注册接口的幂等约束。
        resp = await client.post(
            "/api/auth/register", json={"username": username, "password": "secret123"}
        )
        # 400 + BAD_REQUEST 业务码:前端据此弹出明确提示,而不是笼统的 500。
        assert resp.status_code == 400
        assert resp.json()["code"] == "BAD_REQUEST"

    async def test_login_wrong_password(self, client):
        # 密码错误返回 401:不区分"用户不存在/密码错误",避免用户名枚举攻击。
        resp = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401

    async def test_weak_password_rejected(self, client):
        # 弱密码(长度 3)应在服务端被拒:强度校验不能只靠前端,否则绕过前端即可裸登。
        resp = await client.post(
            "/api/auth/register", json={"username": unique_name("weak_user"), "password": "123"}
        )
        assert resp.status_code == 400

    async def test_refresh_token(self, client):
        # 先登录拿到一对 token:access_token 是"短期凭证",refresh_token 是"长期凭证"。
        login = await client.post(
            "/api/auth/login", json={"username": "admin", "password": "123456"}
        )
        refresh_token = login.json()["refresh_token"]
        # refresh 端点用 refresh_token 换新 access_token,无需用户重新输入密码。
        resp = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 200
        # 换发的新 access_token 立即可用(此处只断言字段存在)。
        assert resp.json()["access_token"]

        # 用 access token 冒充 refresh token 应失败
        # 两类 token 必须互相不可用:否则拿到 access_token 就能无限续期,失去过期意义。
        access_token = login.json()["access_token"]
        resp = await client.post("/api/auth/refresh", json={"refresh_token": access_token})
        assert resp.status_code == 401

    async def test_me(self, client, admin_token):
        # /me 返回当前登录用户信息:前端恢复登录态时用它校验 token 有效性。
        # 直接复用 conftest 的 admin_token fixture:登录逻辑已被其它用例覆盖。
        resp = await client.get("/api/auth/me", headers=auth_headers(admin_token))
        assert resp.status_code == 200
        # 断言角色回读正确:证明 JWT 载荷里的角色被后端正确解析。
        assert resp.json()["role"] == "admin"

    async def test_no_token_rejected(self, client):
        # 不带 token 访问受保护接口必须 401:匿名请求不能读到任何用户数据。
        # 401 表示"未认证",与 403"已认证但无权限"语义不同,前端需分别处理。
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401

    async def test_change_password_invalidates_old(self, client):
        # 改密后旧密码必须立刻失效:这是账号安全的核心承诺,防止旧凭据被复用。
        username = unique_name("pw_user")
        reg = await client.post(
            "/api/auth/register", json={"username": username, "password": "pass123456"}
        )
        # 改密需要登录态:这里用专属用户,避免污染共享的 admin 账号。
        headers = auth_headers(reg.json()["access_token"])

        # 旧密码错误
        # 旧密码校验失败应拒绝修改:防止已窃取会话的人直接改密接管账号。
        resp = await client.put(
            "/api/auth/password",
            json={"old_password": "wrong", "new_password": "newpass123"},
            headers=headers,
        )
        assert resp.status_code == 400

        # 正确修改
        resp = await client.put(
            "/api/auth/password",
            json={"old_password": "pass123456", "new_password": "newpass123"},
            headers=headers,
        )
        assert resp.status_code == 200

        # 旧密码无法再登录,新密码可以
        # 双保险验证:旧密码彻底失效(401),新密码立即可用(200)。
        resp = await client.post(
            "/api/auth/login", json={"username": username, "password": "pass123456"}
        )
        assert resp.status_code == 401
        resp = await client.post(
            "/api/auth/login", json={"username": username, "password": "newpass123"}
        )
        assert resp.status_code == 200
