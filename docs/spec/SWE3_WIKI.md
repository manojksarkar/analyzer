# SWE.3 Software Detailed Design — rules (V1)

Each part of the document follows a rule below. A review comment names the rule it is about, by its
id: `SWE3-<section>-NN`, for example `SWE3-UI-02`.

| Code | Section | In the document | Rules |
|---|---|---|---|
| DOC | General | the whole document; 1 Introduction | 7 |
| SD | Static diagram | 2.1: the two component diagrams, the Component/Unit table; 2.1.1: each unit's diagram | 4 |
| UH | Unit header | 2.1.1.1 | 4 |
| UI | Unit interface | 2.1.1.2 | 6 |
| FD | Flow diagram | 2.1.1.3 onwards: one entry per public function | 3 |
| DB | Dynamic behaviour | 2.2 | 3 |
| FX | Fixed values, Code Metrics, Appendix | values the code does not decide; the last two chapters | 1 |

Section numbers are those of the outline below: the first component, the first unit.

---

## DOC — General

The document as a whole: its outline, what a unit is, which files are read, and what the LLM writes.

```
1  Introduction
   1.1  Purpose
   1.2  Scope
   1.3  Terms, Abbreviations and Definitions
2  <Component>                              ← one per component in the document, A-Z
   2.1  Static Design
        · component container diagram
        · file dependency diagram
        · Component / Unit / Description / Note table
        2.1.1  <Unit>                       ← one per unit that has a source file
               · unit architecture diagram
               2.1.1.1  unit header         ← globals / typedef / enum / define / records
               2.1.1.2  unit interface      ← Interface ID / Name / Information / Data Type /
                                              Data Range / Direction / Source-Destination / Type
               2.1.1.3  <Unit>-<Function>   ← one per public function: table + flowchart(s)
               2.1.1.4  <Unit>-<Function>
   2.2  Dynamic Behaviour
        2.2.1  <Unit> - <Function> (<CallerUnit> - <CallerFunction>)
               · description table + sequence diagram
3  <Component>  …
N  Code Metrics, Coding Rule, Test Coverage
Appendix A  Design Guideline
```

<table border="1" style="width:100%; table-layout:fixed">
<tr><th width="130" style="width:130px">ID</th><th width="200" style="width:200px">Rule</th><th>Details</th></tr>
<tr><td rowspan="2" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-DOC-01</b></td><td rowspan="2" valign="middle" style="vertical-align:middle"><b>One document per component</b></td><td>1. File name <code>software_detailed_design_&lt;component&gt;.docx</code></td></tr>
<tr><td>2. Components generated together share one document, each as its own top-level section</td></tr>
<tr><td rowspan="1" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-DOC-02</b></td><td rowspan="1" valign="middle" style="vertical-align:middle"><b>Outline</b></td><td>1. The document follows the outline above</td></tr>
<tr><td rowspan="3" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-DOC-03</b></td><td rowspan="3" valign="middle" style="vertical-align:middle"><b>What a unit is</b></td><td>1. A source file and the header of the same name, as one: <code>Foo.cpp</code> + <code>Foo.h</code> = unit <code>Foo</code></td></tr>
<tr><td>2. Only a unit with a source file (<code>.cpp</code>, <code>.cc</code>, <code>.cxx</code>) gets a section</td></tr>
<tr><td>3. A header with no source file of its own is listed inside one unit that uses it (SWE3-UH-04)</td></tr>
<tr><td rowspan="5" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-DOC-04</b></td><td rowspan="5" valign="middle" style="vertical-align:middle"><b>Which files are read</b></td><td>1. <code>.cpp</code> <code>.cc</code> <code>.cxx</code> <code>.h</code> <code>.hpp</code> <code>.hxx</code> under the component's folders, in any case</td></tr>
<tr><td>2. A <code>.c</code> file is not read (a change is planned)</td></tr>
<tr><td>3. A file with <code>emul</code> in its name is skipped; the settings can name other patterns</td></tr>
<tr><td>4. A file that two components list belongs to the first one in the settings</td></tr>
<tr><td>5. Code outside the document's components appears only as a name (a diagram box, a Source/Destination unit), never as a section</td></tr>
<tr><td rowspan="3" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-DOC-05</b></td><td rowspan="3" valign="middle" style="vertical-align:middle"><b>What comes from the code, what the LLM writes</b></td><td>1. Built only from the C++ source and the project settings: no requirement database, no hand-written notes</td></tr>
<tr><td>2. The LLM writes only wording (see Reference, at the end); IDs, rows, directions, ranges, arrows and flowchart shapes come from the code</td></tr>
<tr><td>3. The same code gives the same document: LLM answers are reused, and the LLM is told the project's domain</td></tr>
<tr><td rowspan="2" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-DOC-06</b></td><td rowspan="2" valign="middle" style="vertical-align:middle"><b>Changes made in the app</b></td><td>1. A text a reviewer corrected in the app is printed instead of the LLM's; it stays in later versions while the code it describes is unchanged</td></tr>
<tr><td>2. A function marked hidden is left out of the interface table, the function entries and Dynamic Behaviour; hiding applies to that exact function</td></tr>
<tr><td rowspan="2" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-DOC-07</b></td><td rowspan="2" valign="middle" style="vertical-align:middle"><b>Introduction</b></td><td>1. 1.1 Purpose and 1.2 Scope: standard text from the settings, Scope with one bullet per component of this document; 1.3 Terms: every abbreviation in the project's abbreviations file, A–Z</td></tr>
<tr><td>2. Only the component bullets come from the code; the rest is standard text (SWE3-FX-01)</td></tr>
</table>

