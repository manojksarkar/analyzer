#pragma once

// The visibility rule, one fixture per cell. Two questions decide every entry:
//
//   PHASE 1 records `public` or `private` -- two values, and unmarked records as public
//     - a PRIVATE/PROTECTED/PUBLIC macro on the declaration wins wherever it exists
//     - otherwise a MEMBER takes its C++ access, written label or language default
//     - a free function has no access specifier, so it stays `default`
//
//   PHASE 2 buckets it
//     - `private`                -> PIF_, whatever calls it
//     - address in a file-scope table -> IF_  (covered by Poly/OpsTable, not here)
//     - otherwise                -> IF_ only if a function in ANOTHER FILE calls it
//
// So a marking can only RESTRICT. `public` and `default` behave identically, and the
// cases below are laid out to prove exactly that.
//
// C++ access control is what makes some of these callable at all: a `protected:` member
// needs a derived class and a `private:` one needs a `friend`, both supplied from
// AccessMatrixUser.cpp so the caller genuinely lives in another file.

// ---------------------------------------------------------------------------
// Free functions — no access specifier exists, so only the macro speaks.
// The marked trio already live in AccessVisibility.h; these are the cells that
// separate "recorded public" from "published".
// ---------------------------------------------------------------------------

// Unmarked, called from App|Main -> public + cross-file caller -> IF_
int mtxUnmarkedCalled(int v);

// Unmarked, nothing calls it -> public, but no caller -> PIF_. Proof that `public` no
// longer buys a row: this and mtxPublicUncalled below record the same value and share a
// fate, which is the point of recording only two.
int mtxUnmarkedUncalled(int v);

// MARKED PUBLIC and still buried: nothing calls it from another file. This is the
// cell that changed when the PUBLIC marking stopped guaranteeing a row.
PUBLIC int mtxPublicUncalled(int v);

// ---------------------------------------------------------------------------
// A class with NO label at all — C++ makes every member private.
// ---------------------------------------------------------------------------
class MtxNoLabel {
    // No label was written, but the language default is binding on another unit just
    // as a written one is, so this records `private` and is never published.
    int hidden(int v);
};

// ---------------------------------------------------------------------------
// A struct — same four cases, but the language default is PUBLIC, not private.
// ---------------------------------------------------------------------------
struct MtxStruct {
    // No label: implicitly public. Called from App|Main -> IF_
    int plain(int v);

public:
    // Called from App|Main -> IF_
    int exposed(int v);

    // Public, but nothing outside this file calls it -> PIF_ despite being reachable.
    int exposedUncalled(int v);

protected:
    // Reached from a derived class in AccessMatrixUser.cpp -- a real cross-file caller,
    // and still PIF_, because `private` stops phase 2 before the call graph is consulted.
    int guarded(int v);

private:
    // Same shape one step further: a friend in another file calls it, and it stays PIF_.
    int sealed(int v);

    friend int mtxCallSealed(MtxStruct &s);
};

// The friend, declared here so App|Main can reach it. Its own row is ordinary.
PUBLIC int mtxCallSealed(MtxStruct &s);

// ---------------------------------------------------------------------------
// Macro against label — the macro wins in both directions.
// ---------------------------------------------------------------------------
class MtxConflict {
public:
    // Label says public, macro says private. Records `private` -> PIF_, even though
    // App|Main calls it and C++ permits that.
    PRIVATE int markedPrivateUnderPublic(int v);

private:
    // Label says private, macro says public. Records `public`; a friend in another file
    // supplies the caller, so it reaches the table -- the macro overrides the language.
    PUBLIC int markedPublicUnderPrivate(int v);

    friend int mtxCallMarkedPublic(MtxConflict &c);
};

PUBLIC int mtxCallMarkedPublic(MtxConflict &c);

// Reaches the derived class, so the protected member gets its cross-file caller.
PUBLIC int mtxUseDerived(int v);
