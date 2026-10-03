# Evidence Index by Angle Family

**Status: STRUCTURE ONLY — rows not yet supplied.**

## Why this file exists

Agent 1 has no retrieval tool (`ENABLE_AGENT1_WEB_SEARCH` is off by default). It therefore recalls
"evidence" from model weights and then labels it Tier 1 — which is both a `SKILL.md` §5 source-hierarchy
violation and the reason every dossier converges on the same argument. With only
`knowledge/products/core_products.md` and `knowledge/approved-claims/verified_claims.md` to draw on,
there is nothing else for it to find.

The taxonomy in `angle-taxonomy.md` and the gate in `workflows/diversity_gate.py` can reliably vary
**wording and framing**. Only this file can vary **substance**.

## How to fill it

One row per claim, under the matching `angle_family` heading. Every row needs a real, checkable source
and a tier from `SKILL.md` §5. Per `prompt.md` §13, claims and sources are **not** to be invented to
populate this file — an empty section is correct and honest; a plausible-looking fabricated row is not.

A family with no rows is unavailable to Agent 1. It should say the evidence is missing rather than
manufacture support for it.

```text
| claim | source | tier | verification_status |
```

`verification_status` is one of `VERIFIED` / `QUALIFIED` / `CONTESTED` / `UNVERIFIED` / `REJECTED`.

---

## hygiene-biology
*Non-porous surfaces, bacterial load, cleanability, food contact safety.*

| claim | source | tier | verification_status |
| :--- | :--- | :--- | :--- |
| _TODO: Magppie to supply sourced claims_ | | | |

## acoustic-comfort
*Sound, damping, the quietness of a well-built space.*

| claim | source | tier | verification_status |
| :--- | :--- | :--- | :--- |
| _TODO: Magppie to supply sourced claims_ | | | |

## thermal-durability
*Heat, thermal mass, expansion, behaviour near fire and steam.*

| claim | source | tier | verification_status |
| :--- | :--- | :--- | :--- |
| _TODO: Magppie to supply sourced claims_ | | | |

## material-longevity
*Lifespan, fatigue, warping, why this outlasts the alternative.*

| claim | source | tier | verification_status |
| :--- | :--- | :--- | :--- |
| _TODO: Magppie to supply sourced claims_ | | | |

## air-quality
*VOCs, off-gassing, adhesives, what the room adds to the air.*

| claim | source | tier | verification_status |
| :--- | :--- | :--- | :--- |
| _TODO: Magppie to supply sourced claims_ | | | |

## ergonomic-flow
*Reach, movement, working heights, how the body uses the space.*

| claim | source | tier | verification_status |
| :--- | :--- | :--- | :--- |
| _TODO: Magppie to supply sourced claims_ | | | |

## metallurgy-history
*Historical metalwork and material knowledge. Requires archaeological or academic sourcing.*

| claim | source | tier | verification_status |
| :--- | :--- | :--- | :--- |
| _TODO: Magppie to supply sourced claims_ | | | |

## craft-geometry-history
*Historical spatial, geometric and joinery practice. Requires archaeological or academic sourcing.*

| claim | source | tier | verification_status |
| :--- | :--- | :--- | :--- |
| _TODO: Magppie to supply sourced claims_ | | | |

## lifecycle-sustainability
*Recyclability, end of life, embodied material cost. Must name actual material properties, never vague
"eco-friendly" language (`SKILL.md` §6.3).*

| claim | source | tier | verification_status |
| :--- | :--- | :--- | :--- |
| _TODO: Magppie to supply sourced claims_ | | | |
