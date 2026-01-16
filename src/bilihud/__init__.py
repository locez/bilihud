"""Top-level package for bilihud."""

import sys
import os

# 优先查找包内的 vendor (安装模式)
_local_vendor = os.path.join(os.path.dirname(__file__), 'vendor')
# 其次查找项目根目录的 vendor (开发模式)
# 开发模式结构: src/bilihud/__init__.py -> ../../vendor/blivedm
_dev_vendor = os.path.join(os.path.dirname(__file__), '..', '..', 'vendor', 'blivedm')

if os.path.exists(_local_vendor):
    if _local_vendor not in sys.path:
        sys.path.insert(0, _local_vendor)
    # Also add site-packages inside vendor if pip installs there (e.g. vendor/lib/pythonX.Y/site-packages)
    # But for simplicity, we will instruct pip to install flatly or we handle it in CI.
    # Actually, simpler: We will install dependencies into src/bilihud/vendor directly.
    # So imports like 'import qasync' will work if 'src/bilihud/vendor/qasync' exists AND 'src/bilihud/vendor' is in sys.path.
    
elif os.path.exists(_dev_vendor):
    # Only for blivedm submodule in dev mode
    if _dev_vendor not in sys.path:
        sys.path.insert(0, _dev_vendor)

