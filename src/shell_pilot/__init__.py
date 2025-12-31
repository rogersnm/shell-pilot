"""
A more ergonomic subprocess alternative for Python.

Usage:
    from shell_pilot import cmd, sh

    # Simple command
    result = cmd("ls -la").run()
    print(result.stdout)

    # Piping with | operator (just like bash!)
    result = (cmd("ls -la") | cmd("grep .py") | cmd("wc -l")).run()

    # Or use the sh() shorthand
    result = (sh("ls -la") | sh("grep .py") | sh("wc -l")).run()

    # Async support
    result = await cmd("long-running-command").run_async()

    # Check success
    if result.ok:
        print(result.stdout)
    else:
        print(result.stderr)
"""

from __future__ import annotations

import asyncio
import shlex
import subprocess
import threading
from dataclasses import dataclass
from typing import Union, Optional, Iterator, AsyncIterator, IO

__version__ = "0.3.0"

__all__ = [
    "Cmd",
    "cmd",
    "sh",
    "Result",
    "CommandError",
    "TimeoutExpired",
    "Stream",
    "AsyncStream",
    "run",
    "run_async",
    "__version__",
]


@dataclass
class Result:
    """Result of a command execution."""
    stdout: str
    stderr: str
    returncode: int
    returncodes: Optional[list] = None  # All return codes for pipelines

    @property
    def ok(self) -> bool:
        """True if all commands exited with code 0."""
        if self.returncodes is not None:
            return all(rc == 0 for rc in self.returncodes)
        return self.returncode == 0

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        return self.stdout

    def raise_on_error(self) -> "Result":
        """Raise an exception if the command failed."""
        if not self.ok:
            raise CommandError(self)
        return self


class CommandError(Exception):
    """Raised when a command fails."""
    def __init__(self, result: Result):
        self.result = result
        super().__init__(
            f"Command failed with code {result.returncode}\n"
            f"stderr: {result.stderr}"
        )


class TimeoutExpired(Exception):
    """Raised when a command times out."""
    def __init__(self, args: list, timeout: float, stderr: str = ""):
        self.args_list = args
        self.timeout = timeout
        self.stderr = stderr
        super().__init__(f"Command timed out after {timeout}s: {args}")


