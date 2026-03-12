from __future__ import annotations

import os

from opensearchpy import OpenSearch


_DISABLED_VALUES = {"", "disabled", "none", "off", "false", "inactive"}


class OpenSearchDisabledError(RuntimeError):
    pass


def is_opensearch_enabled() -> bool:
    host = os.getenv("OPENSEARCH_HOST", "http://opensearch:9200").strip().lower()
    return host not in _DISABLED_VALUES


def is_opensearch_disabled_error(exc: Exception) -> bool:
    return isinstance(exc, OpenSearchDisabledError) or str(exc).strip().lower() == "opensearch_disabled"


def get_client() -> OpenSearch:
    if not is_opensearch_enabled():
        raise OpenSearchDisabledError("opensearch_disabled")
    host = os.getenv("OPENSEARCH_HOST", "http://opensearch:9200")
    # opensearch-py accepts hosts as list of dicts or urls
    return OpenSearch(hosts=[host])
