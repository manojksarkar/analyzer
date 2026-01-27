# Call Graph Analyzer

This directory contains tools for analyzing C++ code to extract function call graphs and module dependencies.

## Files

- **function_analyzer.py** - Function-level call graph analyzer
  - Analyzes C++ projects and extracts function definitions and call relationships
  - Outputs: `functions.json`
  - Configuration: Set `PROJECT_ROOT` to point to your C++ project

- **module_analyzer.py** - Module-based call graph analyzer
  - Analyzes C++ projects organized by modules (first-level folders under base path)
  - Groups functions by module and tracks inter-module dependencies
  - Outputs: 
    - `modules.json` with `callerModules` and `calleeModules`
    - `component.json` for component diagrams with `incoming`, `outgoing`, and `functions`
  - Configuration: Set `MODULE_BASE_PATH` to point to your module base directory

## Usage

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

## Output Files

- **functions.json** - Contains all functions with their callers and callees
- **modules.json** - Contains modules with their functions and inter-module dependencies
- **component.json** - Component diagram structure with modules, incoming/outgoing dependencies, and functions

## Configuration

Update the paths in each script:
- `function_analyzer.py`: Set `PROJECT_ROOT` to your C++ project path
- `module_analyzer.py`: Set `MODULE_BASE_PATH` to the base directory containing module folders

## Requirements

- Python 3.x
- libclang (LLVM)
- clang Python bindings

