import os
from opensearchpy import OpenSearch

def get_client() -> OpenSearch:
    host = os.getenv("OPENSEARCH_HOST", "http://opensearch:9200")
    # opensearch-py accepts hosts as list of dicts or urls
    return OpenSearch(hosts=[host])
