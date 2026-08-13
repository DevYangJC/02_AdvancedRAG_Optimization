"""语义缓存:规范化问题 → 答案 + 引用来源。

- key = md5(规范化问题):去空白、统一全角标点为半角、小写
- 命中:hit_count +1,直接吐缓存答案(延迟 50ms 级)
- TTL 过期自动失效;后台定期清理过期条目
"""
# 语义缓存解决"同一问题反复问"的重复计算:命中直接吐缓存答案,延迟从秒级降到毫秒级
# 命中采用规范化后的精确匹配而非相似匹配,保证缓存答案与问题严格对应,不会答非所问
# 缓存落数据库而非内存/Redis:多 worker 间共享命中,且服务重启后不丢
import hashlib
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import CacheEntry

logger = logging.getLogger(__name__)

# 全角→半角映射表:输入法常输出全角标点,统一后不会因标点差异漏命中
_FULLWIDTH = str.maketrans(
    "，。！？；：、（）【】“”‘’",
    ",.!?;:、()[]\"\"''",
)


# 规范化问题文本:去空白、统一标点、转小写,让同一语义的不同写法命中同一个缓存 key
def normalize_query(query: str) -> str:
    # translate 按映射表一次替换全部全角标点,比逐个 replace 高效
    q = query.strip().translate(_FULLWIDTH)
    # 压缩全部空白:用户用空格/换行分隔短语是习惯差异,对语义无影响
    q = re.sub(r"\s+", "", q)
    return q.lower()


# 把规范化问题压缩为定长 MD5 key:问题可任意长,定长 key 使入库与检索都更快
def query_hash(query: str) -> str:
    # 只对规范化结果取哈希,保证同义写法哈希一致;MD5 仅作 key 使用,无安全需求
    return hashlib.md5(normalize_query(query).encode("utf-8")).hexdigest()


# 查缓存:命中返回 CacheEntry,未命中/已过期返回 None;参数 db=数据库会话、query=用户原始问题
async def get_cached(db: AsyncSession, query: str) -> CacheEntry | None:
    h = query_hash(query)
    # 按 query_hash 唯一索引定位,一条查询完成
    entry = await db.scalar(select(CacheEntry).where(CacheEntry.query_hash == h))
    # 未命中:返回 None,调用方继续走改写→检索→生成管线
    if entry is None:
        return None
    # 惰性过期:读到时才顺手删除过期条目,避免每次请求都扫描全表
    if entry.expires_at and entry.expires_at < datetime.now():
        await db.delete(entry)
        await db.commit()
        return None
    # hit_count 累加并落库:管理后台的缓存命中率指标来源于此
    entry.hit_count += 1
    await db.commit()
    # 注意:命中不校验生成模型是否一致;升级模型后如需全局失效,可清空缓存表或给 key 加版本号
    return entry


async def set_cached(
    db: AsyncSession,
    query: str,
    answer: str,
    sources: list[dict] | None,
    model: str,
# 写缓存:答案与引用来源一起缓存,命中时无需再走改写/检索/重排环节
# 参数: db=会话、query=原始问题、answer=生成答案、sources=引用来源列表、model=生成模型名
) -> None:
    h = query_hash(query)
    # 先查存在性:区分"覆盖写"与"首次写"两个分支,避免对同一问题累积多行缓存
    existing = await db.scalar(select(CacheEntry).where(CacheEntry.query_hash == h))
    # TTL 从配置读取:过期后查询时惰性删除,后台定期任务兜底清理
    ttl = timedelta(hours=settings.cache_ttl_hours)
    if existing:
        # 同一问题的新答案覆盖旧答案,避免缓存中囤积同一问题的多个版本
        existing.answer = answer
        existing.sources = sources
        existing.model = model
        # 只刷新过期时间而非删旧插新:主键稳定,也不产生碎片行
        existing.expires_at = datetime.now() + ttl
    else:
        # 首次入库:连同原始问题文本一并保存,便于后台排查命中情况
        db.add(
            CacheEntry(
                query_hash=h,
                query=query,
                answer=answer,
                sources=sources,
                model=model,
                # 新行从当前时刻起算 TTL
                expires_at=datetime.now() + ttl,
            )
        )
    await db.commit()


# 清理过期条目:由后台定期任务调用,防止缓存表无限膨胀
async def cleanup_expired(db: AsyncSession) -> int:
    # 一条 delete 完成清理,不需要逐条加载判断后再删
    result = await db.execute(delete(CacheEntry).where(CacheEntry.expires_at < datetime.now()))
    await db.commit()
    # 返回受影响行数,调用方可评估本轮清理规模
    return result.rowcount or 0
