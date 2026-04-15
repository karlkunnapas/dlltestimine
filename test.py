from __future__ import annotations

import ctypes
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Interface constants from the assignment description.
SOLUTION_OK = 0
ERROR_A_IS_ZERO = 1
ERROR_NO_REAL_ROOTS = 2


@dataclass(frozen=True)
class Case:
	id: str
	category: str
	description: str
	a: float
	b: float
	c: float


@dataclass
class RunResult:
	code: int
	x1: float
	x2: float


def expected_behavior(a: float, b: float, c: float) -> tuple[int, Optional[tuple[float, float]]]:
	if a == 0.0:
		return ERROR_A_IS_ZERO, None

	d = b * b - 4.0 * a * c
	if d < 0.0:
		return ERROR_NO_REAL_ROOTS, None

	root_d = math.sqrt(d)
	x1 = (-b - root_d) / (2.0 * a)
	x2 = (-b + root_d) / (2.0 * a)
	return SOLUTION_OK, (x1, x2)


class QuadraticDll:
	def __init__(self, dll_path: Path) -> None:
		self.dll = ctypes.cdll.LoadLibrary(str(dll_path))
		self.dll.setA.restype = None
		self.dll.setA.argtypes = [ctypes.c_double]
		self.dll.setB.restype = None
		self.dll.setB.argtypes = [ctypes.c_double]
		self.dll.setC.restype = None
		self.dll.setC.argtypes = [ctypes.c_double]
		self.dll.getSolution.restype = ctypes.c_int
		self.dll.getSolution.argtypes = [ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)]

	def solve(self, a: float, b: float, c: float) -> RunResult:
		self.dll.setA(float(a))
		self.dll.setB(float(b))
		self.dll.setC(float(c))
		x1 = ctypes.c_double(float("nan"))
		x2 = ctypes.c_double(float("nan"))
		code = int(self.dll.getSolution(ctypes.byref(x1), ctypes.byref(x2)))
		return RunResult(code=code, x1=float(x1.value), x2=float(x2.value))


TEST_CASES = [
	# Equivalence classes for a.
	Case("EC-A-0", "Equivalence Class", "a is zero -> ERROR_A_IS_ZERO", 0.0, 3.0, 2.0),
	Case("EC-A-NEG", "Equivalence Class", "a negative, two real roots", -1.0, 0.0, 4.0),
	Case("EC-A-POS", "Equivalence Class", "a positive, two real roots", 1.0, 0.0, -4.0),
	# Equivalence classes for discriminant.
	Case("EC-D-NEG", "Equivalence Class", "D < 0 -> ERROR_NO_REAL_ROOTS", 1.0, 0.0, 1.0),
	Case("EC-D-ZERO", "Equivalence Class", "D = 0 -> one double root", 1.0, -2.0, 1.0),
	Case("EC-D-POS", "Equivalence Class", "D > 0 -> two roots", 2.0, -3.0, -2.0),
	# Boundary value analysis around a = 0 and discriminant boundaries.
	Case("BVA-A-NEG-EPS", "Boundary Value", "a just below zero", -1e-12, 1.0, -1.0),
	Case("BVA-A-POS-EPS", "Boundary Value", "a just above zero", 1e-12, 1.0, -1.0),
	Case("BVA-D-JUST-NEG", "Boundary Value", "D just below 0", 1.0, 2.0, 1.000000000001),
	Case("BVA-D-JUST-POS", "Boundary Value", "D just above 0", 1.0, 2.0, 0.999999999999),
	Case("BVA-B-ZERO", "Boundary Value", "b = 0 symmetric roots", 1.0, 0.0, -9.0),
	Case("BVA-C-ZERO", "Boundary Value", "c = 0, root includes x=0", 3.0, -12.0, 0.0),
	# Large magnitudes to expose numeric/overflow bugs.
	Case("ROB-LARGE", "Robustness", "large coefficients", 1e150, 2e150, -3e150),
]


def close_enough(x: float, y: float, rel: float = 1e-7, abs_tol: float = 1e-7) -> bool:
	return math.isclose(x, y, rel_tol=rel, abs_tol=abs_tol)


def roots_match(actual: RunResult, expected_roots: tuple[float, float]) -> bool:
	e1, e2 = expected_roots
	# Root order is not guaranteed by the interface.
	direct = close_enough(actual.x1, e1) and close_enough(actual.x2, e2)
	swapped = close_enough(actual.x1, e2) and close_enough(actual.x2, e1)
	return direct or swapped


