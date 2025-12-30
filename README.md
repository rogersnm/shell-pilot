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
from shell_pilot import sh
result = (sh("ls -la") | sh("grep foo") | sh("wc -l")).run()
```

## Installation

```bash
pip install shell-pilot
```

## Usage

### Basic Commands

```python
from shell_pilot import cmd, sh, run

# Simple command execution
result = cmd("echo", "hello", "world").run()
print(result.stdout)  # "hello world\n"

# Shell-style string parsing (auto-splits on spaces)
result = sh("ls -la").run()

# Quick one-liner
output = run("uname -s").stdout
```

### Piping with `|`

Chain commands together just like in bash:

```python
# Two-stage pipe
result = (sh("cat /etc/hosts") | sh("grep localhost")).run()

# Multi-stage pipe
result = (
    sh("ps aux")
    | sh("grep python")
    | sh("grep -v grep")
    | sh("wc -l")
).run()
print(f"Python processes: {result.stdout.strip()}")
```

### Handling Input/Output

```python
# Pass stdin to a command
result = cmd("cat").with_stdin("hello from stdin").run()

# Check if command succeeded
if result.ok:
    print(result.stdout)
else:
    print(f"Error: {result.stderr}")

# Use result as boolean
if run("which python3"):
    print("Python 3 is installed")
```

### Environment Variables & Working Directory

```python
# Set environment variables
result = (
    cmd("sh", "-c", "echo $GREETING $NAME")
    .with_env(GREETING="Hello", NAME="World")
    .run()
)

# Change working directory
result = cmd("ls").with_cwd("/tmp").run()
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
from shell_pilot import cmd, sh, run_async

async def main():
    # Single async command
    result = await cmd("sleep 1 && echo done").run_async()

    # Async pipeline
    result = await (
        sh("cat largefile.txt")
        | sh("grep pattern")
        | sh("sort -u")
    ).run_async()

    # Quick async one-liner
    result = await run_async("curl -s https://api.example.com")

asyncio.run(main())
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

## API Reference

### `Cmd` / `cmd` / `sh`

The main class for building commands. `cmd` and `sh` are convenient aliases.

```python
Cmd(*args, stdin=None, env=None, cwd=None)
```

**Methods:**
- `.run(check=False)` - Execute synchronously, return `Result`
- `.run_async(check=False)` - Execute asynchronously, return `Result`
- `.with_stdin(text)` - Return new Cmd with stdin
- `.with_env(**vars)` - Return new Cmd with additional env vars
- `.with_cwd(path)` - Return new Cmd with working directory
- `|` operator - Pipe to another command

### `Result`

Returned by `.run()` and `.run_async()`.

**Attributes:**
- `.stdout` - Standard output as string
- `.stderr` - Standard error as string
- `.returncode` - Exit code
- `.ok` - `True` if returncode is 0

**Methods:**
- `.raise_on_error()` - Raise `CommandError` if failed, otherwise return self
- `bool(result)` - Returns `.ok`
- `str(result)` - Returns `.stdout`

### `CommandError`

Exception raised when a command fails (with `check=True`).

```python
try:
    cmd("failing-command").run(check=True)
except CommandError as e:
    print(e.result.stderr)
    print(e.result.returncode)
```

### Convenience Functions

```python
run(command, **kwargs) -> Result      # Quick sync execution
run_async(command, **kwargs) -> Result  # Quick async execution
```

## License

MIT
