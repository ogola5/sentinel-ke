import requests
from typing import Dict


class TaxiiClient:
    def __init__(
        self,
        *,
        base_url: str,
        collection_id: str,
        api_root: str = "root",
        username: str | None = None,
        password: str | None = None,
        token: str | None = None,
        verify_tls: bool = True,
    ):
        self.url = f"{base_url}/taxii/{api_root}/collections/{collection_id}/objects/"
        self.verify_tls = verify_tls

        self.auth = None
        self.headers = {
            "Content-Type": "application/vnd.oasis.stix+json;version=2.1"
        }

        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        elif username and password:
            self.auth = (username, password)

    def push_bundle(self, bundle: Dict) -> None:
        r = requests.post(
            self.url,
            json=bundle,
            headers=self.headers,
            auth=self.auth,
            verify=self.verify_tls,
            timeout=15,
        )
        if r.status_code not in (200, 202):
            raise RuntimeError(
                f"TAXII push failed {r.status_code}: {r.text}"
            )
