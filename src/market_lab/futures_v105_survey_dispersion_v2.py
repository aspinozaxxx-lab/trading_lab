"""V105 workbook-URL identity correction; all economics inherited unchanged."""

from __future__ import annotations

import argparse
import copy
import os

import pandas as pd

from market_lab import futures_v105_survey_dispersion as original

base, engine, STORAGE = original.base, original.engine, original.STORAGE
CONFIG = base.PROJECT / "configs/v105_survey_dispersion_v2.json"
SEAL = base.PROJECT / "configs/v105_survey_dispersion_v2.seal.json"


def corrected_config(correction, parent_cfg):
    cfg = copy.deepcopy(parent_cfg)
    base.require(
        correction["protocol_id"] == "v105_survey_dispersion_v2"
        and correction["source_url"] == "https://www.cbr.ru/Content/Document/File/144490/full.xlsx",
        "undeclared correction",
    )
    cfg["protocol_id"] = correction["protocol_id"]
    cfg["source"]["source_url"] = correction["source_url"]
    return cfg


def metadata_identity(meta, cfg):
    selected = original.clocks(meta, metadata=True)
    selected = selected.loc[
        selected.indicator.eq(cfg["signal"]["indicator"])
        & selected.statistic.isin(cfg["signal"]["statistics"])
    ]
    base.require(
        not selected.empty
        and selected.unit.eq(cfg["signal"]["unit"]).all()
        and selected.current_vintage.eq(True).all()
        and selected.source_url.eq(cfg["source"]["source_url"]).all(),
        "metadata source identity mismatch",
    )
    return True


def preflight(cfg, parent, storage=STORAGE):
    result = original.preflight(cfg, parent, storage)
    source = cfg["source"]
    path = base.safe(storage, source["root"]) / source["processed"]["path"]
    meta = pd.read_parquet(path, columns=source["metadata_columns"])
    result["numeric_read_preceded_by_metadata_identity"] = metadata_identity(meta, cfg)
    return result


def preserved_v1(correction, storage=STORAGE):
    root = base.safe(storage, correction["failed_v1_root"])
    base.require(
        {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} == {"inputs.json"}
        and base.sha(root / "inputs.json") == correction["failed_v1_inputs_sha256"],
        "failed V1 evidence changed",
    )
    return True


def load(expected):
    base.require(base.sha(SEAL) == expected, "V105 V2 seal drift")
    for name, digest in original.prior.read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V105 V2 file drift")
    correction = original.prior.read_json(CONFIG)
    parent_cfg, parent = original.load(correction["parent_v105_seal_sha256"])
    return corrected_config(correction, parent_cfg), parent


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    args = cli.parse_args()
    base.require(os.name == "posix" and os.getuid() == 999, "server service only")
    cfg, parent = load(args.seal_sha)
    preserved_v1(original.prior.read_json(CONFIG))
    preflight(cfg, parent)
    original.run(cfg, parent, args.seal_sha)


if __name__ == "__main__":
    main()