---

## SD — Static diagram

2.1 Static Design: at the top of every component, its two diagrams and the Component/Unit table; in every unit (2.1.1), its diagram, where boxes are units and arrows are interfaces.

<table border="1" style="width:100%; table-layout:fixed">
<tr><th width="130" style="width:130px">ID</th><th width="200" style="width:200px">Rule</th><th>Details</th></tr>
<tr><td rowspan="3" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-SD-01</b></td><td rowspan="3" valign="middle" style="vertical-align:middle"><b>Component diagrams</b></td><td>1. Container diagram: the component as a yellow box, with one blue box inside it per unit; no arrows</td></tr>
<tr><td>2. File dependency diagram: an arrow from each source file to each header of this component it includes</td></tr>
<tr><td>3. An include inside <code>#if</code> counts only when its branch is active</td></tr>
<tr><td rowspan="3" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-SD-02</b></td><td rowspan="3" valign="middle" style="vertical-align:middle"><b>Component/Unit table</b></td><td>1. One row per unit that has a source file: Component (without its layer), Unit (the file name), Description, Note</td></tr>
<tr><td>2. Description: one line written by the LLM summing up the unit's public functions and globals; with the LLM off, their descriptions joined and cut at 120 characters</td></tr>
<tr><td>3. Note: always <code>N/A</code> (SWE3-FX-01)</td></tr>
<tr><td rowspan="4" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-SD-03</b></td><td rowspan="4" valign="middle" style="vertical-align:middle"><b>Unit diagram: arrows</b></td><td>1. One diagram per unit: boxes are units; for each public function of this unit, an arrow between it and each unit that calls it, labelled with the interface IDs</td></tr>
<tr><td>2. So each link between two units is drawn once, in the diagram of the unit that provides the function</td></tr>
<tr><td>3. The arrow follows the function's Direction (Unit interface): <code>In</code> points caller → provider, <code>Out</code> points provider → caller</td></tr>
<tr><td>4. Calls between the same two units in the same direction share one arrow</td></tr>
<tr><td rowspan="4" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-SD-04</b></td><td rowspan="4" valign="middle" style="vertical-align:middle"><b>Unit diagram: boxes</b></td><td>1. This unit sits in a yellow box of its component, with the document's units it shares an arrow with; units of other components are outside the box</td></tr>
<tr><td>2. A unit it shares no arrow with is not drawn</td></tr>
<tr><td>3. A unit whose arrow points into this unit is on its left, one it points to on its right; a unit with arrows both ways is drawn twice</td></tr>
<tr><td>4. The unit's own public globals are boxes above it, without arrows; other globals are not drawn</td></tr>
</table>

