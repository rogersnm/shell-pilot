# shell-pilot

A more ergonomic subprocess alternative for Python with bash-like pipe syntax.

## Why?

Python's `subprocess` module is powerful but verbose. Compare:

```python
# subprocess (the pain)
import subprocess
p1 = subprocess.Popen(['ls', '-la'], stdout=subprocess.PIPE)
p2 = subprocess.Popen(['grep', 'foo'], stdin=p1.stdout, stdout=subprocess.PIPE)
p3 = subprocess.Popen(['wc', '-l'], stdin=p2.stdout, stdout=subprocess.PIPE)
p1.stdout.close()
p2.stdout.close()
output = p3.communicate()[0]

# shell-pilot (the joy)
from shell_pilot import cmd
result = (cmd("ls -la") | cmd("grep foo") | cmd("wc -l")).run()
```

## Installation

```bash
pip install shell-pilot
```

```python
# Note: Import uses underscore (Python convention)
from shell_pilot import cmd
```

## Usage

### Basic Commands

```python
from shell_pilot import cmd

# Simple command
result = cmd("echo hello world").run()
print(result.stdout)  # "hello world\n"

# Check success
if result.ok:
    print("Command succeeded")
```

### Piping with `|`

Chain commands together just like in bash:

```python
# Two-stage pipe
result = (cmd("cat /etc/hosts") | cmd("grep localhost")).run()

# Multi-stage pipe
result = (
    cmd("ps aux")
    | cmd("grep python")
    | cmd("grep -v grep")
    | cmd("wc -l")
).run()
print(f"Python processes: {result.stdout.strip()}")
```

### Stdin, Environment & Working Directory

```python
# Pass stdin
result = cmd("cat").with_stdin("hello from stdin").run()

# Set environment variables
result = cmd("echo $GREETING").with_env(GREETING="Hello").run()

# Change working directory
result = cmd("ls").with_cwd("/tmp").run()
```

### Fluent API

All configuration methods return new instances, allowing fluent chaining:

```python
result = (
    cmd("my-script")
    .with_stdin(input_data)
    .with_env(DEBUG="1", LOG_LEVEL="info")
    .with_cwd("/app")
    .run(check=True)
)
```

### Timeouts

Prevent commands from hanging indefinitely:

```python
from shell_pilot import cmd, TimeoutExpired

try:
    result = cmd("long-running-command").run(timeout=30.0)
except TimeoutExpired as e:
    print(f"Command timed out after {e.timeout}s")

# Also works with pipelines and async
result = (cmd("producer") | cmd("consumer")).run(timeout=10.0)
result = await cmd("async-command").run_async(timeout=5.0)
```

### Shell Mode

Use shell features like glob expansion and environment variable substitution:

```python
# Glob expansion
result = cmd("ls *.py", shell=True).run()

# Environment variable expansion
result = cmd("echo $HOME", shell=True).run()

# Shell operators
result = cmd("cmd1 && cmd2 || cmd3", shell=True).run()
```

> **Security Warning:** Using `shell=True` with untrusted input creates command injection vulnerabilities. Never pass user-provided strings directly to shell mode. For pipelines, prefer the `|` operator which is both safer and more Pythonic.

### Streaming

Process output incrementally without loading everything into memory:

```python
# Line-by-line streaming
with cmd("tail -f /var/log/syslog").stream() as s:
    for line in s.iter_lines():
        print(f"Got: {line}")
        if "error" in line:
            break  # Process terminates automatically

# Byte-level streaming
with cmd("cat /dev/urandom").stream() as s:
    for chunk in s.iter_bytes(chunk_size=4096):
        process_binary(chunk)
        if done:
            break

# Pipeline streaming
with (cmd("producer") | cmd("filter")).stream() as s:
    for line in s.iter_lines():
        handle(line)

# Async streaming
async with await cmd("async-producer").stream_async() as s:
    async for line in s.iter_lines():
        await handle(line)
```

### Error Handling

```python
from shell_pilot import cmd, CommandError

# Option 1: Check the result
result = cmd("might-fail").run()
if not result.ok:
    print(f"Failed with code {result.returncode}: {result.stderr}")

# Option 2: Raise on failure
try:
    result = cmd("must-succeed").run(check=True)
except CommandError as e:
    print(f"Command failed: {e.result.stderr}")

# Option 3: Chain raise_on_error()
result = cmd("risky-command").run().raise_on_error()
```

### Async Support

```python
import asyncio
from shell_pilot import cmd

async def main():
    # Single async command
    result = await cmd("echo async").run_async()

    # Async pipeline (runs concurrently!)
    result = await (
        cmd("cat largefile.txt")
        | cmd("grep pattern")
        | cmd("sort -u")
    ).run_async()

    # With timeout
    result = await cmd("slow-command").run_async(timeout=10.0)

asyncio.run(main())
```

## API Reference

### `cmd(command, stdin=None, env=None, cwd=None, shell=False)`

Create a command. Strings are automatically parsed (e.g., `"ls -la"` becomes `["ls", "-la"]`).

**Methods:**
- `.run(check=False, timeout=None)` - Execute synchronously
- `.run_async(check=False, timeout=None)` - Execute asynchronously
- `.stream()` - Start command and return Stream for incremental reading
- `.stream_async()` - Start command and return AsyncStream
- `.with_stdin(text)` - Set stdin input
- `.with_env(**vars)` - Add environment variables
- `.with_cwd(path)` - Set working directory
- `|` - Pipe to another command

### `Result`

**Attributes:**
- `.stdout` - Standard output as string
- `.stderr` - Standard error as string
- `.returncode` - Exit code
- `.ok` - `True` if returncode is 0

**Methods:**
- `.raise_on_error()` - Raise `CommandError` if failed, returns self for chaining
- `bool(result)` - Returns `.ok`
- `str(result)` - Returns `.stdout`

### `Stream` / `AsyncStream`

**Properties:**
- `.stdout` - Raw stdout file object (for select/poll)
- `.stderr` - Raw stderr file object
- `.pid` - PID of last process in pipeline
- `.returncodes` - List of return codes (None if still running)

**Methods:**
- `.iter_bytes(chunk_size=8192)` - Iterate over byte chunks
- `.iter_lines(encoding="utf-8")` - Iterate over lines
- `.read_all(timeout=None)` - Read remaining output as Result
- `.kill()` / `.terminate()` - Signal all processes
- `.close()` - Clean up resources

### Exceptions

- `CommandError` - Raised when command fails (with `check=True`)
- `TimeoutExpired` - Raised when command exceeds timeout

### Convenience Functions

```python
from shell_pilot import run, run_async

result = run("ls -la")                # Quick sync execution
result = await run_async("ls -la")    # Quick async execution
```

## License

MIT
