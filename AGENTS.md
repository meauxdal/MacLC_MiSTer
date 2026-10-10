# AGENTS.md

## Code hygiene

Read every session.

- Preserve tokens: STOP and ask questions when unsure
- No wild goose chases
- Keep code terse and direct
- Prefer the fewest words that preserve clarity
- Do not add historical asides (unless they have ongoing technical value)
- Do not use unusual characters in code or comments. Use plain ASCII only
- No em dashes, emojis, decorative symbols, or typographic punctuation
- Mitigate LLM-evident phrasing
- Do not add compatibility layers, fallback paths, or defensive code without evidence they are required
- Code is readable (self-describing in form) such that it does not require constant commentary
- Comments only explain intent, constraints, hardware behavior, or non-obvious logic
- Think ahead and make arrangements for future needs (if needed, ask; don't guess)
- Use TODO flags liberally to flag for future attention, but be very terse
- Prefer preservation of existing structure unless explicitly refactoring
- Do not invent abstractions without concrete need
- Think small: modules and local reasoning over cleverness
- Match surrounding style
- Keep docs as minimal to mitigate need for constant maintenance
- No implementation history in source

## Guiding rule

Each word, a liability. Why many when few suffice?