class Cmd:
    """
    A command that can be executed or piped to other commands.

    Examples:
        cmd("ls -la").run()
        cmd("echo", "hello").run()
        (cmd("cat file.txt") | cmd("grep pattern")).run()
    """

    def __init__(
        self,
        *args: str,
        stdin: Optional[str] = None,
        env: Optional[dict] = None,
        cwd: Optional[str] = None,
        shell: bool = False,
    ):
        """
        Create a command.

        Args:
            *args: Command and arguments. If a single string is passed,
                   it will be parsed using shell lexing rules.
            stdin: Optional string to pass as stdin.
            env: Optional environment variables (added to current env).
            cwd: Optional working directory.
            shell: If True, run command through the shell (enables glob
                   expansion, env vars, etc). Use with caution for security.
        """
        if len(args) == 1 and isinstance(args[0], str) and " " in args[0] and not shell:
            # Parse shell-style string: "ls -la" -> ["ls", "-la"]
            self._args = shlex.split(args[0])
        else:
            self._args = list(args)

        self._stdin = stdin
        self._env = env
        self._cwd = cwd
        self._shell = shell
        self._pipeline: list[Cmd] = [self]

    def __or__(self, other: "Cmd") -> "Cmd":
        """
        Pipe this command's stdout to another command's stdin.

        Usage: cmd("ls") | cmd("grep foo")
        """
        if not isinstance(other, Cmd):
            return NotImplemented

        # Create a new Cmd that represents the full pipeline
        result = Cmd.__new__(Cmd)
        result._args = other._args
        result._stdin = None  # Pipeline handles stdin
        result._env = other._env
        result._cwd = other._cwd
        result._shell = other._shell
        result._pipeline = self._pipeline + [other]
        return result

    def run(self, check: bool = False, timeout: Optional[float] = None) -> Result:
        """
        Execute the command (or pipeline) synchronously.

        Args:
            check: If True, raise CommandError on non-zero exit.
            timeout: Maximum seconds to wait. None means no timeout.
                     Raises TimeoutExpired if exceeded.

        Returns:
            Result object with stdout, stderr, and returncode.
        """
        if len(self._pipeline) == 1:
            # Single command
            return self._run_single(check=check, timeout=timeout)
        else:
            # Pipeline
            return self._run_pipeline(check=check, timeout=timeout)

    def _run_single(self, check: bool = False, timeout: Optional[float] = None) -> Result:
        """Run a single command."""
        import os

        env = None
        if self._env:
            env = {**os.environ, **self._env}

        if self._shell:
            # For shell mode, pass as single string
            if len(self._args) == 1:
                command = self._args[0]
            else:
                # User passed multiple args with shell=True, join them
                command = shlex.join(self._args)

            try:
                proc = subprocess.run(
                    command,
                    shell=True,
                    input=self._stdin,
                    capture_output=True,
                    text=True,
                    env=env,
                    cwd=self._cwd,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as e:
                raise TimeoutExpired(
                    [command],
                    timeout,
                    stderr=e.stderr if e.stderr else ""
                )
        else:
            try:
                proc = subprocess.run(
                    self._args,
                    input=self._stdin,
                    capture_output=True,
                    text=True,
                    env=env,
                    cwd=self._cwd,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as e:
                raise TimeoutExpired(
                    self._args,
                    timeout,
                    stderr=e.stderr.decode() if e.stderr else ""
                )

        result = Result(
            stdout=proc.stdout,
            stderr=proc.stderr,
            returncode=proc.returncode,
        )

        if check and not result.ok:
            raise CommandError(result)

        return result

    def _run_pipeline(self, check: bool = False, timeout: Optional[float] = None) -> Result:
        """Run pipeline with true Unix pipe semantics."""
        processes, stdin_thread = self._start_pipeline(text=True)

        # Read from last process with timeout
        last_proc = processes[-1]
        try:
            stdout, stderr = last_proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Kill all processes in the pipeline
            for proc in processes:
                try:
                    proc.kill()
                except OSError:
                    pass

            # Try to capture any stderr that was produced
            captured_stderr = ""
            try:
                if last_proc.stderr:
                    captured_stderr = last_proc.stderr.read() or ""
            except Exception:
                pass

            # Wait for them to actually die
            for proc in processes:
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
            raise TimeoutExpired(
                [c._args for c in self._pipeline],
                timeout,
                stderr=captured_stderr
            )

        # Wait for stdin thread to complete
        if stdin_thread:
            stdin_thread.join(timeout=1)

        # Wait for all processes and collect return codes
        return_codes = []
        for proc in processes:
            proc.wait()
            return_codes.append(proc.returncode)

        # Use pipefail semantics: return first non-zero exit code
        final_returncode = 0
        for rc in return_codes:
            if rc != 0:
                final_returncode = rc
                break

        result = Result(
            stdout=stdout,
            stderr=stderr,
            returncode=final_returncode,
            returncodes=return_codes,
        )

        if check and not result.ok:
            raise CommandError(result)

        return result

    async def run_async(self, check: bool = False, timeout: Optional[float] = None) -> Result:
        """
        Execute the command (or pipeline) asynchronously.

        Args:
            check: If True, raise CommandError on non-zero exit.
            timeout: Maximum seconds to wait. None means no timeout.
                     Raises TimeoutExpired if exceeded.

        Returns:
            Result object with stdout, stderr, and returncode.
        """
        if len(self._pipeline) == 1:
            return await self._run_single_async(check=check, timeout=timeout)
        else:
            return await self._run_pipeline_async(check=check, timeout=timeout)

    async def _run_single_async(self, check: bool = False, timeout: Optional[float] = None) -> Result:
        """Run a single command asynchronously."""
        import os

        env = None
        if self._env:
            env = {**os.environ, **self._env}

        proc = await asyncio.create_subprocess_exec(
            *self._args,
            stdin=asyncio.subprocess.PIPE if self._stdin else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=self._cwd,
        )

        stdin_bytes = self._stdin.encode() if self._stdin else None
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin_bytes),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()  # Prevent zombie process
            raise TimeoutExpired(self._args, timeout)

        result = Result(
            stdout=stdout_bytes.decode() if stdout_bytes else "",
            stderr=stderr_bytes.decode() if stderr_bytes else "",
            returncode=proc.returncode,
        )

        if check and not result.ok:
            raise CommandError(result)

        return result

    async def _run_pipeline_async(self, check: bool = False, timeout: Optional[float] = None) -> Result:
        """Run pipeline with true concurrent async pipes."""
        processes, shuttle_tasks = await self._start_pipeline_async()

        # Helper to collect final output
        final_stdout = None
        final_stderr = None

        async def collect_final_output():
            nonlocal final_stdout, final_stderr
            final_stdout, final_stderr = await processes[-1].communicate()

        output_task = asyncio.create_task(collect_final_output())

        # Wait for everything with optional timeout
        all_tasks = shuttle_tasks + [output_task]

        try:
            if timeout:
                done, pending = await asyncio.wait(
                    all_tasks,
                    timeout=timeout,
                    return_when=asyncio.ALL_COMPLETED
                )
                if pending:
                    # Timeout occurred - cancel pending tasks and kill processes
                    for task in pending:
                        task.cancel()
                    for proc in processes:
                        try:
                            proc.kill()
                        except OSError:
                            pass

                    # Try to capture any stderr that was produced
                    captured_stderr = ""
                    try:
                        last_proc = processes[-1]
                        if last_proc.stderr:
                            stderr_bytes = await asyncio.wait_for(
                                last_proc.stderr.read(),
                                timeout=0.5
                            )
                            captured_stderr = stderr_bytes.decode(errors="replace") if stderr_bytes else ""
                    except Exception:
                        pass

                    # Wait for processes to die
                    for proc in processes:
                        try:
                            await asyncio.wait_for(proc.wait(), timeout=1)
                        except asyncio.TimeoutError:
                            pass
                    raise TimeoutExpired(
                        [c._args for c in self._pipeline],
                        timeout,
                        stderr=captured_stderr
                    )
            else:
                # No timeout - wait for all tasks
                await asyncio.gather(*shuttle_tasks, return_exceptions=True)
                await output_task

        except asyncio.CancelledError:
            # External cancellation - cleanup
            for proc in processes:
                try:
                    proc.kill()
                except OSError:
                    pass
            for proc in processes:
                try:
                    await asyncio.wait_for(proc.wait(), timeout=1)
                except asyncio.TimeoutError:
                    pass
            raise

        # Wait for all processes to complete
        for proc in processes:
            await proc.wait()

        # Collect all return codes
        return_codes = [proc.returncode for proc in processes]

        # Pipefail: first non-zero exit code
        final_returncode = 0
        for rc in return_codes:
            if rc != 0:
                final_returncode = rc
                break

        result = Result(
            stdout=final_stdout.decode() if final_stdout else "",
            stderr=final_stderr.decode() if final_stderr else "",
            returncode=final_returncode,
            returncodes=return_codes,
        )

        if check and not result.ok:
            raise CommandError(result)

        return result

    def with_stdin(self, stdin: str) -> "Cmd":
        """Return a new Cmd/pipeline with the given stdin for the first command."""
        if len(self._pipeline) == 1:
            # Single command - set stdin directly
            return Cmd(*self._args, stdin=stdin, env=self._env, cwd=self._cwd, shell=self._shell)
        else:
            # Pipeline - clone with updated first command's stdin
            result = Cmd.__new__(Cmd)
            result._args = self._pipeline[-1]._args
            result._stdin = self._pipeline[-1]._stdin
            result._env = self._pipeline[-1]._env
            result._cwd = self._pipeline[-1]._cwd
            result._shell = self._pipeline[-1]._shell

            # Rebuild pipeline: first command gets new stdin, rest are cloned
            first = self._pipeline[0]
            result._pipeline = [
                Cmd(*first._args, stdin=stdin, env=first._env, cwd=first._cwd, shell=first._shell)
            ] + [
                Cmd(*c._args, stdin=c._stdin, env=c._env, cwd=c._cwd, shell=c._shell)
                for c in self._pipeline[1:]
            ]
            return result

    def with_env(self, **env: str) -> "Cmd":
        """Return a new Cmd/pipeline with additional environment variables for ALL commands."""
        if len(self._pipeline) == 1:
            merged_env = {**(self._env or {}), **env}
            return Cmd(*self._args, stdin=self._stdin, env=merged_env, cwd=self._cwd, shell=self._shell)
        else:
            # Pipeline - apply env to ALL commands
            result = Cmd.__new__(Cmd)
            result._args = self._pipeline[-1]._args
            result._stdin = self._pipeline[-1]._stdin
            result._env = {**(self._pipeline[-1]._env or {}), **env}
            result._cwd = self._pipeline[-1]._cwd
            result._shell = self._pipeline[-1]._shell

            result._pipeline = [
                Cmd(*c._args, stdin=c._stdin, env={**(c._env or {}), **env}, cwd=c._cwd, shell=c._shell)
                for c in self._pipeline
            ]
            return result

    def with_cwd(self, cwd: str) -> "Cmd":
        """Return a new Cmd/pipeline with a different working directory for ALL commands."""
        if len(self._pipeline) == 1:
            return Cmd(*self._args, stdin=self._stdin, env=self._env, cwd=cwd, shell=self._shell)
        else:
            # Pipeline - apply cwd to ALL commands
            result = Cmd.__new__(Cmd)
            result._args = self._pipeline[-1]._args
            result._stdin = self._pipeline[-1]._stdin
            result._env = self._pipeline[-1]._env
            result._cwd = cwd
            result._shell = self._pipeline[-1]._shell

            result._pipeline = [
                Cmd(*c._args, stdin=c._stdin, env=c._env, cwd=cwd, shell=c._shell)
                for c in self._pipeline
            ]
            return result

    def _start_pipeline(self, text: bool = False) -> tuple[list[subprocess.Popen], Optional[threading.Thread]]:
        """Start all processes in pipeline, return handles.

        Args:
            text: If True, use text mode (str) for stdin/stdout/stderr.
                  If False (default), use binary mode (bytes).
        """
        import os

        processes: list[subprocess.Popen] = []

        for i, pipe_cmd in enumerate(self._pipeline):
            is_first = i == 0
            is_last = i == len(self._pipeline) - 1

            stdin_source = None
            if is_first:
                stdin_source = subprocess.PIPE if pipe_cmd._stdin else None
            else:
                stdin_source = processes[-1].stdout

            env = {**os.environ, **(pipe_cmd._env or {})} if pipe_cmd._env else None

            # Handle shell mode
            if pipe_cmd._shell:
                command = pipe_cmd._args[0] if len(pipe_cmd._args) == 1 else shlex.join(pipe_cmd._args)
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    stdin=stdin_source,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE if is_last else subprocess.DEVNULL,
                    text=text,
                    env=env,
                    cwd=pipe_cmd._cwd,
                )
            else:
                proc = subprocess.Popen(
                    pipe_cmd._args,
                    stdin=stdin_source,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE if is_last else subprocess.DEVNULL,
                    text=text,
                    env=env,
                    cwd=pipe_cmd._cwd,
                )
            processes.append(proc)

            if not is_first and processes[-2].stdout:
                processes[-2].stdout.close()

        # Start stdin feeder thread
        stdin_thread = None
        if self._pipeline[0]._stdin:
            def feed_stdin():
                try:
                    data = self._pipeline[0]._stdin
                    # In text mode, write as string; in binary mode, encode
                    if text:
                        processes[0].stdin.write(data)
                    else:
                        if isinstance(data, str):
                            data = data.encode()
                        processes[0].stdin.write(data)
                    processes[0].stdin.close()
                except BrokenPipeError:
                    pass
                except Exception:
                    pass  # Logged but not raised in daemon thread

            stdin_thread = threading.Thread(target=feed_stdin, daemon=True)
            stdin_thread.start()

        return processes, stdin_thread

    def stream(self) -> "Stream":
        """
        Start the command/pipeline and return a Stream for incremental reading.

        The command starts immediately. Use the Stream's iteration methods
        to read output as it becomes available.

        Returns:
            Stream object for reading output.

        Example:
            with cmd("find / -name '*.py'").stream() as s:
                for line in s.iter_lines():
                    print(line)
                    if should_stop():
                        break  # Terminates find
        """
        processes, stdin_thread = self._start_pipeline()
        return Stream(processes=processes, stdin_thread=stdin_thread)

    async def _start_pipeline_async(self) -> tuple[list, list]:
        """Start all async processes in pipeline, return handles and shuttle tasks.

        Returns:
            Tuple of (processes, shuttle_tasks) where shuttle_tasks handle
            stdin feeding and inter-process data piping.
        """
        import os

        processes: list[asyncio.subprocess.Process] = []

        for i, pipe_cmd in enumerate(self._pipeline):
            is_first = i == 0
            is_last = i == len(self._pipeline) - 1

            env = {**os.environ, **(pipe_cmd._env or {})} if pipe_cmd._env else None

            if is_first:
                stdin = asyncio.subprocess.PIPE if pipe_cmd._stdin else None
            else:
                stdin = asyncio.subprocess.PIPE  # We'll feed it manually

            # Handle shell mode
            if pipe_cmd._shell:
                command = pipe_cmd._args[0] if len(pipe_cmd._args) == 1 else shlex.join(pipe_cmd._args)
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdin=stdin,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE if is_last else asyncio.subprocess.DEVNULL,
                    env=env,
                    cwd=pipe_cmd._cwd,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    *pipe_cmd._args,
                    stdin=stdin,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE if is_last else asyncio.subprocess.DEVNULL,
                    env=env,
                    cwd=pipe_cmd._cwd,
                )
            processes.append(proc)

        # Helper to shuttle data between processes
        async def pipe_data(src: asyncio.StreamReader, dst: asyncio.StreamWriter):
            """Copy data from src to dst until EOF."""
            try:
                while True:
                    chunk = await src.read(8192)
                    if not chunk:
                        break
                    dst.write(chunk)
                    await dst.drain()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # Downstream closed, that's fine
            finally:
                try:
                    dst.close()
                    await dst.wait_closed()
                except Exception:
                    pass  # Best effort cleanup

        # Set up data flow tasks
        shuttle_tasks = []

        # Feed initial stdin
        if self._pipeline[0]._stdin:
            async def feed_first_stdin():
                try:
                    data = self._pipeline[0]._stdin
                    if isinstance(data, str):
                        data = data.encode()
                    processes[0].stdin.write(data)
                    await processes[0].stdin.drain()
                    processes[0].stdin.close()
                    await processes[0].stdin.wait_closed()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                except Exception:
                    pass

            shuttle_tasks.append(asyncio.create_task(feed_first_stdin()))

        # Connect intermediate processes
        for i in range(len(processes) - 1):
            shuttle_tasks.append(asyncio.create_task(
                pipe_data(processes[i].stdout, processes[i + 1].stdin)
            ))

        return processes, shuttle_tasks

    async def stream_async(self) -> "AsyncStream":
        """
        Start the command/pipeline and return an AsyncStream for incremental reading.

        The command starts immediately. Use the AsyncStream's iteration methods
        to read output as it becomes available.

        Returns:
            AsyncStream object for reading output.
        """
        processes, shuttle_tasks = await self._start_pipeline_async()
        return AsyncStream(processes=processes, shuttle_tasks=shuttle_tasks)

    def __repr__(self) -> str:
        if len(self._pipeline) == 1:
            return f"Cmd({self._args!r})"
        else:
            cmds = " | ".join(repr(c._args) for c in self._pipeline)
            return f"Pipeline({cmds})"


