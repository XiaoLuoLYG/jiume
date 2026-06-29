"""One-command supervisor for the JiuMe desktop twin."""

from __future__ import annotations

import argparse
import os
import plistlib
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, IO
from urllib.parse import urlparse

from jiume.desktop.app import DEFAULT_AGENT_MODE, DEFAULT_GATEWAY_URL, JiuMeDesktopAvatar
from jiume.desktop.state import set_service_status
from jiume.luckin.mcp_config import ensure_luckin_mcp_config
from jiume.paths import get_jiume_root
from jiume.runtime.status import runtime_config_url
from jiume.twins.store import TwinStore

LAUNCH_AGENT_LABEL = "com.openjiuwen.jiume"
LAUNCHER_LOCK_FILE = "launcher.pid"


@dataclass(frozen=True)
class LaunchPlan:
    setup_command: list[str] | None
    agent_command: list[str] | None
    web_command: list[str] | None
    wait_for_gateway: bool
    runtime_config_url: str


@dataclass
class ManagedProcess:
    name: str
    command: list[str]
    process: subprocess.Popen[bytes]
    log_handle: IO[bytes]
    restart_count: int = 0


@dataclass
class ServiceStatusContext:
    setup_mode: str
    agent_mode: str
    web_mode: str
    gateway_url: str
    runtime_config_url: str
    gateway_ready: bool
    restart_enabled: bool


def _runtime_config_url(*, host: str = "localhost", port: int = 5173) -> str:
    return runtime_config_url(host=host, port=port)


def _gateway_endpoint(gateway_url: str) -> tuple[str, int]:
    parsed = urlparse(gateway_url)
    host = parsed.hostname or "127.0.0.1"
    if parsed.port:
        return host, parsed.port
    return host, 443 if parsed.scheme in {"wss", "https"} else 80


def _port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _launcher_lock_path() -> Path:
    return get_jiume_root() / LAUNCHER_LOCK_FILE


def _read_launcher_pid(path: Path | None = None) -> int | None:
    lock_path = path or _launcher_lock_path()
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        pid = int(raw)
    except ValueError:
        return None
    return pid if pid > 0 else None


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False


def _claim_launcher_lock(
    path: Path | None = None,
    *,
    pid: int | None = None,
    pid_is_running: Callable[[int], bool] = _pid_is_running,
) -> int | None:
    lock_path = path or _launcher_lock_path()
    current_pid = int(pid or os.getpid())
    existing_pid = _read_launcher_pid(lock_path)
    if existing_pid and existing_pid != current_pid and pid_is_running(existing_pid):
        return existing_pid
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(f"{current_pid}\n", encoding="utf-8")
    return None


def _release_launcher_lock(path: Path | None = None, *, pid: int | None = None) -> None:
    lock_path = path or _launcher_lock_path()
    current_pid = int(pid or os.getpid())
    if _read_launcher_pid(lock_path) != current_pid:
        return
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def _build_launch_plan(
    *,
    python_executable: str,
    first_run: bool,
    open_setup: bool,
    no_setup: bool,
    agent: str,
    gateway_url: str,
    gateway_running: bool,
    web_running: bool = False,
    web_host: str = "localhost",
    web_port: int = 5173,
) -> LaunchPlan:
    setup_command: list[str] | None = None
    if not no_setup and (first_run or open_setup):
        setup_command = [python_executable, "-m", "jiume.setup.server"]

    agent_command: list[str] | None = None
    if agent == "on" or (agent == "auto" and not gateway_running):
        agent_command = [python_executable, "-m", "jiuwenswarm.app"]

    web_command: list[str] | None = None
    runtime_setup_needed = not no_setup and (first_run or open_setup)
    if runtime_setup_needed and not web_running:
        web_command = [
            python_executable,
            "-m",
            "jiuwenswarm.channels.web.app_web",
            "--host",
            str(web_host or "localhost"),
            "--port",
            str(int(web_port or 5173)),
        ]

    return LaunchPlan(
        setup_command=setup_command,
        agent_command=agent_command,
        web_command=web_command,
        wait_for_gateway=agent_command is not None,
        runtime_config_url=_runtime_config_url(host=web_host, port=web_port),
    )


