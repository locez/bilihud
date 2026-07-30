# -*- coding: utf-8 -*-
import datetime
import json
from pathlib import Path

from bilihud.danmaku_logger import DanmakuLogger
from bilihud.mock_generator import MockMessageGenerator


def test_danmaku_logger_write_and_cleanup(tmp_path: Path):
    log_dir = tmp_path / "logs"
    logger = DanmakuLogger(log_dir=log_dir, retention_days=7)

    # 模拟写入消息
    msg = MockMessageGenerator.create_mock_danmaku(user="测试员", msg="Hello World")
    record = logger.log_message(msg)

    assert record is not None
    assert record["user"] == "测试员"
    assert record["kind"] == "danmaku"

    # 校验写入文件存在且格式正确
    log_files = logger.get_log_files()
    assert len(log_files) == 1

    content = log_files[0].read_text(encoding="utf-8").strip()
    data = json.loads(content)
    assert data["user"] == "测试员"
    assert "timestamp" in data

    # 模拟过期日志删除
    old_date = datetime.date.today() - datetime.timedelta(days=10)
    old_log_path = log_dir / f"danmaku_{old_date.strftime('%Y-%m-%d')}.jsonl"
    old_log_path.write_text('{"user": "old"}\n', encoding="utf-8")

    removed = logger.cleanup_old_logs()
    assert removed == 1
    assert not old_log_path.exists()
