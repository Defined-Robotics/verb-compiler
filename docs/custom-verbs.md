# Writing Custom Verbs

A verb is a reusable, named action that the robot can perform — `go_to`, `report`, `explore`. Each verb compiles down to a fragment of BehaviorTree.CPP XML. This guide explains how to write your own.

## How verbs work

When you run `defined compile`, the compiler:

1. Reads each step in your task YAML (`verb: my_verb`)
2. Loads the verb definition from the verb library (`my_verb.yaml`)
3. Checks that the robot's RDF declares every capability the verb requires
4. Renders the verb's Jinja2 template (`my_verb.xml.j2`) into BT XML

A verb is just two files: a YAML definition and a Jinja2 template.

## Built-in verbs

| Verb | Required capabilities | What it does |
|---|---|---|
| `go_to` | `differential_drive` | Navigate to `(x, y)` via Nav2 action server |
| `explore` | `differential_drive` | Frontier-based autonomous mapping via explore_lite |
| `report` | — | Publish a string message to `/task_reports` |
| `wait` | — | Pause for `duration` seconds |

## Writing a custom verb

### Step 1: Create the verb definition YAML

Create `verbs/my_verb.yaml`:

```yaml
name: my_verb
description: "What this verb does"

required_capabilities:
  - differential_drive   # list capabilities the robot must have

template: my_verb.xml.j2  # Jinja2 template filename (in same directory)

primitives:
  - navigate_to_pose     # informational: what ROS2 primitive this uses

parameters:
  target:
    type: string
    required: true
    description: "Target location name"
  speed:
    type: float
    required: false
    default: 0.3
    description: "Movement speed in m/s"
```

**`required_capabilities`** must match capability `type` values declared in the robot RDF. If the robot's RDF does not declare all of them, compilation is rejected before any XML is produced.

**`parameters`** defines what the task YAML can pass in. Optional parameters must have a `default`.

### Step 2: Create the Jinja2 template

Create `verbs/my_verb.xml.j2`:

```xml
<Action ID="MyVerb"
    target="{{ target }}"
    speed="{{ speed | default('0.3') }}" />
```

The template receives all `params` from the task YAML step as Jinja2 variables. Use `| default('...')` for optional parameters — it protects against missing values even if the compiler doesn't enforce them.

The `ID` attribute must match a registered BT.CPP action node name in the runtime. For custom verbs, you need to implement and register the corresponding C++ node in `defined_runtime` (or provide your own executor).

### Step 3: Use the verb in a task

```yaml
name: MyTask
steps:
  - verb: my_verb
    params:
      target: "survey-1"
      speed: 0.2
  - verb: report
    params:
      message: "reached survey-1"
```

### Step 4: Compile with your verb directory

```bash
defined compile tasks/my_task.task.yaml \
    --rdf robot.rdf.yaml \
    --verbs-dir verbs/
```

Or from the TUI, set `--verbs-dir` when launching:

```bash
defined --rdf robot.rdf.yaml
```

The TUI uses the `compile_task` function internally which accepts a `verbs_dir` argument when called via the Python API.

## Verb template reference

### Available variables

All keys from the step's `params` dict are available as template variables. For the step:

```yaml
- verb: go_to
  params:
    x: 1.5
    y: 2.0
```

The template receives `{{ x }}` = `1.5` and `{{ y }}` = `2.0`.

### Jinja2 filters

Standard Jinja2 filters work. The most useful:

| Filter | Example | Result |
|---|---|---|
| `default` | `{{ theta \| default('0.0') }}` | `0.0` if `theta` not provided |
| `float` | `{{ speed \| float }}` | cast to float |
| `int` | `{{ retries \| int }}` | cast to int |
| `upper` | `{{ level \| upper }}` | `INFO` |

### Multi-node templates

A template can emit multiple BT XML nodes. Wrap them in a sequence if needed:

```xml
<Sequence>
    <Action ID="GoTo" x="{{ x }}" y="{{ y }}" />
    <Action ID="Report" message="arrived at {{ x }},{{ y }}" />
</Sequence>
```

## Example: built-in go_to verb

**`verb_library/go_to.yaml`:**
```yaml
name: go_to
description: "Navigate the robot to a specified position"
required_capabilities:
  - differential_drive
template: go_to.xml.j2
primitives:
  - navigate_to_pose
parameters:
  x:
    type: float
    required: true
  y:
    type: float
    required: true
  theta:
    type: float
    required: false
    default: 0.0
  timeout:
    type: float
    required: false
    default: 60.0
  frame_id:
    type: string
    required: false
    default: "map"
  server_name:
    type: string
    required: false
    default: "/navigate_to_pose"
  retries:
    type: int
    required: false
    default: 3
```

**`verb_library/go_to.xml.j2`:**
```xml
<RetryUntilSuccessful num_attempts="{{ retries | default('3') }}">
    <Action ID="GoTo" name="go_to_{{ x }}_{{ y }}"
        x="{{ x }}" y="{{ y }}"
        theta="{{ theta | default('0.0') }}"
        frame_id="{{ frame_id | default('map') }}"
        server_name="{{ server_name | default('/navigate_to_pose') }}"
        timeout="{{ timeout | default('60.0') }}" />
</RetryUntilSuccessful>
```

## How capability gating works

Each verb's `required_capabilities` list is checked against the robot's RDF at compile time:

```
Robot RDF declares: differential_drive, lidar_2d
Task uses: go_to (needs: differential_drive) ✓
           take_photo (needs: rgb_camera)     ✗ MISSING → compilation rejected
```

The check happens before any XML is rendered. Either all verbs pass or none are emitted. This makes compilation failures deterministic and prevents partially-valid task XML from reaching the runtime.

To add a capability requirement to your verb, add it to `required_capabilities` in the verb YAML and declare the corresponding capability in the robot's RDF:

```yaml
# robot.rdf.yaml
modules:
  - name: camera_module
    type: camera
    capabilities:
      - name: vision
        type: rgb_camera      # ← must match verb's required_capabilities entry
```

## Project structure

```
verb_library/           # Built-in verbs shipped with defined-compiler
  go_to.yaml
  go_to.xml.j2
  explore.yaml
  explore.xml.j2
  report.yaml
  report.xml.j2
  wait.yaml
  wait.xml.j2

src/defined_compiler/
  parser.py             # load_task() — reads task YAML
  verb_expander.py      # expand_verb() — loads verb YAML, merges params
  capability_gate.py    # check() — validates capabilities against RDF
  bt_emitter.py         # render_bt_xml() — renders Jinja2 templates
  cli.py                # defined-compile CLI entry point
```

## Running tests

```bash
uv sync
uv run pytest
```
