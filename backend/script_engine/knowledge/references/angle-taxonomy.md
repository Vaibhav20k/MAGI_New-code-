# Angle & Opening Taxonomy

**Purpose:** make `SKILL.md` §2's hook-diversity rules machine-checkable instead of prose.

Two closed vocabularies. Both are mirrored as JSON Schema `enum`s in
`schemas/research-dossier.schema.json` and `schemas/script.schema.json`, and both are read by
`workflows/diversity_gate.py`. Adding a value here means adding it to those enums too.

---

## 1. `opening_form` — *how the piece starts*

Derived from the opening options already listed in `SKILL.md` §2. Questions are optional; several of
these deliberately do not open with one.

| Value | The first line does this | Example shape |
| :--- | :--- | :--- |
| `everyday-friction` | Names a specific annoyance the viewer already has | "The cabinet door that stopped closing flush in year two." |
| `sensory-detail` | Leads with something seen, heard, smelled or touched | "A kitchen that makes no sound when you close it." |
| `material-detail` | Leads with the substance itself | "Stone, silver, copper. Three materials, and no wood." |
| `verified-stat` | Leads with a `VERIFIED` number from the dossier | *(only with a Tier 1–2 source; never an invented figure)* |
| `demonstration` | Describes something being done or tested on camera | "Pour it on the seam. Wait an hour. Look again." |
| `contrast` | Puts two things directly against each other | "Wood swells in the monsoon. Stone does not." |
| `direct-statement` | States the thesis flatly, no setup | "Most kitchens are built to be replaced." |
| `historical-discovery` | Opens on a specific, sourced historical finding | *(requires a `VERIFIED`/`QUALIFIED` `historical_evidence` entry)* |

**Rules**
- At least **two** of the three candidate hooks must use a non-historical `opening_form`.
- `historical-discovery` requires a real supported claim in the dossier. Never invent an ancient
  connection to satisfy a framework (`SKILL.md` §2, `prompt.md` §13).
- `verified-stat` requires a claim with `verification_status: VERIFIED`.

---

## 2. `angle_family` — *what the piece is actually about*

This is the vocabulary that matters most. Three runs on "magppie wellness kitchen" once produced three
different sentences that were all `hygiene-biology` underneath — different words, identical argument.
Tracking the family is what makes that visible and preventable.

| Value | The core argument |
| :--- | :--- |
| `hygiene-biology` | Washable surfaces, cleanability, food-contact hygiene (physical behaviour only, never a health claim) |
| `acoustic-comfort` | Sound, damping, the quietness of a well-built space |
| `thermal-durability` | Heat, thermal mass, expansion, behaviour near fire and steam |
| `material-longevity` | Lifespan, fatigue, warping, why this outlasts the alternative |
| `air-quality` | VOCs, off-gassing, adhesives, what the room adds to the air |
| `ergonomic-flow` | Reach, movement, working heights, how the body uses the space |
| `metallurgy-history` | Historical metalwork and material knowledge (needs sourced evidence) |
| `craft-geometry-history` | Historical spatial/geometric/joinery practice (needs sourced evidence) |
| `lifecycle-sustainability` | Recyclability, end of life, embodied material cost |

**Rules**
- **No two consecutive runs on the same topic may share an `angle_family`.** Enforced by
  `diversity_gate.evaluate` against the banned set from `hook_ledger.used_combinations`.
- Agent 1 must propose **≥3** candidate hooks spanning **≥3 distinct** families.
- A family may only be used if the dossier holds supporting evidence for it. If
  `knowledge/references/evidence-index.md` has no rows for a family, that family is not yet available —
  say so rather than inventing support for it.

---

## 3. How the ledger uses these

`runs/_memory/hook-ledger.json` stores `angle_family` and `opening_form` alongside each accepted hook.
The pipeline derives a **banned set** of `(angle_family, opening_form)` pairs — the last 3 runs on the
same topic plus the last 2 globally — and passes it to **Agent 1**, before any writing happens. Variety
is constrained at the evidence layer, because that is where it collapses.
