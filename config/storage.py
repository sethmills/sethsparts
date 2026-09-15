"""Static storage with hashed filenames, tolerant of vendored JS references.

The default manifest storage fails the whole collectstatic run when a JS file
references something it can't resolve — e.g. maplibre-gl.js's
``//# sourceMappingURL=maplibre-gl.js.map`` comment, for which we don't ship the
.map file. ``manifest_strict = False`` downgrades that to a warning so hashing
still happens for everything else.
"""

from whitenoise.storage import CompressedManifestStaticFilesStorage


class LooseManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    manifest_strict = False
