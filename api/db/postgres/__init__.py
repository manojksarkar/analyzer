"""PostgreSQL storage for the analyzer (docs/production-redesign/07).

`schema.py` is the single source of truth for the database shape — shared by the
API repositories, the engine's model/metadata stores, and Alembic. Runtime code
(repositories, ModelStore) uses SQLAlchemy Core against this metadata; there are no
ORM entity classes, because the domain layer is already plain dataclasses
(`api/models/domain.py`) and a second parallel set would only add mapping.
"""
