# GitHub Pages publication

The Pages workflow builds the interactive atlas from the immutable Partizan
commit recorded as `PARTIZAN_REF` in `.github/workflows/pages.yml`. The build
uses the repository subpath for every browser asset, renders the server output
to static HTML, and checks the title, principal dataset count, social image,
and asset prefix before deployment.

The published site is:

<https://devinnicholson.github.io/partizan-reproducibility/>

The atlas payload is exposed at `evidence/fixed-value-atlas.json.gz`. Its
compressed and decoded SHA-256 values are recorded in
`evidence/fixed-value-atlas.manifest.json` inside the deployed artifact.
