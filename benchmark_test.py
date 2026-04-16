"""
Performance Test for quadratic.dll
====================================
Runs for 30 minutes and periodically logs:
  - CPU usage (process + system-wide)
  - RAM usage (process RSS + system-wide used)
  - DLL call throughput (calls/sec in last interval)
  - Per-call latency stats (min / avg / max over last interval)
  - Cumulative error codes returned by getSolution

Results are written to:
  performance_results2.csv   - machine-readable, one row per sample
  performance_results2.txt   - human-readable summary + final report

Requirements:
  pip install psutil
"""

import csv
import os
import statistics
import subprocess
import sys
import threading
import time
from ctypes import POINTER, byref, c_double, c_int, cdll
from datetime import datetime

try:
	import psutil
except ImportError:
	print("psutil is not installed. Installing now...")
	subprocess.check_call([sys.executable, "-m", "pip", "install", "psutil"])
	import psutil

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TEST_DURATION_SECONDS = 30 * 60
SAMPLE_INTERVAL_SECONDS = 10
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DLL_PATH = os.path.join(SCRIPT_DIR, "quadratic.dll")
CSV_OUT = os.path.join(SCRIPT_DIR, "performance_results2.csv")
TXT_OUT = os.path.join(SCRIPT_DIR, "performance_results2.txt")

# ---------------------------------------------------------------------------
# Input sets used to exercise the DLL continuously
# Each tuple is (a, b, c); covers all three result codes
# ---------------------------------------------------------------------------
INPUTS = [
	# Two real roots
	(1.0, -3.0, 2.0),
	(-1.0, 3.0, -2.0),
	(2.0, 4.0, 0.0),
	(1.0, 0.0, -4.0),
	(1.5, -3.5, 2.0),
	(1000.0, 3000.0, 2000.0),
	# One real root (discriminant = 0)
	(1.0, -4.0, 4.0),
	(1.0, 2.0, 1.0),
	(1.0, 0.0, 0.0),
	(0.5, -2.0, 2.0),
	# No real roots
	(1.0, 2.0, 5.0),
	(-1.0, 2.0, -5.0),
	(1.0, 0.0, 4.0),
	(2.5, 1.5, 3.2),
	# a = 0 (error case)
	(0.0, 2.0, 4.0),
	(0.0, 0.0, 5.0),
]

# ---------------------------------------------------------------------------
# Load DLL
# ---------------------------------------------------------------------------
if not os.path.exists(DLL_PATH):
	print(f"ERROR: quadratic.dll not found at {DLL_PATH}")
	sys.exit(1)

mydll = cdll.LoadLibrary(DLL_PATH)
mydll.setA.restype = None
mydll.setA.argtypes = [c_double]
mydll.setB.restype = None
mydll.setB.argtypes = [c_double]
mydll.setC.restype = None
mydll.setC.argtypes = [c_double]
mydll.getSolution.argtypes = [POINTER(c_double), POINTER(c_double)]
mydll.getSolution.restype = c_int

SOLUTION_OK = 0
ERROR_A_IS_ZERO = 1
ERROR_NO_REAL_ROOTS = 2

# ---------------------------------------------------------------------------
# Shared state (updated by worker thread, read by sampler)
# ---------------------------------------------------------------------------
lock = threading.Lock()
interval_calls = 0
interval_latencies = []
total_calls = 0
error_counts = {
	SOLUTION_OK: 0,
	ERROR_A_IS_ZERO: 0,
	ERROR_NO_REAL_ROOTS: 0,
	"other": 0,
}
stop_event = threading.Event()


# ---------------------------------------------------------------------------
# Worker: calls the DLL as fast as possible until stop_event is set
# ---------------------------------------------------------------------------
def worker():
	global interval_calls, interval_latencies, total_calls, error_counts

	idx = 0
	x1 = c_double(0.0)
	x2 = c_double(0.0)

	while not stop_event.is_set():
		a, b, c = INPUTS[idx % len(INPUTS)]
		idx += 1

		t0 = time.perf_counter()
		try:
			mydll.setA(a)
			mydll.setB(b)
			mydll.setC(c)
			ret = mydll.getSolution(byref(x1), byref(x2))
		except Exception:
			ret = -1
		elapsed = time.perf_counter() - t0

		with lock:
			interval_calls += 1
			interval_latencies.append(elapsed)
			total_calls += 1
			if ret in error_counts:
				error_counts[ret] += 1
			else:
				error_counts["other"] += 1


