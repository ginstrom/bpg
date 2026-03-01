4. Event ledger

It should be possible to configure the storage for the immutable event ledger
to one of:
* file system
* sqlite in memory
* sqlite file backed
* postgres

Default to sqlite in memory for unit tests
Default to sqlite file backed for local runs
Default ot postgres for when running in "production" (e.g. dockerized)
