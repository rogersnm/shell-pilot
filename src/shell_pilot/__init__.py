"""
A more ergonomic subprocess alternative for Python.

Usage:
    from shell import cmd, sh

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
from dataclasses import dataclass
from typing import Union, Optional


@dataclass
class Result:
    """Result of a command execution."""
    stdout: str
    stderr: str
    returncode: int

    @property
    def ok(self) -> bool:
        """True if command exited with code 0."""
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
    ):
        """
        Create a command.

        Args:
            *args: Command and arguments. If a single string is passed,
                   it will be parsed using shell lexing rules.
            stdin: Optional string to pass as stdin.
            env: Optional environment variables (added to current env).
            cwd: Optional working directory.
        """
        if len(args) == 1 and isinstance(args[0], str) and " " in args[0]:
            # Parse shell-style string: "ls -la" -> ["ls", "-la"]
            self._args = shlex.split(args[0])
        else:
            self._args = list(args)

        self._stdin = stdin
        self._env = env
        self._cwd = cwd
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
        result._pipeline = self._pipeline + [other]
        return result

    def run(self, check: bool = False) -> Result:
        """
        Execute the command (or pipeline) synchronously.

        Args:
            check: If True, raise CommandError on non-zero exit.

        Returns:
            Result object with stdout, stderr, and returncode.
        """
        if len(self._pipeline) == 1:
            # Single command
            return self._run_single(check=check)
        else:
            # Pipeline
            return self._run_pipeline(check=check)

    def _run_single(self, check: bool = False) -> Result:
        """Run a single command."""
        import os

        env = None
        if self._env:
            env = {**os.environ, **self._env}

        proc = subprocess.run(
            self._args,
            input=self._stdin,
            capture_output=True,
            text=True,
            env=env,
            cwd=self._cwd,
        )

        result = Result(
            stdout=proc.stdout,
            stderr=proc.stderr,
            returncode=proc.returncode,
        )

        if check and not result.ok:
            raise CommandError(result)

        return result

    def _run_pipeline(self, check: bool = False) -> Result:
        """Run a pipeline of commands."""
        import os

        processes: list[subprocess.Popen] = []
        prev_stdout = None

        # Handle initial stdin
        first_stdin = subprocess.PIPE if self._pipeline[0]._stdin else None

        for i, cmd in enumerate(self._pipeline):
            is_first = i == 0
            is_last = i == len(self._pipeline) - 1

            env = None
            if cmd._env:
                env = {**os.environ, **cmd._env}

            proc = subprocess.Popen(
                cmd._args,
                stdin=prev_stdout if not is_first else first_stdin,
                stdout=subprocess.PIPE if not is_last else subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                cwd=cmd._cwd,
            )
            processes.append(proc)

            # Close the previous stdout in parent to allow SIGPIPE
            if prev_stdout is not None:
                prev_stdout.close()

            prev_stdout = proc.stdout

        # Send stdin to first process if provided
        if self._pipeline[0]._stdin and processes:
            processes[0].stdin.write(self._pipeline[0]._stdin)
            processes[0].stdin.close()

        # Get output from last process
        last_proc = processes[-1]
        stdout, stderr = last_proc.communicate()

        # Wait for all processes and collect any stderr
        all_stderr = []
        final_returncode = 0
        for proc in processes:
            proc.wait()
            if proc.stderr:
                err = proc.stderr.read() if proc != last_proc else ""
                if err:
                    all_stderr.append(err)
            if proc.returncode != 0:
                final_returncode = proc.returncode

        # Combine stderr from all processes
        combined_stderr = stderr + "".join(all_stderr)

        result = Result(
            stdout=stdout,
            stderr=combined_stderr,
            returncode=final_returncode,
        )

        if check and not result.ok:
            raise CommandError(result)

        return result

    async def run_async(self, check: bool = False) -> Result:
        """
        Execute the command (or pipeline) asynchronously.

        Args:
            check: If True, raise CommandError on non-zero exit.

        Returns:
            Result object with stdout, stderr, and returncode.
        """
        if len(self._pipeline) == 1:
            return await self._run_single_async(check=check)
        else:
            return await self._run_pipeline_async(check=check)

    async def _run_single_async(self, check: bool = False) -> Result:
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
        stdout_bytes, stderr_bytes = await proc.communicate(input=stdin_bytes)

        result = Result(
            stdout=stdout_bytes.decode() if stdout_bytes else "",
            stderr=stderr_bytes.decode() if stderr_bytes else "",
            returncode=proc.returncode,
        )

        if check and not result.ok:
            raise CommandError(result)

        return result

    async def _run_pipeline_async(self, check: bool = False) -> Result:
        """Run a pipeline of commands asynchronously."""
        import os

        # For async pipelines, we need to chain data manually since
        # asyncio doesn't support direct stdout->stdin piping like subprocess
        current_input = self._pipeline[0]._stdin.encode() if self._pipeline[0]._stdin else None

        final_returncode = 0
        all_stderr: list[str] = []

        for i, cmd in enumerate(self._pipeline):
            env = None
            if cmd._env:
                env = {**os.environ, **cmd._env}

            proc = await asyncio.create_subprocess_exec(
                *cmd._args,
                stdin=asyncio.subprocess.PIPE if current_input is not None or i > 0 else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cmd._cwd,
            )

            stdout_bytes, stderr_bytes = await proc.communicate(input=current_input)

            if stderr_bytes:
                all_stderr.append(stderr_bytes.decode())
            if proc.returncode != 0:
                final_returncode = proc.returncode

            # Output becomes input for next command
            current_input = stdout_bytes

        result = Result(
            stdout=current_input.decode() if current_input else "",
            stderr="".join(all_stderr),
            returncode=final_returncode,
        )

        if check and not result.ok:
            raise CommandError(result)

        return result

    def with_stdin(self, stdin: str) -> "Cmd":
        """Return a new Cmd with the given stdin."""
        new_cmd = Cmd(*self._args, stdin=stdin, env=self._env, cwd=self._cwd)
        new_cmd._pipeline = self._pipeline.copy()
        return new_cmd

    def with_env(self, **env: str) -> "Cmd":
        """Return a new Cmd with additional environment variables."""
        merged_env = {**(self._env or {}), **env}
        new_cmd = Cmd(*self._args, stdin=self._stdin, env=merged_env, cwd=self._cwd)
        new_cmd._pipeline = self._pipeline.copy()
        return new_cmd

    def with_cwd(self, cwd: str) -> "Cmd":
        """Return a new Cmd with a different working directory."""
        new_cmd = Cmd(*self._args, stdin=self._stdin, env=self._env, cwd=cwd)
        new_cmd._pipeline = self._pipeline.copy()
        return new_cmd

    def __repr__(self) -> str:
        if len(self._pipeline) == 1:
            return f"Cmd({self._args!r})"
        else:
            cmds = " | ".join(repr(c._args) for c in self._pipeline)
            return f"Pipeline({cmds})"


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