class Stream:
    """
    Handle for streaming command output with true Unix semantics.

    Provides both byte-level and line-level iteration, plus direct
    access to file descriptors for advanced use (select/poll/epoll).
    """

    def __init__(
        self,
        processes: list[subprocess.Popen],
        stdin_thread: Optional[threading.Thread] = None,
    ):
        self._processes = processes
        self._stdin_thread = stdin_thread
        self._closed = False

    @property
    def stdout(self) -> IO[bytes]:
        """Raw stdout file object. Use for select() or direct reads."""
        return self._processes[-1].stdout

    @property
    def stderr(self) -> Optional[IO[bytes]]:
        """Raw stderr file object (last process only)."""
        return self._processes[-1].stderr

    @property
    def pid(self) -> int:
        """PID of the last process in pipeline."""
        return self._processes[-1].pid

    def iter_bytes(self, chunk_size: int = 8192) -> Iterator[bytes]:
        """
        Iterate over stdout in chunks.

        Args:
            chunk_size: Bytes to read per iteration. Actual chunks may be
                       smaller if less data is available.

        Yields:
            Byte chunks as they become available.
        """
        while True:
            chunk = self.stdout.read(chunk_size)
            if not chunk:
                break
            yield chunk

    def iter_lines(self, encoding: str = "utf-8") -> Iterator[str]:
        """
        Iterate over stdout line by line.

        Note: This buffers internally until newline. For true streaming
        of line-oriented protocols, ensure the producing command flushes
        on newlines (e.g., grep --line-buffered, sed -u, python -u).

        Args:
            encoding: Text encoding for decoding bytes.

        Yields:
            Lines without trailing newline.
        """
        buffer = b""
        for chunk in self.iter_bytes(chunk_size=1024):
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                yield line.decode(encoding)
        # Yield any remaining content without trailing newline
        if buffer:
            yield buffer.decode(encoding)

    def read_all(self, timeout: Optional[float] = None) -> Result:
        """
        Read all remaining output and wait for completion.

        Useful after partial streaming to get final result.
        """
        last_proc = self._processes[-1]
        try:
            stdout, stderr = last_proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.kill()
            self._wait_all()
            raise TimeoutExpired(["pipeline"], timeout)

        self._wait_all()

        # Handle both text and bytes mode
        if isinstance(stdout, bytes):
            stdout = stdout.decode()
        if isinstance(stderr, bytes):
            stderr = stderr.decode()

        return Result(
            stdout=stdout,
            stderr=stderr,
            returncode=self._final_returncode(),
        )

    def _wait_all(self):
        """Wait for all processes to complete."""
        if self._stdin_thread:
            self._stdin_thread.join(timeout=1)
        for proc in self._processes:
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    def _final_returncode(self) -> int:
        """Get first non-zero return code (pipefail semantics)."""
        for proc in self._processes:
            if proc.returncode != 0:
                return proc.returncode
        return 0

    def kill(self):
        """Send SIGKILL to all processes in the pipeline."""
        for proc in self._processes:
            try:
                proc.kill()
            except OSError:
                pass  # Already dead

    def terminate(self):
        """Send SIGTERM to all processes in the pipeline."""
        for proc in self._processes:
            try:
                proc.terminate()
            except OSError:
                pass  # Already dead

    def __enter__(self) -> "Stream":
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        """Clean up resources."""
        if self._closed:
            return
        self._closed = True

        # Close our stdout handle (sends EOF/SIGPIPE upstream)
        try:
            if self.stdout:
                self.stdout.close()
        except OSError:
            pass

        # Kill any still-running processes
        self.kill()
        self._wait_all()

    @property
    def returncodes(self) -> list[Optional[int]]:
        """Return codes of all processes (None if still running)."""
        return [p.returncode for p in self._processes]


