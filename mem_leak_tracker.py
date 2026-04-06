#!/usr/bin/env python3
"""
Memory Leak Tracker - Monitor processes for potential memory leaks
by tracking memory usage patterns over time.
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:
    logging.error("psutil library required. Install with: pip install -r requirements.txt")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class MemorySnapshot:
    """Represents a single memory measurement for a process."""

    def __init__(self, pid, rss, vms, memory_percent, timestamp):
        self.pid = pid
        self.rss = rss
        self.vms = vms
        self.memory_percent = memory_percent
        self.timestamp = timestamp

    def to_dict(self):
        return {
            "pid": self.pid,
            "rss_bytes": self.rss,
            "vms_bytes": self.vms,
            "memory_percent": self.memory_percent,
            "timestamp": self.timestamp,
        }


class ProcessMonitor:
    """Tracks memory usage for a single process over time."""

    def __init__(self, pid, threshold_mb=50, growth_rate_threshold=0.1):
        self.pid = pid
        self.threshold_mb = threshold_mb
        self.growth_rate_threshold = growth_rate_threshold
        self.snapshots = []
        self.baseline_rss = None
        self.leak_detected = False
        self.leak_start_time = None

    def add_snapshot(self, snapshot):
        self.snapshots.append(snapshot)
        if self.baseline_rss is None:
            self.baseline_rss = snapshot.rss

        if len(self.snapshots) >= 3:
            self._analyze_leak_pattern()

    def _analyze_leak_pattern(self):
        if len(self.snapshots) < 3:
            return

        recent = self.snapshots[-3:]
        rss_values = [s.rss for s in recent]

        if rss_values[0] < rss_values[1] < rss_values[2]:
            growth_amount = rss_values[2] - rss_values[0]
            growth_mb = growth_amount / (1024 * 1024)

            if growth_mb > self.threshold_mb:
                self.leak_detected = True
                if self.leak_start_time is None:
                    self.leak_start_time = recent[0].timestamp

    def get_growth_rate(self):
        if len(self.snapshots) < 2:
            return 0.0

        time_span = self.snapshots[-1].timestamp - self.snapshots[0].timestamp
        if time_span <= 0:
            return 0.0

        memory_growth = self.snapshots[-1].rss - self.snapshots[0].rss
        growth_rate_mb_per_sec = (memory_growth / (1024 * 1024)) / time_span
        return growth_rate_mb_per_sec

    def get_summary(self):
        if not self.snapshots:
            return None

        latest = self.snapshots[-1]
        process_info = self._get_process_info()

        return {
            "pid": self.pid,
            "name": process_info.get("name", "unknown"),
            "cmdline": process_info.get("cmdline", ""),
            "current_rss_mb": latest.rss / (1024 * 1024),
            "current_vms_mb": latest.vms / (1024 * 1024),
            "memory_percent": latest.memory_percent,
            "baseline_rss_mb": self.baseline_rss / (1024 * 1024) if self.baseline_rss else 0,
            "total_growth_mb": (latest.rss - self.baseline_rss) / (1024 * 1024) if self.baseline_rss else 0,
            "growth_rate_mb_per_sec": self.get_growth_rate(),
            "leak_detected": self.leak_detected,
            "snapshots_count": len(self.snapshots),
        }

    def _get_process_info(self):
        try:
            proc = psutil.Process(self.pid)
            return {
                "name": proc.name(),
                "cmdline": " ".join(proc.cmdline()) if proc.cmdline() else "",
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return {"name": "unknown", "cmdline": ""}


class MemoryLeakTracker:
    """Main tracker that monitors multiple processes for memory leaks."""

    def __init__(self, output_dir=None, interval=2.0, threshold_mb=50, growth_rate_threshold=0.1):
        self.output_dir = Path(output_dir) if output_dir else Path.cwd()
        self.interval = interval
        self.threshold_mb = threshold_mb
        self.growth_rate_threshold = growth_rate_threshold
        self.monitors = {}
        self.running = False
        self.start_time = None
        self.report_file = None

    def track_pid(self, pid):
        if pid not in self.monitors:
            self.monitors[pid] = ProcessMonitor(
                pid,
                threshold_mb=self.threshold_mb,
                growth_rate_threshold=self.growth_rate_threshold,
            )
        return self.monitors[pid]

    def track_all_processes(self):
        for proc in psutil.process_iter(["pid"]):
            try:
                self.track_pid(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def take_snapshot(self):
        timestamp = time.time()
        removed_pids = []

        for pid, monitor in self.monitors.items():
            try:
                proc = psutil.Process(pid)
                mem_info = proc.memory_info()
                mem_percent = proc.memory_percent()

                snapshot = MemorySnapshot(
                    pid=pid,
                    rss=mem_info.rss,
                    vms=mem_info.vms,
                    memory_percent=mem_percent,
                    timestamp=timestamp,
                )
                monitor.add_snapshot(snapshot)

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                removed_pids.append(pid)

        for pid in removed_pids:
            del self.monitors[pid]

        return len(self.monitors)

    def get_leak_suspects(self):
        suspects = []
        for pid, monitor in self.monitors.items():
            summary = monitor.get_summary()
            if summary and (
                summary["leak_detected"]
                or summary["growth_rate_mb_per_sec"] > self.growth_rate_threshold
            ):
                suspects.append(summary)

        suspects.sort(key=lambda x: x["growth_rate_mb_per_sec"], reverse=True)
        return suspects

    def print_status(self, verbose=False):
        active = len([m for m in self.monitors.values() if m.snapshots])
        leaks = len(self.get_leak_suspects())

        elapsed = time.time() - self.start_time if self.start_time else 0
        logger.info(
            "Tracking %d processes | Elapsed: %.0fs | Potential leaks: %d",
            active, elapsed, leaks
        )

        if verbose and leaks > 0:
            logger.info("--- Leak Suspects ---")
            for suspect in self.get_leak_suspects()[:5]:
                logger.info(
                    "  PID %d: %s | RSS: %.1fMB | Growth: %.2fMB/s",
                    suspect["pid"], suspect["name"],
                    suspect["current_rss_mb"], suspect["growth_rate_mb_per_sec"]
                )

    def save_report(self):
        report = {
            "start_time": datetime.fromtimestamp(self.start_time).isoformat() if self.start_time else None,
            "end_time": datetime.now().isoformat(),
            "duration_seconds": time.time() - self.start_time if self.start_time else 0,
            "threshold_mb": self.threshold_mb,
            "growth_rate_threshold_mb_per_sec": self.growth_rate_threshold,
            "interval_seconds": self.interval,
            "suspects": self.get_leak_suspects(),
            "all_processes": [
                m.get_summary() for m in self.monitors.values() if m.get_summary()
            ],
        }

        report_path = self.output_dir / f"mem_leak_report_{int(time.time())}.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        self.report_file = report_path
        return report_path

    def run(self, duration=None, pids=None, verbose=False):
        self.start_time = time.time()
        self.running = True

        if pids:
            for pid in pids:
                self.track_pid(pid)
        else:
            self.track_all_processes()

        logger.info("Memory Leak Tracker started")
        logger.info(
            "Threshold: %dMB | Growth rate threshold: %.2fMB/s | Interval: %.1fs",
            self.threshold_mb, self.growth_rate_threshold, self.interval,
        )
        if duration:
            logger.info("Duration: %ds (Ctrl+C to stop early)", duration)
        else:
            logger.info("Running until interrupted (Ctrl+C)")

        iterations = 0
        try:
            while self.running:
                self.take_snapshot()
                iterations += 1

                if iterations % 5 == 0:
                    self.print_status(verbose)

                if duration and (time.time() - self.start_time) >= duration:
                    break

                time.sleep(self.interval)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")

        finally:
            self.running = False
            self.print_status(verbose=True)
            report_path = self.save_report()
            logger.info("Report saved to: %s", report_path)

            suspects = self.get_leak_suspects()
            if suspects:
                logger.warning("Found %d potential memory leak(s)", len(suspects))
                for s in suspects[:10]:
                    logger.warning(
                        "  - PID %d (%s): %.2fMB/s growth",
                        s["pid"], s["name"], s["growth_rate_mb_per_sec"]
                    )
            else:
                logger.info("No obvious memory leaks detected")


def signal_handler(tracker, signum, frame):
    tracker.running = False


def main():
    parser = argparse.ArgumentParser(
        description="Track and find memory leaks in running processes"
    )
    parser.add_argument(
        "-p", "--pids",
        type=int,
        nargs="+",
        help="Specific PIDs to monitor (default: all processes)"
    )
    parser.add_argument(
        "-d", "--duration",
        type=int,
        help="Monitoring duration in seconds (default: run until interrupted)"
    )
    parser.add_argument(
        "-i", "--interval",
        type=float,
        default=2.0,
        help="Snapshot interval in seconds (default: 2.0)"
    )
    parser.add_argument(
        "-t", "--threshold",
        type=float,
        default=50,
        help="Memory growth threshold in MB to flag as leak (default: 50)"
    )
    parser.add_argument(
        "-r", "--growth-rate",
        type=float,
        default=0.1,
        help="Growth rate threshold in MB/s to flag as leak (default: 0.1)"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        help="Output directory for reports (default: current directory)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed leak suspect information"
    )

    args = parser.parse_args()

    tracker = MemoryLeakTracker(
        output_dir=args.output,
        interval=args.interval,
        threshold_mb=args.threshold,
        growth_rate_threshold=args.growth_rate,
    )

    signal.signal(signal.SIGINT, lambda s, f: signal_handler(tracker, s, f))
    signal.signal(signal.SIGTERM, lambda s, f: signal_handler(tracker, s, f))

    tracker.run(
        duration=args.duration,
        pids=args.pids,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
