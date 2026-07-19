# TextOp model source boundary

This directory contains the project-local inference subset used by `RobotMDARRuntime`. It includes
upstream-derived diffusion and neural-network implementations plus project-specific TextOp motion feature
conversion. Runtime code must import this directory through `textop_backend.textop_model`; it must not import
an adjacent TextOp or RobotMDAR checkout.

Known provenance:

- `diffusion/gaussian_diffusion.py` and `diffusion/respace.py` declare that they are based on OpenAI
  `guided-diffusion`; the former also cites Jonathan Ho's diffusion implementation.
- The remaining model/operator files were imported with the embedded runtime in commit `41fab88` from the
  implementation used to produce the locked TextOp artifacts.

The exact upstream revision and license mapping for every imported file has not yet been independently
verified. Until that audit is completed, this directory is frozen: do not add model families, training code,
or broad refactors. Any necessary local modification must be documented here with the commit and reason.

Repository policy:

- Ruff and Pyright exclude exactly this directory; the surrounding TextOp adapters remain fully checked.
- Tests must continue to reject external `robotmdar`, editable-install, `.pth`, or `PYTHONPATH` dependencies.
- Model weights and statistics are external artifacts governed by `textop_pretrained.yaml` and SHA-256 checks.
- A future upstream refresh must record source URL, revision, license, imported paths, and local patch set before
  replacing files.
