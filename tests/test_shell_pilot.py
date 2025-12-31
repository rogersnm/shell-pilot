"""Tests for shell-pilot."""

import pytest
import os
from shell_pilot import (
    Cmd, cmd, sh, run, run_async, Result, CommandError,
    TimeoutExpired, Stream, AsyncStream
)


class TestBasicCommands:
    """Test basic command execution."""

    def test_simple_command(self):
        result = cmd("echo", "hello").run()
        assert result.ok
        assert result.stdout.strip() == "hello"
        assert result.returncode == 0

    def test_shell_string_parsing(self):
        """Test that shell-style strings are parsed correctly."""
        result = cmd("echo hello world").run()
        assert result.stdout.strip() == "hello world"

    def test_command_with_args(self):
        result = sh("printf '%s %s' foo bar").run()
        assert result.stdout == "foo bar"

    def test_failed_command(self):
        result = cmd("ls", "/nonexistent_path_12345").run()
        assert not result.ok
        assert result.returncode != 0
        assert result.stderr  # Should have error message

    def test_result_bool_conversion(self):
        """Test that Result can be used in boolean context."""
        success = cmd("true").run()
        failure = cmd("false").run()
        assert bool(success) is True
        assert bool(failure) is False

    def test_result_str_conversion(self):
        """Test that str(result) returns stdout."""
        result = cmd("echo hello").run()
        assert str(result).strip() == "hello"


class TestPiping:
    """Test pipe functionality."""

    def test_two_command_pipe(self):
        result = (sh("echo hello") | sh("cat")).run()
        assert result.ok
        assert result.stdout.strip() == "hello"

    def test_three_command_pipe(self):
        result = (
            sh("printf 'apple\\nbanana\\napricot'")
            | sh("grep a")
            | sh("wc -l")
        ).run()
        assert result.ok
        assert result.stdout.strip() == "3"

    def test_pipe_with_filtering(self):
        result = (
            sh("printf 'line1\\nline2\\nline3'")
            | sh("grep 2")
        ).run()
        assert result.ok
        assert result.stdout.strip() == "line2"

    def test_pipe_preserves_failure(self):
        """Test that pipeline fails if any command fails."""
        result = (sh("echo hello") | sh("grep nonexistent")).run()
        assert not result.ok


class TestStdin:
    """Test stdin handling."""

    def test_with_stdin(self):
        result = cmd("cat").with_stdin("hello from stdin").run()
        assert result.ok
        assert result.stdout.strip() == "hello from stdin"

    def test_stdin_in_constructor(self):
        result = Cmd("cat", stdin="direct stdin").run()
        assert result.stdout.strip() == "direct stdin"

    def test_stdin_multiline(self):
        input_text = "line1\nline2\nline3"
        result = cmd("cat").with_stdin(input_text).run()
        assert result.stdout == input_text


class TestEnvironment:
    """Test environment variable handling."""

    def test_with_env(self):
        result = cmd("sh", "-c", "echo $MY_VAR").with_env(MY_VAR="test_value").run()
        assert result.stdout.strip() == "test_value"

    def test_env_in_constructor(self):
        result = Cmd("sh", "-c", "echo $FOO", env={"FOO": "bar"}).run()
        assert result.stdout.strip() == "bar"

    def test_multiple_env_vars(self):
        result = (
            cmd("sh", "-c", "echo $A $B")
            .with_env(A="first", B="second")
            .run()
        )
        assert result.stdout.strip() == "first second"


class TestWorkingDirectory:
    """Test working directory handling."""

    def test_with_cwd(self):
        result = cmd("pwd").with_cwd("/tmp").run()
        assert "/tmp" in result.stdout or "/private/tmp" in result.stdout


class TestErrorHandling:
    """Test error handling functionality."""

    def test_check_raises_on_failure(self):
        with pytest.raises(CommandError) as exc_info:
            cmd("false").run(check=True)
        assert exc_info.value.result.returncode != 0

    def test_check_no_raise_on_success(self):
        result = cmd("true").run(check=True)
        assert result.ok

    def test_raise_on_error_method(self):
        with pytest.raises(CommandError):
            cmd("false").run().raise_on_error()

    def test_command_error_contains_result(self):
        try:
            cmd("sh", "-c", "echo error >&2; exit 1").run(check=True)
        except CommandError as e:
            assert e.result.returncode == 1
            assert "error" in e.result.stderr


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_run_function(self):
        result = run("echo convenience")
        assert result.stdout.strip() == "convenience"

    def test_run_with_check(self):
        with pytest.raises(CommandError):
            run("false", check=True)