def _bootstrap_luckin_mcp_for_launch(plan: LaunchPlan) -> None:
    if not plan.agent_command:
        return
    try:
        luckin_config = ensure_luckin_mcp_config()
    except Exception as exc:
        print(f"[jiume-launch] warning: Luckin MCP bootstrap skipped ({type(exc).__name__})")
        return
    if luckin_config.get("configured"):
        print(f"[jiume-launch] Luckin MCP configured: {luckin_config.get('name')}")


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    source_root = str(_source_root())
    current_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = source_root if not current_pythonpath else os.pathsep.join([source_root, current_pythonpath])
    return env


def _start_process(name: str, command: list[str], log_dir: Path) -> ManagedProcess:
    log_dir.mkdir(parents=True, exist_ok=True)
    process, log_handle = _spawn_process(name, command, log_dir)
    return ManagedProcess(name=name, command=list(command), process=process, log_handle=log_handle)


def _spawn_process(name: str, command: list[str], log_dir: Path) -> tuple[subprocess.Popen[bytes], IO[bytes]]:
    log_handle = (log_dir / f"{name}.log").open("ab")
    print(f"[jiume-launch] starting {name}: {' '.join(command)}")
    return (
        subprocess.Popen(
            command,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            cwd=str(_source_root()),
            env=_child_env(),
        ),
        log_handle,
    )


def _restart_process(managed: ManagedProcess, log_dir: Path) -> None:
    if managed.process.poll() is None:
        return
    old_code = managed.process.returncode
    managed.log_handle.close()
    managed.restart_count += 1
    print(
        f"[jiume-launch] {managed.name} exited with code {old_code}; "
        f"restarting (attempt {managed.restart_count})"
    )
    managed.process, managed.log_handle = _spawn_process(managed.name, managed.command, log_dir)


def _service_record(
    name: str,
    *,
    mode: str,
    processes: list[ManagedProcess],
    url: str = "",
) -> dict[str, object]:
    fallback_status = "disabled" if mode == "disabled" else "idle" if mode == "idle" else "reused"
    record: dict[str, object] = {"mode": mode, "status": fallback_status}
    if url:
        record["url"] = url
    for managed in processes:
        if managed.name != name:
            continue
        return {
            **record,
            "mode": "managed",
            "status": "running" if managed.process.poll() is None else "exited",
            "pid": managed.process.pid,
            "exit_code": managed.process.returncode,
            "restart_count": managed.restart_count,
        }
    return record


def _write_service_status(
    processes: list[ManagedProcess],
    context: ServiceStatusContext,
    *,
    note: str = "",
) -> None:
    try:
        agent_record = _service_record(
            "agent",
            mode=context.agent_mode,
            processes=processes,
            url=context.gateway_url,
        )
        if agent_record.get("status") in {"running", "reused"}:
            agent_record["gateway_ready"] = bool(context.gateway_ready)
        set_service_status(
            source="jiume-launch",
            note=note or None,
            restart_enabled=context.restart_enabled,
            services={
                "setup": _service_record(
                    "setup",
                    mode=context.setup_mode,
                    processes=processes,
                ),
                "agent": agent_record,
                "web": _service_record(
                    "web",
                    mode=context.web_mode,
                    processes=processes,
                    url=context.runtime_config_url,
                ),
            },
        )
    except Exception:  # noqa: BLE001
        pass


