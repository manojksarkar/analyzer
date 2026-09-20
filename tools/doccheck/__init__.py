"""Compare two generated documents by what they say, not by how they read.

A line diff of two flattened DOCX files answers "are these byte-identical", which
is never the question. The question is whether the same units are described, with
the same interfaces, the same directions, the same callers -- and where they are
not, whether one of our own rules explains it.

The pipeline is `extract -> match -> compare -> report`:

- `blocks`  a DOCX as a block stream, structure kept
- `swe3` / `swe4`  a block stream as an entity tree, per document type
- `match`  which entity on the left is which entity on the right
- `compare`  the level ladder over two matched trees
- `report`  findings as markdown or JSON

Both sides go through the *same* extractor. Taking our side from `model/*.json`
and theirs from a DOCX would be more faithful and would also make every extractor
weakness look like a real difference, on one side only.
"""
