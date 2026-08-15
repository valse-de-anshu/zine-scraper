## Summary of Changes
Provide a brief summary of what this PR introduces, fixes, or refactors.

## Type of Change
- [ ] Bug fix (non-breaking change fixing an issue)
- [ ] New feature / New scraper platform
- [ ] Refactor / Code optimization
- [ ] Documentation update

## Site Isolation & Architecture Checklist
- [ ] Any new scraper is self-contained in `scrapers/<site>/` without cross-dependencies.
- [ ] Interactive selectors are guarded by `sys.stdin.isatty()` and `is_batch` checks.
- [ ] Terminal formatting adheres to the Tokyo Night Storm / Rich theme tags (`[info]`, `[warning]`, `[error]`, `[success]`, `[site]`).
- [ ] Any new dependency is added to `requirements.txt` / install scripts.

## Testing & Verification
Describe the tests you ran to verify your changes:
- Tested URL: 
- Interactive TUI tested: [Yes / No]
- Batch mode tested: [Yes / No]
