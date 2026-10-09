# The agent office: what it was made with

This note records the models and assets behind the 3D office on MAGI's home screen (the people at their desks
in the Marketing department), so anyone picking the work up knows where each part came from and how to redo it.

## AI models

| Used for | Model | How it was used |
|---|---|---|
| All the code on this branch | Claude Opus 5.5 (`claude-opus-5-5`), through Claude Code | Wrote the scene, the people's behaviour, the seated pose, the status endpoint, the tests and the asset packing script, working from the project owner's direction. |
| Concept images for the look and the layout | GPT Image 2.5 (`gpt_image_2_5`), through Higgsfield | Produced reference pictures only: the four character and office directions, and the campus grid and main street layouts. No generated image is shipped in the product. |

The people in the office do not run on an AI model themselves. They are animated figures that follow what MAGI's
real marketing agents are doing, as reported by `GET /api/magi/team`. The models those agents use are unchanged by
this work and are described in the main `README.md`.

## 3D models

| Part | Source | Licence |
|---|---|---|
| The seven people | Quaternius, Ultimate Modular Men and Ultimate Modular Women (https://quaternius.com) | CC0 1.0, public domain |
| Desks, chairs, screens, sofa, plants and the rest of the furniture | Kenney, Furniture Kit 2.0 (https://kenney.nl/assets/furniture-kit) | CC0 1.0, public domain |
| Rendering | three.js 0.185.1 (https://threejs.org), served from `backend/static/magi/vendor/` | MIT |

Which character plays which role:

| Role | Character file in the pack |
|---|---|
| Crawler | Men, `Casual_Hoodie` |
| Filter | Women, `Casual` |
| Knowledge | Men, `Suit` |
| Strategist | Women, `Suit` |
| Blog writer | Men, `Casual_2` |
| Art director | Women, `Formal` |
| Video team | Men, `Beach` |

Skin and hair are recoloured per role in `backend/static/magi/people.js` so the seven read as different people.
Furniture is recoloured to MAGPPIE's stone, wood and copper in `backend/static/magi/furnish.js`.

## What was changed in the assets

Each character arrives as a 3 MB file with 24 animations, most of them fighting moves. `scripts/pack-office-assets.mjs`
keeps five (Idle, Idle_Neutral, Interact, Walk, Wave), removes the pistol, and writes a compact `.glb` of about 0.9 MB.
Furniture files are copied unchanged. The result lives in `backend/static/magi/assets/`, with `LICENSES.txt` beside it.

The pack has no sitting or typing animation and no face shapes. Those are made in code:

- Sitting and typing: `backend/static/magi/seat.js` lays a seated pose over the figure's skeleton.
- Blinking and mouth movement: small overlays added to the face in `backend/static/magi/people.js`. They are only
  added to characters whose model names its eye material, so some characters do not have them.

## Redoing the assets

1. Download the two Quaternius packs (glTF, "Individual Characters") and the Kenney Furniture Kit.
2. Put the seven character files in one folder, named as in the `PEOPLE` table at the top of the script
   (`m_Suit.gltf`, `w_Casual.gltf` and so on), and unzip the furniture kit into a `kenney/` folder beside them.
3. Run `node scripts/pack-office-assets.mjs <that folder>`.

To swap a character, change its entry in `PEOPLE` and run the script again. Any character on the same skeleton
(the same bone names) works without code changes.

## Checking it without the full system

`node tests/home/mock-server.mjs` serves the home screen on http://localhost:8765 with fixture data.
`/__mock/team?m=quiet|crawl|waiting|busy` switches what the team is doing.
`python -m pytest backend/tests -q` runs the tests for the status endpoint.
