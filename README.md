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
from shell_pilot import sh

# Simple command
result = sh("echo hello world").run()
print(result.stdout)  # "hello world\n"

# Check success
if result.ok:
    print("Command succeeded")
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

### Stdin, Environment & Working Directory

```python
# Pass stdin
result = sh("cat").with_stdin("hello from stdin").run()

# Set environment variables
result = sh("echo $GREETING").with_env(GREETING="Hello").run()

# Change working directory
result = sh("ls").with_cwd("/tmp").run()

# Chain them
result = (
    sh("my-script")
    .with_stdin(input_data)
    .with_env(DEBUG="1")
    .with_cwd("/app")
    .run()
)
```

### Error Handling

```python
from shell_pilot import sh, CommandError

# Check the result
result = sh("might-fail").run()
if not result.ok:
    print(f"Failed: {result.stderr}")

# Or raise on failure
try:
    result = sh("must-succeed").run(check=True)
except CommandError as e:
    print(f"Command failed: {e.result.stderr}")
```

### Async Support

```python
import asyncio
from shell_pilot import sh

async def main():
    # Single async command
    result = await sh("echo async").run_async()

    # Async pipeline
    result = await (
        sh("cat largefile.txt")
        | sh("grep pattern")
        | sh("sort -u")
    ).run_async()

asyncio.run(main())
```

## API Reference

### `sh(command, stdin=None, env=None, cwd=None)`

Create a command. Strings are automatically parsed (e.g., `"ls -la"` becomes `["ls", "-la"]`).

**Methods:**
- `.run(check=False)` - Execute synchronously
- `.run_async(check=False)` - Execute asynchronously
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

## License

MIT
