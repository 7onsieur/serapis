"""Builds the two fictional lecture decks used by the owner acceptance test (docs/pilot/OWNER_ACCEPTANCE_TEST.md).

Everything is invented for testing: the module, the lecturer and every claim. Run from the repository root:

    .venv/bin/python docs/pilot/acceptance_material/make_material.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))

from university_jarvis.demo import build_pptx  # noqa: E402

WEEK1 = ("HER201 Week 1 - Community archives (fictional)", [
    ("What is a community archive",
     "A community archive is a collection of records kept and described by the people the records are about, "
     "rather than by a national or institutional archive."),
    ("Provenance and original order",
     "Provenance means the record keeps its origin: who created it and who held it. Original order means the "
     "records stay in the order their creator kept them. Together they let a reader judge how far a record can be trusted."),
    ("Appraisal",
     "Appraisal is the decision about which records are kept. Community archives often appraise by asking whether a "
     "record matters to the community's own story, not only whether it is official."),
    ("Case: the Marlow Street Tenants Group (fictional)",
     "The Marlow Street Tenants Group kept letters, minutes and photographs from 1974 to 1986. The group appraised "
     "photographs of meetings as high value because they showed who took part, which no official record did."),
])
WEEK2 = ("HER201 Week 2 - Access and consent (fictional)", [
    ("Why access is a choice",
     "An archive decides who may see a record and when. Access restrictions protect people named in a record; "
     "they can also hide uncomfortable history. A good policy states its reasons."),
    ("Consent and restricted records",
     "Where a record names a living person, a community archive may ask for consent before opening it. If consent "
     "cannot be obtained, the record can be closed for a set period and reviewed."),
    ("Two ways to describe a record",
     "Neutral description lists what a record is. Contextual description also explains why it was made and for whom. "
     "Contextual description takes longer but helps readers see whose voice is present."),
])

for name, deck in (("her201-week1-community-archives.pptx", WEEK1), ("her201-week2-access-and-consent.pptx", WEEK2)):
    build_pptx(HERE / name, deck[1])
    print("wrote", HERE / name)
