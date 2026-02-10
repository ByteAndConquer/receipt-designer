# Pull Request

## Summary
<!-- What does this PR do? 2–5 sentences max. -->
- 

## Type of change
<!-- Check all that apply -->
- [ ] Bug fix
- [ ] New feature
- [ ] Refactor (no behavior change)
- [ ] Documentation update
- [ ] Build/CI change
- [ ] Performance improvement
- [ ] Test improvements
- [ ] Other: ____________

## Related links / issues
<!-- Link issues, discussions, or context. Use keywords like "Fixes #123" if applicable. -->
- Fixes #
- Related #

## Motivation / Context
<!-- Why are we doing this? What problem does it solve? -->
- 

## What changed
<!-- Bullet list of major changes; avoid listing every tiny commit -->
- 
- 

## Screenshots / Demo (if UI-related)
<!-- Add before/after screenshots, GIFs, or a short video -->
- 

## How to test
<!-- Step-by-step instructions to verify the change -->
1. 
2. 
3. 

## Expected behavior
<!-- What should happen after testing? -->
- 

## Test coverage
<!-- Check what you ran locally -->
- [ ] `python -m pytest -v`
- [ ] `RUN_QT_TESTS=1 python -m pytest -v` (Qt integration tests)
- [ ] Manual smoke test (launch app)
- [ ] Built executable via PyInstaller

## Build / Release notes (if applicable)
<!-- If this affects packaging/release -->
- [ ] Verified `pyinstaller ReceiptDesigner.spec` works
- [ ] Verified assets load in frozen build (icons etc.)
- Notes for release:
  - 

## Compatibility / Environment
<!-- Helps reproduce issues -->
- OS: (Windows 11 / etc.)
- Python: (e.g., 3.13.x)
- PySide6: (optional)
- Printer backend used (if relevant): Network / USB / Serial / ESC/POS

## Risk assessment
<!-- What could break? Where should reviewers focus? -->
- Risk level: [ ] Low  [ ] Medium  [ ] High
- Risk areas:
  - [ ] Save/Load
  - [ ] Autosave/Recovery
  - [ ] Printing backends
  - [ ] Template variables
  - [ ] UI layout/editor tools
  - [ ] Packaging / PyInstaller
  - [ ] Other: ____________

## Backout plan
<!-- How do we revert if it breaks? -->
- [ ] Revert this PR
- [ ] Roll back to tag: ____________
- Notes:
  - 

## Checklist
- [ ] I ran the tests listed above (or explained why not)
- [ ] I updated docs (README / CLAUDE.md) if behavior changed
- [ ] I avoided unrelated formatting-only changes
- [ ] I verified the app launches
- [ ] I added/updated tests where it made sense
