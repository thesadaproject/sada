# Contributing to Sadā

Thanks for your interest. Sadā is free software under the **GNU AGPL-3.0** (see `LICENSE`).

## Before opening a pull request

```bash
make setup
make test    # every test must pass
```

- One pull request, one topic. Describe the problem and the fix in a few lines.
- Add tests for any change in behaviour.
- For a large change, open an issue first so we can discuss it.
- A change to the database models (`sada/backoffice/models.py`) ships with its migration, generated from
  them: `uv run python -m sada.backoffice.migrations revision "what changes"` writes
  `sada/backoffice/schema/versions/NNNN_….py`; read it, adjust it if needed, commit it. A test rebuilds a
  database through the migrations and compares it to the models: a forgotten migration fails the CI.

## Contributor License Agreement

Sadā is also offered as a hosted service. To keep the project under a single maintainer, every
contribution is made under the agreement below. By opening a pull request, you accept it by adding
this line to its description:

> I accept the Sadā Contributor License Agreement (CONTRIBUTING.md).

**Agreement**

1. You confirm that you wrote the contribution, or have the right to submit it, and that it contains
   no code under an incompatible license.
2. You keep the copyright on your contribution.
3. You grant the author and maintainer of Sadā (Nabil, @Bilnaa), and any entity he transfers the
   project to, a worldwide, perpetual, royalty-free, non-exclusive and irrevocable license to use,
   reproduce, modify, distribute and sublicense your contribution, including under terms other than
   the AGPL-3.0 (for example for the hosted version).
4. You grant the same license on any patent you hold that would necessarily be infringed by your
   contribution.
5. Your contribution is always published under the AGPL-3.0 in this repository.
6. Your contribution is provided "as is", without warranty.