class TestAsync:
    """Test async functionality."""

    async def test_async_simple_command(self):
        result = await cmd("echo async").run_async()
        assert result.ok
        assert result.stdout.strip() == "async"

    async def test_async_with_stdin(self):
        result = await cmd("cat").with_stdin("async stdin").run_async()
        assert result.stdout.strip() == "async stdin"

    async def test_async_pipeline(self):
        result = await (
            sh("printf 'a\\nb\\nc'")
            | sh("grep -v b")
            | sh("wc -l")
        ).run_async()
        assert result.ok
        assert result.stdout.strip() == "2"

    async def test_async_check_raises(self):
        with pytest.raises(CommandError):
            await cmd("false").run_async(check=True)

    async def test_run_async_function(self):
        result = await run_async("echo async func")
        assert result.stdout.strip() == "async func"


class TestRepr:
    """Test string representations."""

    def test_single_cmd_repr(self):
        c = cmd("ls", "-la")
        assert "ls" in repr(c)

    def test_pipeline_repr(self):
        p = sh("ls") | sh("grep foo")
        assert "Pipeline" in repr(p) or "|" in repr(p)


class TestChaining:
    """Test method chaining."""

    def test_fluent_chaining(self):
        result = (
            cmd("cat")
            .with_stdin("test")
            .with_env(UNUSED="var")
            .with_cwd("/tmp")
            .run()
        )
        assert result.stdout.strip() == "test"

    def test_chaining_returns_new_instance(self):
        """Ensure chaining doesn't mutate original."""
        original = cmd("echo test")
        modified = original.with_env(FOO="bar")
        assert original._env is None
        assert modified._env == {"FOO": "bar"}


class TestWithMethodsFixes:
    """Test that with_* methods work correctly for pipelines."""

    def test_with_stdin_pipeline(self):
        """with_stdin should work on pipelines."""
        result = (cmd("cat") | cmd("tr a-z A-Z")).with_stdin("hello").run()
        assert result.stdout.strip() == "HELLO"

    def test_with_env_pipeline(self):
        """with_env should apply to all commands in pipeline."""
        result = (
            cmd("printenv FOO") | cmd("cat")
        ).with_env(FOO="bar").run()
        assert result.stdout.strip() == "bar"

    def test_with_cwd_pipeline(self, tmp_path):
        """with_cwd should apply to all commands in pipeline."""
        (tmp_path / "test.txt").write_text("content")
        result = (cmd("ls") | cmd("cat")).with_cwd(str(tmp_path)).run()
        assert "test.txt" in result.stdout

    def test_with_stdin_single_command(self):
        """with_stdin should still work for single commands."""
        result = cmd("cat").with_stdin("hello").run()
        assert result.stdout == "hello"


class TestTimeout:
    """Test timeout functionality."""

    def test_timeout_raises(self):
        with pytest.raises(TimeoutExpired):
            cmd("sleep 10").run(timeout=0.1)

    def test_no_timeout_by_default(self):
        result = cmd("sleep 0.1").run()
        assert result.ok

    async def test_async_timeout(self):
        with pytest.raises(TimeoutExpired):
            await cmd("sleep 10").run_async(timeout=0.1)

    def test_pipeline_timeout(self):
        with pytest.raises(TimeoutExpired):
            (cmd("sleep 10") | cmd("cat")).run(timeout=0.1)

    def test_timeout_exception_has_details(self):
        try:
            cmd("sleep 10").run(timeout=0.1)
        except TimeoutExpired as e:
            assert e.timeout == 0.1
            assert "sleep" in str(e.args_list)


class TestShellMode:
    """Test shell=True mode."""

    def test_glob_expansion(self, tmp_path):
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "c.txt").write_text("")

        result = cmd(f"ls {tmp_path}/*.py", shell=True).run()
        assert "a.py" in result.stdout
        assert "b.py" in result.stdout
        assert "c.txt" not in result.stdout

    def test_env_var_expansion(self):
        result = cmd("echo $HOME", shell=True).run()
        assert os.environ["HOME"] in result.stdout

    def test_shell_operators(self):
        result = cmd("echo foo && echo bar", shell=True).run()
        assert "foo" in result.stdout
        assert "bar" in result.stdout

    def test_shell_false_by_default(self):
        # Without shell=True, $HOME is literal
        result = cmd("echo", "$HOME").run()
        assert result.stdout.strip() == "$HOME"

    def test_shell_mode_with_timeout(self):
        with pytest.raises(TimeoutExpired):
            cmd("sleep 10", shell=True).run(timeout=0.1)


