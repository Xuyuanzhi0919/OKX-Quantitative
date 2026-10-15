"""
K线数据管理服务
负责历史K线数据的获取、存储和查询
"""

from typing import List, Optional, Dict
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
from loguru import logger

from app.models import Kline
from app.services.exchange.okx import OKXExchange


class KlineService:
    """K线数据服务类"""

    def __init__(self, db: Session, exchange: OKXExchange):
        """
        初始化K线服务

        Args:
            db: 数据库会话
            exchange: 交易所实例
        """
        self.db = db
        self.exchange = exchange

    async def fetch_and_save_klines(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
        batch_size: int = 100,
    ) -> Dict:
        """
        从交易所获取历史K线并保存到数据库

        Args:
            symbol: 交易对，如 BTC-USDT
            interval: K线周期，如 1m/5m/15m/1H/4H/1D
            start_time: 开始时间戳(毫秒)
            end_time: 结束时间戳(毫秒)
            batch_size: 每批获取数量，最大100

        Returns:
            {
                "total": 总条数,
                "new": 新增条数,
                "updated": 更新条数,
                "skipped": 跳过条数
            }
        """
        logger.info(
            f"开始获取K线数据: {symbol} {interval} "
            f"{datetime.fromtimestamp(start_time/1000)} - {datetime.fromtimestamp(end_time/1000)}"
        )

        total_count = 0
        new_count = 0
        updated_count = 0
        skipped_count = 0

        current_time = end_time  # 从最新时间开始往历史方向获取
        last_oldest_ts = None  # 记录上一批的最旧时间戳,用于检测重复
        batch_num = 0

        while current_time > start_time:
            try:
                batch_num += 1

                # 使用历史K线接口向过去翻页。OKX /market/candles 只覆盖较近数据，
                # 长周期回测需要 /market/history-candles。
                get_klines = getattr(
                    self.exchange, "get_history_kline", self.exchange.get_kline
                )
                klines = await get_klines(
                    symbol=symbol,
                    timeframe=interval,
                    limit=min(batch_size, 100),
                    after=str(current_time),
                )

                if not klines:
                    logger.info(f"没有更多K线数据")
                    break

                logger.info(f"第 {batch_num} 批: 获取到 {len(klines)} 条K线")

                # 处理每根K线
                should_continue = True  # 标记是否需要继续获取下一批
                for kline_data in klines:
                    ts = int(kline_data["ts"])

                    # 如果超出时间范围(比start_time更早),标记不再继续获取下一批
                    if ts < start_time:
                        should_continue = False
                        continue

                    # 检查是否已存在
                    existing = (
                        self.db.query(Kline)
                        .filter(
                            and_(
                                Kline.symbol == symbol,
                                Kline.interval == interval,
                                Kline.timestamp == ts,
                            )
                        )
                        .first()
                    )

                    if existing:
                        # 如果是未确认的K线，更新它
                        if existing.confirm == 0 or kline_data["confirm"] == "1":
                            existing.open = float(kline_data["o"])
                            existing.high = float(kline_data["h"])
                            existing.low = float(kline_data["l"])
                            existing.close = float(kline_data["c"])
                            existing.volume = float(kline_data["vol"])
                            existing.volume_currency = float(kline_data["volCcy"])
                            existing.confirm = int(kline_data["confirm"])
                            updated_count += 1
                        else:
                            skipped_count += 1
                    else:
                        # 创建新记录
                        new_kline = Kline(
                            symbol=symbol,
                            interval=interval,
                            timestamp=ts,
                            open=float(kline_data["o"]),
                            high=float(kline_data["h"]),
                            low=float(kline_data["l"]),
                            close=float(kline_data["c"]),
                            volume=float(kline_data["vol"]),
                            volume_currency=float(kline_data["volCcy"]),
                            confirm=int(kline_data["confirm"]),
                        )
                        self.db.add(new_kline)
                        new_count += 1

                    total_count += 1

                # 提交本批数据
                self.db.commit()

                # 如果已经获取到start_time之前的数据,停止获取
                if not should_continue:
                    logger.info(f"已获取到start_time之前的数据，停止获取")
                    break

                # 更新下一批的开始时间（取本批最旧的时间戳）
                # OKX的after参数返回的数据是从新到旧排序,最后一条是最旧的
                # 使用最旧的时间戳作为下一批的after参数,继续往历史方向获取
                oldest_ts = int(klines[-1]["ts"])

                # 检查是否与上一批数据重复(说明没有更旧的数据了)
                if last_oldest_ts is not None and oldest_ts == last_oldest_ts:
                    oldest_time = datetime.fromtimestamp(oldest_ts / 1000).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    logger.info(
                        f"返回数据与上一批重复(oldest_ts={oldest_time}),没有更旧的数据了"
                    )
                    break

                # 记录本批的最旧时间戳,用于下次检测重复
                last_oldest_ts = oldest_ts
                current_time = oldest_ts

                logger.info(
                    f"已处理 {total_count} 条K线数据 (新增: {new_count}, 更新: {updated_count}, 跳过: {skipped_count})"
                )

            except Exception as e:
                logger.error(f"获取K线数据失败: {e}")
                self.db.rollback()
                raise

        logger.info(
            f"K线数据获取完成: 总计 {total_count} 条 (新增: {new_count}, 更新: {updated_count}, 跳过: {skipped_count})"
        )

        return {
            "total": total_count,
            "new": new_count,
            "updated": updated_count,
            "skipped": skipped_count,
        }

    def query_klines(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
        limit: Optional[int] = None,
    ) -> List[Kline]:
        """
        从数据库查询K线数据

        Args:
            symbol: 交易对
            interval: K线周期
            start_time: 开始时间戳(毫秒)
            end_time: 结束时间戳(毫秒)
            limit: 限制返回数量

        Returns:
            K线列表（按时间升序）
        """
        query = (
            self.db.query(Kline)
            .filter(
                and_(
                    Kline.symbol == symbol,
                    Kline.interval == interval,
                    Kline.timestamp >= start_time,
                    Kline.timestamp <= end_time,
                    Kline.confirm == 1,  # 只返回已确认的K线
                )
            )
            .order_by(Kline.timestamp.asc())
        )

        if limit:
            query = query.limit(limit)

        return query.all()

    def get_latest_kline(self, symbol: str, interval: str) -> Optional[Kline]:
        """
        获取最新的K线数据

        Args:
            symbol: 交易对
            interval: K线周期

        Returns:
            最新的K线记录，如果不存在返回None
        """
        return (
            self.db.query(Kline)
            .filter(and_(Kline.symbol == symbol, Kline.interval == interval))
            .order_by(desc(Kline.timestamp))
            .first()
        )

    def get_data_range(self, symbol: str, interval: str) -> Optional[Dict]:
        """
        获取数据库中K线数据的时间范围

        Args:
            symbol: 交易对
            interval: K线周期

        Returns:
            {
                "start_time": 最早时间戳,
                "end_time": 最晚时间戳,
                "count": 数据条数
            }
            如果没有数据返回None
        """
        query = self.db.query(Kline).filter(
            and_(Kline.symbol == symbol, Kline.interval == interval)
        )

        count = query.count()
        if count == 0:
            return None

        earliest = query.order_by(Kline.timestamp.asc()).first()
        latest = query.order_by(desc(Kline.timestamp)).first()

        return {
            "start_time": earliest.timestamp,
            "end_time": latest.timestamp,
            "count": count,
        }

    def delete_klines(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> int:
        """
        删除K线数据

        Args:
            symbol: 交易对
            interval: K线周期
            start_time: 开始时间戳(可选)
            end_time: 结束时间戳(可选)

        Returns:
            删除的记录数
        """
        query = self.db.query(Kline).filter(
            and_(Kline.symbol == symbol, Kline.interval == interval)
        )

        if start_time:
            query = query.filter(Kline.timestamp >= start_time)
        if end_time:
            query = query.filter(Kline.timestamp <= end_time)

        count = query.delete()
        self.db.commit()

    def get_available_symbols(self) -> List[Dict]:
        """
        获取数据库中有K线数据的交易对列表

        Returns:
            交易对列表，包含symbol、interval和数据条数
        """
        from sqlalchemy import func

        results = (
            self.db.query(
                Kline.symbol,
                Kline.interval,
                func.count(Kline.id).label("count"),
                func.min(Kline.timestamp).label("earliest"),
                func.max(Kline.timestamp).label("latest"),
            )
            .group_by(Kline.symbol, Kline.interval)
            .all()
        )

        return [
            {
                "symbol": r.symbol,
                "interval": r.interval,
                "count": r.count,
                "earliest": r.earliest,
                "latest": r.latest,
            }
            for r in results
        ]

    def get_symbols(self) -> List[str]:
        """
        获取所有有数据的交易对（去重）

        Returns:
            交易对列表
        """
        from sqlalchemy import distinct

        results = self.db.query(distinct(Kline.symbol)).all()
        return sorted([r[0] for r in results])

        logger.info(f"删除K线数据: {symbol} {interval} 共 {count} 条")
        return count
