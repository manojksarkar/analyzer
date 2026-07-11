"""Incremental document regeneration (version4).

Approach 2 — git-diff narrowed parse + stored-graph impact + selective regen.
See docs/production-redesign/04-incremental-changes-implementation.md.

This package holds the incremental-only logic: entity hashing (M1.2), the slim
type/macro usage index (M1.2b), the D9 store interface (M1.3 — stores.py), and
the detect->impact->regenerate->reassemble engine (M2).
"""
