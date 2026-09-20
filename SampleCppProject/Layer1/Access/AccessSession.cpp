#include "AccessVisibility.h"

// A derived class may call a `protected:` base method. Defining it HERE is what gives
// DbSession::retryBudget a caller in another file -- the only reason that row reaches
// the interface table today.
class DbSessionUser : public DbSession {
public:
    PUBLIC int budget() { return retryBudget(); }
};

PUBLIC int accessSessionBudget() {
    DbSessionUser u;
    return u.budget();
}
