# Learned xLights encodings

One folder per xLights version (e.g. `2025.10/encoding.json`), produced by
`seqtool xlights-learn` from a reference kit. Folders shipped here are
pre-learned; a user's own learned folders live in
`seqtool-prefs/xlights-learned/<version>/` and take priority. The exporter
uses the exact version if present, otherwise the nearest older version (with a
warning), so a user who upgrades xLights only needs to rebuild the kit when
the output no longer loads correctly.
