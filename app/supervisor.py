"""
Majic Movie Selector - Process Supervisor with Rich TUI

A sexy Python-based process manager that provides:
- Auto-restart with exponential backoff
- Health check monitoring
- Live status dashboard
- Colored log output
- Graceful shutdown
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import httpx
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import SpinnerColumn, TextColumn, Progress
from rich.table import Table
from rich.text import Text


@dataclass
class ProcessState:
    """Tracks the state of the supervised process."""
    process: subprocess.Popen | None = None
    pid: int | None = None
    start_time: float = 0.0
    restart_count: int = 0
    last_health_check: float = 0.0
    health_status: str = "unknown"
    backoff_seconds: float = 5.0
    consecutive_failures: int = 0
    is_stopping: bool = False
    last_log_lines: list[str] = field(default_factory=list)


class MajicSupervisor:
    """Process supervisor for the Majic Movie Selector server."""

    # Backoff configuration
    MIN_BACKOFF = 5.0
    MAX_BACKOFF = 60.0
    BACKOFF_MULTIPLIER = 2.0
    HEALTH_CHECK_INTERVAL = 10.0
    MAX_LOG_LINES = 50

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8443,
        log_file: Path | None = None,
    ):
        self.host = host
        self.port = port
        self.log_file = log_file or Path(f"server-{port}.log")
        self.pid_file = Path(f".server-{port}.pid")
        self.console = Console()
        self.state = ProcessState()
        self._stop_event = asyncio.Event()
        self._project_root = Path(__file__).parent.parent

    def _get_uvicorn_command(self) -> list[str]:
        """Build the uvicorn command to run the server."""
        venv_python = self._project_root / ".venv" / "bin" / "python"
        if not venv_python.exists():
            venv_python = Path(sys.executable)

        return [
            str(venv_python),
            "-m", "uvicorn",
            "app.main:app",
            "--host", self.host,
            "--port", str(self.port),
        ]

    def _start_process(self) -> bool:
        """Start the server process."""
        if self.state.process and self.state.process.poll() is None:
            return True  # Already running

        try:
            cmd = self._get_uvicorn_command()
            log_handle = open(self.log_file, "a")

            self.state.process = subprocess.Popen(
                cmd,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                cwd=self._project_root,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            self.state.pid = self.state.process.pid
            self.state.start_time = time.time()

            # Write PID file
            self.pid_file.write_text(str(self.state.pid))

            self.console.print(f"[green]Started server[/green] PID={self.state.pid}")
            return True

        except Exception as e:
            self.console.print(f"[red]Failed to start server:[/red] {e}")
            return False

    def _stop_process(self, timeout: float = 10.0) -> bool:
        """Stop the server process gracefully."""
        if not self.state.process:
            return True

        self.state.is_stopping = True
        pid = self.state.pid

        try:
            # Send SIGTERM for graceful shutdown
            self.state.process.terminate()
            try:
                self.state.process.wait(timeout=timeout)
                self.console.print(f"[green]Server stopped gracefully[/green] PID={pid}")
            except subprocess.TimeoutExpired:
                # Force kill if not responding
                self.state.process.kill()
                self.state.process.wait(timeout=5)
                self.console.print(f"[yellow]Server force-killed[/yellow] PID={pid}")

            # Clean up PID file
            if self.pid_file.exists():
                self.pid_file.unlink()

            self.state.process = None
            self.state.pid = None
            return True

        except Exception as e:
            self.console.print(f"[red]Error stopping server:[/red] {e}")
            return False

    async def _health_check(self) -> bool:
        """Check if the server is healthy."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"http://{self.host}:{self.port}/api/health")
                if response.status_code == 200:
                    data = response.json()
                    self.state.health_status = data.get("status", "ok")
                    return True
                else:
                    self.state.health_status = f"http_{response.status_code}"
                    return False
        except httpx.ConnectError:
            self.state.health_status = "connection_refused"
            return False
        except httpx.TimeoutException:
            self.state.health_status = "timeout"
            return False
        except Exception as e:
            self.state.health_status = f"error: {str(e)[:30]}"
            return False

    def _read_recent_logs(self, lines: int = 10) -> list[str]:
        """Read the most recent log lines."""
        if not self.log_file.exists():
            return []
        try:
            with open(self.log_file, "r") as f:
                all_lines = f.readlines()
                return [line.rstrip() for line in all_lines[-lines:]]
        except Exception:
            return []

    def _create_status_panel(self) -> Panel:
        """Create the status panel for the TUI."""
        # Status table
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="cyan")
        table.add_column("Value")

        # Process status
        if self.state.process and self.state.process.poll() is None:
            status = Text("RUNNING", style="bold green")
        elif self.state.is_stopping:
            status = Text("STOPPING", style="bold yellow")
        else:
            status = Text("STOPPED", style="bold red")

        table.add_row("Status", status)
        table.add_row("PID", str(self.state.pid or "-"))
        table.add_row("Port", str(self.port))

        # Uptime
        if self.state.start_time > 0 and self.state.process:
            uptime = time.time() - self.state.start_time
            uptime_str = self._format_duration(uptime)
        else:
            uptime_str = "-"
        table.add_row("Uptime", uptime_str)

        # Health status
        health_style = "green" if self.state.health_status == "healthy" else "yellow"
        table.add_row("Health", Text(self.state.health_status, style=health_style))

        # Restart count
        table.add_row("Restarts", str(self.state.restart_count))

        # Backoff (if applicable)
        if self.state.consecutive_failures > 0:
            table.add_row("Next retry", f"{self.state.backoff_seconds:.1f}s")

        return Panel(
            table,
            title="[bold magenta]Majic Movie Selector[/bold magenta]",
            subtitle=f"http://{self.host}:{self.port}",
            border_style="magenta",
        )

    def _create_logs_panel(self) -> Panel:
        """Create the logs panel for the TUI."""
        logs = self._read_recent_logs(12)
        if not logs:
            log_text = Text("No logs yet...", style="dim")
        else:
            log_text = Text()
            for line in logs:
                # Color code based on log level
                if "ERROR" in line or "error" in line.lower():
                    log_text.append(line + "\n", style="red")
                elif "WARNING" in line or "warn" in line.lower():
                    log_text.append(line + "\n", style="yellow")
                elif "INFO" in line:
                    log_text.append(line + "\n", style="green")
                else:
                    log_text.append(line + "\n", style="dim")

        return Panel(
            log_text,
            title="[bold cyan]Recent Logs[/bold cyan]",
            border_style="cyan",
        )

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration in human-readable format."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            m, s = divmod(int(seconds), 60)
            return f"{m}m {s}s"
        else:
            h, rem = divmod(int(seconds), 3600)
            m, s = divmod(rem, 60)
            return f"{h}h {m}m"

    def _handle_restart(self) -> None:
        """Handle process restart with exponential backoff."""
        self.state.restart_count += 1
        self.state.consecutive_failures += 1

        # Calculate backoff
        self.state.backoff_seconds = min(
            self.MIN_BACKOFF * (self.BACKOFF_MULTIPLIER ** (self.state.consecutive_failures - 1)),
            self.MAX_BACKOFF,
        )

        self.console.print(
            f"[yellow]Process died. Restarting in {self.state.backoff_seconds:.1f}s "
            f"(attempt #{self.state.restart_count})[/yellow]"
        )

    def _reset_backoff(self) -> None:
        """Reset backoff after successful health check."""
        if self.state.consecutive_failures > 0:
            self.state.consecutive_failures = 0
            self.state.backoff_seconds = self.MIN_BACKOFF

    async def run_supervised(self) -> None:
        """Run the server with supervision (auto-restart, health checks)."""
        self.console.print("[bold magenta]Starting Majic Movie Selector Supervisor[/bold magenta]")

        # Start the server
        if not self._start_process():
            return

        # Wait for initial startup
        await asyncio.sleep(3)

        try:
            with Live(self._create_status_panel(), refresh_per_second=2, console=self.console) as live:
                last_health_check = 0.0

                while not self._stop_event.is_set():
                    # Update display
                    status_panel = self._create_status_panel()
                    logs_panel = self._create_logs_panel()

                    # Combine panels
                    from rich.layout import Layout
                    layout = Layout()
                    layout.split_column(
                        Layout(status_panel, size=12),
                        Layout(logs_panel),
                    )
                    live.update(layout)

                    # Check if process is still running
                    if self.state.process and self.state.process.poll() is not None:
                        if not self.state.is_stopping:
                            self._handle_restart()
                            await asyncio.sleep(self.state.backoff_seconds)
                            self._start_process()

                    # Periodic health check
                    now = time.time()
                    if now - last_health_check >= self.HEALTH_CHECK_INTERVAL:
                        is_healthy = await self._health_check()
                        last_health_check = now
                        if is_healthy:
                            self._reset_backoff()

                    await asyncio.sleep(0.5)

        except KeyboardInterrupt:
            self.console.print("\n[yellow]Received interrupt signal[/yellow]")
        finally:
            self._stop_process()

    async def run_status(self) -> None:
        """Show current status without supervision."""
        # Check if already running via PID file
        if self.pid_file.exists():
            try:
                pid = int(self.pid_file.read_text().strip())
                # Check if process exists
                os.kill(pid, 0)
                self.state.pid = pid
                self.state.start_time = self.pid_file.stat().st_mtime
            except (ValueError, ProcessLookupError, PermissionError):
                self.state.pid = None

        # Do a health check
        await self._health_check()

        # Show status
        self.console.print(self._create_status_panel())
        self.console.print(self._create_logs_panel())

    def stop(self) -> None:
        """Signal the supervisor to stop."""
        self._stop_event.set()
        self.state.is_stopping = True


def create_supervisor(host: str = "127.0.0.1", port: int = 8443) -> MajicSupervisor:
    """Factory function to create a supervisor instance."""
    return MajicSupervisor(host=host, port=port)
