"""Platform adapters for OBS process discovery and detached launch."""

from __future__ import annotations

import csv
import locale
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..app.obs_control import ObsProcess, ObsProcessError, ObsProcessFailureCode
from .system import PlatformContext, PlatformKind, create_platform_context

OBS_PROCESS_NAMES = frozenset({"obs", "obs-studio", "obs64"})


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Portable subset of a process query result used by platform adapters."""

    returncode: int
    stdout: str
    stderr: str


class ProcessCommandRunner(Protocol):
    """Execute one platform process-listing command."""

    def run(self, command: Sequence[str]) -> CommandResult:
        """Run an explicit argv command and return its captured text output."""
        ...


class ProcessLauncher(Protocol):
    """Detach one already-resolved executable from the application process."""

    def launch(self, command: Sequence[str]) -> None:
        """Start an explicit argv command without taking ownership of its lifetime."""
        ...


class _SubprocessCommandRunner:
    """Run process inspection commands with bounded, locale-aware text decoding."""

    def run(self, command: Sequence[str]) -> CommandResult:
        """Run one command without a shell and normalize launch errors."""
        try:
            result = subprocess.run(
                list(command),
                capture_output=True,
                check=False,
                encoding=locale.getpreferredencoding(False),
                errors="replace",
                text=True,
                timeout=5.0,
            )
        except subprocess.TimeoutExpired as exc:
            raise ObsProcessError(
                ObsProcessFailureCode.PROCESS_QUERY_FAILED,
                f"查询 OBS 进程超时: {command[0] if command else 'unknown'}",
            ) from exc
        except OSError as exc:
            raise ObsProcessError(
                ObsProcessFailureCode.PROCESS_QUERY_FAILED,
                f"无法查询 OBS 进程: {exc}",
            ) from exc
        return CommandResult(result.returncode, result.stdout, result.stderr)


class _PosixProcessLauncher:
    """Detach a POSIX child into a new session owned by the desktop user."""

    def launch(self, command: Sequence[str]) -> None:
        """Start OBS with explicit argv and detached standard streams."""
        subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


class _WindowsProcessLauncher:
    """Detach a Windows child without opening a console window."""

    def launch(self, command: Sequence[str]) -> None:
        """Start OBS with Windows process-group and detached-process flags."""
        # These stable Win32 values are exposed as subprocess constants only on Windows.
        creation_flags = 0x00000200 | 0x00000008
        subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creation_flags,
        )


ExecutableLookup = Callable[[str], str | None]


class _ObsExecutableProcess:
    """Shared executable lookup and error normalization for concrete OS adapters."""

    def __init__(
        self,
        *,
        executable_names: tuple[str, ...],
        candidate_executables: tuple[Path, ...],
        runner: ProcessCommandRunner,
        launcher: ProcessLauncher,
        executable_lookup: ExecutableLookup,
    ) -> None:
        """Create an adapter with explicit external command and filesystem capabilities."""
        self._executable_names = executable_names
        self._candidate_executables = candidate_executables
        self._runner = runner
        self._launcher = launcher
        self._executable_lookup = executable_lookup

    def find_executable(self) -> Path | None:
        """Find OBS in platform installation paths, then in PATH."""
        for candidate in self._candidate_executables:
            if candidate.is_file():
                return candidate
        for name in self._executable_names:
            executable = self._executable_lookup(name)
            if executable is not None:
                return Path(executable)
        return None

    def launch(self) -> None:
        """Resolve OBS and hand off its detached process lifetime to the OS."""
        executable = self.find_executable()
        if executable is None:
            names = ", ".join(self._executable_names)
            raise ObsProcessError(
                ObsProcessFailureCode.EXECUTABLE_NOT_FOUND,
                f"未找到 OBS 可执行文件，请确认已安装或加入 PATH（候选: {names}）。",
            )
        try:
            self._launcher.launch((str(executable),))
        except PermissionError as exc:
            raise ObsProcessError(
                ObsProcessFailureCode.PERMISSION_DENIED,
                f"没有权限启动 OBS: {executable}",
            ) from exc
        except FileNotFoundError as exc:
            raise ObsProcessError(
                ObsProcessFailureCode.EXECUTABLE_NOT_FOUND,
                f"OBS 可执行文件已不存在: {executable}",
            ) from exc
        except OSError as exc:
            raise ObsProcessError(
                ObsProcessFailureCode.LAUNCH_FAILED,
                f"启动 OBS 失败: {exc}",
            ) from exc


class LinuxObsProcess(_ObsExecutableProcess):
    """Use Linux ``/proc`` inspection and PATH executable lookup."""

    def __init__(
        self,
        *,
        proc_root: Path = Path("/proc"),
        runner: ProcessCommandRunner | None = None,
        launcher: ProcessLauncher | None = None,
        executable_lookup: ExecutableLookup = shutil.which,
    ) -> None:
        """Create a Linux adapter with injectable process and launch boundaries."""
        super().__init__(
            executable_names=("obs", "obs-studio"),
            candidate_executables=(),
            runner=runner if runner is not None else _SubprocessCommandRunner(),
            launcher=launcher if launcher is not None else _PosixProcessLauncher(),
            executable_lookup=executable_lookup,
        )
        self._proc_root = proc_root

    def is_running(self) -> bool:
        """Inspect numeric Linux process directories without requiring ``ps``."""
        if not self._proc_root.exists():
            return False
        try:
            entries = tuple(self._proc_root.iterdir())
        except OSError as exc:
            raise ObsProcessError(
                ObsProcessFailureCode.PROCESS_QUERY_FAILED,
                f"无法读取 Linux 进程目录: {exc}",
            ) from exc

        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                command = (entry / "comm").read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if is_obs_process_name(command):
                return True
        return False


class MacOSObsProcess(_ObsExecutableProcess):
    """Use macOS ``ps`` inspection and common OBS app-bundle locations."""

    def __init__(
        self,
        context: PlatformContext,
        *,
        runner: ProcessCommandRunner | None = None,
        launcher: ProcessLauncher | None = None,
        executable_lookup: ExecutableLookup = shutil.which,
    ) -> None:
        """Create a macOS adapter with injectable command and launch boundaries."""
        super().__init__(
            executable_names=("obs", "obs-studio"),
            candidate_executables=(
                Path("/Applications/OBS.app/Contents/MacOS/obs"),
                context.home / "Applications" / "OBS.app" / "Contents" / "MacOS" / "obs",
            ),
            runner=runner if runner is not None else _SubprocessCommandRunner(),
            launcher=launcher if launcher is not None else _PosixProcessLauncher(),
            executable_lookup=executable_lookup,
        )

    def is_running(self) -> bool:
        """Inspect command names reported by macOS ``ps``."""
        result = self._runner.run(("ps", "-A", "-o", "comm="))
        _require_success(result, "ps")
        return any(is_obs_process_name(line) for line in result.stdout.splitlines())


class WindowsObsProcess(_ObsExecutableProcess):
    """Use Windows ``tasklist`` and standard OBS installation directories."""

    def __init__(
        self,
        context: PlatformContext,
        *,
        runner: ProcessCommandRunner | None = None,
        launcher: ProcessLauncher | None = None,
        executable_lookup: ExecutableLookup = shutil.which,
    ) -> None:
        """Create a Windows adapter with injectable command and launch boundaries."""
        super().__init__(
            executable_names=("obs64.exe", "obs.exe", "obs-studio.exe", "obs64", "obs", "obs-studio"),
            candidate_executables=_windows_obs_paths(context),
            runner=runner if runner is not None else _SubprocessCommandRunner(),
            launcher=launcher if launcher is not None else _WindowsProcessLauncher(),
            executable_lookup=executable_lookup,
        )

    def is_running(self) -> bool:
        """Inspect executable names from Windows CSV task-list output."""
        result = self._runner.run(("tasklist", "/FO", "CSV", "/NH"))
        _require_success(result, "tasklist")
        try:
            rows = csv.reader(result.stdout.splitlines())
            return any(row and is_obs_process_name(row[0]) for row in rows)
        except csv.Error as exc:
            raise ObsProcessError(
                ObsProcessFailureCode.PROCESS_QUERY_FAILED,
                f"无法解析 Windows 进程列表: {exc}",
            ) from exc


class UnsupportedObsProcess:
    """Report an explicit capability failure on an unknown operating system."""

    def find_executable(self) -> Path | None:
        """Return no executable because process integration is unsupported."""
        return None

    def is_running(self) -> bool:
        """Raise an actionable unsupported-platform failure."""
        raise ObsProcessError(
            ObsProcessFailureCode.UNSUPPORTED_PLATFORM,
            "当前平台不支持 OBS 进程检测。",
        )

    def launch(self) -> None:
        """Raise an actionable unsupported-platform failure."""
        raise ObsProcessError(
            ObsProcessFailureCode.UNSUPPORTED_PLATFORM,
            "当前平台不支持启动 OBS。",
        )


def is_obs_process_name(command: str) -> bool:
    """Match exact OBS executable names across path separators and Windows suffixes."""
    normalized = command.strip().replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if normalized.endswith(".exe"):
        normalized = normalized[:-4]
    return normalized in OBS_PROCESS_NAMES


def create_obs_process(context: PlatformContext | None = None) -> ObsProcess:
    """Create the process adapter selected by one captured operating-system context."""
    selected_context = create_platform_context() if context is None else context
    factory = _OBS_PROCESS_FACTORIES.get(selected_context.kind, _unsupported_process)
    return factory(selected_context)


def _windows_obs_paths(context: PlatformContext) -> tuple[Path, ...]:
    """Return standard Windows OBS executable locations from injected environment values."""
    roots: list[Path] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        value = context.environment.get(variable)
        if value is not None and value.strip():
            roots.append(Path(value))
    return tuple(root / "obs-studio" / "bin" / "64bit" / "obs64.exe" for root in roots)


def _require_success(result: CommandResult, command_name: str) -> None:
    """Convert a non-zero process-listing command into a typed query failure."""
    if result.returncode == 0:
        return
    detail = result.stderr.strip()
    if not detail:
        detail = f"退出码 {result.returncode}"
    raise ObsProcessError(
        ObsProcessFailureCode.PROCESS_QUERY_FAILED,
        f"{command_name} 查询 OBS 进程失败: {detail}",
    )


ProcessFactory = Callable[[PlatformContext], ObsProcess]


def _unsupported_process(_context: PlatformContext) -> ObsProcess:
    """Build the explicit unsupported-platform process capability."""
    return UnsupportedObsProcess()


_OBS_PROCESS_FACTORIES: dict[PlatformKind, ProcessFactory] = {
    PlatformKind.LINUX: lambda context: LinuxObsProcess(),
    PlatformKind.MACOS: MacOSObsProcess,
    PlatformKind.WINDOWS: WindowsObsProcess,
}


__all__ = (
    "CommandResult",
    "LinuxObsProcess",
    "MacOSObsProcess",
    "ProcessCommandRunner",
    "ProcessLauncher",
    "UnsupportedObsProcess",
    "WindowsObsProcess",
    "create_obs_process",
    "is_obs_process_name",
)
