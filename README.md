# C++ Call Graph Analysis Project

This project contains tools for analyzing C++ codebases to extract function call graphs and module dependencies.

## Project Structure

```
Tests/
├── analyzer/              # Analysis tools and outputs
│   ├── function_analyzer.py  # Function-level call graph analyzer
│   ├── module_analyzer.py    # Module-based call graph analyzer
│   ├── functions.json        # Output: function-level analysis
│   ├── modules.json          # Output: module-based analysis
│   ├── component.json        # Output: component diagram structure
│   └── README.md             # Analyzer documentation
│
└── cpp_projects/         # C++ test projects
    ├── cpp_project/      # Simple test project
    └── cpp_project_module_based/  # Module-based test project
```

## Quick Start

### Function-level Analysis
```bash
cd analyzer
python function_analyzer.py
```

### Module-based Analysis
```bash
cd analyzer
python module_analyzer.py
```

## Features

- **Function-level analysis**: Extract all functions with their callers and callees
- **Module-based analysis**: Group functions by module and track inter-module dependencies
- **Namespace and class support**: Handles C++ namespaces, classes, and overloads
- **Cross-module tracking**: Identifies which modules call which other modules

## Requirements

- Python 3.x
- libclang (LLVM)
- clang Python bindings

See `analyzer/README.md` for detailed documentation.

