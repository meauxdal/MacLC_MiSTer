# AGENTS.md

Read every session.

## Philosophy

- Historical preservation and overall machine accuracy is paramount
- Polish and attention to detail is a strong guideline
- Quality of life is important where it makes sense and doesn't take too many resources
- Every word in every context is a liability
- Prefer clear, clean, working code over excessive documentation or code-commentary

## MiSTer cores

- `sys` must match upstream MiSTer; never make project-specific edits there. Make local changes elsewhere so the project remains eligible for MiSTer-devel (important qualification: upstream `sys` updates are allowed and desired whenever there are Template_MiSTer updates to keep the core in line with upstream)

## Token efficiency

What not to do unless asked:
- run full Quartus builds: ask the user to do it
- run long scripts: ask the user to do it
- look for workarounds for missing resources the user assumes you have; stop and ask directly

Preserve tokens:
- ask questions when unsure
- periodically check usage
- make an effort to tie off turns and emit *before* usage exhaustion

## Code hygiene

- Manage whitespace consistently
- Keep code comments terse and direct; prefer fewer words but preserve clarity
- Avoid historical asides (unless they have ongoing technical value)
- Never use unusual characters in code or comments; plain ASCII only (no em dashes, emojis, decorative symbols, etc.)
- Code is readable (self-describing in form) such that it does not require constant commentary
- Comments only explain intent, constraints, hardware behavior, or non-obvious logic
- Think ahead and make arrangements for future needs (ask; don't guess)
- Use TODO flags for future attention, but be direct
- Prefer preservation of existing structure unless refactoring
- Do not invent abstractions without concrete need
- Keep docs minimal to mitigate maintenance scope
- No narrative implementation history in source
- In general, match surrounding style unless it strongly conflicts with above (ask; don't guess)
