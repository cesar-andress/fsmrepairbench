"""Tests for external Variability FL feasibility pass."""

from __future__ import annotations

from pathlib import Path

import pytest

from fsmrepairbench.external_variability_fl_feasibility import (
    run_external_variability_fl_feasibility,
)

VARCOP_CANDIDATE = Path("/tmp/varcop")


@pytest.mark.skipif(not VARCOP_CANDIDATE.is_dir(), reason="VARCOP clone not present")
def test_external_variability_fl_feasibility_runs(tmp_path: Path) -> None:
    result = run_external_variability_fl_feasibility(
        output_dir=tmp_path / "results",
        table_dir=tmp_path / "tables",
        cache_dir=tmp_path / "cache",
        varcop_root=VARCOP_CANDIDATE,
    )
    assert result.feasibility_class == "B"
    assert result.case_count == 338
    assert result.summary_path.is_file()
    assert result.by_stratum_path.is_file()
