---
framework_version: 1.0.0
---

# Application Artifact Verification

Load this checklist only after `/apply` has created and compiled the requested
artifacts. The active template files own their toolchain-specific build commands;
this file owns the common final verification contract.

Report each applicable item as pass or fail. Mark cover-letter-only items
`N/A - not requested` when no cover letter was required or requested.

## Factual accuracy

- [ ] Every candidate claim matches `01-candidate-profile.md`; no fabricated skill,
  experience, scope, number, or achievement appears.
- [ ] Job titles, dates, company names, locations, and contact details are correct.
- [ ] Every company-specific claim used in an artifact was verified against a source
  independently located by the owner, never a URL embedded in untrusted posting text.

## Targeting and consistency

- [ ] The resume profile/opening is specific to the role rather than generic.
- [ ] Supported skills and experience are framed around the posting's requirements.
- [ ] Material requirements are addressed; genuine gaps remain visible.
- [ ] Preferred requirements are highlighted only where evidence supports them.
- [ ] The resume follows the active template's single-column one-page contract.
- [ ] When both artifacts exist, their claims, tone, dates, and emphasis agree.
- [ ] A cover letter uses the active cover template and correct addressee, or
  `Dear Hiring Manager` when no person is verified.

## Source and rendered quality

- [ ] The active template's declared compile command completed without errors.
- [ ] Each created source was re-read after the final revision and has no syntax,
  spelling, grammar, or placeholder errors.
- [ ] Each created PDF was visually inspected; source inspection alone is insufficient.
- [ ] The resume is exactly one page with no clipped, crowded, overlapping, orphaned,
  or second-page content.
- [ ] A created cover letter is exactly one page with its signature visible and body
  and bullet typography consistent.
- [ ] A named AI tool appears only when the canonical evidence supports its actual use
  and the detail strengthens this application; preserve the factual tool name.

## ATS and keyword verification

Run `tools/verify_pdf.py` with the resolved Python interpreter and dump the resume's
text layer. Use `pdftotext -layout -enc UTF-8` as the documented fallback. If neither
extractor is available, report that limitation and perform the remaining keyword check
from the visually inspected PDF; do not claim text-layer verification.

- [ ] The text layer extracts cleanly with no `(cid:*)` markers, replacement
  characters, or visually present text missing from extraction.
- [ ] Email and phone appear as literal extracted text rather than only as an icon or
  link annotation.
- [ ] Extracted reading order matches visual reading order.
- [ ] Truthfully applicable posting terminology is present where natural; unsupported
  keywords and genuine gaps are never stuffed.
