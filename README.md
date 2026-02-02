# C++ Call Graph Analysis Project

This project contains a tool for analyzing C++ codebases to extract function call graphs and module dependencies.

## Project Structure

```
Tests/
├── analyzer.py              # Call graph analyzer (functions, files, modules)
├── modules.json             # Output: functions, files, modules
├── component.json          # Output: component diagram structure
│
└── test_cpp_projects/      # C++ test projects
    ├── cpp_project/        # Simple test project
    └── cpp_project_module_based/  # Module-based test project
```

## Quick Start

```bash
python analyzer.py
```

Generates `modules.json` (functions, files, modules) and `component.json` (component diagram).

## Features

- **Function-level analysis**: Extract all functions with their callers and callees
- **Module-based analysis**: Group functions by module and track inter-module dependencies
- **Namespace and class support**: Handles C++ namespaces, classes, and overloads
- **Cross-module tracking**: Identifies which modules call which other modules

## Requirements

- Python 3.x
- libclang (LLVM)
- clang Python bindings

## Configuration

Paths are relative to the script location. The analyzer uses `test_cpp_projects/cpp_project_module_based/src` (first-level subfolders = modules).

Update `cindex.Config.set_library_file(...)` if your LLVM/libclang install path differs.
