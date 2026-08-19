"""Run the sealed next-open execution proxy for frozen V9 structural strategies."""

from pathlib import Path

from market_lab.futures_v9_structural.execution import run_execution_study

if __name__ == "__main__":
    print(
        run_execution_study(
            Path("configs/futures_v9_structural_execution.yaml").resolve(),
            Path("runs/futures_v9_structural_execution").resolve(),
        )
    )
