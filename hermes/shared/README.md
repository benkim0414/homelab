# Shared Hermes material

This directory is for genuinely reusable repository documentation or runtime
assets. It does not hold credentials, session databases or shared profile state.
No shared runtime asset is introduced by the profile directory reorganization.

The existing runtime-context overlay is House manager-specific. Its implementation
and provenance stay under
[../profiles/house-manager/tools/runtime_context](../profiles/house-manager/tools/runtime_context/README.md).
The three workload configurations remain in their respective profile directories.
