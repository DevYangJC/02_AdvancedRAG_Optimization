"""语义缓存单元测试:规范化 key、写入/命中/过期。"""
# 语义缓存:按"规范化后的问题"做 key,命中的问题直接返回上次答案,省一次完整 RAG 调用。
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from app.models import CacheEntry
from app.services import cache_service


# 查询规范化测试:命中率的高低取决于"同一问题的不同写法"能否映射到同一个 key。
# 注意:这里断言的是"规范化输出是否符合预期",哈希内部算法不是测试关心的。
class TestNormalize:
    def test_trim_and_whitespace(self):
        # 首尾空格与中间多余空格都应被剔除:" 运费多少 " 和 "运 费 多 少" 要命中同一缓存。
        assert cache_service.normalize_query("  运费多少  ") == "运费多少"
        assert cache_service.normalize_query("运 费 多 少") == "运费多少"

    def test_fullwidth_punctuation(self):
        # 全角问号?保留而非删除:删除会导致"包邮吗"与"包邮吗?"同 key,误伤语义。
        assert cache_service.normalize_query("包邮吗?") == "包邮吗?"

    def test_same_hash_after_normalize(self):
        # 规范化是"哈希前的统一入口":同一问题两次哈希必须一致,不同问题必须不一致。
        # 反例同样关键:两个不同问题哈希撞车,会出现"张冠李戴"的错误回答。
        assert cache_service.query_hash("包邮吗?") == cache_service.query_hash("包邮吗?")
        assert cache_service.query_hash("包邮吗?") != cache_service.query_hash("运费多少?")


# 数据库层面的缓存读写测试:验证写入 → 命中 → 过期失效的完整生命周期。
@pytest.mark.asyncio
class TestCacheDB:
    async def test_set_and_get(self):
        async with async_session_maker() as db:
            # 参数依次为 (db, 问题, 答案, 引用来源列表, 模型名):模型名用于区分不同模型生成的缓存。
            await cache_service.set_cached(db, "包邮吗", "包邮的", [], "qwen-plus")
            entry = await cache_service.get_cached(db, "包邮吗")
            assert entry is not None
            assert entry.answer == "包邮的"
            # 命中计数 +1
            # set 时已计一次、get 命中再计一次,所以预期 >= 2:命中次数用于统计缓存收益。
            assert entry.hit_count >= 2

    async def test_miss(self):
        async with async_session_maker() as db:
            # 从没写过的 key 必须返回 None:未命中时走完整 RAG 链路,不能返回残值。
            # 返回 None 而非空串:调用方正是用 None 判断"这次要不要重新生成"。
            assert await cache_service.get_cached(db, "不存在的奇葩问题xyz") is None

    async def test_expired_entry_invalidated(self):
        async with async_session_maker() as db:
            await cache_service.set_cached(db, "过期的", "答案", None, "qwen-plus")
            # 直接查库改 expires_at:等价于"这条缓存是 1 小时前写入且已超 TTL"。
            # 先确认写入成功:set_cached 可能没落库,先断言存在再改时间才可靠。
            entry = await db.scalar(select(CacheEntry).where(CacheEntry.query_hash == cache_service.query_hash("过期的")))
            assert entry is not None
            entry.expires_at = datetime.now() - timedelta(hours=1)
            await db.commit()
            # 过期条目在读取时必须被当作"不存在",否则会返回过时答案。
            assert await cache_service.get_cached(db, "过期的") is None

    async def test_cleanup_expired(self):
        async with async_session_maker() as db:
            await cache_service.set_cached(db, "清理目标", "答案", None, "qwen-plus")
            entry = await db.scalar(select(CacheEntry).where(CacheEntry.query_hash == cache_service.query_hash("清理目标")))
            entry.expires_at = datetime.now() - timedelta(hours=2)
            await db.commit()
            # cleanup_expired 是定时任务路径:批量删除过期行,防止缓存表无限膨胀。
            # 返回值是删除行数:>=1 证明过期行真的被扫掉了,而不是空跑。
            removed = await cache_service.cleanup_expired(db)
            assert removed >= 1
