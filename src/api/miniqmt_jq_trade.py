# coding:utf-8

import requests
from typing import Dict, List, Any
from datetime import datetime, timedelta
import time
import threading
from enum import Enum
from xtquant import xtdata, xttrader
from xtquant.xttype import StockAccount
from xtquant import xtconstant
from xtquant.xttrader import XtQuantTraderCallback

# ==================== 环境配置 ====================
# 环境选择: "simulation" 或 "production"
ENVIRONMENT = "production"  # 修改此值切换环境: "simulation" 或 "production"

# 模拟环境配置
SIMULATION_CONFIG = {
    "account_id": "62048093",  # 模拟账户ID
    "qmt_path": r"C:\Users\Administrator\Desktop\国金QMT交易端模拟\userdata_mini",  # 模拟环境QMT路径
}

# 正式环境配置
PRODUCTION_CONFIG = {
    "account_id": "8885126711",  # 正式账户ID
    "qmt_path": r"C:\Users\Administrator\Desktop\qmt-production\国金证券QMT交易端\userdata_mini",  # 正式环境QMT路径
}

# 根据环境选择配置
if ENVIRONMENT == "simulation":
    CONFIG = SIMULATION_CONFIG
    print("=" * 50)
    print("当前运行环境: 模拟环境 (SIMULATION)")
    print("=" * 50)
elif ENVIRONMENT == "production":
    CONFIG = PRODUCTION_CONFIG
    print("=" * 50)
    print("当前运行环境: 正式环境 (PRODUCTION)")
    print("=" * 50)
else:
    raise ValueError(
        f"无效的环境配置: {ENVIRONMENT}，请设置为 'simulation' 或 'production'"
    )

# 提取配置值
ACCOUNT_ID = CONFIG["account_id"]
QMT_PATH = CONFIG["qmt_path"]

print(f"账户ID: {ACCOUNT_ID}")
print(f"QMT路径: {QMT_PATH}")
print("=" * 50)
# ==================== 环境配置结束 ====================


def _get_order_status_constant(
    new_name: str, old_name: str = None, default_value: int = None
):
    """安全获取订单状态常量，支持多种命名方式

    Args:
        new_name: 新的常量名（如 ORDER_SUCCEEDED）
        old_name: 旧的常量名（如 ORDER_STATUS_ALLTRADED）
        default_value: 如果都不存在，使用的默认数值

    Returns:
        常量值
    """
    try:
        return getattr(xtconstant, new_name)
    except AttributeError:
        if old_name:
            try:
                return getattr(xtconstant, old_name)
            except AttributeError:
                pass
        if default_value is not None:
            return default_value
        raise AttributeError(f"Neither {new_name} nor {old_name} found in xtconstant")


def _get_price_type_constant(
    new_name: str, old_name: str = None, default_value: int = None
):
    """安全获取价格类型常量，支持多种命名方式

    Args:
        new_name: 新的常量名（如 MARKET_PRICE_5）
        old_name: 旧的常量名（如 MARKET_PRICE）
        default_value: 如果都不存在，使用的默认数值（如果为None且不存在则返回None）

    Returns:
        常量值，如果不存在且default_value为None则返回None
    """
    try:
        return getattr(xtconstant, new_name)
    except AttributeError:
        if old_name:
            try:
                return getattr(xtconstant, old_name)
            except AttributeError:
                pass
        if default_value is not None:
            return default_value
        # 如果default_value为None，返回None而不是抛出异常
        return None


# 定义订单状态常量（兼容不同版本的 xtquant）
ORDER_STATUS_ALLTRADED = _get_order_status_constant(
    "ORDER_SUCCEEDED", "ORDER_STATUS_ALLTRADED", 56
)
ORDER_STATUS_CANCELED = _get_order_status_constant(
    "ORDER_CANCELED", "ORDER_STATUS_CANCELED", 57
)
ORDER_STATUS_REJECTED = _get_order_status_constant(
    "ORDER_JUNK", "ORDER_STATUS_REJECTED", 54
)
ORDER_STATUS_NEW = _get_order_status_constant("ORDER_REPORTED", "ORDER_STATUS_NEW", 50)
ORDER_STATUS_PARTTRADED = _get_order_status_constant(
    "ORDER_PART_SUCC", "ORDER_STATUS_PARTTRADED", 51
)

# 定义价格类型常量（兼容不同版本的 xtquant）
# 参考文档：https://dict.thinktrader.net/nativeApi/xttrader.html?id=XxjF3h#%E4%BA%A4%E6%98%93%E5%B8%82%E5%9C%BA-market
# 五档即时成交剩余撤销（市价单，通用）
MARKET_PRICE_5 = _get_price_type_constant(
    "MARKET_PRICE_5", "MARKET_PRICE_IMMEDIATE", 11
)
# 对手方最优价（保护限价市价单，用于9:30抢单，通用）
MARKET_PEER_PRICE_FIRST = _get_price_type_constant(
    "MARKET_PEER_PRICE_FIRST", "MARKET_PEER_PRICE", 12
)
# 上交所股票最优五档剩转限（上交所股票常用，根据文档：xtconstant.MARKET_SH_CONVERT_5_LIMIT）
MARKET_SH_CONVERT_5_LIMIT = _get_price_type_constant(
    "MARKET_SH_CONVERT_5_LIMIT", None, None
)
# 深交所股票最优五档即时成交剩余撤销（深交所股票常用，根据文档：xtconstant.MARKET_SZ_CONVERT_5_CANCEL）
# 注意：MARKET_CONVERT_5 是期货常量，不适用于股票交易
MARKET_SZ_CONVERT_5_CANCEL = _get_price_type_constant(
    "MARKET_SZ_CONVERT_5_CANCEL", None, None
)


class WaitingOrderStatus(Enum):
    COMPLETED = "COMPLETED"  # 所有订单已完成
    NEED_REPLACE = "NEED_REPLACE"  # 有订单已撤单，需要重新下单
    PENDING_CANCEL = "PENDING"  # 有订单等待交易所处理
    ERROR = "ERROR"  # 其他错误


API_URL = "http://117.72.170.182:5366"  # 服务器API地址（自动配置）


class G:
    def __init__(self):
        self.latest_update_time = None
        self.check_orders_scheduled = False  # 新增：标记是否有计划中的检查任务

        self.strategy_name = "sync_positions"
        self.check_orders_interval = 5  # 检查订单状态的时间间隔（秒）
        self.sync_positions_interval = 1  # 持仓同步的时间间隔（秒）
        self.strategy_names = ["打板策略-12-01"]
        self.internal_password = "admin123"  # 内部API密码，用于同步持仓到数据库
        self.account = None
        self.trader = None
        self.account_id = None
        self.last_sync_time = None  # 上次同步时间，用于防抖
        self.sync_delay = 3  # 成交后延迟同步的时间（秒），避免频繁同步
        self.total_asset_update_hour = 15  # 总资产更新的时间（小时）
        self.total_asset_update_minute = 1  # 总资产更新的时间（分钟）
        self.sync_start_hour = 9  # 持仓同步开始时间（小时）
        self.sync_start_minute = 26  # 持仓同步开始时间（分钟），从9:26开始同步
        self.sync_start_millisecond = 0  # 持仓同步开始时间（毫秒），支持毫秒级精度
        self.market_open_delay = 1  # 9:30开盘时下单延迟（秒），避免交易所未准备好
        self.use_protected_market_order = True  # 是否使用保护限价市价单，True时在9:30使用市价单（最优五档剩转限/即时成交剩余撤销），可避免价格笼子限制导致废单
        self.pending_orders = (
            None  # 待执行的交易操作记录（9:26-9:30之间记录，9:30后执行）
        )
        self.pending_update_time = None  # 待执行操作对应的update_time


g = G()


