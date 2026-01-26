from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json
import copy
import hashlib

db = SQLAlchemy()


class StrategyPosition(db.Model):
    __tablename__ = "strategy_positions"

    id = db.Column(db.Integer, primary_key=True)
    strategy_name = db.Column(db.String(100), index=True, nullable=False, unique=True)
    positions = db.Column(db.JSON, nullable=False)
    total_asset = db.Column(db.String(128), nullable=False, server_default="0")
    update_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    @staticmethod
    def update_positions(strategy_name, positions, total_asset=None):
        # 校验策略名称
        if not strategy_name or not isinstance(strategy_name, str):
            raise ValueError("策略名称不能为空且必须为字符串类型")

        # 校验持仓数据
        if not isinstance(positions, list):
            raise ValueError("持仓数据必须为列表类型")

        for pos in positions:
            if not isinstance(pos, dict):
                raise ValueError("持仓数据的每个元素必须为字典类型")

            # 检查必需字段
            required_fields = {"code", "volume", "cost"}
            if not all(field in pos for field in required_fields):
                raise ValueError(f"持仓数据缺少必需字段: {required_fields}")

            # 校验字段类型和值
            if not isinstance(pos["code"], str) or not pos["code"]:
                raise ValueError("股票代码必须为非空字符串")

            # 对于调整策略，允许负数持仓
            if strategy_name.startswith("ADJUSTMENT_"):
                if not isinstance(pos["volume"], (int, float)):
                    raise ValueError("持仓数量必须为数字")
                # 调整策略允许负数持仓和负成本
                if not isinstance(pos["cost"], (int, float)):
                    raise ValueError("成本价必须为数字")
            else:
                if not isinstance(pos["volume"], (int, float)) or pos["volume"] < 0:
                    raise ValueError("持仓数量必须为非负数")

                if not isinstance(pos["cost"], (int, float)) or pos["cost"] <= 0:
                    raise ValueError("成本价必须为正数")

            # 校验股票名称字段（可选）
            if "name" in pos and not isinstance(pos["name"], str):
                raise ValueError("股票名称必须为字符串类型")

            # 禁止持仓项中包含 total_asset 字段，它应该在策略层级
            if "total_asset" in pos:
                raise ValueError(
                    f"持仓项中不允许包含 total_asset 字段（股票代码: {pos.get('code', 'unknown')}）。"
                    "total_asset 应该在策略层级传递，而不是在每个持仓项中。"
                )

        # 校验 total_asset 字段（可选）
        if total_asset is not None:
            # 支持字符串、整数、浮点数输入，统一转换为字符串存储
            if isinstance(total_asset, (int, float)):
                if total_asset < 0:
                    raise ValueError("账户总资产必须为非负数")
                # 转换为字符串，保留足够精度
                total_asset = str(total_asset)
            elif isinstance(total_asset, str):
                # 验证字符串是否可以转换为有效数字
                try:
                    asset_value = float(total_asset)
                    if asset_value < 0:
                        raise ValueError("账户总资产必须为非负数")
                except ValueError:
                    raise ValueError("账户总资产格式无效，必须为数字字符串")
            else:
                raise ValueError("账户总资产必须为字符串、整数或浮点数类型")

        # 确保所有字段都被保留，特别是 name 字段
        # 使用深拷贝确保数据完整性，避免 SQLAlchemy JSON 序列化时丢失字段
        normalized_positions = [copy.deepcopy(pos) for pos in positions]

        # 执行更新
        strategy = StrategyPosition.query.filter_by(strategy_name=strategy_name).first()

        if strategy:
            strategy.positions = normalized_positions
            if total_asset is not None:
                strategy.total_asset = str(total_asset)
        else:
            strategy = StrategyPosition(
                strategy_name=strategy_name,
                positions=normalized_positions,
                total_asset=str(total_asset) if total_asset is not None else "0",
            )
            db.session.add(strategy)

        db.session.commit()

    @staticmethod
    def update_total_asset_only(strategy_name: str, total_asset):
        """仅更新策略的总资产，不更新持仓数据

        Args:
            strategy_name: 策略名称
            total_asset: 总资产值（字符串、整数或浮点数）

        Raises:
            ValueError: 如果参数无效
        """
        # 校验策略名称
        if not strategy_name or not isinstance(strategy_name, str):
            raise ValueError("策略名称不能为空且必须为字符串类型")

        # 校验 total_asset 字段
        if total_asset is None:
            raise ValueError("总资产不能为 None")

        # 支持字符串、整数、浮点数输入，统一转换为字符串存储
        if isinstance(total_asset, (int, float)):
            if total_asset < 0:
                raise ValueError("账户总资产必须为非负数")
            # 转换为字符串，保留足够精度
            total_asset = str(total_asset)
        elif isinstance(total_asset, str):
            # 验证字符串是否可以转换为有效数字
            try:
                asset_value = float(total_asset)
                if asset_value < 0:
                    raise ValueError("账户总资产必须为非负数")
            except ValueError:
                raise ValueError("账户总资产格式无效，必须为数字字符串")
        else:
            raise ValueError("账户总资产必须为字符串、整数或浮点数类型")

        # 执行更新
        strategy = StrategyPosition.query.filter_by(strategy_name=strategy_name).first()

        if strategy:
            # 只更新 total_asset，不更新 positions
            strategy.total_asset = str(total_asset)
            db.session.commit()
        else:
            # 如果策略不存在，创建一个新记录（持仓为空）
            strategy = StrategyPosition(
                strategy_name=strategy_name,
                positions=[],
                total_asset=str(total_asset),
            )
            db.session.add(strategy)
            db.session.commit()

    @staticmethod
    def get_strategy_positions(strategy_name):
        strategy = StrategyPosition.query.filter_by(strategy_name=strategy_name).first()
        return strategy.positions if strategy else []

    @staticmethod
    def get_all_strategy_positions():
        strategies = StrategyPosition.query.all()
        return [
            {
                "strategy_name": strategy.strategy_name,
                "positions": strategy.positions,
                "total_asset": strategy.total_asset,
                "update_time": strategy.update_time,
            }
            for strategy in strategies
        ]

    @staticmethod
    def get_total_positions(strategy_names=None, include_adjustments=True):
        # 获取策略数据
        if strategy_names:
            all_strategies = StrategyPosition.query.filter(
                StrategyPosition.strategy_name.in_(strategy_names)
            ).all()
        else:
            # 获取所有策略，但可以选择是否包含调整策略
            if include_adjustments:
                all_strategies = StrategyPosition.query.all()
            else:
                all_strategies = StrategyPosition.query.filter(
                    ~StrategyPosition.strategy_name.like("ADJUSTMENT_%")
                ).all()

        total_positions = {}
        # 设置默认的最早开始时间
        latest_update_time = datetime(1970, 1, 1)
        # 用于存储总资产（取第一个非空值，因为通常多个策略共享同一个账户）
        total_asset = None

        for strategy in all_strategies:
            # 更新最新时间
            if latest_update_time is None or strategy.update_time > latest_update_time:
                latest_update_time = strategy.update_time

            # 获取总资产（取第一个非空值）
            if total_asset is None and strategy.total_asset is not None:
                total_asset = strategy.total_asset

            for pos in strategy.positions:
                code = pos["code"]
                if code not in total_positions:
                    total_positions[code] = {
                        "code": code,
                        "name": pos.get(
                            "name", code
                        ),  # 使用股票名称，如果没有则使用代码
                        "total_volume": 0,
                        "total_cost": 0,
                    }

                # 对于调整策略，直接加减持仓数量和成本
                if strategy.strategy_name.startswith("ADJUSTMENT_"):
                    total_positions[code]["total_volume"] += pos["volume"]
                    total_positions[code]["total_cost"] += pos["volume"] * pos["cost"]
                else:
                    total_positions[code]["total_volume"] += pos["volume"]
                    total_positions[code]["total_cost"] += pos["volume"] * pos["cost"]

        # 计算平均成本并过滤掉持仓为0的股票
        filtered_positions = {}
        for code in total_positions:
            if total_positions[code]["total_volume"] != 0:
                if total_positions[code]["total_volume"] > 0:
                    total_positions[code]["avg_cost"] = (
                        total_positions[code]["total_cost"]
                        / total_positions[code]["total_volume"]
                    )
                else:
                    # 负持仓的情况，显示平均成本
                    total_positions[code]["avg_cost"] = (
                        total_positions[code]["total_cost"]
                        / total_positions[code]["total_volume"]
                    )
                del total_positions[code]["total_cost"]
                filtered_positions[code] = total_positions[code]

        return {
            "positions": list(filtered_positions.values()),
            "total_asset": total_asset,
            "update_time": latest_update_time,
        }

    @staticmethod
    def get_total_positions_with_coefficients(
        parsed_strategies=None, include_adjustments=True
    ):
        """
        获取带系数的总持仓，支持策略名带系数（如：策略名x0.1）
        最终持仓按最小单位100股进行四舍五入处理
        """
        import math

        # 如果没有指定策略，使用原有逻辑
        if not parsed_strategies:
            return StrategyPosition.get_total_positions(None, include_adjustments)

        # 提取策略名列表
        strategy_names = [s["name"] for s in parsed_strategies]

        # 获取策略数据
        all_strategies = StrategyPosition.query.filter(
            StrategyPosition.strategy_name.in_(strategy_names)
        ).all()

        # 创建策略名到系数的映射
        coefficient_map = {s["name"]: s["coefficient"] for s in parsed_strategies}

        total_positions = {}
        # 设置默认的最早开始时间
        latest_update_time = datetime(1970, 1, 1)
        # 用于存储总资产（取第一个非空值，因为通常多个策略共享同一个账户）
        total_asset = None

        for strategy in all_strategies:
            # 更新最新时间
            if latest_update_time is None or strategy.update_time > latest_update_time:
                latest_update_time = strategy.update_time

            # 获取总资产（取第一个非空值）
            if total_asset is None and strategy.total_asset is not None:
                total_asset = strategy.total_asset

            # 获取该策略的系数
            coefficient = coefficient_map.get(strategy.strategy_name, 1.0)

            for pos in strategy.positions:
                code = pos["code"]
                if code not in total_positions:
                    total_positions[code] = {
                        "code": code,
                        "name": pos.get(
                            "name", code
                        ),  # 使用股票名称，如果没有则使用代码
                        "total_volume": 0,
                        "total_cost": 0,
                    }

                # 应用系数
                adjusted_volume = pos["volume"] * coefficient

                # 对于调整策略，直接加减持仓数量和成本
                if strategy.strategy_name.startswith("ADJUSTMENT_"):
                    total_positions[code]["total_volume"] += adjusted_volume
                    total_positions[code]["total_cost"] += adjusted_volume * pos["cost"]
                else:
                    total_positions[code]["total_volume"] += adjusted_volume
                    total_positions[code]["total_cost"] += adjusted_volume * pos["cost"]

        # 计算平均成本并过滤掉持仓为0的股票，同时进行最小单位处理
        filtered_positions = {}
        for code in total_positions:
            original_volume = total_positions[code]["total_volume"]

            # 按最小单位100股进行向下取整
            if original_volume != 0:
                # 向下取整到最近的100股
                rounded_volume = int(original_volume / 100) * 100

                # 如果向下取整后为0，但原始持仓不为0，则跳过
                if rounded_volume == 0:
                    continue

                total_positions[code]["total_volume"] = int(rounded_volume)

                if total_positions[code]["total_volume"] > 0:
                    total_positions[code]["avg_cost"] = (
                        total_positions[code]["total_cost"]
                        / original_volume  # 使用原始持仓计算平均成本
                    )
                else:
                    # 负持仓的情况，显示平均成本
                    total_positions[code]["avg_cost"] = (
                        total_positions[code]["total_cost"]
                        / original_volume  # 使用原始持仓计算平均成本
                    )
                del total_positions[code]["total_cost"]
                filtered_positions[code] = total_positions[code]

        return {
            "positions": list(filtered_positions.values()),
            "total_asset": total_asset,
            "update_time": latest_update_time,
        }

    @staticmethod
    def refresh_all_strategies_time():
        """刷新所有有效策略的更新时间为当前时间"""
        try:
            # 获取所有策略
            strategies = StrategyPosition.query.all()

            if not strategies:
                return {
                    "success": False,
                    "message": "没有找到任何策略",
                    "updated_count": 0,
                }

            # 更新所有策略的时间
            current_time = datetime.now()
            updated_count = 0

            for strategy in strategies:
                strategy.update_time = current_time
                updated_count += 1

            db.session.commit()

            return {
                "success": True,
                "message": f"成功刷新了 {updated_count} 个策略的时间",
                "updated_count": updated_count,
                "update_time": current_time.strftime("%Y-%m-%d %H:%M:%S"),
            }

        except Exception as e:
            db.session.rollback()
            return {
                "success": False,
                "message": f"刷新策略时间失败: {str(e)}",
                "updated_count": 0,
            }


