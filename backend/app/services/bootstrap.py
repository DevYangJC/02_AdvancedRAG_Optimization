"""启动引导:种子管理员、目录就绪。"""
# 启动引导:应用启动事件中执行,负责"首次运行"必需的环境准备,运行期不再重复
# 若这些目录缺失,后续的上传/日志/缓存功能会在运行时意外失败,故提前建好
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models import User

logger = logging.getLogger(__name__)


# 准备运行目录:上传目录存用户原始文件;data/logs、data/models 是日志与 embedding 磁盘缓存的落点
def ensure_dirs() -> None:
    # 路径统一取自 settings 配置,避免魔法路径散落
    for d in (settings.upload_dir, "data/logs", "data/models"):
        # mkdir 全程 exist_ok=True:重复启动安全,无需先判断目录是否存在
        Path(d).mkdir(parents=True, exist_ok=True)


# 种子管理员:保证首次部署即有可登录账号,避免部署后无账号可用的困境;默认口令是公开值,上线前必须改
async def seed_admin(db: AsyncSession) -> None:
    """幂等创建种子管理员(默认 admin/123456,上线请改密)。"""
    # 按用户名先查一次再创建:重复启动或多 worker 并发启动都不会重复建号
    existing = await db.scalar(select(User).where(User.username == settings.admin_username))
    if existing:
        # 已存在直接返回,绝不覆盖——否则每次重启都会重置管理员密码
        return
    # 密码同样走单向哈希落库,与注册流程一致,泄露也不暴露明文
    db.add(
        User(
            username=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
            role="admin",
            nickname="管理员",
        )
    )
    # 固定 role=admin,种子账号开箱即有管理端权限
    await db.commit()
    # 默认口令写在配置里(而非随机生成)是为了首次部署可登录,日志提示尽快改密
    logger.info("已创建种子管理员账号: %s(请尽快修改默认密码)", settings.admin_username)
    # 引导结果不返回给调用方,靠日志观测;失败异常直接抛出,保证启动失败可见
