"""
交易所抽象基类
说明：这是交易所接口的抽象层，定义了所有交易所需要实现的标准接口
等拿到OKX API文档后，会创建具体的OKX实现类
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from decimal import Decimal


class ExchangeBase(ABC):
    """交易所抽象基类"""

    def __init__(self, api_key: str, secret_key: str, passphrase: Optional[str] = None):
        """
        初始化交易所

        Args:
            api_key: API密钥
            secret_key: Secret密钥
            passphrase: 密码短语（某些交易所需要）
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase

    @abstractmethod
    async def get_ticker(self, symbol: str) -> Dict:
        """
        获取实时价格

        Args:
            symbol: 交易对，如 BTC-USDT

        Returns:
            {
                "symbol": "BTC-USDT",
                "last": 50000.0,  # 最新价
                "bid": 49999.0,   # 买一价
                "ask": 50001.0,   # 卖一价
                "volume": 1000.0, # 24h成交量
                "timestamp": 1234567890
            }
        """
        pass

    @abstractmethod
    async def get_kline(
        self, symbol: str, timeframe: str = "1m", limit: int = 100
    ) -> List[Dict]:
        """
        获取K线数据

        Args:
            symbol: 交易对
            timeframe: 时间周期 (1m, 5m, 15m, 1h, 4h, 1d等)
            limit: 数据条数

        Returns:
            [
                {
                    "timestamp": 1234567890,
                    "open": 50000.0,
                    "high": 50100.0,
                    "low": 49900.0,
                    "close": 50050.0,
                    "volume": 100.0
                },
                ...
            ]
        """
        pass

    @abstractmethod
    async def get_orderbook(self, symbol: str, depth: int = 20) -> Dict:
        """
        获取订单簿

        Args:
            symbol: 交易对
            depth: 深度

        Returns:
            {
                "bids": [[price, amount], ...],  # 买单
                "asks": [[price, amount], ...],  # 卖单
                "timestamp": 1234567890
            }
        """
        pass

    @abstractmethod
    async def get_balance(self) -> Dict:
        """
        获取账户余额

        Returns:
            {
                "BTC": {"free": 1.0, "locked": 0.5, "total": 1.5},
                "USDT": {"free": 10000.0, "locked": 0.0, "total": 10000.0},
                ...
            }
        """
        pass

    @abstractmethod
    async def create_order(
        self,
        symbol: str,
        side: str,  # "buy" or "sell"
        order_type: str,  # "limit" or "market"
        amount: Decimal,
        price: Optional[Decimal] = None,
    ) -> Dict:
        """
        创建订单

        Args:
            symbol: 交易对
            side: 买卖方向 (buy/sell)
            order_type: 订单类型 (limit/market)
            amount: 数量
            price: 价格（市价单不需要）

        Returns:
            {
                "order_id": "123456",
                "symbol": "BTC-USDT",
                "side": "buy",
                "type": "limit",
                "price": 50000.0,
                "amount": 0.1,
                "status": "submitted",
                "timestamp": 1234567890
            }
        """
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> Dict:
        """
        取消订单

        Args:
            order_id: 订单ID
            symbol: 交易对

        Returns:
            {
                "order_id": "123456",
                "status": "canceled"
            }
        """
        pass

    @abstractmethod
    async def get_order(self, order_id: str, symbol: str) -> Dict:
        """
        获取订单详情

        Args:
            order_id: 订单ID
            symbol: 交易对

        Returns:
            订单详细信息
        """
        pass

    @abstractmethod
    async def get_positions(self) -> List[Dict]:
        """
        获取持仓信息

        Returns:
            [
                {
                    "symbol": "BTC-USDT",
                    "amount": 0.1,
                    "avg_price": 50000.0,
                    "unrealized_pnl": 100.0
                },
                ...
            ]
        """
        pass