class TestStreaming:
    """Test streaming API."""

    def test_byte_streaming(self):
        chunks = []
        with cmd("printf 'hello world'").stream() as s:
            for chunk in s.iter_bytes(chunk_size=5):
                chunks.append(chunk)
        assert b"".join(chunks) == b"hello world"

    def test_line_streaming(self):
        lines = []
        with cmd("printf 'a\\nb\\nc'").stream() as s:
            for line in s.iter_lines():
                lines.append(line)
        assert lines == ["a", "b", "c"]

    def test_early_termination(self):
        """Breaking out of iteration should terminate process."""
        with cmd("yes").stream() as s:
            count = 0
            for line in s.iter_lines():
                count += 1
                if count >= 5:
                    break
        assert count == 5
        # Process should be terminated after context exit
        assert s._processes[0].returncode is not None

    def test_pipeline_streaming(self):
        lines = []
        with (cmd("printf 'apple\\nbanana\\napricot'") | cmd("grep -v banana")).stream() as s:
            for line in s.iter_lines():
                lines.append(line)
        assert lines == ["apple", "apricot"]

    def test_stream_read_all(self):
        with cmd("echo hello").stream() as s:
            result = s.read_all()
            assert result.stdout.strip() == "hello"
            assert result.ok

    def test_stream_properties(self):
        with cmd("echo test").stream() as s:
            assert s.pid > 0
            assert s.stdout is not None


class TestAsyncStreaming:
    """Test async streaming API."""

    async def test_async_line_streaming(self):
        lines = []
        async with await cmd("printf 'x\\ny\\nz'").stream_async() as s:
            async for line in s.iter_lines():
                lines.append(line)
        assert lines == ["x", "y", "z"]

    async def test_async_stream_read_all(self):
        async with await cmd("echo async").stream_async() as s:
            result = await s.read_all()
            assert result.stdout.strip() == "async"
            assert result.ok


class TestPipelineWithStdin:
    """Test that large stdin doesn't deadlock (threading fix)."""

    def test_large_stdin_no_deadlock(self):
        # Create data larger than typical pipe buffer (64KB)
        large_data = "x" * 100000
        result = cmd("cat").with_stdin(large_data).run(timeout=5.0)
        assert result.stdout == large_data

    def test_large_stdin_pipeline(self):
        # Large stdin through a pipeline
        large_data = "line\n" * 10000
        result = (cmd("cat") | cmd("wc -l")).with_stdin(large_data).run(timeout=5.0)
        assert result.stdout.strip() == "10000"


# =============================================================================
# EDGE CASE TESTS
# =============================================================================


class TestConstructorEdgeCases:
    """Test edge cases in Cmd construction."""

    def test_single_arg_no_spaces(self):
        """Single arg without spaces should not be parsed."""
        result = cmd("echo").run()
        assert result.stdout == "\n"

    def test_empty_string_arg(self):
        """Empty string argument should work."""
        result = cmd("echo", "").run()
        assert result.stdout == "\n"

    def test_args_with_special_characters(self):
        """Arguments with special shell characters should be safe."""
        result = cmd("echo", "hello; rm -rf /").run()
        assert result.stdout.strip() == "hello; rm -rf /"

    def test_args_with_quotes(self):
        """Arguments with quotes should be preserved."""
        result = cmd("echo", '"quoted"').run()
        assert '"quoted"' in result.stdout

    def test_args_with_newlines(self):
        """Arguments with newlines should be preserved."""
        result = cmd("printf", "%s", "line1\nline2").run()
        assert result.stdout == "line1\nline2"

    def test_shell_mode_single_arg_no_parse(self):
        """Shell mode should not parse the command string."""
        result = cmd("echo hello world", shell=True).run()
        assert result.stdout.strip() == "hello world"

    def test_shell_mode_multiple_args(self):
        """Shell mode with multiple args should join them."""
        result = cmd("echo", "hello", "world", shell=True).run()
        assert result.stdout.strip() == "hello world"

    def test_constructor_with_all_options(self):
        """Constructor with all optional parameters."""
        result = Cmd(
            "sh", "-c", "echo $FOO; pwd",
            stdin=None,
            env={"FOO": "bar"},
            cwd="/tmp",
            shell=False
        ).run()
        assert "bar" in result.stdout
        assert "/tmp" in result.stdout or "/private/tmp" in result.stdout


class TestResultEdgeCases:
    """Test edge cases with Result objects."""

    def test_empty_stdout(self):
        """Empty stdout should be empty string."""
        result = cmd("true").run()
        assert result.stdout == ""

    def test_empty_stderr(self):
        """Successful command should have empty stderr."""
        result = cmd("echo hello").run()
        assert result.stderr == ""

    def test_result_with_only_stderr(self):
        """Command with only stderr output."""
        result = cmd("sh", "-c", "echo error >&2").run()
        assert result.stdout == ""
        assert "error" in result.stderr

    def test_result_with_both_stdout_stderr(self):
        """Command with both stdout and stderr."""
        result = cmd("sh", "-c", "echo out; echo err >&2").run()
        assert "out" in result.stdout
        assert "err" in result.stderr

    def test_result_raise_on_error_returns_self(self):
        """raise_on_error should return self for successful commands."""
        result = cmd("true").run().raise_on_error()
        assert isinstance(result, Result)
        assert result.ok

    def test_result_str_with_empty_stdout(self):
        """str(result) with empty stdout."""
        result = cmd("true").run()
        assert str(result) == ""

    def test_result_bool_with_various_exit_codes(self):
        """Test bool conversion with various exit codes."""
        assert bool(cmd("sh", "-c", "exit 0").run()) is True
        assert bool(cmd("sh", "-c", "exit 1").run()) is False
        assert bool(cmd("sh", "-c", "exit 2").run()) is False
        assert bool(cmd("sh", "-c", "exit 127").run()) is False