---

## UH — Unit header

2.1.1.1 unit header: two columns, declaration and information. It lists what the unit's own files declare; functions are in the interface table.

<table border="1" style="width:100%; table-layout:fixed">
<tr><th width="130" style="width:130px">ID</th><th width="200" style="width:200px">Rule</th><th>Details</th></tr>
<tr><td rowspan="7" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-UH-01</b></td><td rowspan="7" valign="middle" style="vertical-align:middle"><b>What is listed</b></td><td>1. Every symbol declared in the unit's own <code>.cpp</code> and <code>.h</code>: globals (<code>extern</code> too), <code>#define</code>s, enums, typedefs, structs, classes, unions; no functions</td></tr>
<tr><td>2. Listed whatever its access or marking (<code>PRIVATE</code>, <code>static</code>)</td></tr>
<tr><td>3. Listed whether or not it is used (a change is planned)</td></tr>
<tr><td>4. Not listed: include guards, local variables, a type declared inside a class (the class row shows it)</td></tr>
<tr><td>5. A static member's definition in the <code>.cpp</code> is not listed: the class row declares the member, without its starting value</td></tr>
<tr><td>6. A symbol declared twice is listed once: an enum and its typedef; an <code>extern</code> and its definition (the one with the value)</td></tr>
<tr><td>7. Rows are sorted by declaration text</td></tr>
<tr><td rowspan="3" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-UH-02</b></td><td rowspan="3" valign="middle" style="vertical-align:middle"><b>Declaration column</b></td><td>1. Exactly as written in the source, markings and keywords kept, in full over as many lines as it takes</td></tr>
<tr><td>2. Comments are removed</td></tr>
<tr><td>3. A struct or class shows its members; a method only as its declaration; its body is in the flowchart</td></tr>
<tr><td rowspan="5" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-UH-03</b></td><td rowspan="5" valign="middle" style="vertical-align:middle"><b>Information column</b></td><td>1. Global: its starting value; <code>N/A</code> if none</td></tr>
<tr><td>2. <code>#define</code>: its value as written, not worked out (<code>(1&lt;&lt;6)</code>, not <code>64</code>)</td></tr>
<tr><td>3. Enum, or a typedef of one: <code>NAME=value, …</code></td></tr>
<tr><td>4. struct, class, union, or a typedef of one: one line written by the LLM (without the LLM: <code>Structure for …</code>)</td></tr>
<tr><td>5. Any other typedef: <code>N/A</code></td></tr>
<tr><td rowspan="2" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-UH-04</b></td><td rowspan="2" valign="middle" style="vertical-align:middle"><b>Shared headers (a header with no source file of its own)</b></td><td>1. Listed once, in one unit: the first unit by name, in the header's component, that uses it; the same unit in every document</td></tr>
<tr><td>2. Only the symbols some unit uses</td></tr>
</table>

---

## UI — Unit interface

2.1.1.2 unit interface: one row per public function and public global of the unit, in eight columns:

| # | Column | Function row | Global variable row |
|---|---|---|---|
| 1 | **Interface ID** | `IF_<LAYER>_<GROUP>_<UNIT>_<NN>` | same |
| 2 | **Interface Name** | short name with the class in front | short name |
| 3 | **Information** | description, or `-` | description, or `-` |
| 4 | **Data Type** | the parameters, plus a `return:` line | the declared type |
| 5 | **Data Range** | one range per parameter, plus a `return:` line | the type's range |
| 6 | **Direction(In/Out)** | `In` or `Out` | always `In/Out` |
| 7 | **Source/Destination** | the units that **call** it | the unit's own `Component/Unit` |
| 8 | **Interface Type** | `Function` | `Global Variable` |

