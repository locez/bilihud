from collections.abc import Sequence
from pathlib import Path

import pytest

from bilihud.app.obs_control import ObsProcessError, ObsProcessFailureCode
from bilihud.platform.obs_process import (
    CommandResult,
    LinuxObsProcess,
    MacOSObsProcess,
    WindowsObsProcess,
    is_obs_process_name,
)
from bilihud.platform.system import create_platform_context


class FakeRunner:
    """Return deterministic process-listing output and retain argv for assertions."""

    def __init__(self, result: CommandResult) -> None:
        self.result = result
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: Sequence[str]) -> CommandResult:
        self.commands.append(tuple(command))
        return self.result


class FakeLauncher:
    """Capture detached launch argv or raise one configured operating-system error."""

    def __init__(self, error: OSError | None = None) -> None:
        self.error = error
        self.commands: list[tuple[str, ...]] = []

    def launch(self, command: Sequence[str]) -> None:
        self.commands.append(tuple(command))
        if self.error is not None:
            raise self.error


def test_obs_process_name_normalization_matches_exact_windows_and_posix_names() -> None:
    assert is_obs_process_name(r"C:\\Program Files\\obs-studio\\bin\\64bit\\OBS64.EXE")
    assert is_obs_process_name("/usr/bin/obs-studio")
    assert not is_obs_process_name("obsidian.exe")
    assert not is_obs_process_name("python")


def test_linux_process_adapter_reads_proc_comm_only(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    (proc_root / "123").mkdir(parents=True)
    (proc_root / "123" / "comm").write_text("obs\n", encoding="utf-8")
    (proc_root / "not-a-pid").mkdir()

    adapter = LinuxObsProcess(proc_root=proc_root, executable_lookup=lambda _name: None)

    assert adapter.is_running() is True


def test_linux_process_adapter_reports_missing_process_directory_as_not_running(tmp_path: Path) -> None:
    adapter = LinuxObsProcess(proc_root=tmp_path / "missing", executable_lookup=lambda _name: None)

    assert adapter.is_running() is False


def test_macos_process_adapter_parses_ps_output_without_using_linux_proc() -> None:
    runner = FakeRunner(CommandResult(0, "/usr/bin/obs\nobsidian\n", ""))
    adapter = MacOSObsProcess(
        create_platform_context("darwin", environment={}, home=Path("/home/test")),
        runner=runner,
        executable_lookup=lambda _name: None,
    )

    assert adapter.is_running() is True
    assert runner.commands == [("ps", "-A", "-o", "comm=")]


def test_windows_process_adapter_parses_exact_tasklist_names() -> None:
    runner = FakeRunner(
        CommandResult(
            0,
            '"obsidian.exe","10","Console","1","1,000 K"\n'
            '"OBS64.EXE","11","Console","1","2,000 K"\n',
            "",
        )
    )
    adapter = WindowsObsProcess(
        create_platform_context("win32", environment={}, home=Path("C:/Users/test")),
        runner=runner,
        executable_lookup=lambda _name: None,
    )

    assert adapter.is_running() is True
    assert runner.commands == [("tasklist", "/FO", "CSV", "/NH")]


def test_windows_process_adapter_finds_standard_install_path_with_spaces(tmp_path: Path) -> None:
    program_files = tmp_path / "Program Files"
    executable = program_files / "obs-studio" / "bin" / "64bit" / "obs64.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"")
    adapter = WindowsObsProcess(
        create_platform_context("win32", environment={"ProgramFiles": str(program_files)}, home=tmp_path),
        executable_lookup=lambda _name: None,
    )

    assert adapter.find_executable() == executable


def test_obs_process_launch_uses_explicit_argv_and_preserves_unicode_path(tmp_path: Path) -> None:
    executable = tmp_path / "OBS Studio 中文" / "obs64.exe"
    launcher = FakeLauncher()
    adapter = WindowsObsProcess(
        create_platform_context("win32", environment={}, home=tmp_path),
        launcher=launcher,
        executable_lookup=lambda name: str(executable) if name == "obs64.exe" else None,
    )

    adapter.launch()

    assert launcher.commands == [(str(executable),)]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (PermissionError("denied"), ObsProcessFailureCode.PERMISSION_DENIED),
        (OSError("cannot start"), ObsProcessFailureCode.LAUNCH_FAILED),
    ],
)
def test_obs_process_launch_reports_operating_system_failures(
    tmp_path: Path,
    error: OSError,
    code: ObsProcessFailureCode,
) -> None:
    executable = tmp_path / "obs"
    launcher = FakeLauncher(error)
    adapter = LinuxObsProcess(
        launcher=launcher,
        executable_lookup=lambda _name: str(executable),
    )

    with pytest.raises(ObsProcessError) as raised:
        adapter.launch()

    assert raised.value.code is code


def test_obs_process_launch_reports_missing_executable() -> None:
    adapter = LinuxObsProcess(executable_lookup=lambda _name: None)

    with pytest.raises(ObsProcessError) as raised:
        adapter.launch()

    assert raised.value.code is ObsProcessFailureCode.EXECUTABLE_NOT_FOUND