def satisfies_equation(a: float, b: float, c: float, x: float, tol: float = 1e-5) -> bool:
	if math.isinf(x) or math.isnan(x):
		return False
	residual = a * x * x + b * x + c
	return abs(residual) <= tol * max(1.0, abs(a), abs(b), abs(c))


def detect_bug(case: Case, expected_code: int, expected_roots: Optional[tuple[float, float]], actual: RunResult) -> Optional[str]:
	if actual.code != expected_code:
		return (
			f"Return code mismatch. Expected {expected_code}, got {actual.code}. "
			f"Observed roots: x1={actual.x1}, x2={actual.x2}"
		)

	if expected_code == SOLUTION_OK and expected_roots is not None:
		if not roots_match(actual, expected_roots):
			return (
				"Wrong roots returned. "
				f"Expected approx {expected_roots}, got ({actual.x1}, {actual.x2})"
			)

		if not satisfies_equation(case.a, case.b, case.c, actual.x1) or not satisfies_equation(case.a, case.b, case.c, actual.x2):
			return (
				"Reported roots do not satisfy the equation within tolerance. "
				f"Got ({actual.x1}, {actual.x2})"
			)

	return None


def print_strategy_and_plan() -> None:
	print("=== Test Strategy ===")
	print("1. Verify API conformance: return codes and output roots.")
	print("2. Use Equivalence Class Partitioning for input domains of a and discriminant D.")
	print("3. Use Boundary Value Analysis near a=0 and D=0 to expose edge-case defects.")
	print("4. Repeat each case multiple times because the DLL is described as unstable.")
	print()
	print("=== Test Plan ===")
	print("- Tool: Python ctypes test harness")
	print("- Focus: functional correctness and intermittent instability")
	print("- Method: deterministic oracle in Python + repeated execution per case")
	print()


def print_test_cases() -> None:
	print("=== Test Cases ===")
	for case in TEST_CASES:
		print(
			f"{case.id:12s} | {case.category:17s} | "
			f"a={case.a: .6g}, b={case.b: .6g}, c={case.c: .6g} | {case.description}"
		)
	print()


def resolve_dll_path() -> Path:
	env_value = os.environ.get("QUADRATIC_DLL_PATH", "").strip()
	if env_value:
		return Path(env_value)

	local = Path(__file__).resolve().parent / "quadratic.dll"
	if local.exists():
		return local

	return local


def main() -> int:
	print_strategy_and_plan()
	print_test_cases()

	dll_path = resolve_dll_path()
	if not dll_path.exists():
		print("=== Test Report ===")
		print("Status: BLOCKED")
		print(f"Reason: DLL not found at '{dll_path}'.")
		print("Set QUADRATIC_DLL_PATH or place quadratic.dll next to this script.")
		return 1

	print(f"Using DLL: {dll_path}")
	try:
		solver = QuadraticDll(dll_path)
	except OSError as exc:
		print("=== Test Report ===")
		print("Status: BLOCKED")
		print("Reason: DLL could not be loaded on this environment.")
		print(f"Loader error: {exc}")
		print("On macOS, a Windows .dll typically requires a Windows runtime (VM/Wine) or a native .dylib build.")
		return 1

	repeats = 30
	bugs: list[str] = []
	executed = 0

	for case in TEST_CASES:
		expected_code, expected_roots = expected_behavior(case.a, case.b, case.c)
		for run_idx in range(1, repeats + 1):
			executed += 1
			actual = solver.solve(case.a, case.b, case.c)
			bug = detect_bug(case, expected_code, expected_roots, actual)
			if bug is not None:
				bugs.append(
					f"BUG #{len(bugs) + 1}: {case.id} (run {run_idx}/{repeats}) - {bug}"
				)

	print("=== Test Report ===")
	print(f"Executed runs: {executed}")
	print(f"Unique case count: {len(TEST_CASES)}")
	print(f"Detected bug occurrences: {len(bugs)}")

	if not bugs:
		print("No defects were observed in this run. Residual risk remains due to instability claim.")
		return 0

	print("\nDescribed Bugs:")
	for bug in bugs:
		print(f"- {bug}")

	print("\nRecommendation: Re-run tests to reproduce intermittent failures and compare frequency.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