class InternalPassword(db.Model):
    __tablename__ = "internal_passwords"

    id = db.Column(db.Integer, primary_key=True)
    password_hash = db.Column(db.String(64), nullable=False)
    created_time = db.Column(db.DateTime, default=datetime.now)
    updated_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    @staticmethod
    def hash_password(password):
        """对密码进行SHA256哈希"""
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    @staticmethod
    def set_password(password):
        """设置或更新密码"""
        password_hash = InternalPassword.hash_password(password)

        # 查找现有记录
        existing = InternalPassword.query.first()
        if existing:
            existing.password_hash = password_hash
            existing.updated_time = datetime.now()
        else:
            # 创建新记录
            new_password = InternalPassword(password_hash=password_hash)
            db.session.add(new_password)

        db.session.commit()

    @staticmethod
    def verify_password(password):
        """验证密码"""
        password_hash = InternalPassword.hash_password(password)
        existing = InternalPassword.query.first()

        if not existing:
            # 如果没有设置密码，使用默认密码 "admin123"
            default_hash = InternalPassword.hash_password("admin123")
            return password_hash == default_hash

        return existing.password_hash == password_hash

    @staticmethod
    def get_current_password_info():
        """获取当前密码信息（不包含密码本身）"""
        existing = InternalPassword.query.first()
        if existing:
            return {
                "has_password": True,
                "created_time": existing.created_time.strftime("%Y-%m-%d %H:%M:%S"),
                "updated_time": existing.updated_time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        else:
            return {
                "has_password": False,
                "default_password": "admin123",
                "message": "使用默认密码，建议通过数据库修改",
            }
