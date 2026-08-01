import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any


def get_config_path() -> Path:
    """获取配置文件路径 (遵循XDG规范)"""
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    config_dir = Path(xdg_config_home) / "bilihud"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"
    # 清理崩溃残留的原子写入临时文件
    for stale in config_dir.glob(f".{config_path.name}.*.tmp"):
        with suppress(OSError):
            stale.unlink()
    return config_path


def _restrict_permissions(path: Path) -> None:
    # POSIX 下收紧到仅属主可读写，配置含 OBS 密码等敏感信息；失败静默（文件仍可用）
    if os.name == "posix":
        with suppress(OSError):
            path.chmod(0o600)


def _read_config_file(config_path: Path) -> dict[str, Any]:
    # 读时顺带收紧权限；失败仅告警不阻断，避免只读挂载等场景无法读取
    if os.name == "posix":
        try:
            config_path.chmod(0o600)
        except OSError as e:
            print(f"Failed to restrict config permissions: {e}")
    with open(config_path, encoding="utf-8") as config_file:
        config = json.load(config_file)
    if not isinstance(config, dict):
        raise ValueError("Configuration root must be a JSON object")
    return config


def load_config() -> dict[str, Any]:
    """加载配置"""
    config_path = get_config_path()
    if not config_path.exists():
        return {}

    try:
        return _read_config_file(config_path)
    except Exception as e:
        print(f"Failed to load config: {e}")
        return {}


def save_config(data: dict[str, Any]) -> bool:
    """保存配置（原子写入：临时文件 → fsync → replace）。

    现有配置损坏时返回 False 保留原文件，不会用新数据覆盖修复，以免静默丢失其他配置项。
    """
    temp_path: Path | None = None
    try:
        config_path = get_config_path()

        # 读取现有配置以进行合并，防止覆盖其他配置项
        current_config = _read_config_file(config_path) if config_path.exists() else {}
        current_config.update(data)
        serialized_config = json.dumps(current_config, indent=4, ensure_ascii=False)

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            _restrict_permissions(temp_path)
            temp_file.write(serialized_config)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        os.replace(temp_path, config_path)
        temp_path = None
        return True
    except Exception as e:
        print(f"Failed to save config: {e}")
        return False
    finally:
        if temp_path is not None:
            with suppress(OSError):
                temp_path.unlink()


def validate_room_id(room_id_str: str) -> bool:
    """
    验证直播间ID是否有效

    Args:
        room_id_str: 直播间ID字符串

    Returns:
        bool: 如果有效返回True，否则返回False
    """
    try:
        room_id = int(room_id_str)
        return room_id > 0
    except ValueError:
        return False


def format_danmaku_message(danmaku_msg) -> str:
    """
    格式化弹幕消息用于显示

    Args:
        danmaku_msg: 弹幕消息对象

    Returns:
        str: 格式化后的弹幕消息
    """
    return f"{danmaku_msg.uname}: {danmaku_msg.msg}"
