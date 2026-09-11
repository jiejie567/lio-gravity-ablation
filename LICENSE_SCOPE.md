# Licence scope

The root MIT licence covers original experiment, validation, analysis and
reproduction code authored for this study, including original code under
`scripts/` and `verify_review.py`. It does not override any existing file notice.

Bundled FAST-LIO2, LIO-SAM, Livox driver, and their dependencies retain their
own in-tree licences, copyright notices, and applicable obligations. Changes
inside those upstream-derived trees remain subject to their governing terms;
they are not relicensed wholesale as MIT by this repository.

The experimental variants modify upstream state representations, propagation,
updates, logging and direction factors. They are research modifications, not
upstream releases or endorsements.

Dataset ground truth and point-cloud material retain the upstream terms listed
in DATA_SOURCES.md. In particular, MCD-derived material is subject to its
CC BY-NC-SA 4.0 conditions, not the root MIT licence. The same applies to the
MCD-derived point-cloud visualizations in the video and manuscript figures.

The manuscript, video, numerical output files and third-party data are not
relicensed by the software MIT grant. This release supplies them for inspection
and reproducibility; it grants no additional blanket reuse licence for them.
