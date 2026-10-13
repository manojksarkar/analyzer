// Overloads.h — functions that share a name inside ONE unit.
//
// A document names a function in a section heading, an interface row, a flowchart title and a
// test specification. `Class::name` is one string for every function below that shares it, so
// two sections read the same and their flowcharts took one file. Each case here needs something
// different to tell it apart:
//
//   overloads                  one qualified name      -> the parameter types: ovlScale(int)
//   one name, two namespaces   two qualified names     -> the scope: fastpath::ovlInit
//   an override                two classes             -> the class, as always: OvlSquare::area
//   a name nobody shares       —                       -> printed as before: ovlAlone
#pragma once

// Overloads of a free function.
PUBLIC int ovlScale(int value);
PUBLIC int ovlScale(int value, int factor);
PUBLIC float ovlScale(float value);

// The same name in two namespaces.
namespace fastpath {
PUBLIC int ovlInit(int seed);
}
namespace slowpath {
PUBLIC int ovlInit(int seed);
}

// Overloaded methods of one class, and a method a derived class overrides.
class OvlShape {
public:
    virtual int area(int side);
    int resize(int side);
    int resize(int width, int height);
};

class OvlSquare : public OvlShape {
public:
    int area(int side) override;
};

// Shares its name with nobody.
PUBLIC int ovlAlone(int value);