class AsyncStream:
    """Async version of Stream."""

    def __init__(
        self,
        processes: list[asyncio.subprocess.Process],
        shuttle_tasks: Optional[list[asyncio.Task]] = None,
    ):
        self._processes = processes
        self._shuttle_tasks = shuttle_tasks or []
        self._closed = False

    @property
    def stdout(self) -> asyncio.StreamReader:
        """Raw stdout StreamReader."""
        return self._processes[-1].stdout

    @property
    def stderr(self) -> Optional[asyncio.StreamReader]:
        """Raw stderr StreamReader (last process only)."""
        return self._processes[-1].stderr

    @property
    def pid(self) -> int:
        """PID of the last process in pipeline."""
        return self._processes[-1].pid

    async def iter_bytes(self, chunk_size: int = 8192) -> AsyncIterator[bytes]:
        """Iterate over stdout in chunks."""
        while True:
            chunk = await self.stdout.read(chunk_size)
            if not chunk:
                break
            yield chunk

    async def iter_lines(self, encoding: str = "utf-8") -> AsyncIterator[str]:
        """Iterate over stdout line by line."""
        async for line in self.stdout:
            yield line.decode(encoding).rstrip("\n")

    async def read_all(self, timeout: Optional[float] = None) -> Result:
        """Read remaining output and wait for completion."""
        last_proc = self._processes[-1]
        try:
            stdout, stderr = await asyncio.wait_for(
                last_proc.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            await self.kill()
            raise TimeoutExpired(["pipeline"], timeout)

        await self._wait_all()

        return Result(
            stdout=stdout.decode() if stdout else "",
            stderr=stderr.decode() if stderr else "",
            returncode=self._final_returncode(),
        )

    async def _wait_all(self):
        """Wait for all processes to complete."""
        # Cancel any remaining shuttle tasks
        for task in self._shuttle_tasks:
            if not task.done():
                task.cancel()
        # Wait for processes
        for proc in self._processes:
            try:
                await asyncio.wait_for(proc.wait(), timeout=1)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

    def _final_returncode(self) -> int:
        """Get first non-zero return code (pipefail semantics)."""
        for proc in self._processes:
            if proc.returncode != 0:
                return proc.returncode
        return 0

    async def kill(self):
        """Kill all processes."""
        for proc in self._processes:
            try:
                proc.kill()
            except OSError:
                pass
        await self._wait_all()

    async def terminate(self):
        """Terminate all processes."""
        for proc in self._processes:
            try:
                proc.terminate()
            except OSError:
                pass

    async def close(self):
        """Clean up resources."""
        if self._closed:
            return
        self._closed = True
        await self.kill()

    async def __aenter__(self) -> "AsyncStream":
        return self

    async def __aexit__(self, *args):
        await self.close()

    @property
    def returncodes(self) -> list[Optional[int]]:
        """Return codes of all processes (None if still running)."""
        return [p.returncode for p in self._processes]


# Convenient aliases
cmd = Cmd
sh = Cmd


def run(command: str, **kwargs) -> Result:
    """
    Convenience function to run a command string directly.

    Usage:
        result = run("ls -la")
        result = run("echo hello", check=True)
    """
    return Cmd(command).run(**kwargs)


async def run_async(command: str, **kwargs) -> Result:
    """
    Convenience function to run a command string asynchronously.

    Usage:
        result = await run_async("ls -la")
    """
    return await Cmd(command).run_async(**kwargs)
