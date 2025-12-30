"""Tests for shell-pilot."""

import pytest
from shell_pilot import Cmd, cmd, sh, run, run_async, Result, CommandError


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
