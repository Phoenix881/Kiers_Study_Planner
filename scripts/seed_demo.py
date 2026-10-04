import argparse

from sqlalchemy.orm import Session

from app.db import engine
from app.services.seed import seed_demo


def main():
    parser = argparse.ArgumentParser(
        description="Seed unverified demo catalogue data without replacing existing plans."
    )
    parser.add_argument(
        "--with-exchange",
        action="store_true",
        help="Include an exchange term in a newly created demo plan.",
    )
    parser.add_argument(
        "--catalogue-only",
        action="store_true",
        help="Add missing catalogue examples; do not create a profile.",
    )
    args = parser.parse_args()
    with Session(engine) as session:
        created = seed_demo(session, args.with_exchange, args.catalogue_only)
    print(
        "Demo profile and plan created."
        if created
        else "Catalogue updated. Any existing profile and plan were preserved."
    )


if __name__ == "__main__":
    main()
