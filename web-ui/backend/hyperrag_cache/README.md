# Runtime knowledge bases

Knowledge-base caches are generated locally and are not included in this repository.
Create a database through the Web UI, or mount a cache built using the CLI.
The Docker entrypoint may copy a private seed from `/app/cache_seed/case1` into
the writable `/app/hyperrag_cache/case1` volume. Without a seed, the application
starts with an empty knowledge base. Original literature and vectors stay local.
