"""FWD demo CRS vocabulary and project routing (independent of securities QA)."""

import json
from functools import lru_cache
from importlib.resources import files


def uses_crs(project):
    return bool(
        project
        and (
            project.slug == "fwd-insurance-demo"
            or (project.modules or {}).get("crs_classification")
        )
    )


@lru_cache(maxsize=1)
def catalogue():
    return json.loads(
        files("voiceqa_shared").joinpath("crs_catalogue.json").read_text(encoding="utf-8")
    )
