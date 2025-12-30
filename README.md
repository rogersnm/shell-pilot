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

    # Async pipeline
    result = await (
        cmd("cat largefile.txt")
        | cmd("grep pattern")
        | cmd("sort -u")
    ).run_async()

asyncio.run(main())
```

## API Reference

### `cmd(command, stdin=None, env=None, cwd=None)`

Create a command. Strings are automatically parsed (e.g., `"ls -la"` becomes `["ls", "-la"]`).

**Methods:**
- `.run(check=False)` - Execute synchronously
- `.run_async(check=False)` - Execute asynchronously
- `.with_stdin(text)` - Set stdin input
- `.with_env(**vars)` - Add environment variables
- `.with_cwd(path)` - Set working directory
- `.raise_on_error()` - Raise `CommandError` if failed
- `|` - Pipe to another command

### `Result`

**Attributes:**
- `.stdout` - Standard output as string
- `.stderr` - Standard error as string
- `.returncode` - Exit code
- `.ok` - `True` if returncode is 0

### Convenience Functions

```python
from shell_pilot import run, run_async

result = run("ls -la")                # Quick sync execution
result = await run_async("ls -la")    # Quick async execution
```

## License

MIT
