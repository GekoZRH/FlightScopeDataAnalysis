"""Convenience launcher for the full indoor golf analysis workflow.

This script tries to run all available analysis modules in sequence.  Each
analysis step is isolated so that one failing or optional module does not stop
all the others.

Usage
-----
python run_all_260322.py
"""

from __future__ import annotations

import importlib
import traceback
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class AnalysisStep:
    module_name: str
    function_name: str = "main"
    label: Optional[str] = None
    required: bool = False

    @property
    def display_name(self) -> str:
        return self.label or self.module_name


# Ordered workflow. Optional modules are skipped cleanly if not present.
ANALYSIS_STEPS: List[AnalysisStep] = [
    AnalysisStep("swing_session_analysis", label="Swing Session Analysis", required=True),
    AnalysisStep("swing_Gaussian_analysis", label="Swing Gaussian History Analysis", required=True),
    AnalysisStep("swing_skew_normal_analysis", label="Swing Skew Normal History Analysis", required=True),
    AnalysisStep("swing_carry_skew_normal_analysis", label="Swing Skew Normal Carry History Analysis", required=True),
    AnalysisStep("swing_trend_analysis", label="Swing Trend Analysis", required=True),
    AnalysisStep("pitching_Gaussian_analysis", label="Pitching Gaussian History Analysis", required=False),
    AnalysisStep("pitching_skew_normal_analysis", label="Pitching Skew Normal History Analysis", required=False),
]


def _run_step(step: AnalysisStep) -> bool:
    """Run one analysis step and return True on success."""
    print()
    print("=" * 80)
    print(f"Running: {step.display_name}")
    print(f"Module : {step.module_name}")
    print("=" * 80)

    try:
        module = importlib.import_module(step.module_name)
    except ModuleNotFoundError as exc:
        if exc.name == step.module_name and not step.required:
            print(f"Skipped optional module '{step.module_name}': module not found")
            return False
        print(f"Failed to import '{step.module_name}': {exc}")
        raise

    func = getattr(module, step.function_name, None)
    if func is None:
        message = f"Module '{step.module_name}' has no function '{step.function_name}'"
        if step.required:
            raise AttributeError(message)
        print(f"Skipped optional module '{step.module_name}': {message}")
        return False

    try:
        func()
        print(f"Completed: {step.display_name}")
        return True
    except RuntimeError as exc:
        if not step.required:
            print(f"Skipped optional step '{step.display_name}': {exc}")
            return False
        print(f"RuntimeError in required step '{step.display_name}': {exc}")
        raise
    except Exception:
        print(f"Error while running '{step.display_name}':")
        traceback.print_exc()
        if step.required:
            raise
        print(f"Continuing because '{step.display_name}' is optional.")
        return False


def main() -> None:
    """Run all configured analysis steps."""
    completed = 0
    attempted = 0

    for step in ANALYSIS_STEPS:
        attempted += 1
        if _run_step(step):
            completed += 1

    print()
    print("=" * 80)
    print(f"Finished analysis workflow: {completed}/{attempted} step(s) completed")
    print("=" * 80)


if __name__ == "__main__":
    main()