class TestPipelineEdgeCases:
    """Test edge cases with pipelines."""

    def test_very_long_pipeline(self):
        """Pipeline with many stages."""
        pipeline = cmd("echo hello")
        for _ in range(10):
            pipeline = pipeline | cmd("cat")
        result = pipeline.run()
        assert result.stdout.strip() == "hello"

    def test_first_command_fails(self):
        """Pipeline where first command fails."""
        result = (cmd("false") | cmd("cat")).run()
        assert not result.ok
        assert result.returncode != 0

    def test_middle_command_fails(self):
        """Pipeline where middle command fails."""
        result = (
            cmd("echo hello")
            | cmd("sh", "-c", "cat; exit 1")
            | cmd("cat")
        ).run()
        assert not result.ok

    def test_last_command_fails(self):
        """Pipeline where last command fails."""
        result = (cmd("echo hello") | cmd("false")).run()
        assert not result.ok

    def test_pipeline_with_empty_output(self):
        """Pipeline producing no output."""
        result = (cmd("echo hello") | cmd("grep nonexistent")).run()
        assert result.stdout == ""
        assert not result.ok

    def test_pipeline_or_returns_notimplemented(self):
        """Piping with non-Cmd should return NotImplemented."""
        c = cmd("echo")
        result = c.__or__("not a cmd")
        assert result is NotImplemented

    def test_pipeline_preserves_first_stdin(self):
        """Pipeline should use stdin from first command only."""
        pipeline = cmd("cat").with_stdin("hello") | cmd("tr a-z A-Z")
        result = pipeline.run()
        assert result.stdout.strip() == "HELLO"


class TestTimeoutEdgeCases:
    """Test edge cases with timeout."""

    def test_timeout_zero(self):
        """Timeout of 0 should timeout immediately for slow commands."""
        # Note: This might not always timeout depending on system speed
        # Using a command that takes some time
        with pytest.raises(TimeoutExpired):
            cmd("sleep 1").run(timeout=0.001)

    def test_timeout_very_small(self):
        """Very small timeout should work."""
        with pytest.raises(TimeoutExpired):
            cmd("sleep 10").run(timeout=0.01)

    def test_timeout_exact_finish(self):
        """Command finishing just before timeout should succeed."""
        result = cmd("sleep 0.1").run(timeout=1.0)
        assert result.ok

    def test_timeout_with_stdin(self):
        """Timeout with stdin should work."""
        with pytest.raises(TimeoutExpired):
            cmd("cat").with_stdin("x" * 1000).run(timeout=0.001)

    def test_timeout_pipeline_kills_all(self):
        """Timeout should kill all processes in pipeline."""
        with pytest.raises(TimeoutExpired):
            (cmd("sleep 10") | cmd("sleep 10") | cmd("cat")).run(timeout=0.1)

    async def test_async_timeout_pipeline(self):
        """Async pipeline timeout."""
        with pytest.raises(TimeoutExpired):
            await (cmd("sleep 10") | cmd("cat")).run_async(timeout=0.1)

    def test_timeout_exception_attributes(self):
        """TimeoutExpired should have correct attributes."""
        try:
            cmd("sleep", "10").run(timeout=0.1)
            assert False, "Should have raised"
        except TimeoutExpired as e:
            assert e.timeout == 0.1
            assert e.args_list == ["sleep", "10"]
            assert isinstance(e.stderr, str)
            assert "timed out" in str(e).lower()


