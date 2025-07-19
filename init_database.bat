@echo off
chcp 65001 >nul
echo ================================
echo JQ-QMT 数据库初始化脚本
echo ================================
echo.

echo 1. 检查Python环境...
python --version
if %errorlevel% neq 0 (
    echo ❌ Python 未安装或未添加到PATH
    pause
    exit /b 1
)
echo ✓ Python 环境正常

echo.
echo 2. 安装依赖包...
pip install flask flask-sqlalchemy pymysql redis requests cryptography
if %errorlevel% neq 0 (
    echo ⚠️  依赖包安装可能有问题，继续尝试初始化...
) else (
    echo ✓ 依赖包安装完成
)

echo.
echo 3. 运行数据库初始化...
python setup_database.py
if %errorlevel% neq 0 (
    echo.
    echo ❌ Python初始化失败，尝试直接执行SQL文件
    echo 请手动执行以下步骤：
    echo 1. 连接到MySQL服务器
    echo 2. 执行 database_schema.sql 文件
    echo 3. 检查 src/config.py 中的数据库配置
    pause
    exit /b 1
)

echo.
echo 4. 启动应用测试...
echo 正在启动Flask应用进行连接测试...
timeout /t 3 >nul
python -c "
import sys
sys.path.insert(0, '.')
try:
    from src.app import create_app
    app = create_app()
    print('✓ 应用创建成功')
    print('✓ 数据库连接正常')
    print('🚀 可以启动应用: python src/app.py')
except Exception as e:
    print(f'❌ 应用测试失败: {e}')
    sys.exit(1)
"

if %errorlevel% neq 0 (
    echo ❌ 应用测试失败
    pause
    exit /b 1
)

echo.
echo ================================
echo ✅ 数据库初始化完成！
echo ================================
echo.
echo 📋 初始化信息:
echo • 默认密码: admin123
echo • 示例策略: example_strategy, hand_strategy
echo • 管理界面: http://localhost:5366
echo.
echo 🚀 下一步:
echo 1. 运行: python src/app.py
echo 2. 打开浏览器访问管理界面
echo 3. 配置QMT交易脚本
echo.
pause
