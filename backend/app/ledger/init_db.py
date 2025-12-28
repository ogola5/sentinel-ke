from sqlalchemy import create_engine
from app.ledger.models import Base
import os

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL)

def init():
    Base.metadata.create_all(bind=engine)
    print("Ledger tables created")

if __name__ == "__main__":
    init()