def _start_health_monitor(
    processes: list[ManagedProcess],
    *,
    context: ServiceStatusContext,
    log_dir: Path,
    stop_event: threading.Event,
    interval_seconds: float,
) -> threading.Thread | None:
    if not processes:
        return None

    def monitor() -> None:
        while not stop_event.wait(max(0.2, interval_seconds)):
            for managed in list(processes):
                if stop_event.is_set():
                    return
                if managed.name == "setup":
                    continue
                if managed.process.poll() is not None:
                    _restart_process(managed, log_dir)
                    _write_service_status(processes, context, note=f"{managed.name} restarted")

    thread = threading.Thread(target=monitor, name="jiume-service-health", daemon=True)
    thread.start()
    return thread


def _terminate_processes(processes: list[ManagedProcess], stop_event: threading.Event | None = None) -> None:
    if stop_event is not None:
        stop_event.set()
    for managed in processes:
        proc = managed.process
        if proc.poll() is None:
            print(f"[jiume-launch] stopping {managed.name} (pid={proc.pid})")
            proc.terminate()

    deadline = time.time() + 8
    while time.time() < deadline:
        if all(managed.process.poll() is not None for managed in processes):
            break
        time.sleep(0.15)

    for managed in processes:
        proc = managed.process
        if proc.poll() is None:
            print(f"[jiume-launch] killing {managed.name} (pid={proc.pid})")
            proc.kill()
        managed.log_handle.close()


def _wait_for_gateway(gateway_url: str, timeout: float) -> bool:
    host, port = _gateway_endpoint(gateway_url)
    deadline = time.time() + max(0.0, timeout)
    while time.time() < deadline:
        if _port_open(host, port, timeout=0.35):
            print(f"[jiume-launch] Gateway ready at {gateway_url}")
            return True
        time.sleep(0.35)
    print(f"[jiume-launch] Gateway still starting; desktop twin will keep retrying {gateway_url}")
    return False


def _should_open_desktop_avatar(*, first_run: bool, open_setup: bool, no_setup: bool) -> bool:
    if no_setup:
        return True
    if open_setup:
        return False
    return not first_run


def _should_wait_for_first_twin_before_desktop(*, first_run: bool, open_setup: bool, no_setup: bool) -> bool:
    if no_setup or open_setup:
        return False
    return first_run


def _wait_for_first_twin(
    store: TwinStore,
    stop_event: threading.Event,
    *,
    setup_process: ManagedProcess | None = None,
    interval_seconds: float = 0.75,
) -> bool:
    while not stop_event.wait(max(0.2, interval_seconds)):
        if store.get_active_twin_id() is not None:
            return True
        if setup_process is not None and setup_process.process.poll() is not None:
            return store.get_active_twin_id() is not None
    return False


def _login_agent_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


def _launcher_args_for_login(args: argparse.Namespace) -> list[str]:
    launcher_args = [
        "--size",
        str(args.size),
        "--agent",
        str(args.agent),
        "--gateway-url",
        str(args.gateway_url),
        "--agent-mode",
        str(args.agent_mode),
        "--web-host",
        str(getattr(args, "web_host", "localhost")),
        "--web-port",
        str(getattr(args, "web_port", 5173)),
        "--wait-agent-seconds",
        str(args.wait_agent_seconds),
        "--health-check-seconds",
        str(args.health_check_seconds),
    ]
    if args.open_setup:
        launcher_args.append("--open-setup")
    if args.no_setup:
        launcher_args.append("--no-setup")
    if args.no_service_restart:
        launcher_args.append("--no-service-restart")
    return launcher_args


def _launch_agent_payload(
    *,
    python_executable: str,
    launcher_args: list[str],
    working_directory: Path,
    log_dir: Path,
    data_dir: str | None = None,
) -> dict[str, object]:
    env = {"PYTHONPATH": str(working_directory)}
    data_dir = data_dir if data_dir is not None else os.getenv("JIUWENSWARM_DATA_DIR")
    if data_dir:
        env["JIUWENSWARM_DATA_DIR"] = data_dir
    return {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [python_executable, "-m", "jiume.launcher", *launcher_args],
        "WorkingDirectory": str(working_directory),
        "EnvironmentVariables": env,
        "RunAtLoad": True,
        "KeepAlive": {"Crashed": True},
        "StandardOutPath": str(log_dir / "login-item.log"),
        "StandardErrorPath": str(log_dir / "login-item.err.log"),
    }


