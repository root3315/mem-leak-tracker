# mem-leak-tracker

Lightweight tool to track and find memory leaks in running processes.

## Why I Built This

Ever had a process slowly eating up RAM over hours and you had no idea which one? Or you're debugging a service that keeps getting OOM-killed in production? This tool watches processes over time and flags ones with suspicious memory growth patterns.

It's not a full profiler - just a quick way to spot which process is probably leaking.

## Quick Start

```bash
pip install -r requirements.txt
python mem_leak_tracker.py
```

That's it. It'll monitor all processes and print status every 10 snapshots. Hit Ctrl+C when done and it'll dump a JSON report.

## Usage

### Monitor everything
```bash
python mem_leak_tracker.py
```

### Monitor specific PIDs
```bash
python mem_leak_tracker.py -p 1234 5678
```

### Run for a fixed duration
```bash
python mem_leak_tracker.py -d 300
```

### Adjust sensitivity
```bash
# Flag processes growing more than 20MB
python mem_leak_tracker.py -t 20

# Sample every second instead of default 2s
python mem_leak_tracker.py -i 1.0
```

### Verbose output
```bash
python mem_leak_tracker.py -v
```

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-p, --pids` | Specific PIDs to monitor | All processes |
| `-d, --duration` | Run time in seconds | Until Ctrl+C |
| `-i, --interval` | Snapshot interval (seconds) | 2.0 |
| `-t, --threshold` | Growth threshold in MB | 50 |
| `-o, --output` | Report output directory | Current dir |
| `-v, --verbose` | Show leak details | Off |

## How It Works

1. Takes memory snapshots (RSS, VMS, %) at regular intervals
2. Tracks growth patterns over consecutive snapshots
3. Flags a process as a "leak suspect" if:
   - Memory grows consistently across 3+ snapshots, AND
   - Total growth exceeds the threshold (default 50MB)
4. Calculates growth rate in MB/second for ranking

## Output

JSON report includes:
- All monitored processes with current/baseline memory
- Growth rates and leak detection status
- Sorted list of suspects (highest growth rate first)

Report file: `mem_leak_report_<timestamp>.json`

## Limitations

- Needs read access to `/proc/<pid>/` - may miss some processes without root
- Short-lived processes might not be caught
- Doesn't distinguish between legitimate growth and actual leaks
- RSS can fluctuate due to GC, allocator behavior, etc.

Treat findings as hints, not proof.

## Requirements

- Python 3.7+
- psutil

## License

MIT