class MiniQMTTraderCallback(XtQuantTraderCallback):
    """交易回调类"""

    def on_disconnected(self):
        """连接断开"""
        print("交易连接已断开")

    def on_stock_order(self, order):
        """委托回调"""
        # 尝试获取委托时间，如果不存在则使用当前时间
        order_time = (
            getattr(order, "order_time", None)
            or getattr(order, "create_time", None)
            or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        order_price = getattr(order, "price", "N/A")
        print(
            f"委托回调: {order.stock_code} {order.order_status} {order.order_volume} 价格: {order_price} 时间: {order_time}"
        )

    def on_stock_asset(self, asset):
        """资金变动回调"""
        print(f"资金变动: 可用资金 {asset.cash}")

    def on_stock_trade(self, trade):
        """成交回调"""
        # 尝试获取成交时间，如果不存在则使用当前时间
        traded_time = (
            getattr(trade, "traded_time", None)
            or getattr(trade, "time", None)
            or getattr(trade, "create_time", None)
            or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        # 尝试获取成交价格，优先使用 price 字段
        traded_price = (
            getattr(trade, "price", None)
            or getattr(trade, "traded_price", None)
            or getattr(trade, "executed_price", None)
            or getattr(trade, "fill_price", None)
            or "N/A"
        )
        print(
            f"成交回调: {trade.stock_code} {trade.traded_volume} {traded_price} 时间: {traded_time}"
        )



    def on_stock_position(self, position):
        """持仓变动回调"""
        print(f"持仓变动: {position.stock_code} {position.volume}")


class MiniQMTAPI:
    def __init__(self, account_id: str, strategy_names=None):
        self.api_url = API_URL
        self.account_id = account_id
        self.strategy_names = strategy_names
        self.trader = None
        self.callback = MiniQMTTraderCallback()
        self._init_trader()

    def _init_trader(self):
        """初始化交易连接"""
        try:
            # 创建交易连接
            # XtQuantTrader 需要 path 和 session 参数
            # path: MiniQMT 安装路径，通常为空字符串表示使用默认路径
            # session: 会话ID，通常为整数，0 表示默认会话
            try:
                # 尝试使用新版本API（需要 path 和 session）
                self.trader = xttrader.XtQuantTrader(
                    path=QMT_PATH,
                    session=0,
                )
            except TypeError:
                # 如果新版本API不存在，尝试旧版本API（无参数）
                try:
                    self.trader = xttrader.XtQuantTrader()
                except Exception as e:
                    print(f"创建交易连接对象失败: {str(e)}")
                    self.trader = None
                    return False

            if self.trader is None:
                print("交易连接对象创建失败")
                return False

            # 修复 oldloop 属性问题：在析构时可能会访问此属性
            # 如果对象没有此属性，尝试设置一个默认值
            if not hasattr(self.trader, "oldloop"):
                try:
                    import asyncio

                    self.trader.oldloop = asyncio.get_event_loop()
                except (AttributeError, RuntimeError):
                    # 如果无法获取事件循环，设置为 None
                    self.trader.oldloop = None

            # 注册回调
            self.trader.register_callback(self.callback)

            # 启动交易连接
            self.trader.start()

            # 连接账户
            account = StockAccount(self.account_id)
            connect_result = self.trader.connect()
            if connect_result != 0:
                print(f"交易连接失败: {connect_result}")
                self.trader = None
                return False

            # 订阅账户
            subscribe_result = self.trader.subscribe(account)
            if subscribe_result != 0:
                print(f"账户订阅失败: {subscribe_result}")
                self.trader = None
                return False

            print(f"MiniQMT交易连接成功，账户: {self.account_id}")
            return True

        except Exception as e:
            print(f"初始化MiniQMT交易连接失败: {str(e)}")
            self.trader = None
            return False

    def get_total_positions(self) -> Dict:
        """获取目标持仓数据（从API服务器）"""
        try:
            url = f"{self.api_url}/api/v1/positions/total"
            if self.strategy_names:
                url += f'?strategies={",".join(self.strategy_names)}'

            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                print(f"获取总持仓失败: HTTP {response.status_code} - {response.text}")
                return {"positions": [], "update_time": None}
            data = response.json()

            return {
                "positions": data["positions"],
                "update_time": data.get("update_time"),
            }
        except requests.exceptions.Timeout:
            print(f"获取总持仓超时")
            return {"positions": [], "update_time": None}
        except requests.exceptions.RequestException as e:
            print(f"获取总持仓网络错误: {str(e)}")
            return {"positions": [], "update_time": None}
        except Exception as e:
            print(f"获取总持仓其他错误: {str(e)}")
            return {"positions": [], "update_time": None}

    def sync_positions(self):
        """同步持仓"""
        if self.trader is None:
            print("交易连接未初始化，无法同步持仓")
            return

        now = datetime.now()
        current_time = now.time()
        is_pre_trading = is_pre_trading_time(current_time)
        is_after_930 = current_time >= datetime.strptime("09:30:00", "%H:%M:%S").time()

        # 如果内存中有待执行的记录，且当前时间在9:30之后，执行这些记录
        if g.pending_orders is not None and is_after_930:
            print("\n=== 执行内存中待执行的交易操作（9:30后） ===")
            print(f"待执行操作（update_time: {g.pending_update_time}）")

            # 先检查订单状态，确保没有未完成的订单
            max_orders_complete_retry = 10
            status = WaitingOrderStatus.ERROR
            while max_orders_complete_retry > 0:
                max_orders_complete_retry -= 1
                status = self.try_orders_complete()
                if status == WaitingOrderStatus.COMPLETED:
                    break
                elif status == WaitingOrderStatus.NEED_REPLACE:
                    print(
                        f"有订单撤销，等待待撤订单状态更新,等待{g.check_orders_interval}秒后重试..."
                    )
                    continue
                elif status == WaitingOrderStatus.PENDING_CANCEL:
                    print(
                        f"等待未报和待撤订单状态更新,等待{g.check_orders_interval}秒后重试..."
                    )
                    continue
                elif status == WaitingOrderStatus.ERROR:
                    print("检查订单状态时发生错误，延迟执行待执行操作")
                    break

            if status == WaitingOrderStatus.COMPLETED:
                # 执行待执行的订单
                self._execute_pending_orders()
                # 更新latest_update_time
                if g.pending_update_time:
                    g.latest_update_time = g.pending_update_time
                # 清除记录
                g.pending_orders = None
                g.pending_update_time = None
                print("=== 待执行操作已执行并清除 ===\n")
            else:
                print("订单状态检查未完成，延迟执行待执行操作，等待下次同步")

            return

        # 如果内存中有待执行的记录，跳过同步（等待9:30后执行）
        if g.pending_orders is not None:
            print(
                f"\n=== 内存中已有待执行操作（update_time: {g.pending_update_time}），跳过本次同步（等待9:30后执行） ==="
            )
            return

        # 获取最新数据和更新时间
        total_data = self.get_total_positions()
        current_update_time = total_data.get("update_time")

        # 检查是否获取到有效数据
        if current_update_time is None:
            print("获取持仓数据失败，跳过本次同步")
            print(f"获取到的数据: {total_data}")
            return

        # 检查是否需要更新 - 如果远程更新时间等于本地更新时间，跳过更新
        if g.latest_update_time and current_update_time == g.latest_update_time:
            return

        # 新增逻辑：如果current_update_time < latest_update_time，只对比打印差异，不下单
        # if g.latest_update_time and current_update_time < g.latest_update_time:
        #     print(
        #         f"\n=== 检测到时间回退：远程时间({current_update_time}) < 本地时间({g.latest_update_time}) ==="
        #     )
        #     print(
        #         f"存在{current_update_time}未同步的仓位，本轮只进行持仓对比，不执行下单操作"
        #     )

        #     # 只检查持仓一致性，不进行下单
        #     differences = self.check_positions_consistency()

        #     if differences:
        #         print("\n=== 持仓差异详情 ===")
        #         print(
        #             f"{'代码':<10} {'目标':>8} {'当前':>8} {'差异':>8} {'操作建议':<10}"
        #         )
        #         print("-" * 50)
        #         for code, info in sorted(differences.items()):
        #             diff = info["diff"]
        #             operation = "卖出" if diff > 0 else "买入"
        #             print(
        #                 f"{code:<10} {info['target']:>8} {info['current']:>8} {diff:>8} {operation}({abs(diff)}股)"
        #             )
        #     else:
        #         print("持仓完全一致，无差异")

        #     # 更新latest_update_time为current_update_time
        #     g.latest_update_time = current_update_time
        #     print(f"更新latest_update_time为: {g.latest_update_time}")
        #     print("=== 时间回退处理完成 ===\n")
        #     return

        print("\n=== 开始持仓同步 ===")

        # 如果在9:26-9:30之间，预处理所有订单信息
        if is_pre_trading:
            print("当前时间在9:26-9:30之间（预交易时间），预处理订单信息")
            differences = self.check_positions_consistency()
            if differences:
                # 将差异分为卖出和买入两组
                sell_orders = {}
                buy_orders = {}
                for code, info in differences.items():
                    diff = info["diff"]
                    available = info["available"]
                    if diff > 0:  # 需要卖出
                        if available >= diff:
                            sell_orders[code] = {"volume": diff, "available": available}
                        else:
                            print(
                                f"  ! 卖出检查失败 {code}: 需要卖出 {diff} 股，但可用仅有 {available} 股"
                            )
                    else:  # 需要买入
                        buy_orders[code] = {"volume": abs(diff)}

                # 预处理订单信息（计算价格、价格类型等）
                if sell_orders:
                    print("\n=== 预处理卖出订单信息 ===")
                    for code, info in sell_orders.items():
                        prepared_info = self._prepare_order_info(
                            code, info["volume"], "sell"
                        )
                        if prepared_info:
                            sell_orders[code].update(prepared_info)
                        else:
                            print(f"  ⚠ 预处理卖出订单失败: {code}，将在9:30后实时计算")
                    print("=== 卖出订单预处理完成 ===\n")

                if buy_orders:
                    print("\n=== 预处理买入订单信息 ===")
                    for code, info in buy_orders.items():
                        prepared_info = self._prepare_order_info(
                            code, info["volume"], "buy"
                        )
                        if prepared_info:
                            buy_orders[code].update(prepared_info)
                        else:
                            print(f"  ⚠ 预处理买入订单失败: {code}，将在9:30后实时计算")
                    print("=== 买入订单预处理完成 ===\n")

                # 记录到内存
                if sell_orders or buy_orders:
                    g.pending_orders = {"sell": sell_orders, "buy": buy_orders}
                    g.pending_update_time = current_update_time
                    print(
                        f"\n=== 已预处理并记录待执行操作到内存（update_time: {current_update_time}） ==="
                    )
                    print("待执行操作详情：")
                    if g.pending_orders.get("sell"):
                        print("  卖出订单：")
                        for code, info in g.pending_orders["sell"].items():
                            if "order_price" in info:
                                print(
                                    f"    - {code}: {info['volume']} 股, 价格: {info.get('order_price', 'N/A')}"
                                )
                            else:
                                print(f"    - {code}: {info['volume']} 股 (价格待计算)")
                    if g.pending_orders.get("buy"):
                        print("  买入订单：")
                        for code, info in g.pending_orders["buy"].items():
                            if "order_price" in info:
                                print(
                                    f"    + {code}: {info['volume']} 股, 涨停价: {info.get('order_price', 'N/A')}, 价格类型: {info.get('price_type_name', 'N/A')}"
                                )
                            else:
                                print(f"    + {code}: {info['volume']} 股 (价格待计算)")
                    print("=== 等待9:30后直接执行 ===\n")
                else:
                    g.pending_orders = None
                    print("没有需要执行的交易操作")
            else:
                print("没有持仓差异，无需记录")

            # 更新latest_update_time
            g.latest_update_time = current_update_time
            print(f"=== 持仓同步结束 (更新时间: {g.latest_update_time}) ===\n")
            return

        # 9:30之后正常执行同步
        max_sync_positions = 10
        MAX_ORDERS_COMPLETE_RETRY = 10
        while max_sync_positions > 0:
            max_sync_positions -= 1
            max_orders_complete_retry = MAX_ORDERS_COMPLETE_RETRY
            status = WaitingOrderStatus.ERROR
            while max_orders_complete_retry > 0:
                max_orders_complete_retry -= 1
                # 检查是否需要取消订单
                status = self.try_orders_complete()
                if status == WaitingOrderStatus.COMPLETED:
                    break
                elif status == WaitingOrderStatus.NEED_REPLACE:
                    print(
                        f"有订单撤销，等待待撤订单状态更新,等待{g.check_orders_interval}秒后重试..."
                    )
                    continue
                elif status == WaitingOrderStatus.PENDING_CANCEL:
                    print(
                        f"等待未报和待撤订单状态更新,等待{g.check_orders_interval}秒后重试..."
                    )
                    continue
                elif status == WaitingOrderStatus.ERROR:
                    print("检查订单状态时发生错误，跳过本次同步")
                    break
            if status == WaitingOrderStatus.COMPLETED:
                differences = self.check_positions_consistency()
                print(f"\n=== 同步下单:{10 - max_sync_positions} ===")
                if not differences:
                    print("没有持仓差异，无需下单")
                    break
                # 将差异分为卖出和买入两组
                sell_orders = {}
                buy_orders = {}
                for code, info in differences.items():
                    diff = info["diff"]
                    available = info["available"]
                    if diff > 0:  # 需要卖出
                        if available >= diff:
                            sell_orders[code] = {"volume": diff, "available": available}
                        else:
                            print(
                                f"  ! 卖出检查失败 {code}: 需要卖出 {diff} 股，但可用仅有 {available} 股"
                            )
                    else:  # 需要买入
                        buy_orders[code] = {"volume": abs(diff)}

                # 预处理订单信息（复用预处理逻辑，提高下单速度）
                if sell_orders:
                    print("\n=== 预处理卖出订单信息 ===")
                    for code, info in sell_orders.items():
                        prepared_info = self._prepare_order_info(
                            code, info["volume"], "sell"
                        )
                        if prepared_info:
                            sell_orders[code].update(prepared_info)
                    print("=== 卖出订单预处理完成 ===\n")

                if buy_orders:
                    print("\n=== 预处理买入订单信息 ===")
                    for code, info in buy_orders.items():
                        prepared_info = self._prepare_order_info(
                            code, info["volume"], "buy"
                        )
                        if prepared_info:
                            buy_orders[code].update(prepared_info)
                    print("=== 买入订单预处理完成 ===\n")

                if sell_orders:
                    t_orders = sell_orders
                    direction = "sell"
                else:
                    t_orders = buy_orders
                    direction = "buy"
                if t_orders:
                    for code, info in t_orders.items():
                        # 统一使用预处理+快速下单逻辑
                        if "order_type" in info:
                            # 已预处理，直接使用快速下单
                            if direction == "sell":
                                print(f"  - 卖出 {code}: {info['volume']} 股")
                            else:
                                current_time_ms = datetime.now().strftime(
                                    "%Y-%m-%d %H:%M:%S.%f"
                                )[:-3]
                                print(
                                    f"[{current_time_ms}]  + 买入 {code}: {info['volume']} 股"
                                )
                            self._place_order(code, order_info=info)
                        else:
                            # 未预处理，调用统一的下单方法（会自动预处理）
                            if direction == "sell":
                                print(f"  - 卖出 {code}: {info['volume']} 股")
                            else:
                                current_time_ms = datetime.now().strftime(
                                    "%Y-%m-%d %H:%M:%S.%f"
                                )[:-3]
                                print(
                                    f"[{current_time_ms}]  + 买入 {code}: {info['volume']} 股"
                                )
                            self._place_order(code, info["volume"], direction)
                    print("\n=== 同步下单结束 ===")
                    break  # 下单成功后退出外层循环，等待订单完成
                else:
                    print("\n=== 同步下单结束，没有下单 ===")
                    break
            else:
                # 区分不同的失败原因
                if status == WaitingOrderStatus.ERROR:
                    print("订单状态检查发生错误，跳过本次同步")
                elif status == WaitingOrderStatus.NEED_REPLACE:
                    retry_count = MAX_ORDERS_COMPLETE_RETRY - max_orders_complete_retry
                    print(
                        f"订单撤销后等待状态更新超时（已重试{retry_count}次），继续下次同步尝试"
                    )
                elif status == WaitingOrderStatus.PENDING_CANCEL:
                    retry_count = MAX_ORDERS_COMPLETE_RETRY - max_orders_complete_retry
                    print(
                        f"等待订单处理超时（已重试{retry_count}次），继续下次同步尝试"
                    )
                else:
                    print("订单状态检查失败，跳过本次同步")

        if max_sync_positions == 0:
            print("达到最大同步次数，跳过本次同步，请检查同步是否完成!!!!")

        g.latest_update_time = current_update_time
        print(f"=== 持仓同步结束 (更新时间: {g.latest_update_time}) ===\n")

    def _prepare_order_info(self, code: str, volume: int, direction: str) -> Dict:
        """预处理订单信息（9:26-9:30之间调用）

        计算所有下单需要的信息，包括价格、价格类型、订单类型等

        Returns:
            dict: 包含预处理好的订单信息，如果预处理失败返回None
        """
        try:
            # 获取行情数据
            current_tick = None
            try:
                tick_data = xtdata.get_full_tick([code])
                if not tick_data or code not in tick_data:
                    print(f"  获取 {code} 行情数据失败")
                    return None

                current_tick = tick_data[code]
                if (
                    not current_tick
                    or "lastPrice" not in current_tick
                    or current_tick["lastPrice"] <= 0
                ):
                    print(f"  获取 {code} 最新价失败")
                    return None

                price = current_tick["lastPrice"]

            except Exception as e:
                print(f"  获取 {code} 行情异常: {str(e)}")
                return None

            # 获取合约详细信息
            try:
                instrument_detail = xtdata.get_instrument_detail(code)
                if not instrument_detail:
                    print(f"  获取 {code} 合约信息失败")
                    return None

                # 检查停牌状态
                if instrument_detail.get("InstrumentStatus", 0) > 0:
                    print(f"  股票 {code} 停牌，无法下单")
                    return None

                up_limit = instrument_detail.get("UpStopPrice", 0)
                down_limit = instrument_detail.get("DownStopPrice", 0)

            except Exception as e:
                print(f"  获取 {code} 合约信息异常: {str(e)}")
                return None

            # 获取价格精度
            precision = self._get_price_precision(code)

            if direction == "buy":
                # 只支持主板股票交易
                if not self._is_mainboard(code):
                    print(f"  股票 {code} 不是主板股票，跳过预处理")
                    return None

                # 获取卖一价和买一价（用于价格笼子计算）
                ask_price1 = (
                    current_tick["askPrice"][0]
                    if (
                        current_tick
                        and "askPrice" in current_tick
                        and len(current_tick["askPrice"]) > 0
                        and current_tick["askPrice"][0] > 0
                    )
                    else 0
                )
                bid_price1 = (
                    current_tick["bidPrice"][0]
                    if (
                        current_tick
                        and "bidPrice" in current_tick
                        and len(current_tick["bidPrice"]) > 0
                        and current_tick["bidPrice"][0] > 0
                    )
                    else 0
                )

                # 优先使用官方涨停价（从tick数据获取，最准确）
                official_up_limit = 0
                if current_tick and "highLimit" in current_tick:
                    official_up_limit = current_tick.get("highLimit", 0)
                    if official_up_limit > 0:
                        up_limit = official_up_limit

                # 如果tick数据中没有，尝试使用接口返回的涨停价
                if up_limit <= 0:
                    interface_up_limit = instrument_detail.get("UpStopPrice", 0)
                    if interface_up_limit > 0:
                        up_limit = interface_up_limit

                # 如果接口也没有，尝试计算涨停价
                if up_limit <= 0:
                    calculated_up_limit = self._calculate_up_limit_price(code)
                    if calculated_up_limit > 0:
                        up_limit = calculated_up_limit
                    else:
                        print(f"  股票 {code} 涨停价无效，无法预处理")
                        return None

                # 先使用涨停价作为订单价格
                order_price = up_limit

                # 应用价格笼子限制（避免涨停价超过价格笼子上限导致废单）
                order_price = self._apply_price_cage_limit(
                    order_price, "buy", ask_price1, bid_price1, price, precision
                )

                # 根据配置选择价格类型（9:30时使用）
                # 参考文档：https://dict.thinktrader.net/nativeApi/xttrader.html?id=XxjF3h#%E4%BA%A4%E6%98%93%E5%B8%82%E5%9C%BA-market
                # 注意：MARKET_CONVERT_5 是期货常量，不适用于股票交易
                # MiniQMT 对深交所和上交所的常量定义有细微区别，需要根据交易所选择对应的价格类型
                if g.use_protected_market_order:
                    # 根据交易所选择对应的市价单类型
                    if self._is_shanghai_exchange(code):
                        # 上交所股票：使用上海最优五档剩转限（xtconstant.MARKET_SH_CONVERT_5_LIMIT）
                        if MARKET_SH_CONVERT_5_LIMIT is not None:
                            price_type = MARKET_SH_CONVERT_5_LIMIT
                            price_type_name = "上交所最优五档剩转限"
                        else:
                            # 如果常量不存在，回退到对手方最优价
                            price_type = MARKET_PEER_PRICE_FIRST
                            price_type_name = "保护限价市价单（回退）"
                            print(
                                f"  警告: {code} 上交所常量 MARKET_SH_CONVERT_5_LIMIT 不存在，使用回退方案"
                            )
                    else:
                        # 深交所股票：使用最优五档即时成交剩余撤销（xtconstant.MARKET_SZ_CONVERT_5_CANCEL）
                        if MARKET_SZ_CONVERT_5_CANCEL is not None:
                            price_type = MARKET_SZ_CONVERT_5_CANCEL
                            price_type_name = "深交所最优五档即时成交剩余撤销"
                        else:
                            # 如果常量不存在，回退到对手方最优价
                            price_type = MARKET_PEER_PRICE_FIRST
                            price_type_name = "保护限价市价单（回退）"
                            print(
                                f"  警告: {code} 深交所常量 MARKET_SZ_CONVERT_5_CANCEL 不存在，使用回退方案"
                            )
                else:
                    # 使用限价单（涨停价）
                    price_type = xtconstant.FIX_PRICE
                    price_type_name = "涨停价限价单"

                order_type = xtconstant.STOCK_BUY

                # 检查资金是否足够（预处理时检查，9:30执行时不再检查）
                try:
                    account = StockAccount(self.account_id)
                    account_info = self.trader.query_stock_asset(account)
                    if not account_info:
                        print(f"  获取账户资金信息失败: {code}")
                        return None

                    stock_cost = up_limit * volume
                    commission_rate = 0.0000854
                    commission = max(stock_cost * commission_rate, 5.0)
                    total_cost = stock_cost + commission
                    available_cash = account_info.cash

                    if available_cash < total_cost:
                        print(
                            f"  资金不足: {code}, 所需: {total_cost:.2f}, 可用: {available_cash:.2f}"
                        )
                        return None

                except Exception as e:
                    print(f"  检查资金异常: {code}, {str(e)}")
                    return None

                return {
                    "order_price": order_price,
                    "price_type": price_type,
                    "price_type_name": price_type_name,
                    "order_type": order_type,
                    "precision": precision,
                }

            else:  # sell
                # 卖出订单需要实时计算价格（依赖买一、买二等），但可以预处理基础信息
                # 获取实时行情数据计算价格
                try:
                    ask_price1 = (
                        current_tick["askPrice"][0]
                        if (
                            current_tick
                            and "askPrice" in current_tick
                            and len(current_tick["askPrice"]) > 0
                            and current_tick["askPrice"][0] > 0
                        )
                        else 0
                    )
                    bid_price1 = (
                        current_tick["bidPrice"][0]
                        if (
                            current_tick
                            and "bidPrice" in current_tick
                            and len(current_tick["bidPrice"]) > 0
                            and current_tick["bidPrice"][0] > 0
                        )
                        else 0
                    )
                    bid_price2 = (
                        current_tick["bidPrice"][1]
                        if (
                            current_tick
                            and "bidPrice" in current_tick
                            and len(current_tick["bidPrice"]) > 1
                        )
                        else 0
                    )

                    calculated_price = max(
                        round(price * 0.998, precision), down_limit
                    )  # 卖单价格减0.2%
                    # 如果买二价格有效且优于计算价格，使用买二价格
                    if bid_price2 > 0 and bid_price2 > calculated_price:
                        order_price = bid_price2
                    else:
                        order_price = calculated_price

                    # 应用价格笼子限制
                    order_price = self._apply_price_cage_limit(
                        order_price, "sell", ask_price1, bid_price1, price, precision
                    )

                    # 检查是否达到跌停价
                    if price == down_limit:
                        print(f"  股票 {code} 达到跌停价格，无法下卖单")
                        return None

                    order_type = xtconstant.STOCK_SELL
                    price_type = xtconstant.FIX_PRICE

                    return {
                        "order_price": order_price,
                        "order_type": order_type,
                        "price_type": price_type,
                        "precision": precision,
                        "down_limit": down_limit,
                    }
                except Exception as e:
                    print(f"  计算卖出价格异常: {code}, {str(e)}")
                    return None

        except Exception as e:
            print(f"  预处理订单信息异常: {code}, {str(e)}")
            return None

    def _execute_pending_orders(self):
        """执行内存中待执行的交易操作（使用预处理好的信息直接下单）"""
        if not g.pending_orders:
            print("内存中没有待执行的交易操作")
            return

        print(f"执行待执行操作（update_time: {g.pending_update_time}）")

        # 先执行卖出订单
        if g.pending_orders.get("sell"):
            sell_orders = g.pending_orders["sell"]
            print("\n=== 执行卖出订单 ===")
            for code, info in sell_orders.items():
                # 统一使用预处理+快速下单逻辑
                if "order_type" in info:
                    # 已预处理，直接使用快速下单
                    print(f"  - 卖出 {code}: {info['volume']} 股")
                    self._place_order(code, order_info=info)
                else:
                    # 未预处理，调用统一的下单方法（会自动预处理）
                    print(f"  - 卖出 {code}: {info['volume']} 股")
                    self._place_order(code, info["volume"], "sell")
            print("=== 卖出订单执行完成 ===\n")

        # 再执行买入订单
        if g.pending_orders.get("buy"):
            buy_orders = g.pending_orders["buy"]
            print("\n=== 执行买入订单 ===")
            for code, info in buy_orders.items():
                current_time_ms = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                # 统一使用预处理+快速下单逻辑
                if "order_type" in info:
                    # 已预处理，直接使用快速下单
                    print(f"[{current_time_ms}]  + 买入 {code}: {info['volume']} 股")
                    self._place_order(code, order_info=info)
                else:
                    # 未预处理，调用统一的下单方法（会自动预处理）
                    print(f"[{current_time_ms}]  + 买入 {code}: {info['volume']} 股")
                    self._place_order(code, info["volume"], "buy")
            print("=== 买入订单执行完成 ===\n")

    def try_orders_complete(self):
        """检查订单状态"""
        print("\n*** 订单状态检查 ***")
        time.sleep(g.check_orders_interval)

        if self.trader is None:
            print("交易连接未初始化，无法检查订单状态")
            return WaitingOrderStatus.ERROR

        try:
            # 获取所有委托
            account = StockAccount(self.account_id)
            orders = self.trader.query_stock_orders(account)

            # 过滤未完成订单（排除已完成的订单状态）
            pending_orders = [
                order
                for order in orders
                if order.order_status
                not in [
                    ORDER_STATUS_ALLTRADED,
                    ORDER_STATUS_CANCELED,
                    ORDER_STATUS_REJECTED,
                ]
            ]

            print("\n当前所有订单状态：")
            print(
                f"{'订单编号':<12} {'代码':<10} {'方向':<6} {'总数量':>8} {'成交量':>8} "
                f"{'价格':>8} {'状态':>6}"
            )
            print("-" * 70)

            for order in pending_orders:
                direction = (
                    "买入" if order.order_type == xtconstant.STOCK_BUY else "卖出"
                )
                print(
                    f"{order.order_id:<12} {order.stock_code:<10} "
                    f"{direction:<6} {order.order_volume:>8} {order.traded_volume:>8} "
                    f"{order.price:>8.2f} {order.order_status:>6}"
                )

            if not pending_orders:
                print("没有未完成订单")
                return WaitingOrderStatus.COMPLETED

            # 检查是否有待交易所处理的订单
            waiting_orders = [
                order
                for order in pending_orders
                if order.order_status in [ORDER_STATUS_NEW, ORDER_STATUS_PARTTRADED]
            ]

            if waiting_orders:
                print("存在待交易所处理的订单，等待处理完成")
                for order in waiting_orders:
                    print(f"  - {order.order_id}: 状态{order.order_status}")
                return WaitingOrderStatus.PENDING_CANCEL

            # 撤销所有未完成订单
            has_cancelled = False
            for order in pending_orders:
                print(
                    f"正在撤销订单: {order.order_id} - {order.stock_code} "
                    f"(状态: {order.order_status})"
                )

                # 执行撤单
                cancel_result = self.trader.cancel_order_stock(account, order.order_id)
                if cancel_result == 0:
                    print(f"撤销成功:{order.order_id}")
                    has_cancelled = True
                else:
                    print(f"撤销订单失败: {order.order_id}, 错误码: {cancel_result}")
                    return WaitingOrderStatus.ERROR

            if has_cancelled:
                print("已撤销部分订单，等待重新下单")
                return WaitingOrderStatus.NEED_REPLACE
            else:
                print("发现异常状态的订单")
                return WaitingOrderStatus.ERROR

        except Exception as e:
            print(f"检查订单状态异常: {str(e)}")
            return WaitingOrderStatus.ERROR

    def _should_filter_position(self, code: str):
        """判断是否应该过滤该持仓
        只同步沪市和深市的股票：
        - 沪市：代码以 6 开头（600xxx 主板，688xxx 科创板等）
        - 深市：代码以 0 开头（000xxx 主板）或 3 开头（300xxx 创业板，301xxx 创业板等）

        其他所有代码（港股、基金、债券等）都会被过滤

        返回：(是否过滤, 过滤原因)
        """
        pure_code = self._get_pure_code(code)

        # 只允许沪市（6开头）和深市（0或3开头）的股票
        if pure_code.startswith("6"):
            # 沪市股票：600xxx 主板，688xxx 科创板等
            return False, ""
        elif pure_code.startswith(("0", "3")):
            # 深市股票：000xxx 主板，300xxx/301xxx 创业板等
            # 注意：需要排除港股通（00、03开头且长度为5的港股）
            if pure_code.startswith(("00", "03")) and len(pure_code) == 5:
                return True, "港股通"
            return False, ""
        else:
            # 其他所有代码（基金、债券、特殊代码等）都过滤
            return True, "非A股股票"

    def check_positions_consistency(self) -> Dict[str, Dict]:
        """检查持仓一致性"""
        # 获取数据库目标持仓
        db_positions = {
            self._convert_jq_code_to_qmt(pos["code"]): pos["total_volume"]
            for pos in self.get_total_positions()["positions"]
        }

        # 获取MiniQMT实际持仓
        if self.trader is None:
            print("交易连接未初始化，无法获取MiniQMT持仓")
            current_positions = {}
        else:
            try:
                account = StockAccount(self.account_id)
                qmt_positions_data = self.trader.query_stock_positions(account)
                current_positions = {
                    position.stock_code: {
                        "volume": position.volume,
                        "available": position.can_use_volume,
                    }
                    for position in qmt_positions_data
                }
            except Exception as e:
                print(f"获取MiniQMT持仓失败: {str(e)}")
                current_positions = {}

        # 记录过滤的持仓
        filtered_db_codes = []
        filtered_current_codes = []

        # 过滤不需要对比的持仓
        filtered_db_positions = {}
        for code, volume in db_positions.items():
            should_filter, reason = self._should_filter_position(code)
            if should_filter:
                filtered_db_codes.append((code, reason, volume))
            else:
                filtered_db_positions[code] = volume

        filtered_current_positions = {}
        for code, info in current_positions.items():
            should_filter, reason = self._should_filter_position(code)
            if should_filter:
                filtered_current_codes.append((code, reason, info["volume"]))
            else:
                filtered_current_positions[code] = info

        # 打印过滤信息
        if filtered_db_codes or filtered_current_codes:
            print(
                f"\n=== 过滤的持仓 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ==="
            )

            if filtered_db_codes:
                print("\n【远程持仓（数据库目标持仓）】")
                print(f"{'代码':<12} {'过滤原因':<12} {'数量':>8}")
                print("-" * 35)
                for code, reason, volume in sorted(filtered_db_codes):
                    print(f"{code:<12} {reason:<12} {volume:>8}")

            if filtered_current_codes:
                print("\n【本地持仓（MiniQMT实际持仓）】")
                print(f"{'代码':<12} {'过滤原因':<12} {'数量':>8}")
                print("-" * 35)
                for code, reason, volume in sorted(filtered_current_codes):
                    print(f"{code:<12} {reason:<12} {volume:>8}")

            print("\n=== 过滤结束 ===\n")

        # 计算差异
        differences = {}
        all_codes = set(filtered_db_positions.keys()) | set(
            filtered_current_positions.keys()
        )

        for code in all_codes:
            target_vol = filtered_db_positions.get(code, 0)
            current_pos = filtered_current_positions.get(
                code, {"volume": 0, "available": 0}
            )
            diff = current_pos["volume"] - target_vol

            if diff != 0:
                differences[code] = {
                    "target": target_vol,
                    "current": current_pos["volume"],
                    "available": current_pos["available"],
                    "diff": diff,
                }

        # 打印差异
        print(
            f"\n=== Position Differences ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ==="
        )
        if differences:
            print(f"{'Code':<10} {'Target':>8} {'Current':>8} {'Diff':>8}")
            print("-" * 38)
            for code, info in sorted(differences.items()):
                print(
                    f"{code:<10} {info['target']:>8} {info['current']:>8} {info['diff']:>8}"
                )
        else:
            print("  √ All positions are consistent")
        print("=== Check End ===\n")

        return differences

    def _convert_jq_code_to_qmt(self, jq_code: str) -> str:
        """将聚宽代码转换为MiniQMT代码
        511260.XSHG -> 511260.SH
        511260.XSHE -> 511260.SZ
        """
        if "." not in jq_code:
            return jq_code

        code, market = jq_code.split(".")
        if market == "XSHG":
            return f"{code}.SH"
        elif market == "XSHE":
            return f"{code}.SZ"
        return jq_code

    def _get_pure_code(self, full_code: str) -> str:
        """从完整代码中获取纯数字代码
        600000.SH -> 600000
        """
        return full_code.split(".")[0]

    def _is_shanghai_exchange(self, code: str) -> bool:
        """判断是否为上交所股票

        Args:
            code: 股票代码（如 600000.SH 或 000001.SZ）

        Returns:
            bool: 是否为上交所股票（True为上交所，False为深交所）
        """
        if "." in code:
            market = code.split(".")[1]
            return market == "SH"
        else:
            # 如果没有后缀，根据代码前缀判断
            pure_code = code
            # 上交所：60开头（600xxx, 601xxx, 603xxx, 605xxx, 688xxx科创板等）
            return pure_code.startswith("60") or pure_code.startswith("68")

    def _is_shenzhen_exchange(self, code: str) -> bool:
        """判断是否为深交所股票

        Args:
            code: 股票代码（如 600000.SH 或 000001.SZ）

        Returns:
            bool: 是否为深交所股票
        """
        return not self._is_shanghai_exchange(code)

    def _is_fund(self, code: str) -> bool:
        """判断是否为基金
        基金代码规则：
        - ETF基金：51开头（上交所）、15开头（深交所）
        - LOF基金：16开头（深交所）
        - 货币基金：511开头（上交所）、519开头（深交所）
        """
        pure_code = self._get_pure_code(code)
        return pure_code.startswith(("51", "15", "16", "519"))

    def _get_price_precision(self, code: str) -> int:
        """获取价格精度
        基金：3位小数（0.001）
        股票：2位小数（0.01）
        """
        return 3 if self._is_fund(code) else 2

    def _is_mainboard(self, code: str) -> bool:
        """判断是否为主板股票

        主板股票代码规则：
        - 上交所主板：60开头（600xxx, 601xxx, 603xxx, 605xxx）
        - 深交所主板：00开头（000xxx, 001xxx, 002xxx）
        - 不包括：300xxx（创业板）、688xxx（科创板）、8xxx（北交所）

        Args:
            code: 股票代码（如 600000.SH 或 000001.SZ）

        Returns:
            bool: 是否为主板股票
        """
        pure_code = self._get_pure_code(code)

        # 上交所主板：60开头（600, 601, 603, 605等）
        if pure_code.startswith("60"):
            return True

        # 深交所主板：00开头（000, 001, 002等），但不包括300（创业板）
        if pure_code.startswith("00") and not pure_code.startswith("300"):
            return True

        # 其他都不是主板
        return False

    def _get_yesterday_close_price(self, code: str) -> float:
        """获取昨日收盘价

        尝试多种方法获取昨日收盘价：
        1. 使用 get_market_data_ex 获取日线数据
        2. 使用 get_market_data 获取日线数据
        3. 如果都失败，返回0（将使用接口返回的涨停价）

        Args:
            code: 股票代码（如 600000.SH）

        Returns:
            float: 昨日收盘价，如果获取失败返回0
        """
        try:
            # 方法1: 尝试使用 get_market_data_ex 获取日线数据
            try:
                # 获取最近2个交易日的数据
                market_data = xtdata.get_market_data_ex(
                    stock_list=[code],
                    period="1d",
                    count=2,
                    end_time="",
                    dividend_type="front",
                    fill_data=True,
                )
                if market_data and code in market_data:
                    data = market_data[code]
                    # data可能是list或dict，需要根据实际返回格式处理
                    if isinstance(data, list) and len(data) >= 2:
                        # 返回倒数第二天的收盘价（昨日）
                        yesterday_close = (
                            data[-2].get("close", 0)
                            if isinstance(data[-2], dict)
                            else 0
                        )
                        if yesterday_close > 0:
                            return float(yesterday_close)
                    elif isinstance(data, dict):
                        # 如果是dict格式，尝试获取close字段
                        close_data = data.get("close", [])
                        if isinstance(close_data, list) and len(close_data) >= 2:
                            yesterday_close = close_data[-2]
                            if yesterday_close > 0:
                                return float(yesterday_close)
            except Exception as e1:
                # 静默失败，继续尝试其他方法
                pass

            # 方法2: 尝试使用 get_market_data 获取日线数据
            try:
                market_data = xtdata.get_market_data(
                    stock_list=[code],
                    period="1d",
                    count=2,
                    end_time="",
                    dividend_type="front",
                    fill_data=True,
                )
                if market_data and code in market_data:
                    data = market_data[code]
                    if isinstance(data, list) and len(data) >= 2:
                        yesterday_close = (
                            data[-2].get("close", 0)
                            if isinstance(data[-2], dict)
                            else 0
                        )
                        if yesterday_close > 0:
                            return float(yesterday_close)
                    elif isinstance(data, dict):
                        close_data = data.get("close", [])
                        if isinstance(close_data, list) and len(close_data) >= 2:
                            yesterday_close = close_data[-2]
                            if yesterday_close > 0:
                                return float(yesterday_close)
            except Exception as e2:
                # 静默失败
                pass

            # 如果都失败，返回0（将使用接口返回的涨停价）
            return 0.0

        except Exception as e:
            # 静默失败，返回0
            return 0.0

    def _calculate_up_limit_price(
        self, code: str, yesterday_close: float = 0.0
    ) -> float:
        """计算主板股票涨停价

        涨停价计算规则：
        - 主板：昨日收盘价 * 1.10（四舍五入到分）

        注意：只支持主板股票（60/00开头），不支持创业板、科创板、北交所

        Args:
            code: 股票代码
            yesterday_close: 昨日收盘价，如果为0则尝试获取

        Returns:
            float: 计算出的涨停价，如果计算失败或不是主板股票返回0
        """
        # 只处理主板股票
        if not self._is_mainboard(code):
            return 0.0

        # 如果未提供昨日收盘价，尝试获取
        if yesterday_close <= 0:
            yesterday_close = self._get_yesterday_close_price(code)

        if yesterday_close <= 0:
            return 0.0

        # 主板涨停价：+10%
        up_limit_ratio = 1.10

        # 计算涨停价（四舍五入到分）
        precision = self._get_price_precision(code)
        calculated_up_limit = round(yesterday_close * up_limit_ratio, precision)

        return calculated_up_limit

    def _apply_price_cage_limit(
        self,
        order_price: float,
        direction: str,
        ask_price1: float,
        bid_price1: float,
        last_price: float,
        precision: int,
    ) -> float:
        """应用价格笼子限制

        A股价格笼子规则（2020年8月24日起实施）：
        - 买入：不超过买入基准价的102%（买入基准价 = 卖一价，如果没有卖一价则用最新价）
        - 卖出：不低于卖出基准价的98%（卖出基准价 = 买一价，如果没有买一价则用最新价）

        Args:
            order_price: 原始订单价格
            direction: 买卖方向 ("buy" 或 "sell")
            ask_price1: 卖一价
            bid_price1: 买一价
            last_price: 最新成交价
            precision: 价格精度

        Returns:
            调整后的订单价格（如果超过价格笼子则调整到边界）
        """
        if direction == "buy":
            # 买入基准价：优先使用卖一价，如果没有则使用最新价
            buy_base_price = ask_price1 if ask_price1 > 0 else last_price
            if buy_base_price <= 0:
                print(f"  警告: 无法确定买入基准价，跳过价格笼子检查")
                return order_price

            # 价格笼子上限：买入基准价的102%
            price_cage_upper = round(buy_base_price * 1.02, precision)

            if order_price > price_cage_upper:
                format_str = f".{precision}f"
                print(
                    f"  价格笼子限制: 买入价格 {order_price:{format_str}} 超过上限 {price_cage_upper:{format_str}} "
                    f"(基准价: {buy_base_price:{format_str}} * 102%)"
                )
                adjusted_price = price_cage_upper
                print(f"  已调整买入价格至: {adjusted_price:{format_str}}")
                return adjusted_price
            else:
                return order_price
        else:  # sell
            # 卖出基准价：优先使用买一价，如果没有则使用最新价
            sell_base_price = bid_price1 if bid_price1 > 0 else last_price
            if sell_base_price <= 0:
                print(f"  警告: 无法确定卖出基准价，跳过价格笼子检查")
                return order_price

            # 价格笼子下限：卖出基准价的98%
            price_cage_lower = round(sell_base_price * 0.98, precision)

            if order_price < price_cage_lower:
                format_str = f".{precision}f"
                print(
                    f"  价格笼子限制: 卖出价格 {order_price:{format_str}} 低于下限 {price_cage_lower:{format_str}} "
                    f"(基准价: {sell_base_price:{format_str}} * 98%)"
                )
                adjusted_price = price_cage_lower
                print(f"  已调整卖出价格至: {adjusted_price:{format_str}}")
                return adjusted_price
            else:
                return order_price

    def _place_order(
        self,
        code: str,
        volume: int = None,
        direction: str = None,
        order_info: Dict = None,
        retry=0,
    ):
        """执行MiniQMT实际下单（统一入口：支持预处理或直接使用预处理好的信息）

        Args:
            code: 股票代码
            volume: 数量（如果order_info为None时使用）
            direction: 方向 "buy" 或 "sell"（如果order_info为None时使用）
            order_info: 预处理好的订单信息（如果提供则直接使用，否则先预处理）
            retry: 重试次数
        """
        if self.trader is None:
            print(f"交易连接未初始化，无法下单: {code}")
            return

        # 如果提供了预处理好的信息，直接使用；否则先预处理
        if order_info is None:
            # 需要先预处理
            if volume is None or direction is None:
                print(
                    f"参数错误: {code} 需要提供 volume 和 direction，或提供 order_info"
                )
                return

            prepared_info = self._prepare_order_info(code, volume, direction)
            if not prepared_info:
                print(f"  ✗ {code} 预处理失败，无法下单")
                return

            # 合并信息
            order_info = {"volume": volume}
            order_info.update(prepared_info)
        else:
            # 使用预处理好的信息
            direction = (
                "buy" if order_info["order_type"] == xtconstant.STOCK_BUY else "sell"
            )

        # 执行下单逻辑
        try:
            account = StockAccount(self.account_id)
            order_type_str = order_info.get("price_type_name", "限价单")

            # 检查是否在9:30开盘时间（需要延迟下单，仅对买入有效）
            now = datetime.now()
            is_market_open_time = (
                direction == "buy"
                and now.hour == 9
                and now.minute == 30
                and now.second < 2
            )  # 9:30:00-9:30:02之间认为是开盘时间

            # 如果在开盘时间，延迟下单（避免交易所未准备好）
            if is_market_open_time and g.market_open_delay > 0:
                delay_seconds = g.market_open_delay
                current_time_ms = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                print(
                    f"[{current_time_ms}] 检测到开盘时间（9:30），延迟 {delay_seconds} 秒后下单: {code}"
                )
                time.sleep(delay_seconds)
                current_time_ms = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                print(f"[{current_time_ms}] 延迟结束，开始下单: {code}")

            order_time_ms = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

            if direction == "buy":
                print(
                    f"[{order_time_ms}] 发出买入委托单: {code}, 数量: {order_info['volume']} 股, "
                    f"价格类型: {order_type_str}, 价格: {order_info['order_price']}"
                )
            else:
                print(
                    f"[{order_time_ms}] 发出卖出委托单: {code}, 数量: {order_info['volume']} 股, "
                    f"价格: {order_info['order_price']}"
                )

            # 执行下单
            order_id = self.trader.order_stock(
                account=account,
                stock_code=code,
                order_type=order_info["order_type"],
                order_volume=order_info["volume"],
                price_type=order_info["price_type"],
                price=order_info["order_price"],
                strategy_name=g.strategy_name,
                order_remark=f"{retry}_{datetime.now()}",
            )

            if order_id > 0:
                current_time_ms = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                if direction == "buy":
                    print(
                        f"[{current_time_ms}] 下单成功（{order_type_str}）: {code}, 买入, "
                        f"{order_info['volume']} 股, 价格: {order_info['order_price']}, 订单号: {order_id}"
                    )
                else:
                    print(
                        f"[{current_time_ms}] 下单成功: {code}, 卖出, "
                        f"{order_info['volume']} 股, 价格: {order_info['order_price']}, 订单号: {order_id}"
                    )
            else:
                current_time_ms = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                print(f"[{current_time_ms}] 下单失败: {code}, 错误码: {order_id}")

        except Exception as e:
            print(f"下单异常: {code}, {str(e)}")

    def _convert_qmt_code_to_jq(self, qmt_code: str) -> str:
        """将MiniQMT代码转换为聚宽代码
        511260.SH -> 511260.XSHG
        511260.SZ -> 511260.XSHE
        """
        if "." not in qmt_code:
            return qmt_code

        code, market = qmt_code.split(".")
        if market == "SH":
            return f"{code}.XSHG"
        elif market == "SZ":
            return f"{code}.XSHE"
        return qmt_code



    def update_total_asset_only(
        self, strategy_name: str, internal_password: str = "admin123"
    ) -> Dict:
        """仅更新账户总资产和密码（用于下午3点定时更新）

        Args:
            strategy_name: 策略名称
            internal_password: 内部API密码，默认为 "admin123"

        Returns:
            包含更新结果的字典
        """
        if self.trader is None:
            return {
                "success": False,
                "message": "交易连接未初始化，无法获取账户资产",
            }

        try:
            # 获取账户资产信息
            account = StockAccount(self.account_id)
            total_asset = 0.0
            try:
                asset = self.trader.query_stock_asset(account)
                if asset:
                    total_asset = float(asset.total_asset)
                    print(f"账户总资产: {total_asset}")
                else:
                    print("警告: 无法获取账户资产信息，总资产字段将设为0")
            except Exception as e:
                print(f"警告: 查询账户资产信息失败: {str(e)}，总资产字段将设为0")

            # 调用内部API接口，仅更新总资产（不更新持仓）
            url = f"{self.api_url}/api/v1/positions/update/total_asset/internal"
            data = {
                "strategy_name": strategy_name,
                "total_asset": total_asset,
                "internal_password": internal_password,
            }
            headers = {"Content-Type": "application/json"}

            response = requests.post(url, json=data, headers=headers, timeout=10)
            if response.status_code != 200:
                error_msg = (
                    f"更新总资产失败: HTTP {response.status_code} - {response.text}"
                )
                print(error_msg)
                return {
                    "success": False,
                    "message": error_msg,
                }

            result = response.json()
            print(f"总资产更新成功: 策略={strategy_name}, 总资产={total_asset}")
            return {
                "success": True,
                "message": result.get("message", "总资产更新成功"),
                "total_asset": total_asset,
            }

        except requests.exceptions.Timeout:
            error_msg = "更新总资产超时"
            print(error_msg)
            return {
                "success": False,
                "message": error_msg,
            }
        except requests.exceptions.RequestException as e:
            error_msg = f"更新总资产网络错误: {str(e)}"
            print(error_msg)
            return {
                "success": False,
                "message": error_msg,
            }
        except Exception as e:
            error_msg = f"更新总资产异常: {str(e)}"
            print(error_msg)
            return {
                "success": False,
                "message": error_msg,
            }


# 全局变量存储调度任务
scheduled_tasks = {}
task_counter = 0


# 全局定时器回调函数
def global_timer_callback():
    """全局定时器回调函数，检查所有待执行的任务"""
    current_time = datetime.now()
    tasks_to_remove = []

    # 创建字典的副本来避免迭代时修改字典
    tasks_snapshot = dict(scheduled_tasks)

    for task_id, task_info in tasks_snapshot.items():
        # 检查任务是否仍然存在（可能已被其他地方删除）
        if task_id not in scheduled_tasks:
            continue

        if not task_info["executed"] and current_time >= task_info["target_time"]:
            # 在原字典中标记为已执行
            if task_id in scheduled_tasks:
                scheduled_tasks[task_id]["executed"] = True

            try:
                task_info["func"]()
            except Exception as e:
                print(f"执行调度任务时发生错误: {e}")
            finally:
                tasks_to_remove.append(task_id)

    # 清理已执行的任务
    for task_id in tasks_to_remove:
        if task_id in scheduled_tasks:
            del scheduled_tasks[task_id]


def schedule_run(func, target_time):
    """调度函数在指定时间执行"""
    global task_counter
    task_counter += 1
    task_id = f"task_{task_counter}"

    # 存储任务信息
    scheduled_tasks[task_id] = {
        "func": func,
        "target_time": target_time,
        "executed": False,
    }

    return task_id


def cancel_scheduled_task(task_id):
    """取消已调度的任务"""
    if task_id in scheduled_tasks:
        del scheduled_tasks[task_id]
        return True
    return False


DEBUG = False


def get_trading_time_slots():
    """获取实际交易时间段（用于买入判断）

    实际交易时间：
    - 上午：9:30 - 11:30
    - 下午：13:00 - 15:30

    Returns:
        tuple: (morning_start, morning_end, afternoon_start, afternoon_end)
    """
    morning_start = datetime.strptime("09:30:00", "%H:%M:%S").time()
    morning_end = datetime.strptime("11:30:00", "%H:%M:%S").time()
    afternoon_start = datetime.strptime("13:00:00", "%H:%M:%S").time()
    afternoon_end = datetime.strptime("15:30:00", "%H:%M:%S").time()
    return morning_start, morning_end, afternoon_start, afternoon_end


def get_sync_time_slots():
    """获取同步操作时间段（用于持仓同步等操作）

    同步时间：
    - 上午：9:26 - 11:30（比实际交易时间提前4分钟）
    - 下午：13:00 - 15:30

    Returns:
        tuple: (morning_sync_start, morning_end, afternoon_start, afternoon_end)
    """
    morning_sync_start = datetime.strptime("09:26:00", "%H:%M:%S").time()
    morning_end = datetime.strptime("11:30:00", "%H:%M:%S").time()
    afternoon_start = datetime.strptime("13:00:00", "%H:%M:%S").time()
    afternoon_end = datetime.strptime("15:30:00", "%H:%M:%S").time()
    return morning_sync_start, morning_end, afternoon_start, afternoon_end


def is_trading_time_now(current_time=None) -> bool:
    """判断当前时间是否在实际交易时间内（用于买入判断）

    实际交易时间：
    - 上午：9:30 - 11:30
    - 下午：13:00 - 15:30

    Args:
        current_time: 要判断的时间，如果为None则使用当前时间

    Returns:
        bool: 是否在实际交易时间内
    """
    if current_time is None:
        current_time = datetime.now().time()

    morning_start, morning_end, afternoon_start, afternoon_end = (
        get_trading_time_slots()
    )

    # 上午时段：9:30 - 11:30
    in_morning = morning_start <= current_time <= morning_end
    # 下午时段：13:00 - 15:30
    in_afternoon = afternoon_start <= current_time <= afternoon_end

    return in_morning or in_afternoon


def is_sync_time_now(current_time=None) -> bool:
    """判断当前时间是否在同步操作时间内（用于持仓同步等操作）

    同步时间：
    - 上午：9:26 - 11:30（比实际交易时间提前4分钟）
    - 下午：13:00 - 15:30

    Args:
        current_time: 要判断的时间，如果为None则使用当前时间

    Returns:
        bool: 是否在同步操作时间内
    """
    if current_time is None:
        current_time = datetime.now().time()

    morning_sync_start, morning_end, afternoon_start, afternoon_end = (
        get_sync_time_slots()
    )

    # 上午时段：9:26 - 11:30
    in_morning = morning_sync_start <= current_time <= morning_end
    # 下午时段：13:00 - 15:30
    in_afternoon = afternoon_start <= current_time <= afternoon_end

    return in_morning or in_afternoon


def is_pre_trading_time(current_time=None) -> bool:
    """判断当前时间是否在预交易时间（9:26-9:30之间）

    在这个时间段内，只记录交易操作到内存，不实际执行。

    Args:
        current_time: 要判断的时间，如果为None则使用当前时间

    Returns:
        bool: 是否在预交易时间（9:26-9:30之间）
    """
    if current_time is None:
        current_time = datetime.now().time()

    # 判断是否在9:26-9:30之间
    pre_start = datetime.strptime("09:26:00", "%H:%M:%S").time()
    pre_end = datetime.strptime("09:30:00", "%H:%M:%S").time()

    return pre_start <= current_time < pre_end


# 修改原有的adjust函数
def adjust():
    """主要的调整函数（持仓同步操作）"""
    now = datetime.now()
    current_time = now.time()

    # 使用同步时间判断函数（9:26开始）
    is_sync_time = is_sync_time_now(current_time)

    if is_sync_time or DEBUG:
        # 在同步时间内，执行同步操作
        if g.trader:
            g.trader.sync_positions()
        # 安排下一次运行
        next_run = now + timedelta(seconds=g.sync_positions_interval)
        # 检查下一次运行时间是否超出当前同步时段
        if not is_sync_time_now(next_run.time()) and not DEBUG:
            # 如果超出，需要安排到下一个同步时段
            morning_sync_start, morning_end, afternoon_start, afternoon_end = (
                get_sync_time_slots()
            )

            # 根据当前时间判断在哪个同步时段
            if morning_sync_start <= current_time <= morning_end:
                # 当前在上午同步时段，下一个应该是下午13:00
                next_run = now.replace(hour=13, minute=0, second=0, microsecond=0)
            elif afternoon_start <= current_time <= afternoon_end:
                # 当前在下午同步时段，下一个应该是明天上午9:26
                next_run = (now + timedelta(days=1)).replace(
                    hour=9, minute=26, second=0, microsecond=0
                )
            else:
                # 其他情况（理论上不应该发生，因为已经在同步时间内）
                # 但为了安全，安排到下一个同步时段
                if current_time < morning_sync_start:
                    next_run = now.replace(hour=9, minute=26, second=0, microsecond=0)
                elif morning_end < current_time < afternoon_start:
                    next_run = now.replace(hour=13, minute=0, second=0, microsecond=0)
                else:
                    next_run = (now + timedelta(days=1)).replace(
                        hour=9, minute=26, second=0, microsecond=0
                    )
    else:
        # 非同步时间，智能安排下一次运行时间
        morning_sync_start, morning_end, afternoon_start, afternoon_end = (
            get_sync_time_slots()
        )

        if current_time < morning_sync_start:
            # 还没到上午同步时间，安排到今天上午9:26
            next_run = now.replace(hour=9, minute=26, second=0, microsecond=0)
        elif morning_end < current_time < afternoon_start:
            # 在上午和下午之间，安排到今天下午13:00
            next_run = now.replace(hour=13, minute=0, second=0, microsecond=0)
        else:
            # 已经过了下午同步时间，安排到明天上午9:26
            next_run = (now + timedelta(days=1)).replace(
                hour=9, minute=26, second=0, microsecond=0
            )

    # 安排下一次运行
    schedule_run(adjust, next_run)


def update_total_asset_at_3pm():
    """在指定时间更新总资产和密码的定时任务"""
    now = datetime.now()

    # 执行更新操作
    if g.trader and g.trader.trader:
        sync_strategy_name = g.strategy_names[0] if g.strategy_names else "实际持仓"
        result = g.trader.update_total_asset_only(
            strategy_name=sync_strategy_name,
            internal_password=g.internal_password,
        )
        if result["success"]:
            print(
                f"{g.total_asset_update_hour:02d}:{g.total_asset_update_minute:02d} 总资产更新成功: {result.get('total_asset', 'N/A')}"
            )
        else:
            print(
                f"{g.total_asset_update_hour:02d}:{g.total_asset_update_minute:02d} 总资产更新失败: {result.get('message', '未知错误')}"
            )

    else:
        print("警告: 交易连接未建立，跳过总资产更新")

    # 安排明天指定时间再次执行
    next_run = (now + timedelta(days=1)).replace(
        hour=g.total_asset_update_hour,
        minute=g.total_asset_update_minute,
        second=0,
        microsecond=0,
    )
    schedule_run(update_total_asset_at_3pm, next_run)


def init(account_id: str):
    """初始化函数"""
    g.account_id = account_id
    g.trader = MiniQMTAPI(account_id, g.strategy_names)
    print(f"!!!!当前监控策略:{g.strategy_names}")

    # 初始化latest_update_time为当天的0点
    now = datetime.now()

    # 计算今天的启动时间（支持毫秒）
    current_time = now.time()

    # 获取同步时间段（9:26开始）
    morning_sync_start, morning_end, afternoon_start, afternoon_end = (
        get_sync_time_slots()
    )

    # 使用同步时间判断函数（9:26开始）
    if is_sync_time_now(current_time) or DEBUG:
        # 在同步时间内，立即运行
        g.first_run = now.replace(
            hour=g.sync_start_hour,
            minute=g.sync_start_minute,
            second=0,
            microsecond=g.sync_start_millisecond * 1000,
        )
    else:
        # 非同步时间，安排到下一个同步时段
        if current_time < morning_sync_start:
            # 还没到上午同步时间，安排到今天上午9:26
            g.first_run = now.replace(
                hour=9, minute=26, second=0, microsecond=g.sync_start_millisecond * 1000
            )
        elif morning_end < current_time < afternoon_start:
            # 在上午和下午之间，安排到今天下午13:00
            g.first_run = now.replace(
                hour=13, minute=0, second=0, microsecond=g.sync_start_millisecond * 1000
            )
        else:
            # 已经过了下午同步时间，安排到明天上午9:26
            g.first_run = (now + timedelta(days=1)).replace(
                hour=9, minute=26, second=0, microsecond=g.sync_start_millisecond * 1000
            )
    print(f"设置第一次运行时间:{g.first_run}")

    g.latest_update_time = now.strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"初始化latest_update_time为{g.latest_update_time}, 之前更新的策略将不同步，如果需要同步请注释掉此行"
    )

    # 设置调度，从first_run开始运行
    schedule_run(adjust, g.first_run)

    # 设置总资产更新的定时任务
    current_time = now.time()
    target_time = datetime.strptime(
        f"{g.total_asset_update_hour:02d}:{g.total_asset_update_minute:02d}:00",
        "%H:%M:%S",
    ).time()
    if current_time < target_time:
        # 今天还没到指定时间，安排今天执行
        asset_update_time = now.replace(
            hour=g.total_asset_update_hour,
            minute=g.total_asset_update_minute,
            second=0,
            microsecond=0,
        )
    else:
        # 今天已经过了指定时间，安排明天执行
        asset_update_time = (now + timedelta(days=1)).replace(
            hour=g.total_asset_update_hour,
            minute=g.total_asset_update_minute,
            second=0,
            microsecond=0,
        )
    schedule_run(update_total_asset_at_3pm, asset_update_time)
    print(
        f"设置总资产更新任务: 每天 {g.total_asset_update_hour:02d}:{g.total_asset_update_minute:02d} 执行，首次执行时间: {asset_update_time}"
    )

    # 启动定时器检查任务
    import threading

    def timer_loop():
        while True:
            global_timer_callback()
            time.sleep(0.1)  # 100毫秒检查一次

    timer_thread = threading.Thread(target=timer_loop, daemon=True)
    timer_thread.start()




# 主运行函数
def run():
    """主运行函数，保持程序运行"""
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("程序退出")
        if g.trader and g.trader.trader:
            g.trader.trader.stop()


# 使用示例
if __name__ == "__main__":
    # 初始化，使用配置的账户ID
    init(ACCOUNT_ID)

    # 运行程序
    run()
