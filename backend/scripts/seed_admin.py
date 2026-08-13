"""幂等创建种子管理员账号(默认 admin/123456,可用环境变量覆盖)。

用法:
    python -m scripts.seed_admin
"""
import asyncio
import sys
from pathlib import Path

# 应用依赖都在 backend 根目录的 app 包下:先临时把根目录加进 sys.path 才能导入。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import async_session_maker, init_db
from app.services.bootstrap import ensure_dirs, seed_admin


# 初始化顺序固定为:目录 → 建表 → 写账号,后两步都依赖前置步骤完成。
async def main() -> None:
    # 确保上传目录/数据目录存在,否则后续文件写入会报 FileNotFoundError。
    ensure_dirs()
    # 创建全部数据表(幂等):seed_admin 要写 users 表,必须先完成建表。
    await init_db()
    # 种子账号写入是幂等的:已存在则跳过,重复执行本脚本不会报错或产生重复数据。
    async with async_session_maker() as db:
        await seed_admin(db)
    print("种子管理员已就绪(admin/123456)")


if __name__ == "__main__":
    # 模块级守卫:被 import 时不自动执行;
    # 异步入口统一用 asyncio.run 包装,因为脚本顶层无法直接 await。
    asyncio.run(main())