def _install_login_item(args: argparse.Namespace) -> int:
    plist_path = _login_agent_path()
    log_dir = get_jiume_root() / "logs"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = _launch_agent_payload(
        python_executable=sys.executable,
        launcher_args=_launcher_args_for_login(args),
        working_directory=_source_root(),
        log_dir=log_dir,
    )
    with plist_path.open("wb") as file:
        plistlib.dump(payload, file)
    print(f"[jiume-launch] login item installed: {plist_path}")
    print("[jiume-launch] JiuMe will open automatically after the next macOS login.")
    return 0


def _uninstall_login_item() -> int:
    plist_path = _login_agent_path()
    if plist_path.exists():
        plist_path.unlink()
        print(f"[jiume-launch] login item removed: {plist_path}")
    else:
        print(f"[jiume-launch] login item is not installed: {plist_path}")
    return 0


def _login_item_status() -> int:
    plist_path = _login_agent_path()
    if not plist_path.exists():
        print(f"[jiume-launch] login item is not installed: {plist_path}")
        return 0
    try:
        with plist_path.open("rb") as file:
            payload = plistlib.load(file)
    except Exception as exc:  # noqa: BLE001
        print(f"[jiume-launch] login item exists but could not be read: {exc}")
        return 2
    args = payload.get("ProgramArguments") if isinstance(payload, dict) else None
    print(f"[jiume-launch] login item installed: {plist_path}")
    if isinstance(args, list):
        print("[jiume-launch] command: " + " ".join(str(item) for item in args))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the always-on JiuMe desktop assistant.")
    parser.add_argument("--size", type=int, default=128, help="Desktop avatar window size.")
    parser.add_argument("--setup-host", default="127.0.0.1", help=argparse.SUPPRESS)
    parser.add_argument("--setup-port", type=int, default=8765, help=argparse.SUPPRESS)
    parser.add_argument("--open-setup", action="store_true", help="Open the native setup window.")
    parser.add_argument("--no-setup", action="store_true", help="Do not open the native setup window.")
    parser.add_argument(
        "--agent",
        choices=["auto", "on", "off"],
        default="auto",
        help="Start JiuwenSwarm Agent/Gateway when needed, always, or never.",
    )
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL)
    parser.add_argument("--agent-mode", default=DEFAULT_AGENT_MODE)
    parser.add_argument("--web-host", default="localhost", help="JiuwenSwarm Web config host.")
    parser.add_argument("--web-port", type=int, default=5173, help="JiuwenSwarm Web config port.")
    parser.add_argument("--wait-agent-seconds", type=float, default=20.0)
    parser.add_argument("--health-check-seconds", type=float, default=4.0)
    parser.add_argument("--no-service-restart", action="store_true", help="Do not restart managed agent child services after crashes.")
    parser.add_argument("--install-login-item", action="store_true", help="Install a macOS login item for JiuMe.")
    parser.add_argument("--uninstall-login-item", action="store_true", help="Remove the macOS login item.")
    parser.add_argument("--login-item-status", action="store_true", help="Show macOS login item status.")
    return parser.parse_args()


