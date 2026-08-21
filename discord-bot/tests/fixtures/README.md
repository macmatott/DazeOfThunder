# Test Fixtures

Real (or realistic, anonymized) iRacing CSV exports live here, e.g.
`eventresult_87601875_0.csv`. These are the ground truth the CSV parser
and validator are tested against — per the project context doc, the
parser should be built and tested against an actual export, not an
assumed format.

`eventresult_88113080_0.csv` is a real **Hosted session** export (this
league's actual race format) rather than an official iRacing series
race — it has no season/week/strength-of-field metadata, and sandwiches
an extra "League Name"/"League ID" info block before the real results
table. Both shapes need to keep parsing correctly.

`.gitignore` excludes `*.csv` everywhere except this directory, so
fixtures are the one place CSVs are safe to commit.
