# Test Fixtures

Real (or realistic, anonymized) iRacing CSV exports live here, e.g.
`eventresult_87601875_0.csv`. These are the ground truth the CSV parser
and validator are tested against — per the project context doc, the
parser should be built and tested against an actual export, not an
assumed format.

`.gitignore` excludes `*.csv` everywhere except this directory, so
fixtures are the one place CSVs are safe to commit.