def main() -> None:
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    args = _parse_args()
    if args.install_login_item:
        raise SystemExit(_install_login_item(args))
    if args.uninstall_login_item:
        raise SystemExit(_uninstall_login_item())
    if args.login_item_status:
        raise SystemExit(_login_item_status())

    existing_pid = _claim_launcher_lock()
    if existing_pid is not None:
        print(f"[jiume-launch] desktop twin already running (pid={existing_pid}); not opening another copy")
        return 0

    gateway_host, gateway_port = _gateway_endpoint(args.gateway_url)
    gateway_running = _port_open(gateway_host, gateway_port)
    web_running = _port_open(args.web_host, args.web_port)
    store = TwinStore()
    first_run = store.get_active_twin_id() is None
    plan = _build_launch_plan(
        python_executable=sys.executable,
        first_run=first_run,
        open_setup=args.open_setup,
        no_setup=args.no_setup,
        agent=args.agent,
        gateway_url=args.gateway_url,
        gateway_running=gateway_running,
        web_running=web_running,
        web_host=args.web_host,
        web_port=args.web_port,
    )

    log_dir = get_jiume_root() / "logs"
    processes: list[ManagedProcess] = []
    stop_event = threading.Event()
    context = ServiceStatusContext(
        setup_mode="managed" if plan.setup_command else "disabled" if args.no_setup else "idle",
        agent_mode="managed" if plan.agent_command else "disabled" if args.agent == "off" else "reused",
        web_mode="managed" if plan.web_command else "reused" if web_running else "idle",
        gateway_url=args.gateway_url,
        runtime_config_url=plan.runtime_config_url,
        gateway_ready=gateway_running,
        restart_enabled=not args.no_service_restart,
    )
    try:
        _bootstrap_luckin_mcp_for_launch(plan)

        if plan.setup_command:
            processes.append(_start_process("setup", plan.setup_command, log_dir))

        if plan.agent_command:
            processes.append(_start_process("agent", plan.agent_command, log_dir))
            context.gateway_ready = _wait_for_gateway(args.gateway_url, args.wait_agent_seconds)
        elif args.agent != "off":
            print(f"[jiume-launch] reusing Gateway at {args.gateway_url}")
            context.gateway_ready = gateway_running

        if plan.web_command:
            processes.append(_start_process("web", plan.web_command, log_dir))
        elif web_running:
            print(f"[jiume-launch] reusing JiuwenSwarm Web config at {plan.runtime_config_url}")

        _write_service_status(processes, context, note="launcher started")
        if processes and not args.no_service_restart:
            _start_health_monitor(
                processes,
                context=context,
                log_dir=log_dir,
                stop_event=stop_event,
                interval_seconds=args.health_check_seconds,
            )

        setup_process = next((managed for managed in processes if managed.name == "setup"), None)
        if args.open_setup and not args.no_setup:
            print("[jiume-launch] setup requested: native setup is the primary surface; desktop avatar opens after activation")
            _write_service_status(processes, context, note="setup requested")
            if setup_process is not None:
                while setup_process.process.poll() is None and not stop_event.wait(max(0.2, args.health_check_seconds)):
                    pass
            if store.get_active_twin_id() is None:
                _write_service_status(processes, context, note="setup closed without active twin")
                return
            _write_service_status(processes, context, note="setup completed; opening desktop twin")

        if _should_wait_for_first_twin_before_desktop(
            first_run=first_run,
            open_setup=args.open_setup,
            no_setup=args.no_setup,
        ):
            print("[jiume-launch] first run: native setup is the primary surface; desktop avatar opens after activation")
            _write_service_status(processes, context, note="waiting for first twin")
            if not _wait_for_first_twin(
                store,
                stop_event,
                setup_process=setup_process,
                interval_seconds=args.health_check_seconds,
            ):
                return
            _write_service_status(processes, context, note="first twin created")

        print("[jiume-launch] opening desktop twin")
        avatar = JiuMeDesktopAvatar(
            size=args.size,
            gateway_url=args.gateway_url if args.agent != "off" else "",
            agent_mode=args.agent_mode,
        )
        avatar.run()
    except KeyboardInterrupt:
        pass
    finally:
        _terminate_processes(processes, stop_event)
        _write_service_status(processes, context, note="launcher stopped")
        _release_launcher_lock()


if __name__ == "__main__":
    main()
