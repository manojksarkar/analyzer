#pragma once

// =============================================================================
// Module  : mw_types (access portion)  |  Group: middleware
// Purpose : Visibility/access-pattern edge cases — getter, setter, and version
//           query with all three visibility macros in a single unit.
// Edge cases covered:
//   - PRIVATE/PUBLIC/PROTECTED macro definitions (the canonical source for
//     other test units that rely on parser.py's -DPRIVATE= Clang injection)
//   - Getter pattern: PROTECTED DB_TYPE _MTM_SB_GETDbType() — reads global,
//     direction inferred as Out; excluded from interface table (PROTECTED exposed)
//   - Getter with PRIVATE: _MTM_SB_GETDbVersion() — excluded from interface
//     table and unit-header globals table
//   - Setter pattern: PUBLIC void _MTM_SB_SETDbType(DB_TYPE t) — writes global,
//     direction inferred as In
//   - Underscore-prefixed function names (legacy naming convention)
//   - Typedef enum used as both parameter and return type (DB_TYPE)
// =============================================================================

// Visibility macros — empty expansions so Clang treats them as no-ops.
// The analyzer's parser.py also supplies -DPRIVATE= -DPUBLIC= -DPROTECTED= on
// the Clang command line so any TU that forgets this header still compiles.
#define PRIVATE
#define PROTECTED
#define PUBLIC

typedef enum {
    DB_NONE = 0,
    DB_MAIN = 1,
    DB_BACKUP = 2
} DB_TYPE;

/// Getter — returns current DB type. PROTECTED: visible in interface table.
PROTECTED DB_TYPE _MTM_SB_GETDbType();

/// Version getter — PRIVATE: excluded from interface table and header globals.
PRIVATE int _MTM_SB_GETDbVersion();

/// Setter — updates DB type. PUBLIC; direction In (writes global).
PUBLIC void _MTM_SB_SETDbType(DB_TYPE t);
