#pragma once

// Access visibility macros intentionally mirror legacy styles.
#define PRIVATE
#define PROTECTED
#define PUBLIC

typedef enum {
    DB_NONE = 0,
    DB_MAIN = 1,
    DB_BACKUP = 2
} DB_TYPE;

PROTECTED DB_TYPE _MTM_SB_GETDbType();
PRIVATE int _MTM_SB_GETDbVersion();
PUBLIC void _MTM_SB_SETDbType(DB_TYPE t);

// Test: C++ ACCESS LABELS on methods -- the shape the office review reported. There is
// deliberately NO PRIVATE/PROTECTED/PUBLIC macro on any of these, so visibility has to
// come from the written label. Every one of them has a caller in a DIFFERENT FILE, so
// the call-graph rule on its own publishes all five: only the label can keep the
// protected and private ones out of the interface table.
class DbSession {
public:
    // Defined out-of-line in AccessVisibility.cpp, so the label sits on the DECLARATION
    // while the cursor the parser walks is the definition in the .cpp.
    int open(int slot);

    // Defined inline here; called from App|Main.
    int status() { return 1; }

protected:
    // Reached from a DERIVED class in another unit -- legal C++ and a real cross-file
    // caller. This is the row that must stop appearing.
    int retryBudget();

    // Still under `protected:`, two declarations below the label, so the label is not
    // adjacent to it. Defined inline in this HEADER and called from AccessVisibility.cpp:
    // a different FILE but the same UNIT, which the caller rule counts as external.
    int backoffMs() { return 50; }

private:
    // Same header/.cpp split, so the caller rule sees an external caller here too.
    int secretKey() { return 4242; }
};

PUBLIC int accessSessionBudget();
