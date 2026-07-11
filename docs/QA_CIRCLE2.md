# QA — Circle 2 (Ticket T3: Grounding guardrail as visual centerpiece)

_Date: 2026-07-12 · Role: QA/Test · Report-only (no fixes applied)_

## Build & test gates

| Gate | Command | Result |
| --- | --- | --- |
| Frontend build | `cd frontend && npm run build` | PASS — `vite build` 33 modules, built in ~1.1s, no errors |
| Backend tests | `cd backend && source .venv/bin/activate && python -m pytest -q` | PASS — 4 passed in 0.44s |

## T3 acceptance criteria

| # | Criterion | Result | Notes |
| --- | --- | --- | --- |
| 1 | Every bullet renders as a card whose color+badge match `grounding[i].supported` (green verified / red not-supported); absent grounding falls back to verified styling | PASS | `verdictFor()` returns `supported:true, missing:true` when `!g`; `gcard--flagged` + `badge--danger` only when `!ok`. |
| 2 | Verified cards show `evidence`; flagged cards show `issue` with sensible fallback when null | PASS | `detail = ok ? (evidence \|\| 'Verified against your CV') : (issue \|\| 'Not supported by your CV')`. Both fallbacks present. |
| 3 | Summary header shows `N bullets · X verified · Y flagged` + verified-% meter, consistent with `flagged_count` | PASS | Counts derived from `verdicts`; `verified+flagged == bullets`. Backend normalizes `grounding` to bullet length and sets `flagged_count = count(!supported)`, so frontend `flaggedCount` matches `flagged_count`. |
| 4 | "Copy verified bullets" copies only supported bullets; flagged/excluded omitted | PASS (default) | Default `included = verdicts.map(v => v.supported)`; copy joins `includedBullets`. See B1 for the manual-override nuance. |
| 5 | Fabricated CV/JD produces at least one red "Not supported" card with reason | PASS (by code path) | Could not run live (no Groq key in this pass); render logic proven to produce red card + `issue` when `supported===false`. |
| — | Exclude toggle works; defaults (flagged excluded, verified included); resets on new analysis | PASS | Checkbox `toggle(i)`; default from `v.supported`; `useEffect([verdicts])` re-seeds `included` on new tailor payload. `verdicts` memo keyed on `bullets`/`grounding` refs (stable across re-renders, new on new result). |
| — | Cover letter collapsible | PASS | `CoverLetter` component with `open` state; returns null when empty; `aria-expanded` set. |
| — | Responsive: no fixed widths causing horizontal page scroll (check styles.css) | PASS | Layout grid `1fr 1fr` → single column `<900px`; `.meter`/`.textarea` `width:100%`. Only fixed px are 14–15px icons. No page-level horizontal scroll. See B2 (cosmetic). |

## Trace verification (requested scenario)

`bullets=[b0,b1,b2]`, grounding `supported=[true,false,true]`:
- `verdicts` supported = `[true,false,true]` → `verifiedCount=2`, `flaggedCount = 3-2 = 1`.
- `pct = round(2/3*100) = round(66.67) = 67`.
- Summary renders: **3 bullets · 2 verified · 1 flagged**; meter fill `width:67%`. ✓
- `included` default = `[true,false,true]` → `includedBullets = [b0, b2]`.
- "Copy verified bullets" → clipboard text `"• b0\n• b2"` (b1 omitted). ✓

All expected values confirmed.

## Bugs / observations

**B1 — Low / by-design.** The copy button is labeled "Copy verified bullets" but copies whatever is in the `included` set, not strictly `supported===true`. Since the exclude checkbox appears on every card, a user can manually re-include a flagged bullet and it will then be copied. This is the documented "exclude toggle" affordance and the *default* behavior satisfies criterion #4 (flagged excluded on load); noting only that the label + manual override can diverge. No change required for T3.

**B2 — Low / cosmetic.** In `.gcard__top` (flex, no `flex-wrap`) the badge uses `white-space:nowrap` alongside the exclude label; on very narrow (~320px) viewports the badge+label can exceed the inner card width. `.guardrail` has `overflow:hidden`, so this clips rather than producing horizontal page scroll — the acceptance criterion (no horizontal scroll) still holds, but the badge/label may be visually clipped on the smallest phones. Consider `flex-wrap:wrap` on `.gcard__top`.

No correctness, counting, or clipboard defects found. Data consistency between frontend counts and backend `flagged_count` verified via the normalization in `services/grounding.py`.

## VERDICT: PASS