<table border="1" style="width:100%; table-layout:fixed">
<tr><th width="130" style="width:130px">ID</th><th width="200" style="width:200px">Rule</th><th>Details</th></tr>
<tr><td rowspan="5" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-UI-01</b></td><td rowspan="5" valign="middle" style="vertical-align:middle"><b>Which rows</b></td><td>1. One table per unit that has a source file; one row per public function and public global of the unit, from its <code>.cpp</code> and its <code>.h</code></td></tr>
<tr><td>2. Public means another unit uses it: a function another unit calls, or whose address sits in a table of function pointers outside any function; a global another unit reads or writes</td></tr>
<tr><td>3. No marking decides: <code>PUBLIC</code>, <code>PRIVATE</code>, <code>PROTECTED</code>, <code>public:</code>, <code>private:</code> are ignored</td></tr>
<tr><td>4. No row: a file-scope <code>static</code> variable; an <code>extern</code> declaration (the defining unit's row stands for it); types and macros (they are in the unit header)</td></tr>
<tr><td>5. An entry point nothing calls by name (an ISR, a callback) is private unless a table holds its address; a run of one layer cannot see the layer above calling in</td></tr>
<tr><td rowspan="5" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-UI-02</b></td><td rowspan="5" valign="middle" style="vertical-align:middle"><b>Order and Interface ID</b></td><td>1. Functions first, then globals; the ID column counts <code>01</code>, <code>02</code>, <code>03</code> … with no gap</td></tr>
<tr><td>2. <code>IF_&lt;LAYER&gt;_&lt;GROUP&gt;_&lt;UNIT&gt;_&lt;NN&gt;</code>: each part is the name in capitals, letters only; the layer keeps its digits (<code>Flash Core</code> → <code>FLASHCORE</code>)</td></tr>
<tr><td>3. <code>&lt;NN&gt;</code> counts per unit, <code>.cpp</code> and <code>.h</code> together: functions by file and line, then globals</td></tr>
<tr><td>4. <code>Map</code> and <code>Map2</code> both give <code>MAP</code>: they share one count, so no ID is printed twice (a change is planned)</td></tr>
<tr><td>5. An ID is a position: when a function becomes public, the later IDs of its unit move up by one</td></tr>
<tr><td rowspan="3" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-UI-03</b></td><td rowspan="3" valign="middle" style="vertical-align:middle"><b>Interface Name and Information</b></td><td>1. Function: its short name with its class in front, without the namespace (<code>MapCache::insert</code>); global: the name after the last <code>::</code></td></tr>
<tr><td>2. Two functions of one unit never print alike: an overload adds its parameter types (<code>Read(int)</code>, <code>Read(int, int)</code>), one name in two namespaces adds its scope</td></tr>
<tr><td>3. Information: one line written by the LLM describing the function or global; <code>-</code> without the LLM</td></tr>
<tr><td rowspan="4" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-UI-04</b></td><td rowspan="4" valign="middle" style="vertical-align:middle"><b>Data Type and Data Range</b></td><td>1. Function: its parameters as <code>type name; type name; …</code>, as written, then <code>return: &lt;type&gt;</code>; no parameters: <code>VOID</code>; a <code>void</code> return: <code>return: VOID</code>. Global: its declared type</td></tr>
<tr><td>2. Data Range: one range per Data Type line, in the same order, then <code>return: range</code>; <code>NA</code> for <code>void</code> and for no parameters</td></tr>
<tr><td>3. A range is looked up by type name, in this layer's data dictionary (see Reference); a typedef follows the type it stands for (<code>Lba_t</code> → <code>uint32_t</code> → <code>0-0xFFFFFFFF</code>)</td></tr>
<tr><td>4. Structs, unions, pointers and floats are <code>NA</code> on purpose</td></tr>
<tr><td rowspan="4" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-UI-05</b></td><td rowspan="4" valign="middle" style="vertical-align:middle"><b>Direction(In/Out): the first that matches</b></td><td>1. The name holds the whole word <code>set</code> → <code>In</code>, even when it returns a value; else the whole word <code>get</code> → <code>Out</code> (camelCase and snake_case are split into words; <code>isSet</code> matches too)</td></tr>
<tr><td>2. Else a return value (not <code>void</code>) → <code>Out</code>, even when it also writes a global</td></tr>
<tr><td>3. Else: writes a global, itself or through a function it calls → <code>In</code>; otherwise <code>Out</code></td></tr>
<tr><td>4. A global row: always <code>In/Out</code></td></tr>
<tr><td rowspan="5" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-UI-06</b></td><td rowspan="5" valign="middle" style="vertical-align:middle"><b>Source/Destination and Interface Type</b></td><td>1. Function: every other unit that calls it (callers only, not the units it calls), as <code>Component/Unit</code>, A–Z; the same as its arrows in the unit diagram (SWE3-SD-03)</td></tr>
<tr><td>2. Published only through a pointer table: the unit that registers it; nobody: <code>-</code></td></tr>
<tr><td>3. Written without the layer, hyphens kept: <code>Flash-Core/Map</code>, where headings show spaces</td></tr>
<tr><td>4. Global: the unit's own <code>Component/Unit</code></td></tr>
<tr><td>5. Interface Type: <code>Function</code> or <code>Global Variable</code></td></tr>
</table>

---

## FD — Flow diagram

2.1.1.3 onwards: one entry per public function, a table and its flowchart(s).

<table border="1" style="width:100%; table-layout:fixed">
<tr><th width="130" style="width:130px">ID</th><th width="200" style="width:200px">Rule</th><th>Details</th></tr>
<tr><td rowspan="6" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-FD-01</b></td><td rowspan="6" valign="middle" style="vertical-align:middle"><b>The entry</b></td><td>1. One heading <code>&lt;Unit&gt;-&lt;Function&gt;</code> per public function, named as in the interface table; each overload its own; globals get none</td></tr>
<tr><td>2. Under it, a table of five rows: Requirements, Risk, Capacity(Density), Input Name, Output Name</td></tr>
<tr><td>3. Requirements: the function's description, then its flowchart(s), each with its signature above it</td></tr>
<tr><td>4. After its own flowchart, one for each private function it calls directly, drawn once per unit, under the first public function that calls it</td></tr>
<tr><td>5. A private function called only by another private function has no flowchart</td></tr>
<tr><td>6. Risk <code>Medium</code>, Capacity(Density) <code>Common</code> (SWE3-FX-01)</td></tr>
<tr><td rowspan="5" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-FD-02</b></td><td rowspan="5" valign="middle" style="vertical-align:middle"><b>The flowchart</b></td><td>1. The shape comes from the code: an oval for Start and End, a diamond for a decision with Yes/No, a box for everything else</td></tr>
<tr><td>2. The LLM writes only the box labels; without the LLM a box shows its own source text</td></tr>
<tr><td>3. Every call in a box is written <code>Name()</code>; a call the label dropped is added as <code>Calls: X()</code></td></tr>
<tr><td>4. A header that cannot be found removes no branch, except an <code>#if</code> on one of its macros</td></tr>
<tr><td>5. Too tall for a page: split across pages, not shrunk</td></tr>
<tr><td rowspan="4" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-FD-03</b></td><td rowspan="4" valign="middle" style="vertical-align:middle"><b>Input Name and Output Name</b></td><td>1. Input Name: the first parameter's name; with no named parameter, the first global it writes, else reads; nothing: <code>&lt;Function&gt; input</code></td></tr>
<tr><td>2. Output Name: a plain name on the <code>return</code> line; else the return type, unless a basic one (<code>int</code>, <code>bool</code>, …); else the first global it writes, then reads; else <code>&lt;Function&gt; result</code>. <code>TRUE</code>/<code>FALSE</code> returns give <code>TRUE/FALSE</code></td></tr>
<tr><td>3. Tidied: <code>g_</code>, <code>s_</code>, <code>t_</code> dropped, underscores to spaces, a capital first (<code>g_entry_count</code> → <code>Entry count</code>)</td></tr>
<tr><td>4. Only the stand-in names, <code>&lt;Function&gt; input</code> and <code>&lt;Function&gt; result</code>, are sent to the LLM for a better name</td></tr>
</table>

---

## DB — Dynamic behaviour

2.2 Dynamic Behaviour: one entry per call coming into the component from outside, and what it does across the component's units.

<table border="1" style="width:100%; table-layout:fixed">
<tr><th width="130" style="width:130px">ID</th><th width="200" style="width:200px">Rule</th><th>Details</th></tr>
<tr><td rowspan="2" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-DB-01</b></td><td rowspan="2" valign="middle" style="vertical-align:middle"><b>Which functions get an entry</b></td><td>1. A public function that a function in another component calls, whose calls reach another unit of its own component; not hidden</td></tr>
<tr><td>2. One entry per function, for its first caller from another component</td></tr>
<tr><td rowspan="4" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-DB-02</b></td><td rowspan="4" valign="middle" style="vertical-align:middle"><b>Heading and sequence diagram</b></td><td>1. Heading: <code>&lt;Unit&gt; - &lt;Function&gt; (&lt;CallerUnit&gt; - &lt;CallerFunction&gt;)</code></td></tr>
<tr><td>2. One participant per unit, grouped and coloured by component; the outside caller enters the function</td></tr>
<tr><td>3. Calls are followed only inside the function's component</td></tr>
<tr><td>4. Calls within one unit are skipped and the chain joined across them</td></tr>
<tr><td rowspan="2" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-DB-03</b></td><td rowspan="2" valign="middle" style="vertical-align:middle"><b>The table</b></td><td>1. Requirements: <code>Behavior Description</code>, then one bullet per arrow, in diagram order; Risk and Capacity fixed (SWE3-FX-01); Input and Output Name as the function's (SWE3-FD-03)</td></tr>
<tr><td>2. A call bullet: <code>A calls B to &lt;reason&gt;</code> with the LLM (20 words at most), <code>A calls B</code> without; a return bullet: <code>B returns to A</code></td></tr>
</table>

---

## FX — Fixed values, Code Metrics, Appendix

The values the document states without working them out from the code, and its last two chapters.

<table border="1" style="width:100%; table-layout:fixed">
<tr><th width="130" style="width:130px">ID</th><th width="200" style="width:200px">Rule</th><th>Details</th></tr>
<tr><td rowspan="7" nowrap valign="middle" style="white-space:nowrap; vertical-align:middle"><b>SWE3-FX-01</b></td><td rowspan="7" valign="middle" style="vertical-align:middle"><b>Fixed values</b></td><td>1. Risk, in the function and behaviour tables: <code>Medium</code>, an agreed fixed value</td></tr>
<tr><td>2. Capacity, Capacity(Density): <code>Common</code>, an agreed fixed value</td></tr>
<tr><td>3. Note, in the Component/Unit table: <code>N/A</code> for now</td></tr>
<tr><td>4. Requirements row: the description, or the behaviour bullets, for now; links to requirement IDs (SWE.1 / Polarion) come later</td></tr>
<tr><td>5. Introduction text: from the settings; its final wording comes later</td></tr>
<tr><td>6. <code>Code Metrics, Coding Rule, Test Coverage</code> and <code>Appendix A Design Guideline</code>: headings with a standard text for now</td></tr>
<tr><td>7. LLM-written cells with the LLM off: <code>-</code> or <code>N/A</code></td></tr>
</table>

---

## Worked example

A component `FtlCore` with two units, in layer `Ftl`, group `Map`. `FtlMap` is the unit documented;
`FtlCache` is another unit of the component; `HilQueue` is in another component, `HilCore`.

```c
// ---- unit FtlMap.h ----
#define MAP_ENTRY_MAX  (1024)            // used by FtlMap.cpp outside any function
typedef uint32_t Lba_t;

// ---- unit FtlMap.cpp ----
uint16_t        gEntryCount = 64;        // read by FtlCache -> public
PRIVATE uint8_t gErrCount   = 0;         // used only in this unit -> not public

PRIVATE bool isValidLba(Lba_t lba);      // called only in this unit -> no row; flowchart under its caller
PUBLIC  int  FtlSetEntry(Lba_t lba, uint32_t ppn);   // called by HilQueue; calls isValidLba, FtlCacheInsert
PUBLIC  int  FtlGetPpn(Lba_t lba, uint32_t* ppnOut); // called by FtlCache
```

### 2.1.1.1 unit header (FtlMap)

| declaration | information |
|---|---|
| `#define MAP_ENTRY_MAX (1024)` | `(1024)` |
| `PRIVATE uint8_t gErrCount = 0;` | `0` |
| `typedef uint32_t Lba_t;` | `N/A` |
| `uint16_t gEntryCount = 64;` | `64` |

- `gErrCount` is listed though it is private, with its marking; rows are sorted by their text; the
  functions are in the interface table, not here (SWE3-UH-01).
- Comments are gone (SWE3-UH-02).

### 2.1.1.2 unit interface (FtlMap)

| Interface ID | Interface Name | Information | Data Type | Data Range | Direction(In/Out) | Source/Destination | Interface Type |
|---|---|---|---|---|---|---|---|
| `IF_FTL_MAP_FTLMAP_01` | `FtlSetEntry` | Stores a mapping entry for a logical block. | `Lba_t lba; uint32_t ppn`<br>`return: int` | `0-0xFFFFFFFF; 0-0xFFFFFFFF`<br>`return: -0x80000000-0x7FFFFFFF` | `In` | `HilCore/HilQueue` | Function |
| `IF_FTL_MAP_FTLMAP_02` | `FtlGetPpn` | Returns the physical page for a logical block. | `Lba_t lba; uint32_t* ppnOut`<br>`return: int` | `0-0xFFFFFFFF; NA`<br>`return: -0x80000000-0x7FFFFFFF` | `Out` | `FtlCore/FtlCache` | Function |
| `IF_FTL_MAP_FTLMAP_03` | `gEntryCount` | Number of populated map entries. | `uint16_t` | `0-0xFFFF` | `In/Out` | `FtlCore/FtlMap` | Global Variable |

- `FtlSetEntry` and `FtlGetPpn` have rows because another unit calls them; `PUBLIC` did not decide it.
  `isValidLba` and `gErrCount` have none (SWE3-UI-01).
- `FtlSetEntry` is `In` by SWE3-UI-05 (the word `Set`), though it returns `int`: the name is checked first.
  `FtlGetPpn` is `Out` by SWE3-UI-05 (`Get`).
- Functions take `_01`, `_02`, the global `_03` (SWE3-UI-02).
- `Lba_t` gives `0-0xFFFFFFFF` through the typedef; `uint32_t*` is a pointer, so `NA` (SWE3-UI-04).
- Source/Destination names the callers, without the layer (SWE3-UI-06).

### 2.1.1.3 FtlMap-FtlSetEntry

| | |
|---|---|
| Requirements | Stores a mapping entry for a logical block.<br>`int FtlSetEntry(Lba_t lba, uint32_t ppn)` + flowchart<br>`bool isValidLba(Lba_t lba)` + flowchart *(the private function it calls, SWE3-FD-01)* |
| Risk | Medium |
| Capacity(Density) | Common |
| Input Name | `Lba` |
| Output Name | `Entry count` |

Input Name is the first parameter, tidied. Output Name falls through to the first global the function
writes, `gEntryCount`, because the return line is not a plain name and `int` is skipped (SWE3-FD-03).

### 2.2.1 FtlMap - FtlSetEntry (HilQueue - hilFlush)

It qualifies (SWE3-DB-01): public ✓, its calls reach `FtlMap` and `FtlCache` ✓, a caller in `HilCore` ✓, a
cross-unit arrow inside `FtlCore` ✓. `FtlGetPpn` does not: its only caller is in its own component.

| | |
|---|---|
| Requirements | **Behavior Description**<br>• hilFlush calls FtlSetEntry to store a flushed mapping<br>• FtlSetEntry calls FtlCacheInsert to cache the new entry<br>• FtlCacheInsert returns to FtlSetEntry<br>• FtlSetEntry returns to hilFlush |
| Risk | Medium |
| Capacity | Common |
| Input Name | `Lba` |
| Output Name | `Entry count` |

The call to `isValidLba` is not drawn: it stays inside `FtlMap`, so it is skipped and the chain joins
straight to the `FtlCache` arrow (SWE3-DB-02).

---

## Planned changes

Agreed, not built yet. Until then, the rule says what the document does today.

| Rule | Today | Planned |
|---|---|---|
| SWE3-DOC-04 | a `.c` file is not read | read, as C |
| SWE3-UH-01 | a unit's own symbol is listed whether or not it is used | listed only when a unit of its own component uses it; another component's use does not count |
| SWE3-UI-02 | `Map` and `Map2` share the ID part `MAP` | two units never share an ID part |

---

## Reference

**Words used in the rules**

| Word | Means |
|---|---|
| public | used from another unit: a function another unit calls, a global another unit reads or writes (SWE3-UI-01) |
| private | not public: no row in the interface table, no heading |
| interface | a public function or global: one row of the interface table |
| entry | a public function's sub-section, its table and flowchart(s) (SWE3-FD-01) |
| data dictionary | the types of a layer and their value ranges, from the code and the project settings |
| the settings | the project's configuration: layers, groups, components, macros, include paths, texts |

**Layer, group, component, unit** (the examples are the worked example's)

| Level | What it is | Example |
|---|---|---|
| Layer | a top folder of the code: one layer of the software | `Ftl` |
| Group | a named set of components inside a layer | `Map` |
| Component | a named set of folders inside a group; one top-level section of the document | `FtlCore` |
| Unit | one source file and the header of the same name | `FtlMap` = `FtlMap.cpp` + `FtlMap.h` |

Layers, groups and components are set in the project settings; a unit comes from its file name.

**The texts the LLM writes**

| Text | Without the LLM | With the LLM |
|---|---|---|
| Interface **Information** (SWE3-UI-03) | `-` | one line describing the function or global |
| Component/Unit **Description** (SWE3-SD-02) | its interface rows' descriptions joined, cut at 120 characters | one line summarising the unit |
| Unit header **information** of a struct, class or union, or a typedef of one (SWE3-UH-03) | `Structure for …`, `Class for …`, `Union for …`, from the type name | one line from the type name **and** its fields |
| Flowchart box labels (SWE3-FD-02) | the box's own source text | a short label per box |
| Behaviour bullets (SWE3-DB-03) | `A calls B` | `A calls B to …` (20 words at most) |
| Input / Output Name (SWE3-FD-03) | worked out from the code | asked for only when the worked-out name is a stand-in (`<Function> input`) |

**What changes the document**

| Input | What it changes |
|---|---|
| the C++ source | everything below follows from it |
| layers, groups, components (folders) | which documents, sections and units there are; the IDs (SWE3-DOC-01, SWE3-DOC-03, SWE3-UI-02) |
| macros, per layer | which `#if` branches count (SWE3-SD-01, SWE3-FD-02) |
| include paths | which headers are found (SWE3-FD-02) |
| the data dictionary | Data Range (SWE3-UI-04) |
| file name patterns to skip | which files are read (SWE3-DOC-04) |
| the Introduction texts, the abbreviations file | 1 Introduction (SWE3-DOC-07) |
| corrections and hidden functions, made in the app | SWE3-DOC-06 |
| the LLM, on or off | the texts the LLM writes (above) |

---

## Changes

**V1, 2026-11-05:** 28 rules. A rule changes only when the teams agree it. Its ID never changes: a new rule
takes the next free number of its section, and a removed rule stays in its table, struck through.
