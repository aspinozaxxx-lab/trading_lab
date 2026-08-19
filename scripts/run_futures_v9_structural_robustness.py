"""Run the independent frozen V9 structural robustness audit."""

from pathlib import Path

from market_lab.futures_v9_structural.robustness import run_audit

if __name__ == "__main__":
    print(
        run_audit(
            Path("configs/futures_v9_structural_robustness.yaml").resolve(),
            Path("runs/futures_v9_structural_robustness").resolve(),
        )
    )