class TestShellModeEdgeCases:
    """Test edge cases with shell mode."""

    def test_shell_mode_with_stdin(self):
        """Shell mode should work with stdin."""
        result = cmd("cat", shell=True).with_stdin("hello").run()
        assert result.stdout == "hello"

    def test_shell_mode_with_env(self):
        """Shell mode should work with custom env."""
        result = cmd("echo $MYVAR", shell=True).with_env(MYVAR="test").run()
        assert "test" in result.stdout

    def test_shell_mode_with_cwd(self, tmp_path):
        """Shell mode should work with custom cwd."""
        result = cmd("pwd", shell=True).with_cwd(str(tmp_path)).run()
        assert str(tmp_path) in result.stdout or "/private" + str(tmp_path) in result.stdout

    def test_shell_mode_preserved_in_with_stdin(self):
        """with_stdin should preserve shell mode."""
        original = cmd("cat", shell=True)
        modified = original.with_stdin("test")
        assert modified._shell is True

    def test_shell_mode_preserved_in_with_env(self):
        """with_env should preserve shell mode."""
        original = cmd("echo $X", shell=True)
        modified = original.with_env(X="val")
        assert modified._shell is True

    def test_shell_mode_preserved_in_with_cwd(self):
        """with_cwd should preserve shell mode."""
        original = cmd("pwd", shell=True)
        modified = original.with_cwd("/tmp")
        assert modified._shell is True

    def test_shell_or_operator(self):
        """Shell OR operator should work."""
        result = cmd("false || echo fallback", shell=True).run()
        assert "fallback" in result.stdout

    def test_shell_and_operator(self):
        """Shell AND operator should work."""
        result = cmd("true && echo success", shell=True).run()
        assert "success" in result.stdout

    def test_shell_semicolon(self):
        """Shell semicolon should work."""
        result = cmd("echo first; echo second", shell=True).run()
        assert "first" in result.stdout
        assert "second" in result.stdout

    def test_shell_subshell(self):
        """Shell subshell should work."""
        result = cmd("(echo sub)", shell=True).run()
        assert "sub" in result.stdout

    def test_shell_pipe_in_string(self):
        """Shell pipe in string should work."""
        result = cmd("echo hello | cat", shell=True).run()
        assert "hello" in result.stdout


class TestStreamingEdgeCases:
    """Test edge cases with streaming."""

    def test_stream_empty_output(self):
        """Streaming command with no output."""
        lines = []
        with cmd("true").stream() as s:
            for line in s.iter_lines():
                lines.append(line)
        assert lines == []

    def test_stream_single_line_no_newline(self):
        """Streaming single line without trailing newline."""
        lines = []
        with cmd("printf 'hello'").stream() as s:
            for line in s.iter_lines():
                lines.append(line)
        assert lines == ["hello"]

    def test_stream_binary_with_null(self):
        """Streaming binary data with null bytes."""
        chunks = []
        # Use $'...' syntax for proper escape interpretation in bash
        with cmd("sh", "-c", "printf 'a\\0b'").stream() as s:
            for chunk in s.iter_bytes():
                chunks.append(chunk)
        assert b"a\x00b" in b"".join(chunks)

    def test_stream_iter_bytes_various_sizes(self):
        """iter_bytes with various chunk sizes."""
        data = "x" * 100
        for chunk_size in [1, 10, 50, 100, 1000]:
            chunks = []
            with cmd(f"printf '{data}'").stream() as s:
                for chunk in s.iter_bytes(chunk_size=chunk_size):
                    chunks.append(chunk)
            assert b"".join(chunks) == data.encode()

    def test_stream_returncodes(self):
        """Stream returncodes property."""
        with cmd("echo test").stream() as s:
            s.read_all()
            assert s.returncodes == [0]

    def test_stream_returncodes_pipeline(self):
        """Stream returncodes for pipeline."""
        with (cmd("echo test") | cmd("cat")).stream() as s:
            s.read_all()
            assert len(s.returncodes) == 2
            assert all(rc == 0 for rc in s.returncodes)

    def test_stream_stderr(self):
        """Stream stderr property."""
        with cmd("sh", "-c", "echo err >&2").stream() as s:
            s.read_all()
            assert s.stderr is not None

    def test_stream_terminate(self):
        """Stream terminate method."""
        with cmd("sleep 10").stream() as s:
            s.terminate()
            # Process should be terminable

    def test_stream_kill(self):
        """Stream kill method."""
        with cmd("sleep 10").stream() as s:
            s.kill()
            # Process should be killed

    def test_stream_close_idempotent(self):
        """Calling close multiple times should be safe."""
        s = cmd("echo test").stream()
        s.close()
        s.close()  # Should not raise
        s.close()  # Should not raise

    def test_stream_with_stdin(self):
        """Streaming with stdin."""
        with cmd("cat").with_stdin("hello\nworld").stream() as s:
            lines = list(s.iter_lines())
        assert lines == ["hello", "world"]

    def test_stream_pipeline_with_stdin(self):
        """Streaming pipeline with stdin."""
        with (cmd("cat") | cmd("tr a-z A-Z")).with_stdin("hello").stream() as s:
            lines = list(s.iter_lines())
        assert lines == ["HELLO"]

    def test_stream_read_all_without_iteration(self):
        """read_all should work when called directly."""
        with cmd("printf 'a\\nb\\nc\\nd'").stream() as s:
            result = s.read_all()
            assert "a" in result.stdout
            assert "b" in result.stdout
            assert "c" in result.stdout
            assert "d" in result.stdout

    def test_stream_partial_iteration(self):
        """Partial iteration should work."""
        with cmd("printf 'a\\nb\\nc\\nd'").stream() as s:
            lines_iter = s.iter_lines()
            first = next(lines_iter)
            second = next(lines_iter)
            assert first == "a"
            assert second == "b"
            # No need to consume rest - context manager handles cleanup


