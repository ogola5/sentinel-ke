import os
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db import registry as _  # noqa: F401  # register models
from app.campaign.models import Campaign, CampaignEntity
from app.ledger.infra_clusters import InfraCluster, InfraClusterMember
from app.analytics.layer3.shared_infra_worker import run_shared_infra_claims, CLAIM_TYPE, WINDOW
from app.campaign.claims import CampaignClaim


TEST_DB_URL_ENV = "TEST_DATABASE_URL"


def _session():
    url = os.environ.get(TEST_DB_URL_ENV)
    if not url:
        pytest.skip(f"{TEST_DB_URL_ENV} not set (expected a Postgres URL for integration test)")
    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return Session()


def _ts(minutes: int = 0):
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


@pytest.fixture()
def db():
    session = _session()
    try:
        # clean tables this test touches
        for model in (
            CampaignClaim,
            CampaignEntity,
            Campaign,
            InfraClusterMember,
            InfraCluster,
        ):
            session.query(model).delete()
        session.commit()
        yield session
    finally:
        session.close()


def test_shared_infra_claims_inserts_and_idempotent(db):
    # two campaigns share the same infra cluster
    c1 = Campaign(type="TYPE_A", primary_key="a", first_seen=_ts(30), last_seen=_ts(20))
    c2 = Campaign(type="TYPE_A", primary_key="b", first_seen=_ts(25), last_seen=_ts(10))
    db.add_all([c1, c2])
    db.flush()

    cluster_id = "cluster-1"
    cl = InfraCluster(
        cluster_id=cluster_id,
        kind="vpn_exit",
        confidence=0.5,
        first_seen=_ts(40),
        last_seen=_ts(5),
        member_count=2,
        summary_json={},
    )
    db.add(cl)
    db.flush()

    db.add_all(
        [
            InfraClusterMember(
                cluster_id=cluster_id,
                entity_key="ip:1.1.1.1",
                first_seen=_ts(40),
                last_seen=_ts(5),
                event_count=1,
            ),
            InfraClusterMember(
                cluster_id=cluster_id,
                entity_key="ip:2.2.2.2",
                first_seen=_ts(40),
                last_seen=_ts(5),
                event_count=1,
            ),
        ]
    )

    db.add_all(
        [
            CampaignEntity(
                campaign_id=c1.id,
                entity_key=f"infra_cluster:{cluster_id}",
                entity_type="InfraCluster",
                role="infrastructure",
                last_seen=_ts(10),
            ),
            CampaignEntity(
                campaign_id=c2.id,
                entity_key=f"infra_cluster:{cluster_id}",
                entity_type="InfraCluster",
                role="infrastructure",
                last_seen=_ts(10),
            ),
        ]
    )
    db.commit()

    # first run inserts one claim
    inserted = run_shared_infra_claims(db=db)
    assert inserted == 1

    rows = (
        db.query(CampaignClaim)
        .filter(CampaignClaim.claim_type == CLAIM_TYPE)
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert set(row.infra_cluster_ids) == {cluster_id}
    assert row.window == WINDOW

    # second run should be idempotent (no duplicates)
    inserted_again = run_shared_infra_claims(db=db)
    assert inserted_again == 0
    rows_after = db.query(CampaignClaim).all()
    assert len(rows_after) == 1
