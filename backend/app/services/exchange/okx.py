"""
OKX交易所实现
基于OKX API V5文档
"""
from typing import Dict, List, Optional
from decimal import Decimal
import hmac
import base64
import hashlib
from datetime import datetime, timezone
import asyncio
import aiohttp
import socket
from urllib.parse import urlparse
from loguru import logger
from .base import ExchangeBase


class OKXExchange(ExchangeBase):
    """
    OKX交易所实现类

    文档参考：https://www.okx.com/docs-v5/zh/
    """

    def __init__(self, api_key: str, secret_key: str, passphrase: str, simulated: bool = False, proxy: Optional[str] = None):
        """
        初始化OKX交易所

        Args:
            api_key: API密钥
            secret_key: Secret密钥
            passphrase: API密码短语
            simulated: 是否使用模拟盘（默认False使用实盘）
            proxy: HTTP代理地址,如 http://127.0.0.1:7890
        """
        super().__init__(api_key, secret_key, passphrase)

        # 实盘和模拟盘URL
        self.base_url = "https://www.okx.com"
        self.simulated = simulated
        self.proxy = proxy.strip() if proxy and proxy.strip() else None
        self._proxy_checked = False
        self._instrument_cache: Dict[str, Dict] = {}

        # WebSocket URLs
        if simulated:
            # 模拟盘WebSocket
            self.ws_public_url = "wss://wspap.okx.com:8443/ws/v5/public"
            self.ws_private_url = "wss://wspap.okx.com:8443/ws/v5/private"
            self.ws_business_url = "wss://wspap.okx.com:8443/ws/v5/business"
        else:
            # 实盘WebSocket
            self.ws_public_url = "wss://ws.okx.com:8443/ws/v5/public"
            self.ws_private_url = "wss://ws.okx.com:8443/ws/v5/private"
            self.ws_business_url = "wss://ws.okx.com:8443/ws/v5/business"

        # Session用于复用连接
        self.session: Optional[aiohttp.ClientSession] = None

        # 注意: 模拟盘不使用MockOrderManager，而是直接调用OKX模拟盘API
        # 通过 x-simulated-trading 请求头区分模拟盘和实盘

        logger.info(f"初始化OKX交易所 - 模式: {'模拟盘' if simulated else '实盘'}, 代理: {self.proxy or '未设置'}")

    def _check_proxy_available(self) -> None:
        """Fail fast when a local proxy is configured but not listening."""
        if not self.proxy or self._proxy_checked:
            return

        parsed = urlparse(self.proxy)
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            raise ValueError(f"代理地址格式无效: {self.proxy}")

        if host in {"127.0.0.1", "localhost", "::1"}:
            try:
                with socket.create_connection((host, port), timeout=0.5):
                    pass
            except OSError as exc:
                raise ConnectionError(
                    f"本地代理不可用: {self.proxy}。请启动代理或在 API 配置中改成可用端口。"
                ) from exc

        self._proxy_checked = True

    @staticmethod
    def _plain_decimal(value) -> str:
        if isinstance(value, (Decimal, float)):
            return format(value, 'f')
        return str(value)

    @staticmethod
    def _decimal(value) -> Decimal:
        return Decimal(str(value))

    @classmethod
    def _is_multiple(cls, value: Decimal, step: str) -> bool:
        step_decimal = cls._decimal(step)
        if step_decimal <= 0:
            return True
        return value.remainder_near(step_decimal) == 0

    @classmethod
    def _validate_order_precision(
        cls,
        instrument: Dict,
        amount: Decimal,
        price: Optional[Decimal],
        order_type: str
    ) -> None:
        min_sz = instrument.get("minSz")
        lot_sz = instrument.get("lotSz")
        tick_sz = instrument.get("tickSz")
        amount_decimal = cls._decimal(amount)

        if min_sz and amount_decimal < cls._decimal(min_sz):
            raise ValueError(f"下单数量 {amount_decimal} 小于最小下单量 minSz={min_sz}")
        if lot_sz and not cls._is_multiple(amount_decimal, lot_sz):
            raise ValueError(f"下单数量 {amount_decimal} 不符合数量步长 lotSz={lot_sz}")

        if order_type in {"limit", "post_only", "fok", "ioc"} and price is not None and tick_sz:
            price_decimal = cls._decimal(price)
            if not cls._is_multiple(price_decimal, tick_sz):
                raise ValueError(f"委托价格 {price_decimal} 不符合价格步长 tickSz={tick_sz}")

    @staticmethod
    def _infer_inst_type(symbol: str) -> str:
        parts = symbol.upper().split("-")
        if len(parts) >= 5 and parts[-1] in {"C", "P"}:
            return "OPTION"
        if len(parts) >= 3 and parts[-1] == "SWAP":
            return "SWAP"
        if len(parts) >= 3 and parts[-1].isdigit():
            return "FUTURES"
        return "SPOT"

    async def get_instrument(self, symbol: str) -> Dict:
        """Fetch and cache OKX instrument metadata for exact symbol."""
        if symbol in self._instrument_cache:
            return self._instrument_cache[symbol]

        inst_type = self._infer_inst_type(symbol)
        instruments = await self.get_instruments(inst_type=inst_type, inst_id=symbol)
        if not instruments:
            raise ValueError(f"未找到交易产品: {symbol}")

        instrument = instruments[0]
        state = instrument.get("state")
        if state and state != "live":
            raise ValueError(f"交易产品 {symbol} 当前不可交易，状态: {state}")

        self._instrument_cache[symbol] = instrument
        return instrument

    async def get_ticker(self, symbol: str) -> Dict:
        """
        获取单个产品行情信息

        Args:
            symbol: 产品ID,如 BTC-USDT、BTC-USD-SWAP

        Returns:
            {
                'instType': 'SWAP',
                'instId': 'BTC-USD-SWAP',
                'last': '56956.1',      # 最新成交价
                'lastSz': '3',           # 最新成交量
                'askPx': '56959.1',      # 卖一价
                'askSz': '10582',        # 卖一量
                'bidPx': '56959',        # 买一价
                'bidSz': '4552',         # 买一量
                'open24h': '55926',      # 24小时开盘价
                'high24h': '57641.1',    # 24小时最高价
                'low24h': '54570.1',     # 24小时最低价
                'volCcy24h': '81137.755',# 24小时成交量(币)
                'vol24h': '46258703',    # 24小时成交量(张)
                'ts': '1620289117764',   # 时间戳
                'sodUtc0': '55926',      # UTC+0开盘价
                'sodUtc8': '55926'       # UTC+8开盘价
            }
        """
        endpoint = "/api/v5/market/ticker"
        params = {"instId": symbol}

        response = await self._request(
            method="GET",
            endpoint=endpoint,
            params=params,
            auth_required=False  # 公共接口不需要认证
        )

        # OKX响应格式: {"code": "0", "msg": "", "data": [...]}
        if response.get("code") != "0":
            raise Exception(f"获取ticker失败: {response.get('msg')}")

        data = response.get("data", [])
        if not data:
            raise Exception(f"未找到产品 {symbol} 的行情数据")

        return data[0]

    async def get_tickers(self, inst_type: str = "SWAP") -> List[Dict]:
        """
        获取某类产品的全量行情信息。

        Args:
            inst_type: 产品类型，如 SPOT / SWAP / FUTURES / OPTION

        Returns:
            OKX /market/tickers 的 data 数组
        """
        endpoint = "/api/v5/market/tickers"
        params = {"instType": inst_type}

        response = await self._request(
            method="GET",
            endpoint=endpoint,
            params=params,
            auth_required=False
        )

        if response.get("code") != "0":
            raise Exception(f"获取tickers失败: {response.get('msg')}")

        return response.get("data", [])

    async def get_kline(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None
    ) -> List[Dict]:
        """
        获取K线数据

        Args:
            symbol: 产品ID,如 BTC-USDT
            timeframe: 时间粒度,默认1m
                支持: 1m/3m/5m/15m/30m/1H/2H/4H
                UTC+8: 6H/12H/1D/2D/3D/1W/1M/3M
                UTC+0: 6Hutc/12Hutc/1Dutc/2Dutc/3Dutc/1Wutc/1Mutc/3Mutc
            limit: 返回K线数量,最大300,默认100
            after: 请求此时间戳之前的数据(更旧)
            before: 请求此时间戳之后的数据(更新)

        Returns:
            [
                {
                    'ts': '1597026383085',      # 开始时间
                    'o': '3.721',                # 开盘价
                    'h': '3.743',                # 最高价
                    'l': '3.677',                # 最低价
                    'c': '3.708',                # 收盘价
                    'vol': '8422410',            # 交易量(张)
                    'volCcy': '22698348.04',     # 交易量(币)
                    'volCcyQuote': '12698348.04',# 交易量(计价货币)
                    'confirm': '0'               # 0:未完结 1:已完结
                },
                ...
            ]
        """
        endpoint = "/api/v5/market/candles"
        params = {
            "instId": symbol,
            "bar": timeframe,
            "limit": str(limit)
        }

        if after:
            params["after"] = after
        if before:
            params["before"] = before

        response = await self._request(
            method="GET",
            endpoint=endpoint,
            params=params,
            auth_required=False
        )

        if response.get("code") != "0":
            raise Exception(f"获取K线失败: {response.get('msg')}")

        # 返回的data是二维数组: [[ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm], ...]
        raw_data = response.get("data", [])

        # 转换为字典格式方便使用
        result = []
        for candle in raw_data:
            result.append({
                'ts': candle[0],
                'o': candle[1],
                'h': candle[2],
                'l': candle[3],
                'c': candle[4],
                'vol': candle[5],
                'volCcy': candle[6],
                'volCcyQuote': candle[7],
                'confirm': candle[8]
            })

        return result

    async def get_history_kline(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None
    ) -> List[Dict]:
        """
        获取历史K线数据。

        OKX /market/candles 只覆盖较近数据；更长时间跨度回测应使用
        /market/history-candles。
        """
        endpoint = "/api/v5/market/history-candles"
        params = {
            "instId": symbol,
            "bar": timeframe,
            "limit": str(limit)
        }

        if after:
            params["after"] = after
        if before:
            params["before"] = before

        response = await self._request(
            method="GET",
            endpoint=endpoint,
            params=params,
            auth_required=False
        )

        if response.get("code") != "0":
            raise Exception(f"获取历史K线失败: {response.get('msg')}")

        result = []
        for candle in response.get("data", []):
            result.append({
                'ts': candle[0],
                'o': candle[1],
                'h': candle[2],
                'l': candle[3],
                'c': candle[4],
                'vol': candle[5],
                'volCcy': candle[6],
                'volCcyQuote': candle[7],
                'confirm': candle[8]
            })

        return result

    async def get_orderbook(self, symbol: str, depth: int = 20) -> Dict:
        """
        获取产品深度(订单簿)

        Args:
            symbol: 产品ID,如 BTC-USDT
            depth: 深度档位数量,最大400,默认20

        Returns:
            {
                'asks': [
                    ['41006.8', '0.60038921', '0', '1'],  # [价格, 数量, 弃用字段, 订单数]
                    ...
                ],
                'bids': [
                    ['41006.3', '0.30178218', '0', '2'],
                    ...
                ],
                'ts': '1629966436396'  # 时间戳
            }

        Note:
            - 合约: 数量为合约张数
            - 现货: 数量为交易币数量
            - 数据每50ms更新一次
        """
        endpoint = "/api/v5/market/books"
        params = {
            "instId": symbol,
            "sz": str(min(depth, 400))  # 最大400档
        }

        response = await self._request(
            method="GET",
            endpoint=endpoint,
            params=params,
            auth_required=False
        )

        if response.get("code") != "0":
            raise Exception(f"获取深度失败: {response.get('msg')}")

        data = response.get("data", [])
        if not data:
            raise Exception(f"未找到产品 {symbol} 的深度数据")

        return data[0]

    async def get_instruments(
        self,
        inst_type: str = "SPOT",
        uly: Optional[str] = None,
        inst_id: Optional[str] = None
    ) -> List[Dict]:
        """
        获取交易产品基础信息(公共API,无需认证)

        Args:
            inst_type: 产品类型
                SPOT: 币币
                SWAP: 永续合约
                FUTURES: 交割合约
                OPTION: 期权
            uly: 标的指数,如 BTC-USD (仅适用于交割/永续/期权)
            inst_id: 产品ID,如 BTC-USDT

        Returns:
            [
                {
                    'instId': 'BTC-USDT',           # 产品ID
                    'instType': 'SPOT',              # 产品类型
                    'baseCcy': 'BTC',                # 交易货币币种
                    'quoteCcy': 'USDT',              # 计价货币币种
                    'settleCcy': '',                 # 盈亏结算和保证金币种
                    'ctVal': '',                     # 合约面值
                    'ctMult': '',                    # 合约乘数
                    'ctValCcy': '',                  # 合约面值计价币种
                    'optType': '',                   # 期权类型
                    'stk': '',                       # 行权价格
                    'listTime': '1606468800000',     # 上线时间
                    'expTime': '',                   # 到期时间
                    'lever': '10',                   # 最大杠杆倍数
                    'tickSz': '0.1',                 # 下单价格精度
                    'lotSz': '0.00000001',           # 下单数量精度
                    'minSz': '0.00001',              # 最小下单数量
                    'ctType': 'linear',              # 合约类型
                    'alias': '',                     # 合约日期别名
                    'state': 'live',                 # 产品状态 live/suspend/preopen/test
                    'maxLmtSz': '9999999',           # 最大限价单数量
                    'maxMktSz': '1000000',           # 最大市价单数量
                    'maxTwapSz': '1000000',          # 最大冰山/时间加权数量
                    'maxIcebergSz': '1000000',       # 最大冰山数量
                    'maxTriggerSz': '9999999',       # 最大计划单数量
                    'maxStopSz': '9999999',          # 最大止盈止损数量
                    ...
                }
            ]

        Note:
            - 公共数据,无需认证
            - 仅返回状态为 live 的产品
        """
        endpoint = "/api/v5/public/instruments"
        params = {"instType": inst_type}

        if uly:
            params["uly"] = uly
        if inst_id:
            params["instId"] = inst_id

        response = await self._request(
            method="GET",
            endpoint=endpoint,
            params=params,
            auth_required=False
        )

        if response.get("code") != "0":
            raise Exception(f"获取交易产品失败: {response.get('msg')}")

        return response.get("data", [])

    async def get_balance(self, ccy: Optional[str] = None) -> Dict:
        """
        获取账户余额

        Args:
            ccy: 币种,如 BTC。支持多币种查询(不超过20个),逗号分隔,如 "BTC,ETH"
                 不传则返回所有资产余额

        Returns:
            {
                'uTime': '1705474164160',        # 更新时间
                'totalEq': '55837.43556134779',  # 美金层面权益
                'isoEq': '0',                     # 逐仓仓位权益
                'adjEq': '55415.624719833286',    # 有效保证金
                'ordFroz': '',                    # 挂单占用保证金
                'imr': '0',                       # 占用保证金
                'mmr': '0',                       # 维持保证金
                'mgnRatio': '',                   # 维持保证金率
                'notionalUsd': '0',               # 持仓数量(美元)
                'details': [                      # 各币种详细信息
                    {
                        'ccy': 'USDT',
                        'eq': '4992.890093622894',      # 币种总权益
                        'cashBal': '4850.435693622894', # 币种余额
                        'availBal': '4834.317093622894',# 可用余额
                        'frozenBal': '158.573',         # 占用金额
                        'ordFrozen': '0',               # 挂单冻结
                        'liab': '0',                    # 负债额
                        'upl': '-7.545600000000006',    # 未实现盈亏
                        'uTime': '1705449605015',       # 更新时间
                        ...
                    }
                ]
            }

        Note:
            需要API密钥认证
        """
        endpoint = "/api/v5/account/balance"
        params = {}
        if ccy:
            params["ccy"] = ccy

        response = await self._request(
            method="GET",
            endpoint=endpoint,
            params=params if params else None,
            auth_required=True  # 账户接口需要认证
        )

        if response.get("code") != "0":
            raise Exception(f"获取余额失败: {response.get('msg')}")

        data = response.get("data", [])
        if not data:
            raise Exception("账户余额数据为空")

        return data[0]

    async def get_pending_algo_orders(
        self,
        ord_type: str = "conditional",
        inst_type: Optional[str] = None,
        inst_id: Optional[str] = None,
    ) -> List[Dict]:
        """Return untriggered algo orders used to detect live stop protection."""
        params = {"ordType": ord_type}
        if inst_type:
            params["instType"] = inst_type
        if inst_id:
            params["instId"] = inst_id
        response = await self._request(
            method="GET",
            endpoint="/api/v5/trade/orders-algo-pending",
            params=params,
            auth_required=True,
        )
        if response.get("code") != "0":
            raise Exception(f"获取未触发策略委托失败: {response.get('msg')}")
        return response.get("data", [])

    async def get_leverage(self, inst_id: str, mgn_mode: str = "cross") -> Dict:
        """
        获取杠杆倍数

        Args:
            inst_id: 产品ID,如 BTC-USDT-SWAP
            mgn_mode: 保证金模式 cross(全仓) / isolated(逐仓)

        Returns:
            {
                'instId': 'BTC-USDT-SWAP',
                'mgnMode': 'cross',
                'posSide': 'net',
                'lever': '10'  # 杠杆倍数
            }
        """
        endpoint = "/api/v5/account/leverage-info"
        params = {
            "instId": inst_id,
            "mgnMode": mgn_mode
        }

        response = await self._request(
            method="GET",
            endpoint=endpoint,
            params=params,
            auth_required=True
        )

        if response.get("code") != "0":
            raise Exception(f"获取杠杆倍数失败: {response.get('msg')}")

        data = response.get("data", [])
        if not data:
            raise Exception("杠杆倍数数据为空")

        return data[0]

    async def set_leverage(
        self,
        lever: str,
        mgn_mode: str = "cross",
        inst_id: Optional[str] = None,
        ccy: Optional[str] = None,
        pos_side: Optional[str] = None
    ) -> Dict:
        """
        设置杠杆倍数

        Args:
            lever: 杠杆倍数,如 "10"
            mgn_mode: 保证金模式 cross(全仓) / isolated(逐仓)
            inst_id: 产品ID,如 BTC-USDT-SWAP (SWAP/FUTURES必填)
            ccy: 币种,如 BTC (币币杠杆必填)
            pos_side: 持仓方向 long(开多)/short(开空)/net(买卖模式,默认)

        Returns:
            {
                'instId': 'BTC-USDT-SWAP',
                'lever': '10',
                'mgnMode': 'cross',
                'posSide': 'net'
            }

        Note:
            - 永续合约/交割合约: 需要传入 inst_id
            - 币币杠杆: 需要传入 ccy
            - 买卖模式下 pos_side 传 net 或不传
            - 开平仓模式下 pos_side 传 long 或 short
        """
        endpoint = "/api/v5/account/set-leverage"

        data = {
            "lever": lever,
            "mgnMode": mgn_mode
        }

        if inst_id:
            data["instId"] = inst_id
        if ccy:
            data["ccy"] = ccy
        if pos_side:
            data["posSide"] = pos_side

        response = await self._request(
            method="POST",
            endpoint=endpoint,
            data=data,
            auth_required=True
        )

        if response.get("code") != "0":
            raise Exception(f"设置杠杆倍数失败: {response.get('msg')}")

        data = response.get("data", [])
        if not data:
            raise Exception("设置杠杆倍数返回数据为空")

        return data[0]

    async def set_position_mode(self, pos_mode: str = "long_short_mode") -> Dict:
        """
        设置持仓模式

        Args:
            pos_mode: 持仓模式
                - long_short_mode: 开平仓模式（双向持仓，支持同时持有多空）
                - net_mode: 买卖模式（单向持仓，默认）

        Returns:
            {'posMode': 'long_short_mode'}
        """
        response = await self._request(
            method="POST",
            endpoint="/api/v5/account/set-position-mode",
            data={"posMode": pos_mode},
            auth_required=True
        )

        if response.get("code") != "0":
            raise Exception(f"设置持仓模式失败: {response.get('msg')}")

        data = response.get("data", [{}])
        return data[0] if data else {}

    async def get_account_config(self) -> Dict:
        """
        获取账户配置，包含当前持仓模式 posMode。

        posMode:
            - long_short_mode: 开平仓模式（双向持仓）
            - net_mode: 买卖模式（单向净持仓）
        """
        response = await self._request(
            method="GET",
            endpoint="/api/v5/account/config",
            auth_required=True
        )

        if response.get("code") != "0":
            raise Exception(f"获取账户配置失败: {response.get('msg')}")

        data = response.get("data", [])
        if not data:
            raise Exception("账户配置返回数据为空")
        return data[0]

    async def create_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        amount: Decimal,
        price: Optional[Decimal] = None,
        td_mode: str = "cash",
        cl_ord_id: Optional[str] = None,
        pos_side: Optional[str] = None,
        reduce_only: bool = False,
        tgt_ccy: Optional[str] = None,
        attach_algo_ords: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        创建订单

        Args:
            symbol: 产品ID,如 BTC-USDT
            side: 订单方向 buy/sell
            order_type: 订单类型
                market: 市价单
                limit: 限价单
                post_only: 只做maker单
                fok: 全部成交或立即取消
                ioc: 立即成交并取消剩余
            amount: 委托数量
            price: 委托价格(limit/post_only/fok/ioc必填)
            td_mode: 交易模式
                cash: 非保证金(现货)
                isolated: 逐仓
                cross: 全仓
            cl_ord_id: 客户自定义订单ID(1-32位字母数字)
            pos_side: 持仓方向(开平仓模式必填)
                long: 开多/平多
                short: 开空/平空
                net: 买卖模式
            reduce_only: 是否只减仓,默认False
            tgt_ccy: 市价单委托数量单位(仅币币市价单)
                base_ccy: 交易货币
                quote_ccy: 计价货币

        Returns:
            {
                'ordId': '12345689',           # 订单ID
                'clOrdId': 'oktswap6',         # 客户自定义ID
                'tag': '',                      # 订单标签
                'ts': '1695190491421',         # 时间戳
                'sCode': '0',                   # 执行结果码
                'sMsg': ''                      # 执行消息
            }

        Note:
            - 需要API密钥认证
            - 仅当账户有足够资金时才能下单
            - 市价单会多冻结5%资产确保成交
            - 模拟盘和实盘都调用真实的OKX API，通过请求头区分环境
        """
        # 模拟盘和实盘都调用真实的OKX API
        # 模拟盘通过 x-simulated-trading 请求头标识
        endpoint = "/api/v5/trade/order"

        side = side.lower()
        order_type = order_type.lower()
        td_mode = td_mode.lower()
        if side not in {"buy", "sell"}:
            raise ValueError("订单方向必须是 buy 或 sell")
        if order_type not in {"market", "limit", "post_only", "fok", "ioc"}:
            raise ValueError("订单类型必须是 market/limit/post_only/fok/ioc")
        if td_mode not in {"cash", "cross", "isolated"}:
            raise ValueError("交易模式必须是 cash/cross/isolated")

        instrument = await self.get_instrument(symbol)
        inst_type = instrument.get("instType", self._infer_inst_type(symbol))
        is_derivative = inst_type in {"SWAP", "FUTURES", "OPTION"}
        self._validate_order_precision(instrument, amount, price, order_type)

        if is_derivative and td_mode == "cash":
            raise ValueError(f"{symbol} 是 {inst_type} 产品，td_mode 不能为 cash，请使用 cross 或 isolated")
        if is_derivative:
            ct_val = instrument.get("ctVal")
            if not ct_val:
                raise ValueError(f"无法获取 {symbol} 的合约面值 ctVal，拒绝下单")
            if tgt_ccy:
                raise ValueError(
                    f"{symbol} 是 {inst_type} 产品，当前接口的 amount 必须是合约张数。"
                    "如需按 USDT 名义价值或保证金金额下单，需要先换算并确认张数。"
                )
            logger.info(
                f"合约下单预检: instId={symbol}, instType={inst_type}, ctVal={ct_val}, "
                f"ctValCcy={instrument.get('ctValCcy')}, sz={amount}, tgtCcy={tgt_ccy or 'contracts'}"
            )
            if symbol.upper().endswith("-USD-SWAP"):
                logger.warning(f"{symbol} 是币本位反向合约，保证金和盈亏通常按币结算，不是 USDT")
        elif tgt_ccy and tgt_ccy not in {"base_ccy", "quote_ccy"}:
            raise ValueError("现货市价单 tgt_ccy 只能是 base_ccy 或 quote_ccy")

        if order_type != "market" and tgt_ccy:
            raise ValueError("tgt_ccy 仅适用于市价单")

        # 确保数量使用普通十进制格式，避免科学计数法
        amount_str = self._plain_decimal(amount)

        data = {
            "instId": symbol,
            "tdMode": td_mode,
            "side": side,
            "ordType": order_type,
            "sz": amount_str
        }

        # 限价单必须指定价格
        if order_type in ["limit", "post_only", "fok", "ioc"]:
            if price is None:
                raise ValueError(f"订单类型 {order_type} 必须指定价格")
            # 确保价格使用普通十进制格式，避免科学计数法
            data["px"] = self._plain_decimal(price)

        # 可选参数
        if cl_ord_id:
            data["clOrdId"] = cl_ord_id
        if pos_side:
            data["posSide"] = pos_side
        if reduce_only:
            data["reduceOnly"] = str(reduce_only).lower()
        if tgt_ccy:
            data["tgtCcy"] = tgt_ccy
        if attach_algo_ords:
            data["attachAlgoOrds"] = attach_algo_ords

        response = await self._request(
            method="POST",
            endpoint=endpoint,
            data=data,
            auth_required=True
        )

        if response.get("code") != "0":
            # 尝试获取详细错误信息
            result_data = response.get("data", [])
            if result_data and isinstance(result_data, list) and len(result_data) > 0:
                error_code = result_data[0].get("sCode", "")
                error_msg = result_data[0].get("sMsg", "")
                if error_code or error_msg:
                    raise Exception(f"下单失败 [{error_code}]: {error_msg}")
            raise Exception(f"下单失败: {response.get('msg')}")

        result_data = response.get("data", [])
        if not result_data:
            raise Exception("下单返回数据为空")

        order_result = result_data[0]

        # 检查订单执行结果
        if order_result.get("sCode") != "0":
            error_code = order_result.get("sCode", "")
            error_msg = order_result.get("sMsg", "")
            raise Exception(f"下单执行失败 [{error_code}]: {error_msg}")

        if is_derivative:
            order_result["instType"] = inst_type
            order_result["ctVal"] = instrument.get("ctVal")
            order_result["ctValCcy"] = instrument.get("ctValCcy")
            order_result["sizeUnit"] = "contracts"

        return order_result

    async def cancel_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        cl_ord_id: Optional[str] = None
    ) -> Dict:
        """
        取消订单

        Args:
            symbol: 产品ID,如 BTC-USDT
            order_id: 订单ID(order_id和cl_ord_id至少传一个)
            cl_ord_id: 客户自定义订单ID

        Returns:
            {
                'ordId': '12345689',      # 订单ID
                'clOrdId': 'oktswap6',    # 客户自定义ID
                'ts': '1695190491421',    # 时间戳
                'sCode': '0',             # 执行结果码
                'sMsg': ''                # 执行消息
            }

        Note:
            - 需要API密钥认证
            - 撤单成功(sCode=0)不代表订单已撤销,以订单状态为准
            - order_id和cl_ord_id至少传一个,若都传则以order_id为主
        """
        if not order_id and not cl_ord_id:
            raise ValueError("order_id和cl_ord_id至少需要传一个")

        # 调用OKX API撤销订单（包括模拟盘和实盘）
        endpoint = "/api/v5/trade/cancel-order"

        data = {"instId": symbol}

        if order_id:
            data["ordId"] = order_id
        if cl_ord_id:
            data["clOrdId"] = cl_ord_id

        response = await self._request(
            method="POST",
            endpoint=endpoint,
            data=data,
            auth_required=True
        )

        if response.get("code") != "0":
            raise Exception(f"撤单失败: {response.get('msg')}")

        result_data = response.get("data", [])
        if not result_data:
            raise Exception("撤单返回数据为空")

        cancel_result = result_data[0]

        # 检查撤单执行结果
        if cancel_result.get("sCode") != "0":
            raise Exception(f"撤单执行失败: {cancel_result.get('sMsg')}")

        return cancel_result

    async def get_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        cl_ord_id: Optional[str] = None
    ) -> Dict:
        """
        获取订单详情

        Args:
            symbol: 产品ID,如 BTC-USDT
            order_id: 订单ID(order_id和cl_ord_id至少传一个)
            cl_ord_id: 客户自定义订单ID

        Returns:
            {
                'instType': 'SPOT',            # 产品类型
                'instId': 'BTC-USDT',          # 产品ID
                'ordId': '680800019749904384', # 订单ID
                'clOrdId': '',                 # 客户自定义ID
                'tag': '',                     # 订单标签
                'px': '',                      # 委托价格
                'sz': '100',                   # 委托数量
                'ordType': 'market',           # 订单类型
                'side': 'buy',                 # 订单方向
                'posSide': 'net',              # 持仓方向
                'tdMode': 'cash',              # 交易模式
                'accFillSz': '0.00192834',     # 累计成交数量
                'fillPx': '51858',             # 最新成交价格
                'fillSz': '0.00192834',        # 最新成交数量
                'fillTime': '1708587373361',   # 最新成交时间
                'avgPx': '51858',              # 成交均价
                'state': 'filled',             # 订单状态
                'lever': '',                   # 杠杆倍数
                'tgtCcy': 'quote_ccy',         # 市价单数量单位
                'fee': '-0.00000192834',       # 手续费
                'feeCcy': 'BTC',               # 手续费币种
                'rebate': '0',                 # 返佣
                'rebateCcy': 'USDT',           # 返佣币种
                'pnl': '0',                    # 收益
                'cTime': '1708587373361',      # 创建时间
                'uTime': '1708587373362',      # 更新时间
                ...
            }

        Note:
            - 需要API密钥认证
            - 仅适用于交易中的产品
            - 订单状态: canceled/live/partially_filled/filled/mmp_canceled
        """
        if not order_id and not cl_ord_id:
            raise ValueError("order_id和cl_ord_id至少需要传一个")

        # 调用OKX API获取订单详情（包括模拟盘和实盘）
        endpoint = "/api/v5/trade/order"

        params = {"instId": symbol}

        if order_id:
            params["ordId"] = order_id
        if cl_ord_id:
            params["clOrdId"] = cl_ord_id

        response = await self._request(
            method="GET",
            endpoint=endpoint,
            params=params,
            auth_required=True
        )

        if response.get("code") != "0":
            raise Exception(f"获取订单失败: {response.get('msg')}")

        data = response.get("data", [])
        if not data:
            raise Exception(f"未找到订单信息")

        return data[0]

    async def get_orders_pending(
        self,
        inst_type: str = "SPOT",
        inst_id: Optional[str] = None,
        state: Optional[str] = None
    ) -> List[Dict]:
        """
        获取未完成订单列表

        Args:
            inst_type: 产品类型 SPOT/MARGIN/SWAP/FUTURES/OPTION
            inst_id: 产品ID,如 BTC-USDT
            state: 订单状态 live/partially_filled

        Returns:
            [
                {
                    'instId': 'BTC-USDT',
                    'ordId': '680800019749904384',
                    'clOrdId': '',
                    'px': '50000',
                    'sz': '0.001',
                    'ordType': 'limit',
                    'side': 'buy',
                    'state': 'live',
                    'accFillSz': '0',
                    'avgPx': '',
                    'cTime': '1708587373361',
                    'uTime': '1708587373362',
                    ...
                }
            ]
        """
        # 调用OKX API获取未完成订单（包括模拟盘和实盘）
        endpoint = "/api/v5/trade/orders-pending"

        params = {"instType": inst_type}

        if inst_id:
            params["instId"] = inst_id
        if state:
            params["state"] = state

        response = await self._request(
            method="GET",
            endpoint=endpoint,
            params=params,
            auth_required=True
        )

        if response.get("code") != "0":
            raise Exception(f"获取未完成订单列表失败: {response.get('msg')}")

        return response.get("data", [])

    async def get_orders_history(
        self,
        inst_type: str = "SPOT",
        inst_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        获取历史订单列表(近7天)

        Args:
            inst_type: 产品类型 SPOT/MARGIN/SWAP/FUTURES/OPTION
            inst_id: 产品ID,如 BTC-USDT
            state: 订单状态 canceled/filled
            limit: 返回数量,最大100

        Returns:
            订单列表,格式同 get_orders_pending
        """
        endpoint = "/api/v5/trade/orders-history"

        params = {
            "instType": inst_type,
            "limit": str(limit)
        }

        if inst_id:
            params["instId"] = inst_id
        if state:
            params["state"] = state

        response = await self._request(
            method="GET",
            endpoint=endpoint,
            params=params,
            auth_required=True
        )

        if response.get("code") != "0":
            raise Exception(f"获取历史订单列表失败: {response.get('msg')}")

        return response.get("data", [])

    async def get_positions(
        self,
        inst_type: Optional[str] = None,
        inst_id: Optional[str] = None,
        pos_id: Optional[str] = None
    ) -> List[Dict]:
        """
        获取持仓信息

        Args:
            inst_type: 产品类型
                MARGIN: 币币杠杆
                SWAP: 永续合约
                FUTURES: 交割合约
                OPTION: 期权
            inst_id: 产品ID,如 BTC-USDT-SWAP。支持多个(不超过10个),逗号分隔
            pos_id: 持仓ID。支持多个(不超过20个),逗号分隔

        Returns:
            [
                {
                    'instId': 'BTC-USDT',           # 产品ID
                    'instType': 'MARGIN',           # 产品类型
                    'mgnMode': 'isolated',          # 保证金模式 cross/isolated
                    'posId': '1752810569801498626', # 持仓ID
                    'posSide': 'net',               # 持仓方向 long/short/net
                    'pos': '0.00190433573',         # 持仓数量
                    'posCcy': 'BTC',                # 仓位资产币种
                    'availPos': '0.00190433573',    # 可平仓数量
                    'avgPx': '62961.4',             # 开仓均价
                    'upl': '-0.0000033452492717',   # 未实现收益
                    'uplRatio': '-0.0105311101755551', # 未实现收益率
                    'lever': '5',                   # 杠杆倍数
                    'liqPx': '53615.448336593756',  # 预估强平价
                    'markPx': '62891.9',            # 标记价格
                    'imr': '',                      # 初始保证金
                    'margin': '0.000317654',        # 保证金余额
                    'mgnRatio': '9.404143929947395',# 维持保证金率
                    'mmr': '0.0000318005395854',    # 维持保证金
                    'liab': '-99.9998177776581948', # 负债额
                    'liabCcy': 'USDT',              # 负债币种
                    'interest': '0',                # 利息
                    'notionalUsd': '119.756628017499', # 持仓美元价值
                    'adl': '1',                     # ADL信号区(1-5)
                    'ccy': 'BTC',                   # 占用保证金币种
                    'last': '62892.9',              # 最新成交价
                    'idxPx': '62890.5',             # 最新指数价格
                    'cTime': '1724740225685',       # 持仓创建时间
                    'uTime': '1724742632153',       # 最后更新时间
                    ...
                }
            ]

        Note:
            - 需要API密钥认证
            - 仅返回有实际持仓的信息
            - 按仓位创建时间倒序排列
        """
        endpoint = "/api/v5/account/positions"
        params = {}

        if inst_type:
            params["instType"] = inst_type
        if inst_id:
            params["instId"] = inst_id
        if pos_id:
            params["posId"] = pos_id

        response = await self._request(
            method="GET",
            endpoint=endpoint,
            params=params if params else None,
            auth_required=True
        )

        if response.get("code") != "0":
            raise Exception(f"获取持仓失败: {response.get('msg')}")

        return response.get("data", [])

    # 辅助方法

    def _get_timestamp(self) -> str:
        """
        获取ISO格式的UTC时间戳
        格式：2020-12-08T09:08:57.715Z
        """
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """
        生成OKX API签名

        签名算法：
        1. 拼接字符串：timestamp + method + requestPath + body
        2. 使用HMAC SHA256加密
        3. Base64编码

        Args:
            timestamp: ISO格式时间戳，如 2020-12-08T09:08:57.715Z
            method: 请求方法，大写，如 GET、POST
            request_path: 请求路径，如 /api/v5/account/balance?ccy=BTC
            body: 请求体JSON字符串，GET请求为空字符串

        Returns:
            Base64编码的签名字符串
        """
        # 拼接待签名字符串
        message = timestamp + method.upper() + request_path + body

        # HMAC SHA256加密
        mac = hmac.new(
            bytes(self.secret_key, encoding='utf-8'),
            bytes(message, encoding='utf-8'),
            digestmod=hashlib.sha256
        )

        # Base64编码
        signature = base64.b64encode(mac.digest()).decode('utf-8')

        logger.debug(f"生成签名 - message: {message[:50]}..., signature: {signature[:20]}...")
        return signature

    def _get_headers(self, timestamp: str, method: str, request_path: str, body: str = "") -> Dict:
        """
        生成OKX API请求头

        Args:
            timestamp: ISO格式时间戳
            method: 请求方法
            request_path: 请求路径
            body: 请求体

        Returns:
            请求头字典
        """
        signature = self._generate_signature(timestamp, method, request_path, body)

        headers = {
            'OK-ACCESS-KEY': self.api_key,
            'OK-ACCESS-SIGN': signature,
            'OK-ACCESS-TIMESTAMP': timestamp,
            'OK-ACCESS-PASSPHRASE': self.passphrase,
            'Content-Type': 'application/json'
        }

        # 模拟盘需要添加特殊header
        if self.simulated:
            headers['x-simulated-trading'] = '1'

        return headers

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建aiohttp session"""
        if self.session is None or self.session.closed:
            # 创建连接器 - 优化连接池配置
            connector = aiohttp.TCPConnector(
                ssl=False if self.proxy else None,  # 代理时禁用SSL验证
                limit=100,  # 总连接数限制
                limit_per_host=30,  # 每个主机的连接数限制
                ttl_dns_cache=300,  # DNS缓存时间(秒)
                keepalive_timeout=60,  # keepalive超时时间
                enable_cleanup_closed=True,  # 启用关闭连接清理
                force_close=False  # 不强制关闭连接，允许复用
            )
            self.session = aiohttp.ClientSession(connector=connector)
        return self.session

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        auth_required: bool = True
    ) -> Dict:
        """
        发送HTTP请求

        Args:
            method: 请求方法（GET/POST）
            endpoint: API端点，如 /api/v5/market/ticker
            params: URL参数（用于GET请求）
            data: 请求体数据（用于POST请求）
            auth_required: 是否需要认证

        Returns:
            API响应数据
        """
        session = await self._get_session()
        self._check_proxy_available()

        # 构建完整URL
        url = self.base_url + endpoint

        # 构建request_path（包含查询参数）
        request_path = endpoint
        if params:
            query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
            request_path = f"{endpoint}?{query_string}"

        # 构建请求体
        body_str = ""
        if data:
            import json
            body_str = json.dumps(data)

        # 构建请求头
        headers = {}
        if auth_required:
            timestamp = self._get_timestamp()
            headers = self._get_headers(timestamp, method, request_path, body_str)
        else:
            headers = {'Content-Type': 'application/json'}

        logger.info(f"请求 {method} {url} - params: {params}, auth: {auth_required}, proxy: {self.proxy or '未设置'}")
        if data:
            logger.debug(f"请求体: {data}")

        # 重试配置
        max_retries = 3
        retry_delay = 1  # 秒

        for attempt in range(max_retries):
            try:
                # 构建请求参数
                request_kwargs = {
                    "method": method,
                    "url": url,
                    "headers": headers,
                    "params": params,
                    "json": data,
                    "timeout": aiohttp.ClientTimeout(total=30)  # 增加超时时间到30秒
                }

                # 如果配置了代理，添加代理参数
                if self.proxy:
                    request_kwargs["proxy"] = self.proxy
                    logger.debug(f"使用代理: {self.proxy}")

                async with session.request(**request_kwargs) as response:
                    response_data = await response.json()

                    logger.debug(f"响应: {response.status} - {response_data}")

                    if response.status != 200:
                        logger.error(f"API请求失败: {response.status} - {response_data}")
                        raise Exception(f"OKX API Error: {response_data}")

                    return response_data

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                # 网络相关错误才重试
                if attempt < max_retries - 1:
                    logger.warning(
                        f"请求失败 (尝试 {attempt + 1}/{max_retries}): {e}, "
                        f"proxy={self.proxy or '未设置'}, {retry_delay}秒后重试..."
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避
                else:
                    logger.error(
                        f"请求失败，已达最大重试次数: {e}. proxy={self.proxy or '未设置'}。"
                        "如果当前网络无法直连OKX，请启动本地代理，并在 API 配置或 backend/.env 中设置 "
                        "OKX_PROXY=http://127.0.0.1:7897"
                    )
                    if isinstance(e, aiohttp.ClientConnectorError):
                        raise ConnectionError(
                            "连接 OKX 失败：当前没有可用代理或网络无法直连。"
                            "请启动本地代理，并在 API 配置里填写代理地址，例如 http://127.0.0.1:7897。"
                        ) from e
                    raise
            except Exception as e:
                # 其他错误直接抛出
                logger.error(f"请求异常: {e}")
                raise

    async def close(self):
        """关闭session"""
        if self.session and not self.session.closed:
            await self.session.close()