# ---------------------------------------------------------------------------
# Main: sample loop
# ---------------------------------------------------------------------------
def main():
	global interval_calls, interval_latencies, total_calls

	process = psutil.Process(os.getpid())
	start_time = time.time()
	end_time = start_time + TEST_DURATION_SECONDS
	run_start_dt = datetime.now()

	print(f"Performance test started at {run_start_dt.strftime('%Y-%m-%d %H:%M:%S')}")
	print(
		f"Duration: {TEST_DURATION_SECONDS // 60} minutes  |  "
		f"Sample interval: {SAMPLE_INTERVAL_SECONDS}s"
	)
	print(f"Results will be written to:\n  {CSV_OUT}\n  {TXT_OUT}\n")

	t = threading.Thread(target=worker, daemon=True)
	t.start()

	samples = []

	csv_file = open(CSV_OUT, "w", newline="")
	csv_writer = csv.writer(csv_file)
	csv_writer.writerow(
		[
			"elapsed_s",
			"timestamp",
			"proc_cpu_pct",
			"sys_cpu_pct",
			"proc_ram_mb",
			"sys_ram_used_mb",
			"sys_ram_pct",
			"calls_in_interval",
			"calls_per_sec",
			"latency_min_us",
			"latency_avg_us",
			"latency_max_us",
			"total_calls",
		]
	)

	txt_lines = []
	header = (
		f"Quadratic DLL - Performance Test\n"
		f"Started : {run_start_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
		f"Duration: {TEST_DURATION_SECONDS // 60} min, sample every {SAMPLE_INTERVAL_SECONDS}s\n"
		f"{'=' * 80}\n"
	)
	txt_lines.append(header)
	print(header, end="")

	col_hdr = (
		f"{'Elapsed':>8}  {'ProcCPU%':>9}  {'SysCPU%':>8}  "
		f"{'ProcRAM MB':>11}  {'SysRAM%':>8}  "
		f"{'Calls/s':>9}  {'AvgLat us':>10}  {'MaxLat us':>10}  {'TotalCalls':>12}"
	)
	txt_lines.append(col_hdr)
	print(col_hdr)

	process.cpu_percent(interval=None)
	psutil.cpu_percent(interval=None)
	time.sleep(SAMPLE_INTERVAL_SECONDS)

	while time.time() < end_time:
		elapsed = time.time() - start_time

		with lock:
			calls = interval_calls
			latencies = interval_latencies[:]
			interval_calls = 0
			interval_latencies.clear()
			current_total_calls = total_calls

		proc_cpu = process.cpu_percent(interval=None)
		sys_cpu = psutil.cpu_percent(interval=None)
		mem_info = process.memory_info()
		proc_ram = mem_info.rss / (1024**2)
		sys_mem = psutil.virtual_memory()
		sys_ram = sys_mem.used / (1024**2)
		sys_ram_p = sys_mem.percent

		calls_per_sec = calls / SAMPLE_INTERVAL_SECONDS if calls > 0 else 0
		lat_min = lat_avg = lat_max = 0.0
		if latencies:
			lat_min = min(latencies) * 1e6
			lat_avg = statistics.mean(latencies) * 1e6
			lat_max = max(latencies) * 1e6

		ts = datetime.now().strftime("%H:%M:%S")

		csv_writer.writerow(
			[
				f"{elapsed:.1f}",
				ts,
				f"{proc_cpu:.1f}",
				f"{sys_cpu:.1f}",
				f"{proc_ram:.2f}",
				f"{sys_ram:.2f}",
				f"{sys_ram_p:.1f}",
				calls,
				f"{calls_per_sec:.1f}",
				f"{lat_min:.2f}",
				f"{lat_avg:.2f}",
				f"{lat_max:.2f}",
				current_total_calls,
			]
		)
		csv_file.flush()

		row = (
			f"{elapsed:>7.0f}s  {proc_cpu:>8.1f}%  {sys_cpu:>7.1f}%  "
			f"{proc_ram:>10.2f}  {sys_ram_p:>7.1f}%  "
			f"{calls_per_sec:>9.1f}  {lat_avg:>10.2f}  "
			f"{lat_max:>10.2f}  {current_total_calls:>12,}"
		)
		txt_lines.append(row)
		print(row)

		samples.append(
			{
				"elapsed_s": elapsed,
				"proc_cpu": proc_cpu,
				"sys_cpu": sys_cpu,
				"proc_ram": proc_ram,
				"sys_ram_pct": sys_ram_p,
				"calls_per_sec": calls_per_sec,
				"lat_avg": lat_avg,
				"lat_max": lat_max,
			}
		)

		next_sample = start_time + (len(samples) + 1) * SAMPLE_INTERVAL_SECONDS
		sleep_for = max(0.0, next_sample - time.time())
		stop_event.wait(timeout=sleep_for)

	stop_event.set()
	t.join(timeout=5)
	csv_file.close()

	run_end_dt = datetime.now()
	actual_duration = run_end_dt - run_start_dt

	if samples:
		avg_proc_cpu = statistics.mean(s["proc_cpu"] for s in samples)
		peak_proc_cpu = max(s["proc_cpu"] for s in samples)
		avg_sys_cpu = statistics.mean(s["sys_cpu"] for s in samples)
		peak_sys_cpu = max(s["sys_cpu"] for s in samples)
		avg_ram = statistics.mean(s["proc_ram"] for s in samples)
		peak_ram = max(s["proc_ram"] for s in samples)
		avg_cps = statistics.mean(s["calls_per_sec"] for s in samples)
		peak_cps = max(s["calls_per_sec"] for s in samples)
		latency_samples = [s["lat_avg"] for s in samples if s["lat_avg"] > 0]
		avg_lat = statistics.mean(latency_samples) if latency_samples else 0
		peak_lat = max(s["lat_max"] for s in samples)
	else:
		avg_proc_cpu = peak_proc_cpu = avg_sys_cpu = peak_sys_cpu = 0
		avg_ram = peak_ram = avg_cps = peak_cps = avg_lat = peak_lat = 0

	summary = (
		f"\n{'=' * 80}\n"
		f"FINAL SUMMARY\n"
		f"{'=' * 80}\n"
		f"Test ended  : {run_end_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
		f"Actual run  : {str(actual_duration).split('.')[0]}\n"
		f"Total DLL calls  : {total_calls:,}\n"
		f"\n"
		f"--- CPU ---\n"
		f"  Process avg / peak : {avg_proc_cpu:.1f}% / {peak_proc_cpu:.1f}%\n"
		f"  System  avg / peak : {avg_sys_cpu:.1f}% / {peak_sys_cpu:.1f}%\n"
		f"\n"
		f"--- RAM (process) ---\n"
		f"  avg / peak         : {avg_ram:.2f} MB / {peak_ram:.2f} MB\n"
		f"\n"
		f"--- Throughput ---\n"
		f"  avg / peak calls/s : {avg_cps:.1f} / {peak_cps:.1f}\n"
		f"\n"
		f"--- Latency per DLL call sequence (setA+setB+setC+getSolution) ---\n"
		f"  avg latency        : {avg_lat:.2f} us\n"
		f"  worst-case latency : {peak_lat:.2f} us\n"
		f"\n"
		f"--- Return code distribution ---\n"
		f"  SOLUTION_OK        : {error_counts[SOLUTION_OK]:,}\n"
		f"  ERROR_A_IS_ZERO    : {error_counts[ERROR_A_IS_ZERO]:,}\n"
		f"  ERROR_NO_REAL_ROOTS: {error_counts[ERROR_NO_REAL_ROOTS]:,}\n"
		f"  Unexpected / crash : {error_counts['other']:,}\n"
		f"{'=' * 80}\n"
	)
	print(summary)
	txt_lines.append(summary)

	with open(TXT_OUT, "w", encoding="utf-8") as f:
		f.write("\n".join(txt_lines))

	print(f"\nDone. Results saved to:\n  {CSV_OUT}\n  {TXT_OUT}")


if __name__ == "__main__":
	main()