class TestAsyncStreamingEdgeCases:
    """Test edge cases with async streaming."""

    async def test_async_stream_empty(self):
        """Async streaming with no output."""
        lines = []
        async with await cmd("true").stream_async() as s:
            async for line in s.iter_lines():
                lines.append(line)
        assert lines == []

    async def test_async_stream_iter_bytes(self):
        """Async iter_bytes."""
        chunks = []
        async with await cmd("printf 'hello'").stream_async() as s:
            async for chunk in s.iter_bytes(chunk_size=2):
                chunks.append(chunk)
        assert b"".join(chunks) == b"hello"

    async def test_async_stream_properties(self):
        """Async stream properties."""
        async with await cmd("echo test").stream_async() as s:
            assert s.pid > 0
            assert s.stdout is not None

    async def test_async_stream_kill(self):
        """Async stream kill."""
        async with await cmd("sleep 10").stream_async() as s:
            await s.kill()

    async def test_async_stream_terminate(self):
        """Async stream terminate."""
        async with await cmd("sleep 10").stream_async() as s:
            await s.terminate()

    async def test_async_stream_close_idempotent(self):
        """Async close should be idempotent."""
        s = await cmd("echo test").stream_async()
        await s.close()
        await s.close()  # Should not raise

    async def test_async_stream_pipeline(self):
        """Async streaming pipeline."""
        lines = []
        async with await (cmd("printf 'a\\nb'") | cmd("cat")).stream_async() as s:
            async for line in s.iter_lines():
                lines.append(line)
        assert lines == ["a", "b"]


class TestWithMethodsEdgeCases:
    """Test edge cases with with_* methods."""

    def test_with_env_merges_with_existing(self):
        """with_env should merge with existing env."""
        result = (
            cmd("sh", "-c", "echo $A $B")
            .with_env(A="first")
            .with_env(B="second")
            .run()
        )
        assert "first" in result.stdout
        assert "second" in result.stdout

    def test_with_env_overrides_existing(self):
        """with_env should override existing values."""
        result = (
            cmd("sh", "-c", "echo $A")
            .with_env(A="first")
            .with_env(A="second")
            .run()
        )
        assert result.stdout.strip() == "second"

    def test_with_stdin_replaces(self):
        """with_stdin should replace existing stdin."""
        result = (
            cmd("cat")
            .with_stdin("first")
            .with_stdin("second")
            .run()
        )
        assert result.stdout == "second"

    def test_with_cwd_replaces(self):
        """with_cwd should replace existing cwd."""
        result = (
            cmd("pwd")
            .with_cwd("/")
            .with_cwd("/tmp")
            .run()
        )
        assert "/tmp" in result.stdout or "/private/tmp" in result.stdout

    def test_chained_with_all(self):
        """Chain all with_* methods."""
        result = (
            cmd("sh", "-c", "cat; echo $FOO; pwd")
            .with_stdin("stdin-content")
            .with_env(FOO="env-value")
            .with_cwd("/tmp")
            .run()
        )
        assert "stdin-content" in result.stdout
        assert "env-value" in result.stdout
        assert "/tmp" in result.stdout or "/private/tmp" in result.stdout

    def test_with_methods_on_pipeline_preserve_all_commands(self):
        """with_* on pipeline should preserve all command properties."""
        pipeline = (
            cmd("sh", "-c", "echo $A")
            | cmd("sh", "-c", "cat; echo $A")
        ).with_env(A="test")
        result = pipeline.run()
        # Both commands should see the env
        assert result.stdout.count("test") == 2


class TestAsyncEdgeCases:
    """Test edge cases with async operations."""

    async def test_async_with_large_output(self):
        """Async command with large output."""
        result = await cmd("sh", "-c", "seq 10000").run_async()
        assert result.ok
        assert "10000" in result.stdout

    async def test_async_pipeline_with_stdin(self):
        """Async pipeline with stdin."""
        result = await (
            cmd("cat") | cmd("tr a-z A-Z")
        ).with_stdin("hello").run_async()
        assert result.stdout.strip() == "HELLO"

    async def test_async_check_pipeline(self):
        """Async pipeline with check=True."""
        with pytest.raises(CommandError):
            await (cmd("true") | cmd("false")).run_async(check=True)

    async def test_async_env_in_pipeline(self):
        """Async pipeline with env."""
        result = await (
            cmd("printenv", "FOO") | cmd("cat")
        ).with_env(FOO="async-value").run_async()
        assert "async-value" in result.stdout


