<!-- Thank you for contributing. The policy is in CONTRIBUTING.md; this is its short form. -->

## What this changes, and why

<!-- One change per pull request. Link the issue it closes, if there is one: "Closes #123". -->

## Checklist

- [ ] An issue was opened first, if this is a large change
- [ ] Tests come with it, and a fix has one that fails without it
- [ ] The full suite and the linter pass (`pytest -n auto tests`, `ruff check`, `ruff format --check`)
- [ ] A line in `pyscopegui/help/changelog.md` under *Unreleased*, if a user would notice it
- [ ] The help page is updated, if the behaviour it describes changed
- [ ] Anything that drives an output -- a signal generator -- does so only when it is chosen
- [ ] Any new dependency is explained here and is not GPL-only
- [ ] No maker's library or other proprietary material is included

## Tested on

<!-- Windows or Linux; the instrument, if real hardware was used. -->
