"""Which version this is.

There is no release process behind this app — it is distributed by cloning a git
repository, so this number is bumped by hand when something meaningful changes. That
is honest about what it is: a signal for the update check to compare against, not a
promise about semantic versioning.

Keep it in step with the git tags in the repository, **in the same commit the tag goes
on**. If they drift, the update check starts telling people they are out of date when
they are not, which is worse than not telling them at all — and it is a two-way drift:
a tag without the bump tells every install, including the newly-tagged one, that a newer
version exists; a bump without the tag tells them they are current while the repository
has moved on.
"""

__version__ = "0.5.0"