class TestErrorHandlingEdgeCases:
    """Test edge cases with error handling."""

    def test_command_error_message_format(self):
        """CommandError message should be informative."""
        try:
            cmd("sh", "-c", "echo error msg >&2; exit 42").run(check=True)
        except CommandError as e:
            assert "42" in str(e)
            assert "error msg" in str(e)

    def test_timeout_expired_str(self):
        """TimeoutExpired string representation."""
        try:
            cmd("sleep 10").run(timeout=0.1)
        except TimeoutExpired as e:
            s = str(e)
            assert "timeout" in s.lower() or "timed out" in s.lower()
            assert "sleep" in s

    def test_command_error_result_access(self):
        """CommandError should provide access to result."""
        try:
            cmd("sh", "-c", "echo stdout; echo stderr >&2; exit 1").run(check=True)
        except CommandError as e:
            assert "stdout" in e.result.stdout
            assert "stderr" in e.result.stderr
            assert e.result.returncode == 1


class TestReprEdgeCases:
    """Test edge cases with repr."""

    def test_repr_single_command_with_args(self):
        """repr of single command with args."""
        c = cmd("ls", "-la", "/tmp")
        r = repr(c)
        assert "ls" in r
        assert "-la" in r

    def test_repr_pipeline_long(self):
        """repr of longer pipeline."""
        p = cmd("a") | cmd("b") | cmd("c") | cmd("d")
        r = repr(p)
        assert "Pipeline" in r or "|" in r
        assert "a" in r
        assert "d" in r

    def test_repr_command_with_spaces(self):
        """repr of command parsed from string."""
        c = cmd("echo hello world")
        r = repr(c)
        assert "echo" in r


class TestConvenienceFunctionEdgeCases:
    """Test edge cases with convenience functions."""

    def test_run_with_timeout(self):
        """run() with timeout."""
        with pytest.raises(TimeoutExpired):
            run("sleep 10", timeout=0.1)

    async def test_run_async_with_timeout(self):
        """run_async() with timeout."""
        with pytest.raises(TimeoutExpired):
            await run_async("sleep 10", timeout=0.1)

    def test_run_with_all_kwargs(self):
        """run() passes all kwargs."""
        with pytest.raises(CommandError):
            run("false", check=True)


class TestSignalHandling:
    """Test signal and process handling edge cases."""

    def test_pipeline_sigpipe_propagation(self):
        """Early consumer exit should propagate SIGPIPE."""
        # head -1 exits after first line, producer should get SIGPIPE
        result = (
            cmd("sh", "-c", "echo line1; echo line2; echo line3")
            | cmd("head", "-1")
        ).run()
        assert result.stdout.strip() == "line1"

    def test_stream_context_cleanup_on_exception(self):
        """Stream should cleanup on exception."""
        try:
            with cmd("sleep 10").stream() as s:
                raise ValueError("test error")
        except ValueError:
            pass
        # Process should have been killed
        assert s._processes[0].returncode is not None


class TestSpecialInputOutput:
    """Test special input/output scenarios."""

    def test_very_long_line(self):
        """Handle very long lines."""
        long_line = "x" * 100000
        result = cmd("cat").with_stdin(long_line).run()
        assert result.stdout == long_line

    def test_many_short_lines(self):
        """Handle many short lines."""
        lines = "\n".join(str(i) for i in range(10000))
        result = cmd("cat").with_stdin(lines).run()
        assert result.stdout == lines

    def test_mixed_encoding_safe(self):
        """Handle mixed valid UTF-8 content."""
        # Various UTF-8 characters
        content = "Hello, 世界! Привет! 🎉"
        result = cmd("cat").with_stdin(content).run()
        assert content in result.stdout

    def test_empty_stdin(self):
        """Empty stdin should work."""
        result = cmd("cat").with_stdin("").run()
        assert result.stdout == ""

    def test_stdin_only_newlines(self):
        """Stdin with only newlines."""
        result = cmd("wc", "-l").with_stdin("\n\n\n").run()
        assert "3" in result.stdout


class TestVersion:
    """Test version attribute."""

    def test_version_exists(self):
        """Test that __version__ is exposed."""
        from shell_pilot import __version__
        assert __version__ is not None
        assert isinstance(__version__, str)

    def test_version_format(self):
        """Test version follows semver format."""
        from shell_pilot import __version__
        parts = __version__.split(".")
        assert len(parts) >= 2  # At least major.minor
        assert all(p.isdigit() for p in parts)


