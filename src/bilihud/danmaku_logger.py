# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any

from .mirror_state import message_to_mirror_entry

logger = logging.getLogger(__name__)

DEFAULT_LOG_DIR = Path.home() / ".local" / "share" / "bilihud" / "logs"
DEFAULT_RETENTION_DAYS = 30


class DanmakuLogger:
    """持久化记录弹幕、礼物、互动消息为 JSONL 日志文件的记录器。"""

    def __init__(
        self,
        log_dir: str | Path | None = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        enabled: bool = True,
    ):
        self.log_dir = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        self.retention_days = retention_days
        self.enabled = enabled
        self._seq = 1

        if self.enabled:
            self._ensure_log_dir()
            self.cleanup_old_logs()

    def _ensure_log_dir(self) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.error("Failed to create log directory %s: %s", self.log_dir, exc)

    def get_log_file_path(self, date_obj: datetime.date | None = None) -> Path:
        if date_obj is None:
            date_obj = datetime.date.today()
        filename = f"danmaku_{date_obj.strftime('%Y-%m-%d')}.jsonl"
        return self.log_dir / filename

    def log_message(self, message: Any) -> dict[str, Any] | None:
        """记录单条消息到当天的 JSONL 日志文件中。"""
        if not self.enabled:
            return None

        try:
            now = datetime.datetime.now(datetime.timezone.utc).astimezone()
            entry = message_to_mirror_entry(self._seq, message)
            self._seq += 1

            record = {
                "timestamp": now.isoformat(),
                **entry,
            }

            log_path = self.get_log_file_path(now.date())
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            return record
        except Exception as exc:
            logger.error("Failed to log message: %s", exc)
            return None

    def cleanup_old_logs(self) -> int:
        """根据保留天数清理废弃日志，返回清理的文件数量。"""
        if self.retention_days <= 0 or not self.log_dir.exists():
            return 0

        removed_count = 0
        cutoff_date = datetime.date.today() - datetime.timedelta(days=self.retention_days)

        for log_file in self.get_log_files():
            try:
                stem = log_file.stem
                if stem.startswith("danmaku_"):
                    date_str = stem[len("danmaku_"):]
                    file_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                    if file_date < cutoff_date:
                        log_file.unlink(missing_ok=True)
                        removed_count += 1
            except Exception as exc:
                logger.warning("Failed to check/cleanup log file %s: %s", log_file, exc)

        return removed_count

    def get_log_files(self) -> list[Path]:
        """获取所有存留的历史日志文件列表（按日期倒序）。"""
        if not self.log_dir.exists():
            return []
        return sorted(self.log_dir.glob("danmaku_*.jsonl"), reverse=True)