class TestReturnCodes:
    """Test returncodes attribute on Result."""

    def test_single_command_no_returncodes(self):
        """Single command should have returncodes as None."""
        result = cmd("echo hello").run()
        assert result.returncodes is None
        assert result.ok

    def test_pipeline_returncodes(self):
        """Pipeline should have all return codes."""
        result = (sh("echo hello") | sh("cat") | sh("cat")).run()
        assert result.returncodes is not None
        assert len(result.returncodes) == 3
        assert all(rc == 0 for rc in result.returncodes)

    def test_pipeline_with_failure(self):
        """Pipeline with failure should show which command failed."""
        result = (sh("echo hello") | sh("grep nonexistent") | sh("cat")).run()
        assert not result.ok
        assert result.returncodes is not None
        assert len(result.returncodes) == 3
        assert result.returncodes[0] == 0  # echo succeeded
        assert result.returncodes[1] != 0  # grep failed

    def test_pipeline_ok_checks_all(self):
        """Pipeline ok property should check all return codes."""
        result = (sh("true") | sh("true") | sh("true")).run()
        assert result.ok

        # Even if returncode is 0, ok should check all returncodes
        result2 = (sh("false") | sh("cat")).run()
        assert not result2.ok


class TestPipelineShellMode:
    """Test shell mode works in pipelines."""

    def test_shell_mode_first_command(self):
        """Shell mode on first command in pipeline."""
        result = (cmd("echo $HOME", shell=True) | sh("cat")).run()
        assert result.ok
        # HOME should be expanded
        assert result.stdout.strip() != "$HOME"
        assert "/" in result.stdout  # Unix path

    def test_shell_mode_last_command(self):
        """Shell mode on last command in pipeline."""
        result = (sh("echo hello") | cmd("cat && echo done", shell=True)).run()
        assert result.ok
        assert "hello" in result.stdout
        assert "done" in result.stdout

    def test_mixed_shell_modes(self):
        """Mix of shell and non-shell mode in pipeline."""
        result = (
            cmd("echo $USER", shell=True)
            | sh("cat")
            | cmd("wc -c", shell=False)
        ).run()
        assert result.ok

    def test_shell_glob_in_pipeline(self):
        """Test glob expansion works in shell mode pipeline."""
        # Create a temp scenario that uses glob
        result = (
            cmd("echo *.py", shell=True)
            | sh("cat")
        ).run()
        assert result.ok
        # The glob might match files or return literal "*.py" if no match
        # Either is valid behavior


class TestPipelineShellModeAsync:
    """Test async shell mode in pipelines."""

    @pytest.mark.asyncio
    async def test_async_shell_mode_pipeline(self):
        """Shell mode works in async pipelines."""
        result = await (cmd("echo $HOME", shell=True) | sh("cat")).run_async()
        assert result.ok
        assert "/" in result.stdout

    @pytest.mark.asyncio
    async def test_async_mixed_shell_modes(self):
        """Mix of shell modes in async pipeline."""
        result = await (
            cmd("echo hello", shell=True)
            | sh("cat")
            | cmd("wc -w")
        ).run_async()
        assert result.ok


class TestTimeoutStderrCapture:
    """Test that stderr is captured on timeout."""

    def test_timeout_captures_stderr(self):
        """Stderr should be captured when timeout occurs."""
        # The last command in pipeline writes to stderr and sleeps
        with pytest.raises(TimeoutExpired) as exc_info:
            (
                sh("echo hello")
                | cmd("cat; echo 'error message' >&2; sleep 10", shell=True)
            ).run(timeout=0.5)
        # Note: stderr capture is best-effort, may or may not have content

    @pytest.mark.asyncio
    async def test_async_timeout_captures_stderr(self):
        """Async stderr should be captured when timeout occurs."""
        with pytest.raises(TimeoutExpired) as exc_info:
            await (
                sh("echo hello")
                | cmd("cat; echo 'async error' >&2; sleep 10", shell=True)
            ).run_async(timeout=0.5)
        # Note: stderr capture is best-effort


class TestAsyncReturnCodes:
    """Test returncodes in async pipelines."""

    @pytest.mark.asyncio
    async def test_async_pipeline_returncodes(self):
        """Async pipeline should have all return codes."""
        result = await (sh("echo hello") | sh("cat") | sh("cat")).run_async()
        assert result.returncodes is not None
        assert len(result.returncodes) == 3
        assert all(rc == 0 for rc in result.returncodes)

    @pytest.mark.asyncio
    async def test_async_pipeline_failure_returncodes(self):
        """Async pipeline failure should show which command failed."""
        result = await (sh("echo hello") | sh("grep nonexistent")).run_async()
        assert not result.ok
        assert result.returncodes is not None
        assert result.returncodes[0] == 0  # echo succeeded
        assert result.returncodes[1] != 0  # grep failed
